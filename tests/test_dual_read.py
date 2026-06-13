"""Tests for the JSONL-vs-SQLite dual-read comparison (Phase 6.5 Step 3).

Builds a fixture corpus of interactive state, backfills it into a tmp SQLite DB, then
asserts the index rows built from JSONL and from SQLite are byte-identical.
"""

from __future__ import annotations

import json

import pytest

import cli.db_migrate as migrate
import cli.stats as stats
from models.record import ApplicationRecord

from tests.factories import make_record

JOB = "sha256:a"


@pytest.fixture
def fixture_corpus(tmp_path, monkeypatch):
    monkeypatch.setenv("JR_DB_PATH", str(tmp_path / "test.db"))

    jd = make_record(id=JOB, source_url="http://x", company="Acme", raw_text="Senior PM\nblah")
    score = ApplicationRecord(
        job_id=JOB, profile_version="1.2", scored_at="2026-06-09T00:00:00Z",
        fit_score=7, fit_label="good_fit", fit_label_reason="ok",
        requirement_gaps=[], blocking_constraints=[], priority_score=7,
        application_status="new", notes="",
    )
    scores = {JOB: score}
    jds = {JOB: jd}
    metas = {"http://x": {"source_url": "http://x", "title": "Senior PM", "location_str": "London"}}

    al = tmp_path / "activity_log.jsonl"
    al.write_text(
        json.dumps({"v": 1, "ts": "2026-06-10T00:00:00Z", "job_id": JOB, "event": "status", "value": "applied", "notes": "sent"}) + "\n"
        + json.dumps({"v": 1, "ts": "2026-06-11T00:00:00Z", "job_id": JOB, "event": "note", "value": None, "notes": "called back"}) + "\n",
        encoding="utf-8",
    )
    ann = tmp_path / "annotations.jsonl"
    ann.write_text(
        json.dumps({"v": 1, "ts": "2026-06-10T01:00:00Z", "job_id": JOB, "annotation_type": "extraction_error",
                    "field": "domain", "observed": ["X"], "expected": ["Y"], "reason": "wrong",
                    "scorer_label": "good_fit", "scorer_fit_score": 7}) + "\n"
        + json.dumps({"v": 1, "ts": "2026-06-10T02:00:00Z", "job_id": JOB, "annotation_type": "rejection_reason",
                      "field": None, "observed": None, "expected": None, "reason": "compensation_below_range",
                      "scorer_label": "good_fit", "scorer_fit_score": 7}) + "\n",
        encoding="utf-8",
    )
    cvt = tmp_path / "cv_tailor_links.jsonl"
    cvt.write_text(
        json.dumps({"v": 1, "ts": "2026-06-10T03:00:00Z", "job_id": JOB, "cv_tailor_run_id": "run-1",
                    "fit_score": 0.8, "coverage_score": 0.6, "cv_quality_score": 7.5,
                    "cvcm_enabled": True, "tailoring_mode": "full", "output_link": "http://o",
                    "notes": "", "source": "manual"}) + "\n",
        encoding="utf-8",
    )

    migrate.backfill_activity_log(str(al))
    migrate.backfill_annotations(str(ann))
    migrate.backfill_cv_tailor_links(str(cvt))

    paths = dict(activity_log=str(al), annotations=str(ann), cv_tailor_links=str(cvt))
    return scores, jds, metas, paths


def test_dual_read_zero_divergences(fixture_corpus):
    scores, jds, metas, paths = fixture_corpus
    rows_j = stats.build_rows_for_source("jsonl", scores, jds, metas, **paths)
    rows_s = stats.build_rows_for_source("sqlite", scores, jds, metas, **paths)
    assert stats.compare_index_rows(rows_j, rows_s) == []
    # Sanity: the interactive state actually landed (not "both empty, trivially equal").
    assert rows_s[0]["application_status"] == "applied"
    assert rows_s[0]["annotation_count"] == 2
    assert rows_s[0]["cv_tailor"]["has_output"] is True
    assert rows_s[0]["cv_tailor"]["cvcm_enabled"] is True


def test_compare_detects_field_divergence():
    a = [{"job_id": "x", "application_status": "applied"}]
    b = [{"job_id": "x", "application_status": "new"}]
    diffs = stats.compare_index_rows(a, b)
    assert any("application_status" in d for d in diffs)


def test_compare_detects_missing_job():
    diffs = stats.compare_index_rows([{"job_id": "x"}], [])
    assert diffs == ["x: present in A only"]


def test_main_source_both_clean(fixture_corpus, tmp_path, monkeypatch, capsys):
    """End-to-end through main(): --source both exits 0 and prints 0 divergences."""
    scores, jds, metas, paths = fixture_corpus
    # Write the pipeline-artefact files main() loads (scores/validated/meta).
    scored = tmp_path / "scored.jsonl"
    scored.write_text(scores[JOB].to_jsonl() + "\n", encoding="utf-8")
    validated = tmp_path / "validated.jsonl"
    validated.write_text(jds[JOB].to_jsonl() + "\n", encoding="utf-8")
    meta = tmp_path / "meta.jsonl"
    meta.write_text(json.dumps(metas["http://x"]) + "\n", encoding="utf-8")
    # Stub the writer so the test never touches the real corpus/index.json (the default
    # path arg is bound at def time, so patching the constant wouldn't redirect it).
    written = {}
    monkeypatch.setattr(stats, "export_index", lambda rows, st, **kw: written.update(rows=rows) or "index.json")

    rc = stats.main([
        "--input", str(validated), "--export-index", "--source", "both",
        "--scored", str(scored), "--validated", str(validated), "--meta", str(meta),
        "--activity-log", paths["activity_log"], "--annotations", paths["annotations"],
        "--cv-tailor-links", paths["cv_tailor_links"], "--stats-file", str(tmp_path / "nope.json"),
    ])
    out = capsys.readouterr().out
    assert rc == 0
    assert "0 divergences" in out
