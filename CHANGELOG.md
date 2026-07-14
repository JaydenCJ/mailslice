# Changelog

All notable changes to this project are documented in this file. The format is
based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-07-13

### Added

- Constant-memory streaming mbox reader: fixed-size chunk reads, at most one
  line plus one capped header block in memory, bodies handed to writers as a
  single-shot stream — file size and attachment size never affect memory use.
- Conservative message-boundary detection: a line only splits messages when
  it matches a real mbox separator (envelope token + asctime date, with
  Gmail's optional numeric timezone) after a blank line, so unescaped
  ``From `` prose inside Takeout bodies stays intact.
- From-stuffing reversal with selectable `--escaping` mode: `mboxrd`
  (default), `mboxo`, or `none`.
- Gmail label awareness: `X-Gmail-Labels` parsing with quoted commas and
  RFC 2047 encoded words, nested `Parent/Child` labels, state labels
  (Unread/Starred/Trash/Drafts) mapped to maildir flags instead of folders,
  and primary-label routing with `--all-labels` duplication as an option.
- Filesystem-safe label paths: separator/control characters replaced, NTFS
  trailing-dot and reserved-device-name traps defused, segment length capped,
  Unicode preserved.
- Date recovery ladder (`Date` header → newest `Received` → the mbox From
  line) with a visible `no-date` bucket for undatable mail.
- `mailslice split`: maildir (tmp→cur rename, deterministic names, flag
  suffixes) or EML (date+subject filenames with collision suffixes) output,
  grouped by `label/year`, `label`, `year`, or `none`; hierarchical
  `--include-label` / `--exclude-label`, `--since` / `--until` year window,
  `--all-labels`, `--dry-run`, `--progress`, `--json`.
- `mailslice scan`: inventory of labels, years, sizes, and malformed counts
  without writing anything; `--limit` for quick previews of huge files.
- Transparent gzip input and `-` for stdin; a deterministic Takeout-shaped
  sample generator in `examples/`.
- 93 offline pytest tests and `scripts/smoke.sh` (prints `SMOKE OK`).

### Notes

- The repository ships no CI workflow; verification is local —
  `pip install -e '.[dev]' && pytest && bash scripts/smoke.sh`.

[0.1.0]: https://github.com/JaydenCJ/mailslice/releases/tag/v0.1.0
