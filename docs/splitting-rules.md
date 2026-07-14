# Splitting rules

This document pins down every decision mailslice makes between the first byte
of an mbox and the final file on disk. If a behavior here changes, the change
must land in the same pull request as the code (see CONTRIBUTING.md).

## 1. Message boundaries

A line starts a new message **only** when both conditions hold:

1. It matches a real mbox separator: `From ` + an envelope token (no spaces)
   + an asctime date — weekday, month, day (space-padded singles allowed),
   `HH:MM[:SS]`, an optional numeric timezone (`+0000`, Gmail Takeout style),
   and a four-digit year. Nothing may follow the year.
2. It comes immediately after a blank line (or at the very start of the file,
   or directly after a message's empty body).

Rule 1 is what keeps a paragraph starting with "From the summit…" inside its
message: Google Takeout does **not** reliably escape body `From ` lines, and
splitting on `startswith("From ")` — the mb2md-era approach — shreds real
mail. Rule 2 is standard mbox framing; the single blank line before a
separator (and the one before EOF) belongs to the framing, not the body.

Known trade-off: a body that legitimately contains a blank line followed by a
byte-perfect separator line will split. Such a line is indistinguishable from
a real boundary by construction; no mbox consumer can do better without
Content-Length headers, which Takeout does not write.

If the first non-blank line of the input is not a valid separator, mailslice
raises `NotAnMboxError` before writing anything — pointing the tool at the
wrong Takeout artifact fails fast.

## 2. From-stuffing (`--escaping`)

| Mode | Body-line rewrite | Use when |
|---|---|---|
| `mboxrd` (default) | `>From ` → `From `, `>>From ` → `>From `, … (strip one `>`) | Standard exports; fully reversible |
| `mboxo` | `>From ` → `From ` only | Old exports that used the lossy classic scheme |
| `none` | nothing | Archives that never escaped bodies |

Stuffed lines are never treated as boundaries in any mode.

## 3. Headers

Headers are buffered up to a cap (1 MiB by default). Beyond the cap the
message is flagged *malformed* in the report and the remaining lines flow to
the body — nothing is dropped. Folded values unfold with a single space;
lines without a colon are skipped; bytes decode as UTF-8 with a Latin-1
fallback. RFC 2047 encoded words are decoded wherever labels or subjects are
interpreted; unknown charsets degrade to replacement characters instead of
aborting the run.

## 4. Labels

`X-Gmail-Labels` is split on commas outside double quotes, trimmed,
de-duplicated case-insensitively (first spelling wins). Labels then classify
as:

| Class | Members | Effect |
|---|---|---|
| State (flags) | Unread, Opened, Starred, Important | Never folders; map to maildir flags |
| System folders | Inbox, Sent, Archived, Drafts, Spam, Trash/Bin, Chat, Snoozed, Scheduled, `Category …` | Folders, but outranked by user labels |
| User labels | everything else, `Parent/Child` nesting preserved | Preferred folders |

**Primary-label routing (default):** first user label in header order, else
first system folder label, else `Unlabeled`. **`--all-labels`:** one copy per
folder-class label (state labels still excluded), written once and then
file-copied — the source mbox is never re-read.

Maildir flags: `S` unless Unread, `F` for Starred, `T` for Trash/Bin, `D`
for Drafts, emitted in ASCII order.

## 5. Dates and years

Trust order: `Date` header → newest `Received` header (timestamp after its
last `;`) → the separator line's own asctime date. Messages where all three
fail land in a visible `no-date` bucket; `--since`/`--until` windows skip
them (a year filter can only keep datable mail), and each skip is counted by
reason in the report.

## 6. Filesystem mapping

Each `/`-segment of a label is sanitized independently: `\ : * ? " < > |`,
control bytes and DEL become `_`; trailing dots/spaces are trimmed (NTFS
strips them silently, which would merge distinct labels); leading dots are
un-hidden; Windows device names (`CON`, `NUL`, `COM1`…) get a `_` prefix;
segments cap at 80 characters and are never empty. Unicode is preserved.

Output filenames:

| Format | Pattern | Example |
|---|---|---|
| maildir | `<epoch>.M<seq>.mailslice:2,<flags>` in `cur/` | `1577955600.M000001.mailslice:2,S` |
| EML | `<YYYYMMDD-HHMMSS>-<subject-slug>[-N].eml` | `20200102-090000-Kickoff-notes.eml` |

Maildir deliveries write into `tmp/` and rename into `cur/` (imported mail is
historical, hence `cur/` not `new/`). Epochs are UTC; sequence numbers make
names unique and re-runs reproducible. Note that maildir names contain `:`
and are therefore not directly copyable to NTFS — use the EML format for
archives destined for Windows.

## 7. Message content

Written messages are the raw header block, the original blank separator line
(CRLF preserved), and the unstuffed body — byte-for-byte otherwise. The mbox
`From ` envelope line is dropped, as both maildir and EML conventions expect.
Content is identical across both output formats.
