"""End-to-end library flow: mbox bytes in, maildir/EML trees + report out."""

import pytest

from mailslice.router import RouteConfig, Router
from mailslice.splitter import scan, split

from conftest import make_mbox, make_message, reader_for


def default_router(**kwargs) -> Router:
    return Router(RouteConfig(**kwargs))


MSG_2020 = make_message(
    subject="kickoff",
    labels="Inbox,Important,Work/Projects",
    body=("notes", "", ">From the archive"),
)
MSG_2021 = make_message(
    subject="lunch",
    labels="Sent,Opened",
    date="Fri, 15 Jan 2021 09:15:00 +0000",
    from_line="From 1610702100000000004@xxx Fri Jan 15 09:15:00 +0000 2021",
    body=("noon works",),
)
MSG_SPAM = make_message(
    subject="win big",
    labels="Spam,Unread",
    date="Tue, 14 Sep 2021 09:00:00 +0000",
    from_line="From 1631610000000000007@xxx Tue Sep 14 09:00:00 +0000 2021",
    body=("click here",),
)


class TestScan:
    def test_counts_every_label_per_message_and_unlabeled(self):
        report = scan(reader_for(make_mbox(MSG_2020)))
        assert {label for label, _ in report.buckets} == {
            "Inbox", "Important", "Work/Projects",
        }
        assert report.messages == 1
        unlabeled = scan(reader_for(make_mbox(make_message(labels=None))))
        assert ("Unlabeled", "2020") in unlabeled.buckets

    def test_limit_stops_early(self):
        report = scan(reader_for(make_mbox(MSG_2020, MSG_2021, MSG_SPAM)), limit=2)
        assert report.messages == 2


class TestSplitMaildir:
    def test_primary_label_routing_writes_exactly_one_copy(self, tmp_path):
        report = split(
            reader_for(make_mbox(MSG_2020)),
            out_dir=tmp_path,
            fmt="maildir",
            router=default_router(),
        )
        files = list((tmp_path / "Work" / "Projects" / "2020" / "cur").iterdir())
        assert len(files) == 1
        assert report.messages == 1
        # No stray copies under the system labels.
        assert not (tmp_path / "Inbox").exists()

    def test_body_is_unstuffed_in_output(self, tmp_path):
        split(
            reader_for(make_mbox(MSG_2020)),
            out_dir=tmp_path,
            fmt="maildir",
            router=default_router(),
        )
        (message_file,) = (tmp_path / "Work" / "Projects" / "2020" / "cur").iterdir()
        content = message_file.read_bytes()
        assert b"\n>From the archive" not in content
        assert b"\nFrom the archive" in content

    def test_all_labels_duplicates_message_byte_identically(self, tmp_path):
        report = split(
            reader_for(make_mbox(MSG_2020)),
            out_dir=tmp_path,
            fmt="maildir",
            router=default_router(all_labels=True),
        )
        (inbox,) = (tmp_path / "Inbox" / "2020" / "cur").iterdir()
        (work,) = (tmp_path / "Work" / "Projects" / "2020" / "cur").iterdir()
        assert inbox.read_bytes() == work.read_bytes()
        assert report.messages == 1  # counted once despite two deliveries

    def test_filters_skip_report_and_still_write_the_rest(self, tmp_path):
        report = split(
            reader_for(make_mbox(MSG_2020, MSG_SPAM)),
            out_dir=tmp_path / "a",
            fmt="maildir",
            router=default_router(exclude=frozenset({"spam"})),
        )
        assert report.skipped == {"excluded label": 1}
        assert report.messages == 2
        assert not (tmp_path / "a" / "Spam").exists()
        report = split(
            reader_for(make_mbox(MSG_2020, MSG_2021)),
            out_dir=tmp_path / "b",
            fmt="maildir",
            router=default_router(since=2021),
        )
        assert report.skipped == {"before --since": 1}
        assert not (tmp_path / "b" / "Work").exists()
        assert (tmp_path / "b" / "Sent" / "2021" / "cur").is_dir()

    def test_dry_run_writes_nothing_but_reports_everything(self, tmp_path):
        out = tmp_path / "out"
        calls = []
        report = split(
            reader_for(make_mbox(MSG_2020, MSG_2021)),
            out_dir=out,
            fmt="maildir",
            router=default_router(),
            dry_run=True,
            progress=calls.append,
        )
        assert not out.exists()
        assert report.messages == 2
        assert ("Sent", "2021") in report.buckets
        assert calls == []  # progress fires every 1000, not for 2 messages

    def test_dry_run_byte_counts_match_a_real_run_exactly(self, tmp_path):
        # "Honest accounting" includes the rehearsal: the sizes a --dry-run
        # reports must be the bytes a real split would put on disk.
        mbox = make_mbox(MSG_2020, MSG_2021)
        dry = split(
            reader_for(mbox),
            out_dir=tmp_path / "dry",
            fmt="maildir",
            router=default_router(),
            dry_run=True,
        )
        wet = split(
            reader_for(mbox),
            out_dir=tmp_path / "wet",
            fmt="maildir",
            router=default_router(),
        )
        assert dry.buckets == wet.buckets


class TestSplitEml:
    def test_eml_files_named_by_date_and_subject(self, tmp_path):
        split(
            reader_for(make_mbox(MSG_2020, MSG_2021)),
            out_dir=tmp_path,
            fmt="eml",
            router=default_router(),
        )
        assert (
            tmp_path / "Work" / "Projects" / "2020" / "20200102-090000-kickoff.eml"
        ).is_file()
        assert (tmp_path / "Sent" / "2021" / "20210115-091500-lunch.eml").is_file()
        # group_by="none" flattens everything into the output root.
        flat = tmp_path / "flat"
        split(
            reader_for(make_mbox(MSG_2020, MSG_2021)),
            out_dir=flat,
            fmt="eml",
            router=default_router(group_by="none"),
        )
        assert len(list(flat.glob("*.eml"))) == 2

    def test_eml_filename_decodes_rfc2047_subject(self, tmp_path):
        # Gmail sends non-ASCII subjects as "=?UTF-8?B?...?="; the slug must
        # come from the decoded text, never from the encoding artifacts.
        encoded = make_message(
            subject="=?UTF-8?B?6KuL5rGC5pu4?= resend please",
            labels="Inbox",
            body=("see attached",),
        )
        split(
            reader_for(make_mbox(encoded)),
            out_dir=tmp_path,
            fmt="eml",
            router=default_router(),
        )
        (path,) = (tmp_path / "Inbox" / "2020").glob("*.eml")
        assert "UTF-8" not in path.name and "6KuL" not in path.name
        # 請求書 is non-ASCII so it slugs away; the ASCII words survive.
        assert path.name == "20200102-090000-resend-please.eml"

    def test_invalid_format_rejected(self, tmp_path):
        with pytest.raises(ValueError):
            split(
                reader_for(make_mbox(MSG_2020)),
                out_dir=tmp_path,
                fmt="pdf",
                router=default_router(),
            )
