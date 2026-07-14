#!/usr/bin/env python3
"""Generate a deterministic, Takeout-shaped sample mbox.

Usage:  python examples/make_sample_mbox.py sample.mbox

The output reproduces the quirks mailslice is built to survive: Gmail-style
``From `` separator lines with numeric timezones, ``X-Gmail-Labels`` headers
(nested labels, quoted labels with commas, RFC 2047-encoded non-ASCII
labels), mboxrd From-stuffing in bodies, a body paragraph starting with a
bare ``From `` that must NOT be treated as a message boundary, a CRLF
message, and a message with no Date header at all. Every byte is fixed, so
repeated runs are identical — handy for tests and demos.
"""

from __future__ import annotations

import sys

MESSAGES = [
    {
        "from_line": "From 1577955600000000001@xxx Thu Jan  2 09:00:00 +0000 2020",
        "headers": [
            "From: Alice <alice@example.test>",
            "To: you@example.test",
            "Subject: Kickoff notes",
            "Date: Thu, 2 Jan 2020 09:00:00 +0000",
            "Message-ID: <kickoff-1@example.test>",
            "X-Gmail-Labels: Inbox,Important,Work/Projects",
        ],
        "body": [
            "Notes from the kickoff.",
            "",
            ">From the archive: last year's plan still applies.",
            "From here on we meet weekly.",
        ],
    },
    {
        "from_line": "From 1583053200000000002@xxx Sun Mar  1 08:00:00 +0000 2020",
        "headers": [
            "From: Bob <bob@example.test>",
            "To: you@example.test",
            "Subject: Receipt #4411",
            "Date: Sun, 1 Mar 2020 08:00:00 +0000",
            "Message-ID: <receipt-4411@example.test>",
            'X-Gmail-Labels: "Receipts, 2020",Archived,Opened',
        ],
        "body": [
            "Your order has shipped.",
            "Total: 42.00",
        ],
    },
    {
        "from_line": "From 1593595800000000003@xxx Wed Jul  1 09:30:00 +0000 2020",
        "headers": [
            "From: Carol <carol@example.test>",
            "To: you@example.test",
            "Subject: =?UTF-8?B?6KuL5rGC5pu444Gu56K66KqN?=",
            "Date: Wed, 1 Jul 2020 09:30:00 +0000",
            "Message-ID: <seikyu-7@example.test>",
            "X-Gmail-Labels: =?UTF-8?B?6KuL5rGC5pu4?=,Inbox,Unread",
        ],
        "body": [
            "Please find the invoice attached.",
        ],
    },
    {
        "from_line": "From 1610702100000000004@xxx Fri Jan 15 09:15:00 +0000 2021",
        "headers": [
            "From: you@example.test",
            "To: Dave <dave@example.test>",
            "Subject: Re: lunch?",
            "Date: Fri, 15 Jan 2021 09:15:00 +0000",
            "Message-ID: <lunch-1@example.test>",
            "X-Gmail-Labels: Sent,Opened",
        ],
        "body": [
            "Sure, noon works.",
        ],
    },
    {
        # CRLF line endings end to end, like mail relayed by Windows MTAs.
        "from_line": "From 1614589200000000005@xxx Mon Mar  1 09:00:00 +0000 2021",
        "headers": [
            "From: Erin <erin@example.test>",
            "To: you@example.test",
            "Subject: Quarterly summary",
            "Date: Mon, 1 Mar 2021 09:00:00 +0000",
            "Message-ID: <q1-summary@example.test>",
            "X-Gmail-Labels: Work/Projects/Q1,Starred",
        ],
        "body": [
            "Numbers attached below.",
            "",
            "Q1 closed green.",
        ],
        "eol": "\r\n",
    },
    {
        # No Date header and no Received: only the From line dates this one.
        "from_line": "From 1623834000000000006@xxx Wed Jun 16 09:00:00 +0000 2021",
        "headers": [
            "From: Frank <frank@example.test>",
            "To: you@example.test",
            "Subject: (no date header)",
            "Message-ID: <undated-1@example.test>",
            "X-Gmail-Labels: Inbox,Unread",
        ],
        "body": [
            "This message has no Date header.",
        ],
    },
    {
        "from_line": "From 1631610000000000007@xxx Tue Sep 14 09:00:00 +0000 2021",
        "headers": [
            "From: noreply@example.test",
            "To: you@example.test",
            "Subject: You may have won",
            "Date: Tue, 14 Sep 2021 09:00:00 +0000",
            "Message-ID: <spam-1@example.test>",
            "X-Gmail-Labels: Spam,Unread",
        ],
        "body": [
            "Click here. Or better: do not.",
        ],
    },
    {
        "from_line": "From 1640163600000000008@xxx Wed Dec 22 09:00:00 +0000 2021",
        "headers": [
            "From: Grace <grace@example.test>",
            "To: you@example.test",
            "Subject: Trip photos",
            "Date: Wed, 22 Dec 2021 09:00:00 +0000",
            "Message-ID: <trip-1@example.test>",
            "X-Gmail-Labels: Travel,Inbox,Starred",
        ],
        "body": [
            "Photos from the trip are in the shared album.",
            "",
            "From the summit the view was unreal (this line is prose,",
            "not a message boundary, because it has no envelope+date).",
        ],
    },
]


def render() -> bytes:
    out = []
    for msg in MESSAGES:
        eol = msg.get("eol", "\n")
        out.append(msg["from_line"] + "\n")  # separators are always LF
        for header in msg["headers"]:
            out.append(header + eol)
        out.append(eol)
        for line in msg["body"]:
            out.append(line + eol)
        out.append("\n")  # inter-message separator blank line
    return "".join(out).encode("utf-8")


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: make_sample_mbox.py OUTPUT.mbox", file=sys.stderr)
        return 2
    data = render()
    with open(sys.argv[1], "wb") as fp:
        fp.write(data)
    print(f"wrote {sys.argv[1]} ({len(data)} bytes, {len(MESSAGES)} messages)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
