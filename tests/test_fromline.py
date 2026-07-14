"""Separator recognition: the heuristic that keeps bodies from being shredded.

Google Takeout does not reliably escape ``From `` at the start of body lines,
so mailslice only treats a line as a message boundary when it carries an
envelope token and an asctime date. These tests pin both directions: real
separators (Gmail's and classic MTAs') are accepted, prose is not.
"""

import pytest

from mailslice.mboxstream import is_from_line, unstuff


class TestIsFromLine:
    def test_real_separators_accepted(self):
        # Gmail Takeout (numeric tz), classic MTA, padded single-digit day,
        # optional seconds, CRLF terminator — all genuine separators.
        for line in (
            b"From 1604289821235122186@xxx Fri Oct 30 09:33:41 +0000 2020\n",
            b"From alice@example.test Thu Jan  9 09:00:00 2020\n",
            b"From bob@example.test Mon Feb  3 23:59:59 1999\n",
            b"From bob@example.test Mon Feb 13 23:59 1999\n",
            b"From a@example.test Thu Jan  2 09:00:00 +0000 2020\r\n",
        ):
            assert is_from_line(line), line

    def test_prose_and_headers_rejected(self):
        # The classic mb2md failure mode is splitting on any "From " —
        # every one of these is a real line that must stay inside a body.
        for line in (
            b"From the summit the view was unreal.\n",
            b"From: alice@example.test\n",
            b"From Thu Jan  2 09:00:00 2020\n",  # no envelope token
            b"From a@example.test Xxx Jan  2 09:00:00 2020\n",  # bad weekday
            b">From a@example.test Thu Jan  2 09:00:00 2020\n",  # stuffed
            b"From a@example.test Thu Jan  2 09:00:00 2020 and more words\n",
        ):
            assert not is_from_line(line), line


class TestUnstuff:
    def test_mboxrd_strips_exactly_one_level(self):
        # ">>From " came from a body that originally said ">From ".
        assert unstuff(b">From x\n", "mboxrd") == b"From x\n"
        assert unstuff(b">>From x\n", "mboxrd") == b">From x\n"
        assert unstuff(b"> quoted reply\n", "mboxrd") == b"> quoted reply\n"

    def test_mboxo_rewrites_one_level_and_none_passes_through(self):
        assert unstuff(b">From x\n", "mboxo") == b"From x\n"
        assert unstuff(b">>From x\n", "mboxo") == b">>From x\n"
        assert unstuff(b">From x\n", "none") == b">From x\n"
        assert unstuff(b"From x\n", "none") == b"From x\n"

    def test_unknown_mode_raises(self):
        with pytest.raises(ValueError):
            unstuff(b"x\n", "mboxcl2")
