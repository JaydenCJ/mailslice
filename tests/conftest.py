"""Shared fixtures: build small, precise Takeout-shaped mboxes in memory.

Every test constructs its input from these helpers instead of fixture files,
so each test states exactly the quirk it exercises (a quoted label, a CRLF
body, a missing Date header) and nothing else.
"""

from __future__ import annotations

import io
from typing import Iterable, Optional

import pytest

from mailslice.mboxstream import MboxReader

DEFAULT_FROM_LINE = "From 1577955600000000001@xxx Thu Jan  2 09:00:00 +0000 2020"


def make_message(
    subject: str = "Hello",
    labels: Optional[str] = "Inbox",
    date: Optional[str] = "Thu, 2 Jan 2020 09:00:00 +0000",
    body: Iterable[str] = ("hello world",),
    from_line: str = DEFAULT_FROM_LINE,
    extra_headers: Iterable[str] = (),
    eol: str = "\n",
) -> str:
    """Render one mbox message (From line, headers, blank line, body)."""
    headers = [
        "From: alice@example.test",
        "To: you@example.test",
        f"Subject: {subject}",
    ]
    if date is not None:
        headers.append(f"Date: {date}")
    if labels is not None:
        headers.append(f"X-Gmail-Labels: {labels}")
    headers.extend(extra_headers)
    parts = [from_line + "\n"]
    parts.extend(h + eol for h in headers)
    parts.append(eol)
    parts.extend(line + eol for line in body)
    return "".join(parts)


def make_mbox(*messages: str) -> bytes:
    """Join rendered messages with the separating blank line mbox requires."""
    return "\n".join(messages).encode("utf-8") + b"\n"


def reader_for(data: bytes, **kwargs) -> MboxReader:
    """An MboxReader over an in-memory stream (no filesystem, no network)."""
    return MboxReader(io.BytesIO(data), **kwargs)


@pytest.fixture
def simple_mbox() -> bytes:
    """Two plain messages, one 2020 Inbox and one 2021 Sent."""
    return make_mbox(
        make_message(subject="first", labels="Inbox", body=("one",)),
        make_message(
            subject="second",
            labels="Sent",
            date="Fri, 15 Jan 2021 09:15:00 +0000",
            from_line="From 1610702100000000004@xxx Fri Jan 15 09:15:00 +0000 2021",
            body=("two",),
        ),
    )
