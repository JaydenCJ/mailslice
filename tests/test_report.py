"""Report rendering and JSON output: stable, parseable, correctly summed."""

import json

from mailslice.report import SplitReport, human_size


def sample_report() -> SplitReport:
    report = SplitReport()
    report.add("Inbox", "2020", 100)
    report.add("Inbox", "2020", 50)
    report.add("Inbox", "2021", 25)
    report.add("Work/Q3", "2021", 10)
    report.note_message(150, 2020, malformed=False)
    report.note_message(150, 2020, malformed=False)
    report.note_message(35, 2021, malformed=True)
    report.note_skip("excluded label")
    report.note_skip("excluded label")
    report.note_skip("before --since")
    return report


class TestHumanSize:
    def test_binary_units(self):
        assert human_size(0) == "0 B"
        assert human_size(1023) == "1023 B"
        assert human_size(1024) == "1.0 KiB"
        assert human_size(1536) == "1.5 KiB"
        assert human_size(40 * 1024 * 1024 * 1024) == "40.0 GiB"


class TestSplitReport:
    def test_buckets_accumulate_and_year_span_tracks_extremes(self):
        report = sample_report()
        assert report.buckets[("Inbox", "2020")] == [2, 150]
        assert report.year_span == "2020-2021"
        single = SplitReport()
        single.note_message(1, 2020, malformed=False)
        assert single.year_span == "2020"
        assert SplitReport().year_span == "-"

    def test_render_sorted_rows_aligned_columns_and_totals(self):
        text = sample_report().render()
        lines = text.splitlines()
        assert lines[0].startswith("label/year")
        assert lines[1].startswith("Inbox/2020")
        assert lines[-1] == "total: 3 messages, 335 B, 1 malformed, 3 skipped"
        size_column = lines[0].index("size")
        for line in lines[1:-1]:
            assert len(line) > size_column
        # Exactly one message must not read "1 messages".
        single = SplitReport()
        single.add("Inbox", "2020", 10)
        single.note_message(10, 2020, malformed=False)
        assert single.render().splitlines()[-1] == (
            "total: 1 message, 10 B, 0 malformed, 0 skipped"
        )

    def test_to_json_round_trips_sorted_with_stable_fields(self):
        data = json.loads(json.dumps(sample_report().to_json()))
        assert data["messages"] == 3
        assert data["malformed"] == 1
        assert data["skipped"] == {"before --since": 1, "excluded label": 2}
        assert data["skipped_total"] == 3
        labels = [(b["label"], b["year"]) for b in data["buckets"]]
        assert labels == sorted(labels)
        assert set(data["buckets"][0]) == {"label", "year", "messages", "bytes"}
