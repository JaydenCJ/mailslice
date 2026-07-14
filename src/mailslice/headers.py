"""Tolerant, allocation-light RFC 5322 header parsing.

mailslice only ever needs a handful of headers per message (labels, date,
subject), so this module parses the raw header block into a small list of
unfolded name/value pairs instead of building a full ``email.message.Message``
— the stdlib parser materializes and re-encodes the entire message, which
defeats constant-memory streaming. Real Takeout exports contain plenty of
malformed headers (bare 8-bit bytes, missing colons, folded garbage); every
parse path here degrades gracefully instead of raising.
"""

from __future__ import annotations

import re
from datetime import datetime
from email.header import decode_header
from email.utils import parsedate_to_datetime
from typing import Iterator, List, Optional, Tuple

__all__ = [
    "HeaderBlock",
    "decode_mime_words",
    "parse_from_line_date",
    "message_date",
    "message_year",
]

_MONTHS = {
    "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
    "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12,
}

# Trailing asctime-style date of an mbox From line, with Gmail Takeout's
# optional numeric timezone between seconds and year, e.g.
#   "From 16042898...@xxx Fri Oct 30 09:33:41 +0000 2020"
_FROM_LINE_DATE_RE = re.compile(
    r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
    r" +(\d{1,2}) (\d{2}):(\d{2})(?::(\d{2}))?(?: [+-]\d{4})? (\d{4})\s*$"
)


class HeaderBlock:
    """An ordered, case-insensitive view over one message's raw headers."""

    __slots__ = ("_entries",)

    def __init__(self, entries: List[Tuple[str, str]]):
        self._entries = entries

    @classmethod
    def parse(cls, raw: bytes) -> "HeaderBlock":
        """Parse a raw header block (bytes up to the blank line).

        Folded continuation lines are joined with a single space. Lines
        without a colon (mangled by whatever produced the mbox) are skipped
        rather than fatal. Bytes are decoded as UTF-8 when valid, otherwise
        Latin-1, which never fails and preserves every byte value.
        """
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            text = raw.decode("latin-1")
        entries: List[Tuple[str, str]] = []
        name: Optional[str] = None
        value = ""
        for line in text.splitlines():
            if line[:1] in (" ", "\t"):
                if name is not None:
                    value += " " + line.strip()
                continue
            if name is not None:
                entries.append((name, value))
                name = None
            colon = line.find(":")
            if colon <= 0:
                continue  # tolerate malformed header lines
            name = line[:colon].strip()
            value = line[colon + 1:].strip()
        if name is not None:
            entries.append((name, value))
        return cls(entries)

    def get(self, name: str, default: str = "") -> str:
        """Return the first value of ``name`` (case-insensitive)."""
        wanted = name.lower()
        for key, value in self._entries:
            if key.lower() == wanted:
                return value
        return default

    def get_all(self, name: str) -> List[str]:
        """Return every value of ``name`` in message order."""
        wanted = name.lower()
        return [v for k, v in self._entries if k.lower() == wanted]

    def items(self) -> Iterator[Tuple[str, str]]:
        return iter(self._entries)

    def __contains__(self, name: str) -> bool:
        wanted = name.lower()
        return any(k.lower() == wanted for k, _ in self._entries)

    def __len__(self) -> int:
        return len(self._entries)


def decode_mime_words(value: str) -> str:
    """Decode RFC 2047 encoded words, tolerating every malformed variant.

    Gmail encodes any non-ASCII label or subject this way
    (``=?UTF-8?B?...?=``); a decoder that raises on a single bad charset
    would abort a 40 GB run on one broken message.
    """
    try:
        parts = decode_header(value)
    except Exception:
        return value
    out: List[str] = []
    for data, charset in parts:
        if isinstance(data, bytes):
            try:
                out.append(data.decode(charset or "utf-8", errors="replace"))
            except LookupError:  # unknown charset advertised by the sender
                out.append(data.decode("latin-1", errors="replace"))
        else:
            out.append(data)
    return "".join(out)


def parse_from_line_date(from_line: bytes) -> Optional[datetime]:
    """Extract the asctime date from an mbox ``From `` separator line."""
    text = from_line.decode("ascii", errors="replace")
    match = _FROM_LINE_DATE_RE.search(text)
    if match is None:
        return None
    month, day, hour, minute, second, year = match.groups()
    try:
        return datetime(
            int(year), _MONTHS[month], int(day),
            int(hour), int(minute), int(second or 0),
        )
    except ValueError:  # e.g. "Feb 30" in a corrupted line
        return None


def _parse_rfc_date(value: str) -> Optional[datetime]:
    if not value.strip():
        return None
    try:
        parsed = parsedate_to_datetime(value)
    except Exception:
        return None
    return parsed


def message_date(headers: HeaderBlock, from_line: bytes = b"") -> Optional[datetime]:
    """Best-effort message date, in decreasing order of trust.

    1. the ``Date`` header;
    2. the newest ``Received`` header (first in the block) — its timestamp
       sits after the last ``;``;
    3. the asctime date Gmail writes on the mbox ``From `` line itself.

    Returns ``None`` only when all three are missing or unparseable; such
    messages land in the ``no-date`` bucket rather than being dropped.
    """
    parsed = _parse_rfc_date(headers.get("Date"))
    if parsed is not None:
        return parsed
    for received in headers.get_all("Received"):
        _, _, stamp = received.rpartition(";")
        parsed = _parse_rfc_date(stamp)
        if parsed is not None:
            return parsed
    return parse_from_line_date(from_line)


def message_year(headers: HeaderBlock, from_line: bytes = b"") -> Optional[int]:
    """The year used for ``by year`` routing, or ``None`` for undatable mail."""
    date = message_date(headers, from_line)
    return None if date is None else date.year
