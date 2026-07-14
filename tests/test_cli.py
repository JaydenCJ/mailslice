"""CLI behavior: exit codes, output shape, JSON mode, error messages.

These run ``main()`` in-process for speed; scripts/smoke.sh covers the same
surface through a real subprocess.
"""

import gzip
import json
import subprocess
import sys
from pathlib import Path

import pytest

from mailslice import __version__
from mailslice.cli import main

from conftest import make_mbox, make_message


@pytest.fixture
def mbox_path(tmp_path, simple_mbox):
    path = tmp_path / "takeout.mbox"
    path.write_bytes(simple_mbox)
    return path


class TestScanCommand:
    def test_scan_reports_counts_span_and_json(self, mbox_path, capsys):
        assert main(["scan", str(mbox_path)]) == 0
        out = capsys.readouterr().out
        assert "messages: 2" in out
        assert "span: 2020-2021" in out
        assert "Inbox/2020" in out
        assert "Sent/2021" in out
        assert main(["scan", str(mbox_path), "--json"]) == 0
        data = json.loads(capsys.readouterr().out)
        assert data["messages"] == 2
        assert data["year_span"] == "2020-2021"
        assert main(["scan", str(mbox_path), "--limit", "1", "--json"]) == 0
        assert json.loads(capsys.readouterr().out)["messages"] == 1

    def test_scan_reads_gzip_transparently(self, tmp_path, simple_mbox, capsys):
        path = tmp_path / "takeout.mbox.gz"
        path.write_bytes(gzip.compress(simple_mbox))
        assert main(["scan", str(path), "--json"]) == 0
        assert json.loads(capsys.readouterr().out)["messages"] == 2


class TestSplitCommand:
    def test_split_writes_maildir_and_prints_table(self, mbox_path, tmp_path, capsys):
        out_dir = tmp_path / "mail"
        assert main(["split", str(mbox_path), "-o", str(out_dir)]) == 0
        stdout = capsys.readouterr().out
        assert "total: 2 messages" in stdout
        assert f"wrote maildir folders under {out_dir}/" in stdout
        assert any((out_dir / "Inbox" / "2020" / "cur").iterdir())
        eml_dir = tmp_path / "eml"
        assert main(
            ["split", str(mbox_path), "-o", str(eml_dir), "--format", "eml"]
        ) == 0
        assert list((eml_dir / "Inbox" / "2020").glob("*.eml"))

    def test_split_dry_run_writes_nothing(self, mbox_path, tmp_path, capsys):
        out_dir = tmp_path / "mail"
        assert main(["split", str(mbox_path), "-o", str(out_dir), "--dry-run"]) == 0
        assert not out_dir.exists()
        assert "dry run: nothing written" in capsys.readouterr().out

    def test_split_exclude_label_reported_in_json(self, mbox_path, tmp_path, capsys):
        out_dir = tmp_path / "mail"
        assert main(
            [
                "split", str(mbox_path), "-o", str(out_dir),
                "--exclude-label", "Sent", "--json",
            ]
        ) == 0
        data = json.loads(capsys.readouterr().out)
        assert data["skipped"] == {"excluded label": 1}
        assert not (out_dir / "Sent").exists()

    def test_split_since_after_until_is_an_error(self, mbox_path, tmp_path, capsys):
        rc = main(
            [
                "split", str(mbox_path), "-o", str(tmp_path / "m"),
                "--since", "2021", "--until", "2020",
            ]
        )
        assert rc == 1
        assert "--since" in capsys.readouterr().err


class TestErrorsAndMeta:
    def test_missing_and_non_mbox_inputs_are_clean_errors(self, tmp_path, capsys):
        assert main(["scan", str(tmp_path / "absent.mbox")]) == 1
        assert "no such file" in capsys.readouterr().err
        path = tmp_path / "notmail.mbox"
        path.write_bytes(b"PK\x03\x04 this is a zip, not an mbox\n")
        assert main(["scan", str(path)]) == 1
        err = capsys.readouterr().err
        assert "mailslice:" in err and "mbox" in err

    def test_os_level_failures_are_clean_errors_not_tracebacks(
        self, tmp_path, capsys
    ):
        # A directory where a file is expected: the mistake of pointing
        # mailslice at the extracted Takeout folder instead of the mbox.
        assert main(["scan", str(tmp_path)]) == 1
        err = capsys.readouterr().err
        assert err.startswith("mailslice:") and "Traceback" not in err
        # A .gz that is not actually gzip data must fail the same clean way.
        bad_gz = tmp_path / "takeout.mbox.gz"
        bad_gz.write_bytes(b"this is not gzip data\n")
        assert main(["scan", str(bad_gz)]) == 1
        err = capsys.readouterr().err
        assert err.startswith("mailslice:") and "Traceback" not in err

    def test_version_flag(self, capsys):
        with pytest.raises(SystemExit) as excinfo:
            main(["--version"])
        assert excinfo.value.code == 0
        assert capsys.readouterr().out.strip() == f"mailslice {__version__}"

    def test_usage_errors_exit_2(self, mbox_path, tmp_path):
        with pytest.raises(SystemExit) as no_command:
            main([])
        assert no_command.value.code == 2
        with pytest.raises(SystemExit) as bad_choice:
            main(
                [
                    "split", str(mbox_path), "-o", str(tmp_path / "m"),
                    "--group-by", "month",
                ]
            )
        assert bad_choice.value.code == 2


class TestSampleGenerator:
    """The examples/ generator is part of the demo surface; keep it honest."""

    def test_sample_mbox_splits_cleanly(self, tmp_path, capsys):
        sample = tmp_path / "sample.mbox"
        script = (
            Path(__file__).resolve().parent.parent
            / "examples" / "make_sample_mbox.py"
        )
        proc = subprocess.run(
            [sys.executable, str(script), str(sample)],
            capture_output=True, text=True,
        )
        assert proc.returncode == 0, proc.stderr
        assert main(["scan", str(sample), "--json"]) == 0
        data = json.loads(capsys.readouterr().out)
        assert data["messages"] == 8
        assert data["malformed"] == 0
        labels = {bucket["label"] for bucket in data["buckets"]}
        assert "請求書" in labels  # encoded-word label decoded
        assert "Receipts, 2020" in labels  # quoted label with comma
