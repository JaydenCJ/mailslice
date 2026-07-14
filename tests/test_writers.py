"""Maildir and EML writers: layout, naming, atomicity leftovers, fidelity."""

from datetime import datetime, timezone

from mailslice.writers import EmlWriter, MaildirWriter, slugify

DATE = datetime(2020, 1, 2, 9, 0, 0, tzinfo=timezone.utc)

HEADERS = b"Subject: test\nX-Gmail-Labels: Inbox\n"


def deliver(writer, body_lines=(b"hello\n",), flags="S", subject="test", date=DATE):
    if isinstance(writer, MaildirWriter):
        return writer.deliver(date, flags, HEADERS, b"\n", iter(body_lines))
    return writer.deliver(date, subject, HEADERS, b"\n", iter(body_lines))


class TestMaildirWriter:
    def test_message_lands_in_cur_with_flags_and_tmp_is_empty(self, tmp_path):
        # The spec's crash-safety dance: create cur/new/tmp, write to tmp/,
        # rename into cur/, leave nothing behind.
        writer = MaildirWriter(tmp_path)
        for sub in ("cur", "new", "tmp"):
            assert (tmp_path / sub).is_dir()
        path, _ = deliver(writer, flags="FS")
        assert path.parent.name == "cur"
        assert path.name.endswith(":2,FS")
        assert list((tmp_path / "tmp").iterdir()) == []

    def test_content_is_headers_blank_line_body(self, tmp_path):
        writer = MaildirWriter(tmp_path)
        path, written = deliver(writer, body_lines=(b"line one\n", b"line two\n"))
        content = path.read_bytes()
        assert content == HEADERS + b"\n" + b"line one\nline two\n"
        assert written == len(content)

    def test_names_are_deterministic_and_unique(self, tmp_path):
        writer = MaildirWriter(tmp_path)
        first, _ = deliver(writer)
        second, _ = deliver(writer)
        undated, _ = deliver(writer, date=None)
        assert first.name == "1577955600.M000001.mailslice:2,S"
        assert second.name == "1577955600.M000002.mailslice:2,S"
        assert undated.name.startswith("0.M000003.")

    def test_deliver_copy_duplicates_bytes_exactly(self, tmp_path):
        writer = MaildirWriter(tmp_path / "a")
        original, _ = deliver(writer, body_lines=(b"payload\n",))
        other = MaildirWriter(tmp_path / "b")
        copy, size = other.deliver_copy(original, DATE, "S")
        assert copy.read_bytes() == original.read_bytes()
        assert size == original.stat().st_size


class TestEmlWriter:
    def test_filename_from_date_and_subject(self, tmp_path):
        writer = EmlWriter(tmp_path)
        path, _ = deliver(writer, subject="Kickoff notes")
        assert path.name == "20200102-090000-Kickoff-notes.eml"

    def test_collisions_get_numeric_suffix(self, tmp_path):
        writer = EmlWriter(tmp_path)
        names = [deliver(writer, subject="Re: lunch?")[0].name for _ in range(3)]
        assert names == [
            "20200102-090000-Re-lunch.eml",
            "20200102-090000-Re-lunch-2.eml",
            "20200102-090000-Re-lunch-3.eml",
        ]
        # Undated, subjectless mail still gets a stable fallback name.
        path, _ = deliver(writer, subject="", date=None)
        assert path.name == "no-date-no-subject.eml"

    def test_content_matches_maildir_content(self, tmp_path):
        # Identical bytes in both formats is what makes --all-labels able
        # to copy files instead of re-reading the source mbox.
        maildir = MaildirWriter(tmp_path / "md")
        eml = EmlWriter(tmp_path / "eml")
        body = (b"same\n", b"bytes\n")
        md_path, _ = deliver(maildir, body_lines=body)
        eml_path, _ = deliver(eml, body_lines=body)
        assert md_path.read_bytes() == eml_path.read_bytes()

    def test_deliver_copy_duplicates_bytes_exactly(self, tmp_path):
        writer = EmlWriter(tmp_path / "a")
        original, _ = deliver(writer, subject="orig")
        other = EmlWriter(tmp_path / "b")
        copy, _ = other.deliver_copy(original, DATE, "orig")
        assert copy.read_bytes() == original.read_bytes()


class TestSlugify:
    def test_punctuation_length_and_unicode_behavior(self):
        assert slugify("Re: lunch?") == "Re-lunch"
        assert len(slugify("word " * 50)) <= 40
        # Callers fall back to "no-subject"; slugify itself stays honest.
        assert slugify("請求書の確認") == ""
