"""Constant-memory streaming reader for mbox files.

The whole reason mailslice exists is that a Google Takeout mbox routinely
weighs 40 GB and ``mailbox.mbox`` builds an in-memory table of the entire
file before yielding a single message. This reader instead scans the file
in fixed-size chunks, holds at most one line plus one message's header block
in memory, and hands the body to the caller as a stream of lines. Memory use
is bounded by the longest single line and the header cap — it does not grow
with the size of the mbox or of any attachment.

Message boundary detection is deliberately conservative: a line only starts a
new message if it *looks like* a real mbox separator (``From `` + envelope +
asctime date, with Gmail's optional numeric timezone) **and** follows a blank
line. Takeout does not reliably escape ``From `` at the start of body lines,
so a naive ``startswith(b"From ")`` splitter shreds real mail mid-paragraph.
See docs/splitting-rules.md for the full rules.
"""

from __future__ import annotations

import gzip
import re
import sys
from typing import BinaryIO, Iterator, List, Optional

from .errors import BodyConsumedError, NotAnMboxError
from .headers import HeaderBlock

__all__ = [
    "DEFAULT_CHUNK_SIZE",
    "DEFAULT_HEADER_CAP",
    "ESCAPING_MODES",
    "is_from_line",
    "unstuff",
    "iter_lines",
    "MboxMessage",
    "MboxReader",
    "open_mbox",
]

DEFAULT_CHUNK_SIZE = 1024 * 1024  # 1 MiB reads: large enough to amortize I/O
DEFAULT_HEADER_CAP = 1024 * 1024  # headers larger than this are treated as body

ESCAPING_MODES = ("mboxrd", "mboxo", "none")

# A real mbox separator: "From ", an envelope token, then an asctime date.
# Gmail Takeout writes e.g. "From 1604289821235122186@xxx Fri Oct 30 09:33:41
# +0000 2020"; classic MTAs write "From alice@example.test Thu Jan  9 09:00:00
# 2020". Both match; prose lines starting with "From " do not.
_FROM_LINE_RE = re.compile(
    rb"^From \S+ +"
    rb"(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun) "
    rb"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) "
    rb"[ 0-3]?\d [0-2]\d:[0-5]\d(?::[0-6]\d)? "
    rb"(?:[+-]\d{4} )?"
    rb"\d{4}\s*$"
)

_STUFFED_RD_RE = re.compile(rb"^>+From ")

_BLANK_LINES = (b"\n", b"\r\n")


def is_from_line(line: bytes) -> bool:
    """True if ``line`` is a plausible mbox message separator."""
    return _FROM_LINE_RE.match(line) is not None


def unstuff(line: bytes, mode: str) -> bytes:
    """Reverse From-line escaping on one body line.

    ``mboxrd`` strips one ``>`` from any ``>+From `` run (fully reversible);
    ``mboxo`` only rewrites ``>From `` (the lossy classic); ``none`` passes
    bodies through untouched for exports that never escaped anything.
    """
    if mode == "mboxrd":
        if _STUFFED_RD_RE.match(line):
            return line[1:]
    elif mode == "mboxo":
        if line.startswith(b">From "):
            return line[1:]
    elif mode != "none":
        raise ValueError(f"unknown escaping mode: {mode!r}")
    return line


def iter_lines(fp: BinaryIO, chunk_size: int = DEFAULT_CHUNK_SIZE) -> Iterator[bytes]:
    """Yield lines (terminators included) from fixed-size binary reads.

    Unlike iterating the file object directly, this never trusts the input
    to be seekable or text-decodable, and a pathological multi-gigabyte
    "line" costs memory proportional to that one line only — partial line
    pieces are collected in a list and joined once, avoiding quadratic
    re-copying.
    """
    pending: List[bytes] = []
    while True:
        chunk = fp.read(chunk_size)
        if not chunk:
            break
        start = 0
        while True:
            newline = chunk.find(b"\n", start)
            if newline == -1:
                rest = chunk[start:]
                if rest:
                    pending.append(rest)
                break
            piece = chunk[start:newline + 1]
            if pending:
                pending.append(piece)
                yield b"".join(pending)
                pending.clear()
            else:
                yield piece
            start = newline + 1
    if pending:
        yield b"".join(pending)  # final line without trailing newline


class MboxMessage:
    """One message streamed out of an mbox.

    Headers are fully parsed and safe to inspect at any time; the body is a
    single-shot stream (:meth:`iter_body`) that must be consumed before the
    reader can advance — advancing the reader drains it automatically, so
    ``scan``-style passes that never touch bodies still work and still get
    accurate byte counts.
    """

    __slots__ = (
        "seq", "from_line", "header_bytes", "header_sep", "headers",
        "truncated_headers", "body_bytes", "_body_iter", "_consumed",
    )

    def __init__(
        self,
        seq: int,
        from_line: bytes,
        header_bytes: bytes,
        header_sep: bytes,
        headers: HeaderBlock,
        truncated_headers: bool,
        body_iter: Iterator[bytes],
    ):
        self.seq = seq
        self.from_line = from_line
        self.header_bytes = header_bytes
        self.header_sep = header_sep
        self.headers = headers
        self.truncated_headers = truncated_headers
        self.body_bytes = 0
        self._body_iter = body_iter
        self._consumed = False

    def iter_body(self) -> Iterator[bytes]:
        """Yield body lines (unstuffed, terminators preserved). Single-shot."""
        if self._consumed:
            raise BodyConsumedError(
                f"body of message #{self.seq} was already consumed"
            )
        self._consumed = True
        return self._body_iter

    def drain(self) -> int:
        """Consume (or finish consuming) the body; return its total bytes."""
        if not self._consumed:
            self._consumed = True
        for _ in self._body_iter:
            pass
        return self.body_bytes

    @property
    def size(self) -> int:
        """Header + body bytes (valid once the body has been drained)."""
        return len(self.header_bytes) + self.body_bytes


class MboxReader:
    """Iterate messages of an mbox stream in constant memory.

    ``escaping`` selects how body lines were From-stuffed (default
    ``mboxrd``); ``header_cap`` bounds how many header bytes are buffered
    per message before the remainder is treated as body and the message is
    marked ``truncated_headers``.
    """

    def __init__(
        self,
        fp: BinaryIO,
        escaping: str = "mboxrd",
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        header_cap: int = DEFAULT_HEADER_CAP,
    ):
        if escaping not in ESCAPING_MODES:
            raise ValueError(
                f"escaping must be one of {ESCAPING_MODES}, got {escaping!r}"
            )
        self.escaping = escaping
        self.header_cap = header_cap
        self._lines = iter_lines(fp, chunk_size)
        self._pushback: Optional[bytes] = None
        self._eof = False
        self._current: Optional[MboxMessage] = None
        self._seq = 0
        self._started = False

    def __iter__(self) -> "MboxReader":
        return self

    def __next__(self) -> MboxMessage:
        if self._current is not None:
            self._current.drain()
            self._current = None
        from_line = self._next_from_line()
        if from_line is None:
            raise StopIteration
        header_bytes, header_sep, truncated = self._read_headers()
        headers = HeaderBlock.parse(header_bytes)
        message = MboxMessage(
            seq=self._seq,
            from_line=from_line,
            header_bytes=header_bytes,
            header_sep=header_sep,
            headers=headers,
            truncated_headers=truncated,
            body_iter=iter(()),  # replaced below; placeholder for __init__
        )
        message._body_iter = self._body_lines(message)
        self._seq += 1
        self._current = message
        return message

    # -- internals ---------------------------------------------------------

    def _next_line(self) -> Optional[bytes]:
        if self._pushback is not None:
            line, self._pushback = self._pushback, None
            return line
        if self._eof:
            return None
        try:
            return next(self._lines)
        except StopIteration:
            self._eof = True
            return None

    def _next_from_line(self) -> Optional[bytes]:
        """Position on the next separator; validate the very first one."""
        while True:
            line = self._next_line()
            if line is None:
                return None
            if not self._started:
                if line in _BLANK_LINES:
                    continue  # tolerate leading blank lines
                if not is_from_line(line):
                    raise NotAnMboxError(
                        "input does not start with a valid mbox 'From ' "
                        "separator line — is this really an mbox file?"
                    )
                self._started = True
                return line
            # After the first message the body iterator only pushes back
            # lines it already validated as separators.
            return line

    def _read_headers(self) -> "tuple[bytes, bytes, bool]":
        parts: List[bytes] = []
        length = 0
        while True:
            line = self._next_line()
            if line is None:
                return b"".join(parts), b"\n", False
            if line in _BLANK_LINES:
                return b"".join(parts), line, False
            if length + len(line) > self.header_cap:
                # Pathological header block: stop buffering, hand the rest
                # (including this line) to the body stream.
                self._pushback = line
                return b"".join(parts), b"\n", True
            parts.append(line)
            length += len(line)

    def _body_lines(self, message: MboxMessage) -> Iterator[bytes]:
        """Yield unstuffed body lines until the next separator or EOF.

        A blank line is held back one step: if the following line is a valid
        separator, the blank was the inter-message gap and is dropped; the
        single trailing blank before EOF is dropped the same way. Real blank
        lines inside bodies (there is always a non-blank or second blank
        after them) are re-emitted untouched.
        """
        pending_blank: Optional[bytes] = None
        at_start = True
        while True:
            line = self._next_line()
            if line is None:
                return  # EOF; a held blank was the file's trailing separator
            if line in _BLANK_LINES:
                if pending_blank is not None:
                    message.body_bytes += len(pending_blank)
                    yield pending_blank
                pending_blank = line
                at_start = False
                continue
            if (pending_blank is not None or at_start) and is_from_line(line):
                # `at_start` covers empty-body messages, where the blank line
                # ending the headers doubles as the message separator.
                self._pushback = line
                return
            if pending_blank is not None:
                message.body_bytes += len(pending_blank)
                yield pending_blank
                pending_blank = None
            at_start = False
            out = unstuff(line, self.escaping)
            message.body_bytes += len(out)
            yield out


def open_mbox(path: str) -> BinaryIO:
    """Open an mbox source for streaming: a path, ``-`` for stdin, or ``.gz``.

    Takeout offers .tgz/.zip downloads; once extracted, users often re-gzip
    the giant mbox to save disk — transparent gzip means they never have to
    inflate it again just to slice it.
    """
    if path == "-":
        return sys.stdin.buffer
    if path.endswith(".gz"):
        return gzip.open(path, "rb")  # type: ignore[return-value]
    return open(path, "rb")
