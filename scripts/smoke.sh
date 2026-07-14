#!/usr/bin/env bash
# Smoke test for mailslice: generate a Takeout-shaped sample mbox, scan it,
# split it to maildir and EML, and assert on the real output tree.
# Self-contained: pure stdlib, no network, idempotent (works from a clean tree).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${PYTHON:-python3}"
if [ -x "$ROOT/.venv/bin/python" ]; then
  PYTHON="$ROOT/.venv/bin/python"
fi

# The package has zero runtime dependencies, so running from src/ needs no install.
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

WORKDIR="$(mktemp -d "${TMPDIR:-/tmp}/mailslice-smoke.XXXXXX")"
trap 'rm -rf "$WORKDIR"' EXIT

fail() { echo "SMOKE FAIL: $1" >&2; exit 1; }

echo "[smoke] python: $("$PYTHON" --version 2>&1)"

# 1. Generate the deterministic sample mbox (8 messages, all the quirks).
"$PYTHON" "$ROOT/examples/make_sample_mbox.py" "$WORKDIR/sample.mbox" \
  || fail "sample generator exited non-zero"

# 2. scan: message count, year span, decoded and quoted labels all present.
scan_out="$("$PYTHON" -m mailslice scan "$WORKDIR/sample.mbox")"
echo "$scan_out" | sed 's/^/[scan] /'
echo "$scan_out" | grep -q "messages: 8" || fail "scan did not count 8 messages"
echo "$scan_out" | grep -q "span: 2020-2021" || fail "scan year span wrong"
echo "$scan_out" | grep -q "請求書/2020" || fail "encoded-word label not decoded"
echo "$scan_out" | grep -q "Receipts, 2020/2020" || fail "quoted label not parsed"

# 3. scan --json is parseable and agrees.
"$PYTHON" -m mailslice scan "$WORKDIR/sample.mbox" --json \
  | "$PYTHON" -c 'import json,sys; d=json.load(sys.stdin); assert d["messages"]==8 and d["malformed"]==0' \
  || fail "scan --json unparseable or wrong"

# 4. split to maildir, excluding Spam.
split_out="$("$PYTHON" -m mailslice split "$WORKDIR/sample.mbox" -o "$WORKDIR/mail" --exclude-label Spam)"
echo "$split_out" | sed 's/^/[split] /'
echo "$split_out" | grep -q "total: 8 messages" || fail "split totals wrong"
echo "$split_out" | grep -q "1 skipped" || fail "Spam exclusion not reported"
[ -d "$WORKDIR/mail/Work/Projects/2020/cur" ] || fail "nested label maildir missing"
[ -d "$WORKDIR/mail/請求書/2020/cur" ] || fail "unicode label maildir missing"
[ ! -e "$WORKDIR/mail/Spam" ] || fail "excluded Spam directory was created"
delivered=$(find "$WORKDIR/mail" -path '*/cur/*' -type f | wc -l)
[ "$delivered" -eq 7 ] || fail "expected 7 delivered messages, got $delivered"
# (relative find: the workdir itself lives under /tmp, so anchor at mail/)
leftover=$(cd "$WORKDIR/mail" && find . -path '*/tmp/*' -type f | wc -l)
[ "$leftover" -eq 0 ] || fail "maildir tmp/ not empty after delivery"

# 5. maildir flags: the starred CRLF message must carry :2,FS.
find "$WORKDIR/mail/Work/Projects/Q1/2021/cur" -name '*:2,FS' | grep -q . \
  || fail "starred message missing F flag"

# 6. body fidelity: mboxrd unstuffed, prose 'From ' kept inside one body.
kickoff="$(find "$WORKDIR/mail/Work/Projects/2020/cur" -type f | head -1)"
grep -q "^From the archive" "$kickoff" || fail "mboxrd stuffing not reversed"
trip="$(find "$WORKDIR/mail/Travel/2021/cur" -type f | head -1)"
grep -q "^From the summit" "$trip" || fail "prose From-line was split or lost"

# 7. split to EML with year-only grouping.
"$PYTHON" -m mailslice split "$WORKDIR/sample.mbox" -o "$WORKDIR/eml" \
  --format eml --group-by year >/dev/null || fail "eml split exited non-zero"
[ -f "$WORKDIR/eml/2020/20200102-090000-Kickoff-notes.eml" ] \
  || fail "expected EML filename missing"
emls=$(find "$WORKDIR/eml" -name '*.eml' | wc -l)
[ "$emls" -eq 8 ] || fail "expected 8 EML files, got $emls"

# 8. --dry-run must write nothing.
"$PYTHON" -m mailslice split "$WORKDIR/sample.mbox" -o "$WORKDIR/dry" --dry-run >/dev/null
[ ! -e "$WORKDIR/dry" ] || fail "--dry-run created the output directory"

# 9. gzip transparency: same counts from a .gz of the same mbox.
gzip -c "$WORKDIR/sample.mbox" > "$WORKDIR/sample.mbox.gz"
"$PYTHON" -m mailslice scan "$WORKDIR/sample.mbox.gz" --json \
  | "$PYTHON" -c 'import json,sys; assert json.load(sys.stdin)["messages"]==8' \
  || fail "gzip input not read transparently"

# 10. non-mbox input fails fast with exit 1 and a clean message.
set +e
err_out="$("$PYTHON" -m mailslice scan "$ROOT/pyproject.toml" 2>&1)"
err_rc=$?
set -e
[ "$err_rc" -eq 1 ] || fail "non-mbox input should exit 1, got $err_rc"
echo "$err_out" | grep -q "mailslice:" || fail "non-mbox error message missing"

# 11. --version agrees with the package version.
version_out="$("$PYTHON" -m mailslice --version)"
pkg_version="$("$PYTHON" -c 'import mailslice; print(mailslice.__version__)')"
[ "$version_out" = "mailslice $pkg_version" ] \
  || fail "--version mismatch: '$version_out' vs package '$pkg_version'"

echo "SMOKE OK"
