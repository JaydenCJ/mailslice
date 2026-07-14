# Contributing to mailslice

Thanks for your interest in contributing. Issues, discussions, and pull
requests are all welcome.

## Development setup

```bash
git clone https://github.com/JaydenCJ/mailslice
cd mailslice
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

## Running the checks

```bash
pytest                 # 93 unit and end-to-end tests
bash scripts/smoke.sh  # real CLI run: generate, scan, split, verify the tree
```

Both must pass before a pull request is reviewed; `smoke.sh` must print
`SMOKE OK`. The suite runs fully offline, needs no mail account, and never
touches the network.

## Ground rules

- **No new runtime dependencies.** The package is standard-library only;
  that is a feature. Test-only dependencies belong in the `dev` extra.
- **Byte fidelity is sacred.** Any change to the reader or writers needs a
  test proving message bytes survive the round trip, including line endings
  and From-stuffing.
- **Splitting-rule changes need docs.** Anything that alters boundary
  detection, label routing, or filename schemes must update
  `docs/splitting-rules.md` in the same pull request.
- **Keep the three READMEs aligned.** `README.md`, `README.zh.md`, and
  `README.ja.md` share the same structure; update all three when you change
  one (English is the authoritative version).
- Code comments and doc comments are written in English.

## Reporting bugs

Please include `mailslice --version` output, the exact command line, the
final report (or `--json` output), and — if you can share it — a minimal
mbox snippet that reproduces the problem with real addresses replaced by
`example.test` ones. `examples/make_sample_mbox.py` shows the shape a good
repro takes.

## Security

Do not open public issues for security problems; use GitHub private
vulnerability reporting on this repository instead.
