"""Gmail label semantics: parsing, classification, flags, and safe paths.

The X-Gmail-Labels header is the only place Takeout preserves your folder
structure; getting its edge cases right (quoted commas, encoded words,
nested labels, hostile characters) is what separates a usable archive from
a directory called `CON` that Windows refuses to delete.
"""

from mailslice.headers import HeaderBlock
from mailslice.labels import (
    UNLABELED,
    folder_labels,
    gmail_labels,
    is_flag_label,
    is_system_label,
    label_to_path,
    maildir_flags,
    parse_label_header,
    primary_label,
    sanitize_segment,
)


class TestParseLabelHeader:
    def test_comma_separated_with_whitespace_and_empties(self):
        assert parse_label_header("Inbox,Important,Work") == [
            "Inbox", "Important", "Work",
        ]
        assert parse_label_header(" Inbox , Sent ,,") == ["Inbox", "Sent"]
        assert parse_label_header("") == []

    def test_quoted_commas_and_nested_labels_kept_whole(self):
        assert parse_label_header('"Trips, 2020",Inbox') == ["Trips, 2020", "Inbox"]
        assert parse_label_header("Work/Projects/Q3") == ["Work/Projects/Q3"]

    def test_duplicates_removed_case_insensitively_keeping_first(self):
        assert parse_label_header("Inbox,INBOX,inbox,Sent") == ["Inbox", "Sent"]


class TestGmailLabels:
    def test_reads_and_rfc2047_decodes_the_header(self):
        headers = HeaderBlock.parse(
            b"X-Gmail-Labels: =?UTF-8?B?6KuL5rGC5pu4?=,Inbox\n"
        )
        assert gmail_labels(headers) == ["請求書", "Inbox"]
        assert gmail_labels(HeaderBlock.parse(b"Subject: x\n")) == []


class TestClassification:
    def test_state_labels_are_flags_not_folders(self):
        for label in ("Unread", "unread", "Starred", "Important", "Opened"):
            assert is_flag_label(label)
        assert folder_labels(["Inbox", "Unread", "Starred"]) == ["Inbox"]

    def test_system_vs_user_labels(self):
        assert is_system_label("Category Updates")
        assert is_system_label("Sent")
        assert not is_system_label("Receipts")
        assert not is_system_label("Work/Projects")


class TestPrimaryLabel:
    def test_first_user_label_beats_system_labels(self):
        assert primary_label(["Inbox", "Important", "Receipts"]) == "Receipts"
        assert primary_label(["Travel", "Receipts"]) == "Travel"

    def test_fallbacks_system_folder_then_unlabeled(self):
        assert primary_label(["Sent", "Opened"]) == "Sent"
        assert primary_label(["Unread", "Starred"]) == UNLABELED
        assert primary_label([]) == UNLABELED


class TestMaildirFlags:
    def test_seen_unless_unread(self):
        assert maildir_flags(["Inbox"]) == "S"
        assert maildir_flags(["Inbox", "Unread"]) == ""

    def test_starred_trash_and_drafts_map_to_sorted_standard_flags(self):
        assert maildir_flags(["Inbox", "Starred"]) == "FS"
        assert maildir_flags(["Trash"]) == "ST"
        assert maildir_flags(["Bin"]) == "ST"
        assert maildir_flags(["Drafts"]) == "DS"
        # The maildir spec requires ASCII-sorted flags; TSF breaks clients.
        assert maildir_flags(["Drafts", "Starred", "Trash"]) == "DFST"


class TestSanitization:
    def test_unsafe_and_control_characters_replaced(self):
        assert sanitize_segment("Receipts") == "Receipts"
        assert sanitize_segment('a\\b:c*d?e"f<g>h|i') == "a_b_c_d_e_f_g_h_i"
        assert sanitize_segment("bad\x00label\x1f") == "bad_label_"

    def test_ntfs_traps_defused(self):
        # NTFS strips trailing dots/spaces silently (merging distinct
        # labels) and refuses device names outright.
        assert sanitize_segment("archive. ") == "archive"
        assert sanitize_segment("CON") == "_CON"
        assert sanitize_segment("com1") == "_com1"

    def test_hidden_names_length_and_emptiness_guarded(self):
        assert sanitize_segment(".secret") == "_secret"
        assert len(sanitize_segment("x" * 500)) == 80
        assert sanitize_segment("") == "_"
        assert sanitize_segment("...") == "_"

    def test_nested_labels_become_nested_paths_sanitized_per_segment(self):
        assert label_to_path("Work/Projects/Q3") == "Work/Projects/Q3"
        assert label_to_path("Re: invoices?/2020.") == "Re_ invoices_/2020"

    def test_unicode_preserved_and_degenerate_labels_safe(self):
        assert label_to_path("請求書") == "請求書"
        assert label_to_path("///") == "_"
