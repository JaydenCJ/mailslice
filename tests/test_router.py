"""Routing policy: grouping schemes, filters, and multi-label delivery."""

import pytest

from mailslice.router import RouteConfig, Router


def route(labels, year=2020, **config_kwargs):
    return Router(RouteConfig(**config_kwargs)).route(labels, year)


class TestGrouping:
    def test_default_label_slash_year(self):
        result = route(["Inbox"], 2020)
        assert result.destinations == [("Inbox", "2020", "Inbox/2020")]

    def test_alternative_grouping_schemes(self):
        assert route(["Inbox"], 2020, group_by="label").destinations == [
            ("Inbox", "2020", "Inbox")
        ]
        assert route(["Inbox"], 2020, group_by="year").destinations == [
            ("Inbox", "2020", "2020")
        ]
        # "none" flattens everything into the output root.
        assert route(["Inbox"], 2020, group_by="none").destinations == [
            ("Inbox", "2020", "")
        ]
        # Undated mail lands in a visible no-date bucket, never dropped.
        assert route(["Inbox"], None).destinations == [
            ("Inbox", "no-date", "Inbox/no-date")
        ]

    def test_invalid_group_by_rejected(self):
        with pytest.raises(ValueError):
            RouteConfig(group_by="month")


class TestPrimaryVsAllLabels:
    def test_default_routes_to_primary_label_only(self):
        result = route(["Inbox", "Receipts", "Travel"])
        assert [d[0] for d in result.destinations] == ["Receipts"]

    def test_all_labels_duplicates_into_every_folder_label(self):
        result = route(["Inbox", "Receipts", "Unread"], all_labels=True)
        assert [d[0] for d in result.destinations] == ["Inbox", "Receipts"]
        # Flag-only messages still need a home.
        fallback = route(["Unread", "Starred"], all_labels=True)
        assert [d[0] for d in fallback.destinations] == ["Unlabeled"]

    def test_labels_sanitizing_to_same_dir_delivered_once(self):
        # "Trips?" and "Trips*" both sanitize to "Trips_" — one copy, not two.
        result = route(["Trips?", "Trips*"], all_labels=True)
        assert len(result.destinations) == 1


class TestFilters:
    def test_exclude_is_hierarchical_but_not_a_prefix_match(self):
        result = route(["Spam", "Unread"], exclude=frozenset({"spam"}))
        assert result.skipped and result.skip_reason == "excluded label"
        assert route(["Work/Q3"], exclude=frozenset({"work"})).skipped
        # "Workshop" is not under "Work" — substring matching would be wrong.
        assert not route(["Workshop"], exclude=frozenset({"work"})).skipped

    def test_include_keeps_only_matching_including_children(self):
        assert not route(["Receipts"], include=frozenset({"receipts"})).skipped
        assert route(["Travel"], include=frozenset({"receipts"})).skipped
        assert not route(["Work/Q3/Reports"], include=frozenset({"work"})).skipped

    def test_exclude_beats_include(self):
        result = route(
            ["Receipts", "Spam"],
            include=frozenset({"receipts"}),
            exclude=frozenset({"spam"}),
        )
        assert result.skipped

    def test_since_and_until_bound_the_year_range_inclusively(self):
        assert route(["Inbox"], 2019, since=2020).skipped
        assert not route(["Inbox"], 2020, since=2020).skipped
        assert route(["Inbox"], 2022, until=2021).skipped
        assert not route(["Inbox"], 2021, until=2021).skipped
        # Documented behavior: a date window can only keep datable mail.
        assert route(["Inbox"], None, since=2020).skipped
        assert route(["Inbox"], None, until=2020).skipped
