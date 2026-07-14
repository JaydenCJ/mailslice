"""Orchestration: pump messages from a reader through the router to writers.

This is the only module that touches reader, router, writers, and report at
once, and it stays deliberately thin: per-message metadata extraction, the
dry-run short-circuit, the stream-once-copy-rest strategy for multi-label
delivery, and progress callbacks. All policy lives in the modules it wires
together.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Dict, Optional, Union

from .headers import decode_mime_words, message_date
from .labels import gmail_labels, maildir_flags
from .mboxstream import MboxMessage, MboxReader
from .report import SplitReport
from .router import Router
from .writers import EmlWriter, MaildirWriter

__all__ = ["FORMATS", "scan", "split"]

FORMATS = ("maildir", "eml")

ProgressCallback = Callable[[int], None]

_PROGRESS_EVERY = 1000


def _is_malformed(message: MboxMessage) -> bool:
    """Messages we deliver anyway but flag in the report."""
    return message.truncated_headers or len(message.headers) == 0


def scan(
    reader: MboxReader,
    limit: Optional[int] = None,
    progress: Optional[ProgressCallback] = None,
) -> SplitReport:
    """Inventory an mbox without writing anything.

    Buckets count every label a message carries (state labels like Unread
    included), so a message with three labels appears in three rows; the
    totals line still counts it once.
    """
    report = SplitReport()
    for message in reader:
        year = _year_of(message)
        year_display = str(year) if year is not None else "no-date"
        message.drain()
        labels = gmail_labels(message.headers) or ["Unlabeled"]
        for label in labels:
            report.add(label, year_display, message.size)
        report.note_message(message.size, year, _is_malformed(message))
        if progress is not None and report.messages % _PROGRESS_EVERY == 0:
            progress(report.messages)
        if limit is not None and report.messages >= limit:
            break
    return report


def split(
    reader: MboxReader,
    out_dir: Union[str, Path],
    fmt: str,
    router: Router,
    dry_run: bool = False,
    progress: Optional[ProgressCallback] = None,
) -> SplitReport:
    """Split an mbox into per-label/per-year maildirs or EML directories.

    Each message's body is streamed exactly once. When ``--all-labels``
    routes a message to several directories, the first destination receives
    the stream and the rest are file copies of the finished result — the
    source mbox is never re-read or buffered.
    """
    if fmt not in FORMATS:
        raise ValueError(f"format must be one of {FORMATS}, got {fmt!r}")
    out_root = Path(out_dir)
    report = SplitReport()
    writers: Dict[str, Union[MaildirWriter, EmlWriter]] = {}

    for message in reader:
        headers = message.headers
        labels = gmail_labels(headers)
        date = message_date(headers, message.from_line)
        year = None if date is None else date.year
        route = router.route(labels, year)

        if route.skipped:
            message.drain()
            report.note_skip(route.skip_reason or "skipped")
            report.note_message(message.size, year, _is_malformed(message))
            if progress is not None and report.messages % _PROGRESS_EVERY == 0:
                progress(report.messages)
            continue

        if dry_run:
            message.drain()
            # Predict exactly what a real run would write: header block +
            # the blank separator line + unstuffed body (see _write_stream).
            would_write = message.size + len(message.header_sep)
            for label, year_display, _rel_dir in route.destinations:
                report.add(label, year_display, would_write)
        else:
            flags = maildir_flags(labels)
            # Decode RFC 2047 words so EML filenames slug the readable
            # subject, not "=?UTF-8?B?...?=" transfer-encoding artifacts.
            subject = decode_mime_words(headers.get("Subject"))
            first_path: Optional[Path] = None
            for label, year_display, rel_dir in route.destinations:
                writer = writers.get(rel_dir)
                if writer is None:
                    writer = _make_writer(fmt, out_root / rel_dir)
                    writers[rel_dir] = writer
                if first_path is None:
                    first_path, written = _deliver_stream(
                        writer, message, date, flags, subject
                    )
                else:
                    _, written = _deliver_copy(
                        writer, first_path, date, flags, subject
                    )
                report.add(label, year_display, written)

        report.note_message(message.size, year, _is_malformed(message))
        if progress is not None and report.messages % _PROGRESS_EVERY == 0:
            progress(report.messages)
    return report


def _year_of(message: MboxMessage) -> Optional[int]:
    date = message_date(message.headers, message.from_line)
    return None if date is None else date.year


def _make_writer(fmt: str, root: Path) -> Union[MaildirWriter, EmlWriter]:
    if fmt == "maildir":
        return MaildirWriter(root)
    return EmlWriter(root)


def _deliver_stream(writer, message, date, flags, subject):
    if isinstance(writer, MaildirWriter):
        return writer.deliver(
            date, flags, message.header_bytes, message.header_sep,
            message.iter_body(),
        )
    return writer.deliver(
        date, subject, message.header_bytes, message.header_sep,
        message.iter_body(),
    )


def _deliver_copy(writer, source, date, flags, subject):
    if isinstance(writer, MaildirWriter):
        return writer.deliver_copy(source, date, flags)
    return writer.deliver_copy(source, date, subject)
