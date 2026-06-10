"""Tests for tier2_review — accept/edit/skip mechanics, checkpoint, resume."""

import json

import cli.tier2_review as t2
from collectors.base import build_raw_record
from models.record import _EXTRACTION_FIELDS, JDRecord


def _rec(i: int) -> JDRecord:
    r = build_raw_record(
        source_url=f"https://x/{i}",
        source_ats="greenhouse",
        company=f"Company {i}",
        collected_at="2026-06-09",
        raw_text=f"job description number {i}",
    )
    r.id = f"sha256:{i:064d}"
    return r


def _scripted(answers):
    it = iter(answers)
    return lambda prompt="": next(it)


def _paths(tmp_path):
    return {
        "accepted_path": str(tmp_path / "tier2.jsonl"),
        "skipped_path": str(tmp_path / "tier2_skipped.jsonl"),
        "checkpoint_path": str(tmp_path / "progress.json"),
    }


def test_accept_edit_skip_all_work(tmp_path):
    records = [_rec(1), _rec(2), _rec(3)]
    paths = _paths(tmp_path)

    # r1 accept; r2 skip; r3 edit (set role_type + seniority, keep the other 15).
    answers = ["a", "s", "e", "Product, GTM", "senior_ic"] + [""] * (len(_EXTRACTION_FIELDS) - 2)
    counts = t2.run(records, **paths, input_fn=_scripted(answers), output_fn=lambda *a: None)

    assert counts == {"accepted": 1, "edited": 1, "skipped": 1, "already_reviewed": 0}

    accepted = [JDRecord.from_jsonl(l) for l in open(paths["accepted_path"], encoding="utf-8")]
    skipped = [JDRecord.from_jsonl(l) for l in open(paths["skipped_path"], encoding="utf-8")]

    assert [r.company for r in accepted] == ["Company 1", "Company 3"]
    assert all(r.tier == 2 for r in accepted)  # accepted records become Tier 2
    assert [r.company for r in skipped] == ["Company 2"]

    edited = accepted[1]
    assert edited.role_type == ["Product", "GTM"]  # list field parsed from CSV
    assert edited.seniority == "senior_ic"
    assert edited.technical_depth is None  # blank kept the placeholder None


def test_checkpoint_written_after_each_record(tmp_path):
    records = [_rec(1), _rec(2)]
    paths = _paths(tmp_path)
    t2.run(records, **paths, input_fn=_scripted(["a", "s"]), output_fn=lambda *a: None)

    data = json.load(open(paths["checkpoint_path"], encoding="utf-8"))
    assert set(data["reviewed"]) == {records[0].id, records[1].id}


def test_resume_skips_already_reviewed(tmp_path):
    records = [_rec(1), _rec(2)]
    paths = _paths(tmp_path)
    # Pre-seed the checkpoint as if r1 was already reviewed in a prior run.
    with open(paths["checkpoint_path"], "w", encoding="utf-8") as fh:
        json.dump({"reviewed": [records[0].id]}, fh)

    # Only r2 needs an answer; if r1 were re-prompted, next() would raise.
    counts = t2.run(records, **paths, input_fn=_scripted(["a"]), output_fn=lambda *a: None)

    assert counts["already_reviewed"] == 1
    assert counts["accepted"] == 1
    accepted = [JDRecord.from_jsonl(l) for l in open(paths["accepted_path"], encoding="utf-8")]
    assert [r.company for r in accepted] == ["Company 2"]


def test_load_records_and_unlabelled_filter(tmp_path):
    labelled = _rec(1)
    labelled.role_type = ["Product"]  # already extracted
    unlabelled = _rec(2)  # role_type is None
    f = tmp_path / "clean_20260609.jsonl"
    f.write_text(labelled.to_jsonl() + "\n" + unlabelled.to_jsonl() + "\n", encoding="utf-8")

    loaded = t2.load_records(str(tmp_path / "clean_*.jsonl"))
    assert len(loaded) == 2
    to_review = [r for r in loaded if t2.is_unlabelled(r)]
    assert [r.company for r in to_review] == ["Company 2"]
