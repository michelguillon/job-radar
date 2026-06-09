"""Tests for the score.py CLI — loading, presentation filters, and output."""

import json
from pathlib import Path

import pytest

import score as cli
from models.record import ApplicationRecord, validate_application_record
from tests.factories import make_record

MANUAL_JSONL = (
    Path(__file__).resolve().parents[1] / "corpus" / "manual" / "manual_20260606.jsonl"
)


# --- Presentation filter (§6.3 table) ---


@pytest.mark.parametrize(
    "label,mode,shown",
    [
        ("strong_fit", "selective", True),
        ("stretch", "selective", True),
        ("blocked_fit", "selective", True),
        ("interview_practice", "selective", False),
        ("income_bridge", "selective", False),
        ("interview_practice", "active", True),
        ("income_bridge", "active", False),
        ("income_bridge", "broad", True),
    ],
)
def test_is_shown_by_mode(label, mode, shown):
    assert cli.is_shown(label, 9, mode, min_fit=1) is shown


def test_is_shown_respects_min_fit():
    assert cli.is_shown("strong_fit", 5, "selective", min_fit=6) is False
    assert cli.is_shown("strong_fit", 6, "selective", min_fit=6) is True


# --- load_records ---


def test_load_records_skips_bad_lines(tmp_path):
    good = make_record(raw_text="good").to_jsonl()
    bad_version = json.loads(good)
    bad_version["schema_version"] = "9.9"
    f = tmp_path / "validated_x.jsonl"
    f.write_text(good + "\n" + json.dumps(bad_version) + "\n" + "{garbage\n", encoding="utf-8")

    records = cli.load_records(str(tmp_path / "validated_*.jsonl"))
    assert len(records) == 1


# --- main: end-to-end ---


def test_main_writes_one_valid_record_per_input(tmp_path, monkeypatch, capsys):
    # Use the real manual corpus as input; redirect output into tmp_path.
    monkeypatch.setattr(cli, "OUT_DIR", str(tmp_path / "scored"))
    rc = cli.main(["--input", str(MANUAL_JSONL)])
    assert rc == 0

    out_files = list((tmp_path / "scored").glob("scored_*.jsonl"))
    assert len(out_files) == 1
    lines = [ln for ln in out_files[0].read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) == 10  # one ApplicationRecord per JDRecord

    for line in lines:
        rec = ApplicationRecord.from_jsonl(line)
        assert validate_application_record(rec) == []
        assert rec.application_status == "new"

    out = capsys.readouterr().out
    assert "Scored 10 record(s)" in out
    assert "fit_label distribution" in out


def test_main_does_not_mutate_input(tmp_path, monkeypatch):
    src = tmp_path / "validated_src.jsonl"
    src.write_text(MANUAL_JSONL.read_text(encoding="utf-8"), encoding="utf-8")
    before = src.read_text(encoding="utf-8")

    monkeypatch.setattr(cli, "OUT_DIR", str(tmp_path / "scored"))
    cli.main(["--input", str(src)])

    assert src.read_text(encoding="utf-8") == before  # input untouched


def test_main_min_fit_changes_shown_count(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "OUT_DIR", str(tmp_path / "scored"))
    cli.main(["--input", str(MANUAL_JSONL), "--min-fit", "8"])
    out = capsys.readouterr().out
    # The two good_fit (score 7) manual records fall below min-fit 8.
    assert "Filtered: 2" in out
