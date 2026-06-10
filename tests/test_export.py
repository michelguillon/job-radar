"""Tests for export.py — set selection, exclusions, and pair format."""

import json

import cli.export as export
from collectors.base import build_raw_record
from models.record import _EXTRACTION_FIELDS
from tests.factories import make_record


def _labelled(tier: int):
    return make_record(raw_text=f"jd tier {tier}", tier=tier)


def test_to_pair_format():
    pair = export.to_pair(_labelled(1))
    assert set(pair) == {"prompt", "completion"}
    assert pair["prompt"] == "jd tier 1"
    completion = json.loads(pair["completion"])  # completion is a valid JSON string
    assert set(completion) == set(_EXTRACTION_FIELDS)
    assert completion["seniority"] == "ic"


def test_eval_excludes_tier4():
    records = [_labelled(1), _labelled(2), _labelled(3), _labelled(4)]
    eval_set = export.select(records, "eval")
    assert sorted(r.tier for r in eval_set) == [1, 2, 3]  # no Tier 4


def test_train_and_full_include_all_tiers():
    records = [_labelled(1), _labelled(4)]
    assert sorted(r.tier for r in export.select(records, "train")) == [1, 4]
    assert sorted(r.tier for r in export.select(records, "full")) == [1, 4]


def test_excludes_unlabelled_and_invalid():
    labelled = _labelled(1)
    unlabelled = build_raw_record(
        source_url="u", source_ats="greenhouse", company="C", collected_at="2026-06-09", raw_text="raw"
    )  # role_type is None
    invalid = _labelled(2)
    invalid.seniority = "bogus"  # fails schema validation

    out = export.select([labelled, unlabelled, invalid], "full")
    assert [r.company for r in out] == ["Test Co"]  # only the valid labelled one
    assert out == [labelled]


def test_load_records_skips_wrong_schema_version(tmp_path):
    good = _labelled(1).to_jsonl()
    bad = dict(json.loads(good))
    bad["schema_version"] = "0.1"
    f = tmp_path / "v.jsonl"
    f.write_text(good + "\n" + json.dumps(bad) + "\n", encoding="utf-8")

    loaded = export.load_records(str(tmp_path / "*.jsonl"))
    assert len(loaded) == 1  # wrong-schema_version line skipped


def test_load_records_excludes_calibration_fixtures(tmp_path):
    # Calibration fixtures must never reach a fine-tune export, even if globbed.
    train_dir = tmp_path / "validated"
    cal_dir = tmp_path / "calibration"
    train_dir.mkdir()
    cal_dir.mkdir()
    (train_dir / "validated_x.jsonl").write_text(_labelled(4).to_jsonl() + "\n", encoding="utf-8")
    (cal_dir / "validated_x.jsonl").write_text(_labelled(4).to_jsonl() + "\n", encoding="utf-8")

    loaded = export.load_records(str(tmp_path / "**" / "*.jsonl"))
    assert len(loaded) == 1  # only the non-calibration file is loaded
