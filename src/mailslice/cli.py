"""Command-line interface: ``mailslice scan`` and ``mailslice split``.

The CLI is a thin argparse layer over the library; every error mailslice
raises on purpose surfaces as one clear line on stderr and exit code 1,
never a traceback. All informational output (progress, final report) that a
script might want to parse is available as ``--json`` on stdout.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import List, Optional

from . import __version__
from .errors import MailsliceError
from .mboxstream import ESCAPING_MODES, MboxReader, open_mbox
from .report import human_size
from .router import GROUP_CHOICES, RouteConfig, Router
from .splitter import FORMATS, scan, split

__all__ = ["main", "build_parser"]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mailslice",
        description=(
            "Stream-split giant Google Takeout mbox files into maildir or "
            "EML by Gmail label and year, in constant memory."
        ),
    )
    parser.add_argument(
        "--version", action="version", version=f"mailslice {__version__}"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    scan_p = sub.add_parser(
        "scan",
        help="inventory an mbox (labels, years, sizes) without writing anything",
    )
    _add_input_args(scan_p)
    scan_p.add_argument(
        "--limit", type=int, metavar="N",
        help="stop after N messages (quick preview of a huge file)",
    )
    scan_p.add_argument(
        "--json", action="store_true", help="emit the report as JSON on stdout"
    )
    scan_p.add_argument(
        "--progress", action="store_true",
        help="print a progress line to stderr every 1000 messages",
    )

    split_p = sub.add_parser(
        "split",
        help="split an mbox into per-label/per-year maildir or EML directories",
    )
    _add_input_args(split_p)
    split_p.add_argument(
        "-o", "--out", required=True, metavar="DIR",
        help="output directory (created if missing)",
    )
    split_p.add_argument(
        "--format", choices=FORMATS, default="maildir",
        help="output format (default: maildir)",
    )
    split_p.add_argument(
        "--group-by", choices=GROUP_CHOICES, default="label/year",
        help="directory scheme (default: label/year)",
    )
    split_p.add_argument(
        "--include-label", action="append", default=[], metavar="LABEL",
        help="only split messages carrying LABEL (repeatable; matches nested "
             "labels, so 'Work' includes 'Work/Q3')",
    )
    split_p.add_argument(
        "--exclude-label", action="append", default=[], metavar="LABEL",
        help="skip messages carrying LABEL (repeatable)",
    )
    split_p.add_argument(
        "--since", type=int, metavar="YEAR",
        help="only messages from YEAR onward (undated mail is skipped)",
    )
    split_p.add_argument(
        "--until", type=int, metavar="YEAR",
        help="only messages up to YEAR (undated mail is skipped)",
    )
    split_p.add_argument(
        "--all-labels", action="store_true",
        help="deliver a copy into every label directory instead of only the "
             "primary label",
    )
    split_p.add_argument(
        "--dry-run", action="store_true",
        help="route and report without writing any file",
    )
    split_p.add_argument(
        "--json", action="store_true", help="emit the report as JSON on stdout"
    )
    split_p.add_argument(
        "--progress", action="store_true",
        help="print a progress line to stderr every 1000 messages",
    )
    return parser


def _add_input_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "mbox",
        help="path to the mbox file ('-' for stdin; .gz is read transparently)",
    )
    parser.add_argument(
        "--escaping", choices=ESCAPING_MODES, default="mboxrd",
        help="how body 'From ' lines were escaped (default: mboxrd)",
    )


def _progress_printer(count: int) -> None:
    print(f"[mailslice] processed {count} messages...", file=sys.stderr)


def _run_scan(args: argparse.Namespace) -> int:
    fp = open_mbox(args.mbox)
    try:
        reader = MboxReader(fp, escaping=args.escaping)
        report = scan(
            reader,
            limit=args.limit,
            progress=_progress_printer if args.progress else None,
        )
    finally:
        if args.mbox != "-":
            fp.close()
    if args.json:
        print(json.dumps(report.to_json(), indent=2, sort_keys=True))
    else:
        print(f"messages: {report.messages}   "
              f"size: {human_size(report.total_bytes)}   "
              f"span: {report.year_span}")
        print(report.render(bucket_header="label/year"))
    return 0


def _run_split(args: argparse.Namespace) -> int:
    if args.since is not None and args.until is not None and args.since > args.until:
        print("mailslice: --since must not be greater than --until", file=sys.stderr)
        return 1
    config = RouteConfig(
        group_by=args.group_by,
        include=frozenset(label.lower() for label in args.include_label),
        exclude=frozenset(label.lower() for label in args.exclude_label),
        since=args.since,
        until=args.until,
        all_labels=args.all_labels,
    )
    fp = open_mbox(args.mbox)
    try:
        reader = MboxReader(fp, escaping=args.escaping)
        report = split(
            reader,
            out_dir=args.out,
            fmt=args.format,
            router=Router(config),
            dry_run=args.dry_run,
            progress=_progress_printer if args.progress else None,
        )
    finally:
        if args.mbox != "-":
            fp.close()
    if args.json:
        print(json.dumps(report.to_json(), indent=2, sort_keys=True))
    else:
        # The report always breaks down by label AND year, whatever the
        # directory scheme — --group-by only changes where files land.
        print(report.render(bucket_header="label/year"))
        if args.dry_run:
            print(f"dry run: nothing written (would write under {args.out}/)")
        else:
            print(f"wrote {args.format} folders under {args.out}/")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "scan":
            return _run_scan(args)
        return _run_split(args)
    except MailsliceError as exc:
        print(f"mailslice: {exc}", file=sys.stderr)
        return 1
    except BrokenPipeError:
        return 1  # e.g. `mailslice scan … | head`; not an error worth noise
    except FileNotFoundError as exc:
        print(f"mailslice: {exc.filename}: no such file", file=sys.stderr)
        return 1
    except OSError as exc:
        # One clean line for every other I/O failure a user can provoke:
        # a directory instead of a file, a corrupt .gz, an unwritable or
        # occupied output path, a permission problem.
        detail = exc.strerror or str(exc)
        where = f"{exc.filename}: " if exc.filename else ""
        print(f"mailslice: {where}{detail}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
