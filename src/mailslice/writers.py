"""Streaming maildir and EML writers.

Both writers accept the body as an iterator of lines and never hold a whole
message in memory — a 2 GB attachment flows chunk-by-chunk from the mbox to
its destination file. Written message content is identical in both formats
(headers, blank separator, unstuffed body; no mbox ``From `` envelope line),
so duplicating a message into several label directories (``--all-labels``)
streams it once and then copies the finished file instead of re-reading the
source.

Maildir deliveries follow the spec's safety dance: write into ``tmp/``, then
atomically rename into ``cur/`` with an info suffix carrying the flags derived
from Gmail's state labels. Filenames are deterministic (message timestamp +
monotonic sequence + fixed host tag) so re-running a split is reproducible.
"""

from __future__ import annotations

import calendar
import os
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterator, Optional, Tuple

__all__ = ["MaildirWriter", "EmlWriter", "slugify"]

_HOST_TAG = "mailslice"

_SLUG_STRIP = re.compile(r"[^A-Za-z0-9._-]+")

_MAX_SLUG_LEN = 40


def slugify(text: str) -> str:
    """Reduce a subject to a filesystem-friendly slug (may be empty)."""
    slug = _SLUG_STRIP.sub("-", text.strip()).strip("-.")
    return slug[:_MAX_SLUG_LEN].rstrip("-.")


def _write_stream(
    path: Path,
    header_bytes: bytes,
    header_sep: bytes,
    body_iter: Iterator[bytes],
) -> int:
    written = 0
    with open(path, "wb") as out:
        out.write(header_bytes)
        out.write(header_sep)
        written += len(header_bytes) + len(header_sep)
        for line in body_iter:
            out.write(line)
            written += len(line)
    return written


class MaildirWriter:
    """Deliver messages into one maildir (``cur``/``new``/``tmp``) root."""

    def __init__(self, root: Path):
        self.root = Path(root)
        for sub in ("cur", "new", "tmp"):
            (self.root / sub).mkdir(parents=True, exist_ok=True)
        self._seq = 0

    def _unique_name(self, date: Optional[datetime]) -> str:
        if date is None:
            epoch = 0
        elif date.tzinfo is None:
            # Treat naive dates as UTC so names are machine-independent.
            epoch = calendar.timegm(date.timetuple())
        else:
            epoch = int(date.timestamp())
        self._seq += 1
        return f"{epoch}.M{self._seq:06d}.{_HOST_TAG}"

    def deliver(
        self,
        date: Optional[datetime],
        flags: str,
        header_bytes: bytes,
        header_sep: bytes,
        body_iter: Iterator[bytes],
    ) -> Tuple[Path, int]:
        """Stream one message in; return (final path, bytes written).

        Imported mail is historical, so it lands in ``cur/`` (already seen
        by a client) rather than ``new/``, with flags in the standard
        ``:2,`` info suffix.
        """
        name = self._unique_name(date)
        tmp_path = self.root / "tmp" / name
        written = _write_stream(tmp_path, header_bytes, header_sep, body_iter)
        final_path = self.root / "cur" / f"{name}:2,{flags}"
        os.replace(tmp_path, final_path)
        return final_path, written

    def deliver_copy(
        self, source: Path, date: Optional[datetime], flags: str
    ) -> Tuple[Path, int]:
        """Deliver a copy of an already-written message file."""
        name = self._unique_name(date)
        tmp_path = self.root / "tmp" / name
        shutil.copyfile(source, tmp_path)
        final_path = self.root / "cur" / f"{name}:2,{flags}"
        os.replace(tmp_path, final_path)
        return final_path, final_path.stat().st_size


class EmlWriter:
    """Write one ``.eml`` file per message into a flat directory."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._names: Dict[str, int] = {}

    def _unique_path(self, date: Optional[datetime], subject: str) -> Path:
        stamp = date.strftime("%Y%m%d-%H%M%S") if date is not None else "no-date"
        slug = slugify(subject) or "no-subject"
        base = f"{stamp}-{slug}"
        count = self._names.get(base, 0) + 1
        self._names[base] = count
        # First "Re: lunch" is 20200101-093000-Re-lunch.eml; collisions get
        # -2, -3, ... so identical subjects on the same second never clobber.
        name = base if count == 1 else f"{base}-{count}"
        return self.root / f"{name}.eml"

    def deliver(
        self,
        date: Optional[datetime],
        subject: str,
        header_bytes: bytes,
        header_sep: bytes,
        body_iter: Iterator[bytes],
    ) -> Tuple[Path, int]:
        """Stream one message to ``<stamp>-<subject-slug>.eml``."""
        path = self._unique_path(date, subject)
        written = _write_stream(path, header_bytes, header_sep, body_iter)
        return path, written

    def deliver_copy(
        self, source: Path, date: Optional[datetime], subject: str
    ) -> Tuple[Path, int]:
        """Deliver a copy of an already-written message file."""
        path = self._unique_path(date, subject)
        shutil.copyfile(source, path)
        return path, path.stat().st_size
