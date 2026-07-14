"""Streaming reader behavior: boundaries, unstuffing, EOLs, error paths.

These tests treat the reader as a black box over crafted byte streams and
assert on the exact bytes that come back out — byte fidelity is the entire
value proposition of an archival tool. Bodies are single-shot streams, so
the helper consumes them in reading order, exactly as a writer would.
"""

import io

import pytest

from mailslice.errors import BodyConsumedError, NotAnMboxError
from mailslice.mboxstream import MboxReader, iter_lines

from conftest import make_mbox, make_message, reader_for


def read_all(data: bytes, **kwargs):
    """[(message, body_bytes), ...] consuming each body before advancing."""
    out = []
    for message in reader_for(data, **kwargs):
        out.append((message, b"".join(message.iter_body())))
    return out


class TestIterLines:
    def test_lines_keep_terminators_and_final_line_may_lack_one(self):
        assert list(iter_lines(io.BytesIO(b"a\nbb\nccc\n"))) == [
            b"a\n", b"bb\n", b"ccc\n",
        ]
        assert list(iter_lines(io.BytesIO(b"a\nb"))) == [b"a\n", b"b"]
        assert list(iter_lines(io.BytesIO(b""))) == []

    def test_chunking_is_invisible_to_line_content(self):
        # A "line" longer than the chunk size must come back intact —
        # this is the constant-memory path for huge base64 attachments.
        data = b"x" * 10_000 + b"\n" + b"tail\n"
        lines = list(iter_lines(io.BytesIO(data), chunk_size=64))
        assert lines == [b"x" * 10_000 + b"\n", b"tail\n"]
        # And every chunk size yields identical output, including when a
        # chunk boundary lands exactly on a newline.
        data = b"ab\ncd\n\nef\n"
        expected = [b"ab\n", b"cd\n", b"\n", b"ef\n"]
        for chunk_size in range(1, 12):
            assert list(iter_lines(io.BytesIO(data), chunk_size=chunk_size)) == expected


class TestMessageIteration:
    def test_messages_split_in_order_with_sequence_numbers(self, simple_mbox):
        messages = read_all(simple_mbox)
        assert [m.headers.get("Subject") for m, _ in messages] == ["first", "second"]
        assert [m.seq for m, _ in messages] == [0, 1]

    def test_bodies_exact_and_separator_blank_excluded(self, simple_mbox):
        (_, first_body), (_, second_body) = read_all(simple_mbox)
        assert first_body == b"one\n"
        assert second_body == b"two\n"

    def test_body_blank_lines_preserved_but_final_separator_dropped(self):
        mbox = make_mbox(make_message(body=("para one", "", "", "para two")))
        ((_, body),) = read_all(mbox)
        assert body == b"para one\n\n\npara two\n"
        # A body genuinely ending with a blank keeps it; only the single
        # trailing separator blank at EOF is removed.
        raw = make_message(body=("end", "")).encode() + b"\n"
        ((_, body),) = read_all(raw)
        assert body == b"end\n\n"

    def test_prose_from_line_stays_in_body(self):
        mbox = make_mbox(
            make_message(body=("intro", "", "From the summit it was unreal")),
            make_message(subject="next"),
        )
        (first, first_body), (second, _) = read_all(mbox)
        assert b"From the summit" in first_body
        assert second.headers.get("Subject") == "next"

    def test_unstuffing_honors_escaping_mode(self):
        mbox = make_mbox(make_message(body=(">From x", ">>From y", "> quoted")))
        ((_, body),) = read_all(mbox)  # default mboxrd
        assert body == b"From x\n>From y\n> quoted\n"
        ((_, body),) = read_all(mbox, escaping="none")
        assert body == b">From x\n>>From y\n> quoted\n"

    def test_crlf_messages_and_empty_bodies_round_trip(self):
        mbox = make_mbox(make_message(body=("crlf body",), eol="\r\n"))
        ((msg, body),) = read_all(mbox)
        assert msg.header_sep == b"\r\n"
        assert body == b"crlf body\r\n"
        # An empty-body message must not swallow its successor.
        mbox = make_mbox(
            make_message(subject="a", body=()),
            make_message(subject="b", body=("real",)),
        )
        (first, first_body), (second, second_body) = read_all(mbox)
        assert first.headers.get("Subject") == "a"
        assert first_body == b""
        assert second_body == b"real\n"

    def test_leading_blanks_and_missing_final_newline_tolerated(self, simple_mbox):
        assert len(read_all(b"\n\n" + simple_mbox)) == 2
        raw = make_message(body=()).encode() + b"no newline at eof"
        ((_, body),) = read_all(raw)
        assert body == b"no newline at eof"

    def test_headers_available_before_body_is_consumed(self, simple_mbox):
        # Routing must be decidable from headers alone, pre-stream.
        reader = reader_for(simple_mbox)
        msg = next(reader)
        assert msg.headers.get("X-Gmail-Labels") == "Inbox"
        assert msg.body_bytes == 0  # nothing consumed yet


class TestBodyContract:
    def test_iter_body_is_single_shot(self, simple_mbox):
        reader = reader_for(simple_mbox)
        msg = next(reader)
        list(msg.iter_body())
        with pytest.raises(BodyConsumedError):
            msg.iter_body()

    def test_advancing_reader_drains_unread_body(self, simple_mbox):
        reader = reader_for(simple_mbox)
        first = next(reader)
        second = next(reader)  # caller never touched first's body
        assert first.body_bytes == len(b"one\n")
        assert b"".join(second.iter_body()) == b"two\n"

    def test_drain_counts_bytes_even_after_partial_read(self):
        mbox = make_mbox(make_message(body=("one", "two", "three")))
        reader = reader_for(mbox)
        msg = next(reader)
        body = msg.iter_body()
        assert next(body) == b"one\n"
        msg.drain()
        assert msg.body_bytes == len(b"one\ntwo\nthree\n")
        assert msg.size == len(msg.header_bytes) + msg.body_bytes


class TestErrorPaths:
    def test_non_mbox_input_raises_before_any_message(self):
        with pytest.raises(NotAnMboxError):
            next(iter(reader_for(b'{"kind": "takeout-metadata"}\n')))

    def test_empty_input_and_bad_escaping_mode(self):
        assert list(reader_for(b"")) == []
        with pytest.raises(ValueError):
            MboxReader(io.BytesIO(b""), escaping="mboxcl")

    def test_header_cap_marks_message_truncated_without_losing_bytes(self):
        big_header = "X-Big: " + "v" * 4096
        mbox = make_mbox(make_message(extra_headers=(big_header,), body=("b",)))
        ((msg, body),) = read_all(mbox, header_cap=256)
        assert msg.truncated_headers
        # The oversized line lands in the body instead of being lost.
        assert b"X-Big" in body
        # And an ordinary message is never marked truncated.
        ((normal, _),) = read_all(make_mbox(make_message()))
        assert not normal.truncated_headers
