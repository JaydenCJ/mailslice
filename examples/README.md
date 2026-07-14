# Examples

## `make_sample_mbox.py`

Generates a deterministic, Takeout-shaped sample mbox — every byte fixed, so
demos and tests are reproducible:

```bash
python examples/make_sample_mbox.py sample.mbox
```

The 8 messages cover the quirks mailslice exists to handle:

- Gmail-style separator lines with numeric timezones
- `X-Gmail-Labels` with nested labels (`Work/Projects/Q1`), a quoted label
  containing a comma (`"Receipts, 2020"`), and an RFC 2047-encoded Japanese
  label (`請求書`)
- mboxrd From-stuffing (`>From …`) that must be reversed
- a body paragraph starting with a bare `From ` that must **not** split
- one CRLF message, one message with no `Date` header, and one Spam message
  to exercise `--exclude-label`

Then try the full flow:

```bash
mailslice scan sample.mbox
mailslice split sample.mbox -o mail --exclude-label Spam
find mail -type f | sort
```

`scripts/smoke.sh` runs exactly this end to end and asserts on the results.
