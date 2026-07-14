"""Header parsing and date recovery.

Takeout headers are messy in very specific ways — folded values, raw 8-bit
bytes, encoded words with bogus charsets, missing Date headers — and every
mess here maps to a real message that must still be routed somewhere.
"""

from datetime import datetime, timezone

from mailslice.headers import (
    HeaderBlock,
    decode_mime_words,
    message_date,
    message_year,
    parse_from_line_date,
)


def block(*lines: str) -> HeaderBlock:
    return HeaderBlock.parse("\n".join(lines).encode("utf-8"))


class TestHeaderBlock:
    def test_lookup_is_case_insensitive_with_defaults(self):
        headers = block("X-Gmail-Labels: Inbox", "Subject: hello")
        assert headers.get("x-gmail-labels") == "Inbox"
        assert "X-GMAIL-LABELS" in headers
        assert headers.get("Date", "fallback") == "fallback"

    def test_folded_value_unfolds_with_single_space(self):
        headers = block("Subject: a very", "\tlong subject", " indeed")
        assert headers.get("Subject") == "a very long subject indeed"

    def test_multiple_received_headers_kept_in_order(self):
        headers = block(
            "Received: from relay-b; Fri, 15 Jan 2021 09:15:02 +0000",
            "Received: from relay-a; Fri, 15 Jan 2021 09:15:00 +0000",
        )
        assert len(headers.get_all("Received")) == 2
        assert "relay-b" in headers.get_all("Received")[0]

    def test_malformed_encodings_and_lines_never_fatal(self):
        headers = block("garbage line no colon", "Subject: ok")
        assert headers.get("Subject") == "ok"
        assert len(headers) == 1
        assert len(HeaderBlock.parse(b"")) == 0
        # Bare 8-bit bytes (not valid UTF-8) and CRLF must not crash the run.
        headers = HeaderBlock.parse(b"Subject: caf\xe9\r\nTo: you@example.test\r\n")
        assert headers.get("Subject") == "café"
        assert headers.get("To") == "you@example.test"


class TestDecodeMimeWords:
    def test_utf8_encoded_words_decoded_in_context(self):
        assert decode_mime_words("=?UTF-8?B?6KuL5rGC5pu4?=") == "請求書"
        mixed = decode_mime_words("=?UTF-8?B?6KuL5rGC5pu4?=,Inbox")
        assert "請求書" in mixed and "Inbox" in mixed

    def test_plain_ascii_and_unknown_charsets_degrade_gracefully(self):
        assert decode_mime_words("Inbox,Sent") == "Inbox,Sent"
        # A charset Python has never heard of must not abort a 40 GB run.
        result = decode_mime_words("=?x-mystery-charset?B?aGVsbG8=?=")
        assert isinstance(result, str) and result


class TestFromLineDate:
    def test_gmail_and_classic_separator_dates_parsed(self):
        assert parse_from_line_date(
            b"From 1604289821235122186@xxx Fri Oct 30 09:33:41 +0000 2020\n"
        ) == datetime(2020, 10, 30, 9, 33, 41)
        assert parse_from_line_date(
            b"From alice@example.test Thu Jan  2 09:00:00 2020\n"
        ) == datetime(2020, 1, 2, 9, 0, 0)

    def test_invalid_dates_return_none(self):
        # Feb 30 exists in corrupted archives; headers, in every archive.
        assert parse_from_line_date(
            b"From a@example.test Tue Feb 30 09:00:00 2021\n"
        ) is None
        assert parse_from_line_date(b"From: alice@example.test\n") is None


class TestMessageDate:
    def test_date_header_wins_over_received(self):
        headers = block(
            "Date: Fri, 15 Jan 2021 09:15:00 +0000",
            "Received: from relay; Thu, 1 Apr 1999 00:00:00 +0000",
        )
        assert message_date(headers) == datetime(
            2021, 1, 15, 9, 15, tzinfo=timezone.utc
        )

    def test_newest_received_used_when_date_missing(self):
        headers = block(
            "Received: from relay-b; Fri, 15 Jan 2021 09:15:02 +0000",
            "Received: from relay-a; Thu, 2 Jan 2020 09:00:00 +0000",
        )
        assert message_year(headers) == 2021

    def test_from_line_is_the_last_resort(self):
        headers = block("Subject: undated")
        assert message_year(
            headers, b"From x@xxx Wed Jun 16 09:00:00 +0000 2021\n"
        ) == 2021

    def test_garbled_dates_fall_through_then_give_up_cleanly(self):
        headers = block(
            "Date: yesterday-ish",
            "Received: from relay; Thu, 2 Jan 2020 09:00:00 +0000",
        )
        assert message_year(headers) == 2020
        hopeless = block("Date: not a date at all", "Subject: x")
        assert message_date(hopeless, b"From: not a separator\n") is None
        assert message_year(hopeless) is None
