"""Gmail label semantics: parsing, classification, and safe filesystem paths.

Google Takeout serializes every label a message carries into a single
``X-Gmail-Labels`` header — comma-separated, optionally double-quoted when a
label itself contains a comma, RFC 2047-encoded when non-ASCII, and with
Gmail's nested labels spelled ``Parent/Child``. This module turns that header
into routing decisions: which labels are folders, which are per-message state
(and become maildir flags instead), which single label "owns" a message, and
how a label maps onto a directory path that is safe on every filesystem.
"""

from __future__ import annotations

import re
from typing import Iterable, List

from .headers import HeaderBlock, decode_mime_words

__all__ = [
    "UNLABELED",
    "parse_label_header",
    "gmail_labels",
    "is_flag_label",
    "is_system_label",
    "folder_labels",
    "primary_label",
    "maildir_flags",
    "sanitize_segment",
    "label_to_path",
]

UNLABELED = "Unlabeled"

# Per-message state, not mailboxes: these never become directories.
# They map onto maildir flags in maildir_flags() below.
_FLAG_LABELS = frozenset({"unread", "opened", "starred", "important"})

# Labels Gmail manages itself. They can still be folders (a message that is
# only "Sent" belongs in Sent/), but user labels win when picking the
# primary label for a message.
_SYSTEM_FOLDER_LABELS = frozenset({
    "inbox", "sent", "archived", "drafts", "draft", "spam", "trash", "bin",
    "chat", "chats", "snoozed", "scheduled",
})

# Windows-reserved device names; a directory called "con" bricks a copy to
# NTFS, so these get an underscore prefix during sanitization.
_RESERVED_NAMES = frozenset(
    {"con", "prn", "aux", "nul"}
    | {f"com{i}" for i in range(1, 10)}
    | {f"lpt{i}" for i in range(1, 10)}
)

_UNSAFE_CHARS = re.compile(r'[\\:*?"<>|\x00-\x1f\x7f]')

_MAX_SEGMENT_LEN = 80


def parse_label_header(raw: str) -> List[str]:
    """Split an ``X-Gmail-Labels`` value into individual labels.

    Handles double-quoted labels containing commas (``"Trips, 2020"``),
    trims whitespace, drops empties, and de-duplicates while preserving
    the original order (the order encodes Gmail's own priority).
    """
    labels: List[str] = []
    seen = set()
    current: List[str] = []
    in_quotes = False
    for ch in raw:
        if ch == '"':
            in_quotes = not in_quotes
        elif ch == "," and not in_quotes:
            _push(labels, seen, "".join(current))
            current = []
        else:
            current.append(ch)
    _push(labels, seen, "".join(current))
    return labels


def _push(labels: List[str], seen: set, candidate: str) -> None:
    label = candidate.strip()
    if label and label.lower() not in seen:
        seen.add(label.lower())
        labels.append(label)


def gmail_labels(headers: HeaderBlock) -> List[str]:
    """All labels on a message, RFC 2047-decoded, in header order."""
    raw = headers.get("X-Gmail-Labels")
    if not raw:
        return []
    return parse_label_header(decode_mime_words(raw))


def is_flag_label(label: str) -> bool:
    """True for state labels (Unread/Starred/...) that never become folders."""
    return label.lower() in _FLAG_LABELS


def is_system_label(label: str) -> bool:
    """True for labels Gmail manages, including ``Category ...`` tabs."""
    lower = label.lower()
    return (
        lower in _SYSTEM_FOLDER_LABELS
        or lower in _FLAG_LABELS
        or lower.startswith("category ")
    )


def folder_labels(labels: Iterable[str]) -> List[str]:
    """The labels eligible to become directories (state labels removed)."""
    return [label for label in labels if not is_flag_label(label)]


def primary_label(labels: Iterable[str]) -> str:
    """The single label that owns a message in the default (non-``--all-labels``) mode.

    User labels beat system labels — someone who labeled a message
    ``Receipts`` wants it in ``Receipts/``, not ``Inbox/`` — and within each
    tier the first label in header order wins. Messages with no folder label
    at all land in ``Unlabeled``.
    """
    folders = folder_labels(labels)
    for label in folders:
        if not is_system_label(label):
            return label
    if folders:
        return folders[0]
    return UNLABELED


def maildir_flags(labels: Iterable[str]) -> str:
    """Map Gmail state labels onto standard maildir info flags.

    ``S`` (seen) unless Unread, ``F`` (flagged) for Starred, ``T`` (trashed)
    for Trash/Bin, ``D`` (draft) for Drafts. Flags are emitted in ASCII
    order as the maildir spec requires.
    """
    lowered = {label.lower() for label in labels}
    flags = set()
    if "unread" not in lowered:
        flags.add("S")
    if "starred" in lowered:
        flags.add("F")
    if lowered & {"trash", "bin"}:
        flags.add("T")
    if lowered & {"drafts", "draft"}:
        flags.add("D")
    return "".join(sorted(flags))


def sanitize_segment(segment: str) -> str:
    """Make one path segment safe on POSIX, NTFS, and APFS alike.

    Replaces separator/control/reserved characters with ``_``, trims
    trailing dots and spaces (NTFS strips them silently, which would merge
    distinct labels), guards Windows device names, hides nothing behind a
    leading dot, and caps length so deeply nested labels cannot overflow
    PATH_MAX. Never returns an empty string.
    """
    cleaned = _UNSAFE_CHARS.sub("_", segment).strip()
    cleaned = cleaned.rstrip(". ")
    if cleaned.startswith("."):
        cleaned = "_" + cleaned.lstrip(".")
    if cleaned.lower() in _RESERVED_NAMES:
        cleaned = "_" + cleaned
    if len(cleaned) > _MAX_SEGMENT_LEN:
        cleaned = cleaned[:_MAX_SEGMENT_LEN].rstrip(". ")
    return cleaned or "_"


def label_to_path(label: str) -> str:
    """Convert a (possibly nested) Gmail label into a relative directory path.

    ``Work/Projects/Q3`` becomes three nested directories; each segment is
    sanitized independently so ``Re: invoices?`` still yields a valid name.
    """
    segments = [sanitize_segment(part) for part in label.split("/") if part.strip()]
    if not segments:
        return "_"  # a label made only of slashes/whitespace
    return "/".join(segments)
