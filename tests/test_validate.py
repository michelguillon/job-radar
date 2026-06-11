"""Tests for pipeline.validate and the validate.py CLI loader."""

import cli.validate as cli
from models.record import JDRECORD_SCHEMA_VERSION
from pipeline.validate import validate_records
from tests.factories import base_envelope, make_record


def test_validate_records_splits_pass_fail():
    valid = make_record(raw_text="ok")
    invalid = make_record(raw_text="bad")
    invalid.seniority = "bogus"  # not in the SENIORITY enum
    passed, failed = validate_records([valid, invalid])

    assert passed == [valid]
    assert len(failed) == 1
    assert any("seniority" in e for e in failed[0]["validation_errors"])
    assert failed[0]["company"] == "Test Co"  # failed entry carries the envelope


def test_validate_records_all_pass():
    records = [make_record(raw_text=f"r{i}") for i in range(3)]
    passed, failed = validate_records(records)
    assert len(passed) == 3 and failed == []


def test_cli_load_lines_treats_bad_lines_as_failures(tmp_path):
    good = make_record(raw_text="good").to_jsonl()
    wrong_version = dict(base_envelope())
    wrong_version["schema_version"] = "9.9"
    import json

    f = tmp_path / "labelled.jsonl"
    f.write_text(
        good + "\n" + json.dumps(wrong_version) + "\n" + "{not json}\n",
        encoding="utf-8",
    )

    records, parse_failures = cli.load_lines(str(tmp_path / "*.jsonl"))
    assert len(records) == 1  # only the good line parses
    assert len(parse_failures) == 2  # wrong schema_version + garbage
    assert all("validation_errors" in pf for pf in parse_failures)


def test_schema_version_constant_is_current():
    # guard: the JDRecord fixture and the model agree on JDRecord's frozen version
    assert base_envelope()["schema_version"] == JDRECORD_SCHEMA_VERSION


def test_cli_runs_bare_with_date_default(tmp_path):
    # No --input: defaults to corpus/labelled/labelled_<date>T*.jsonl. A future date matches
    # nothing, so validate runs cleanly over zero records and exits 0 (proves bare invocation
    # works for the weekly cron — argparse no longer requires --input).
    rc = cli.main(["--date", "20990101", "--out-dir", str(tmp_path)])
    assert rc == 0
