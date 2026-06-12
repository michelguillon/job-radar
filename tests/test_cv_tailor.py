"""Tests for the cv-tailor integration Phase 1 data model + read-model join (SPEC §11.3).

Covers the validator (models.record.validate_cv_tailor_link), the latest-per-job loader
(cli.stats.load_cv_tailor_links), and the embedded ``cv_tailor`` section on an index row
(cli.stats.build_index_rows). The API endpoints are exercised in tests/test_api.py.
"""

from __future__ import annotations

from cli.stats import build_index_rows, load_cv_tailor_links
from cli.track import _default_state
from models.record import ApplicationRecord, validate_cv_tailor_link


def _link(job_id: str, *, ts: str, run: str, **over) -> dict:
    rec = {
        "v": 1, "ts": ts, "job_id": job_id, "cv_tailor_run_id": run,
        "fit_score": 0.56, "coverage_score": 0.35, "cv_quality_score": 8.1,
        "cvcm_enabled": True, "tailoring_mode": "full",
        "output_link": "https://cv-tailor.example/runs/" + run, "notes": "ok", "source": "manual",
    }
    rec.update(over)
    return rec


def _score(job_id: str) -> ApplicationRecord:
    return ApplicationRecord(
        job_id=job_id, profile_version="1.2", scored_at="2026-06-11T00:00:00Z", fit_score=8,
        fit_label="good_fit", fit_label_reason="r", requirement_gaps=[], blocking_constraints=[],
        priority_score=7, application_status="new", notes="",
    )


# --- validator -----------------------------------------------------------------

def test_validate_cv_tailor_link_valid():
    assert validate_cv_tailor_link(_link("sha256:j1", ts="2026-06-11T12:00:00Z", run="run_1")) == []


def test_validate_fit_score_valid():
    assert validate_cv_tailor_link(
        _link("sha256:j1", ts="2026-06-11T12:00:00Z", run="run_1", fit_score=0.56)
    ) == []


def test_validate_fit_score_out_of_range():
    errors = validate_cv_tailor_link(
        _link("sha256:j1", ts="2026-06-11T12:00:00Z", run="run_1", fit_score=1.5)
    )
    assert any("fit_score" in e for e in errors)


def test_validate_cv_quality_score_valid():
    # 8.1 is valid on the 0–10 rubric scale (would FAIL the 0–1 check fit/coverage use).
    assert validate_cv_tailor_link(
        _link("sha256:j1", ts="2026-06-11T12:00:00Z", run="run_1", cv_quality_score=8.1)
    ) == []


def test_validate_cv_quality_score_out_of_range():
    errors = validate_cv_tailor_link(
        _link("sha256:j1", ts="2026-06-11T12:00:00Z", run="run_1", cv_quality_score=11.0)
    )
    assert any("cv_quality_score" in e for e in errors)


def test_validate_cv_tailor_link_optional_fields_omitted():
    # Only v/ts/job_id are required; everything else may be absent.
    assert validate_cv_tailor_link({"v": 1, "ts": "2026-06-11T12:00:00Z", "job_id": "sha256:j1"}) == []


def test_validate_cv_tailor_link_missing_job_id():
    errors = validate_cv_tailor_link({"v": 1, "ts": "2026-06-11T12:00:00Z", "job_id": ""})
    assert any("job_id" in e for e in errors)


def test_validate_cv_tailor_link_bad_source():
    errors = validate_cv_tailor_link(
        _link("sha256:j1", ts="2026-06-11T12:00:00Z", run="run_1", source="bogus")
    )
    assert any("source" in e for e in errors)


def test_validate_cv_tailor_link_cvcm_not_bool():
    errors = validate_cv_tailor_link(
        _link("sha256:j1", ts="2026-06-11T12:00:00Z", run="run_1", cvcm_enabled="yes")
    )
    assert any("cvcm_enabled" in e for e in errors)


# --- loader --------------------------------------------------------------------

def test_load_cv_tailor_links_latest_per_job(tmp_path):
    path = tmp_path / "cv_tailor_links.jsonl"
    import json
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(_link("sha256:j1", ts="2026-06-10T00:00:00Z", run="run_old")) + "\n")
        fh.write(json.dumps(_link("sha256:j1", ts="2026-06-11T00:00:00Z", run="run_new")) + "\n")
    links = load_cv_tailor_links(str(path))
    assert set(links) == {"sha256:j1"}
    assert links["sha256:j1"]["cv_tailor_run_id"] == "run_new"  # latest ts wins


def test_load_cv_tailor_links_missing_file(tmp_path):
    assert load_cv_tailor_links(str(tmp_path / "nope.jsonl")) == {}


def test_load_migrates_old_field_names(tmp_path):
    # A Phase-1 record on disk: old cv_tailor_score + speculative grounding_score (deviation 43).
    path = tmp_path / "cv_tailor_links.jsonl"
    import json
    old = {
        "v": 1, "ts": "2026-06-11T00:00:00Z", "job_id": "sha256:j1", "cv_tailor_run_id": "run_old",
        "cv_tailor_score": 0.72, "coverage_score": 0.81, "grounding_score": 0.96, "source": "manual",
    }
    path.write_text(json.dumps(old) + "\n", encoding="utf-8")
    rec = load_cv_tailor_links(str(path))["sha256:j1"]
    assert rec["fit_score"] == 0.72        # cv_tailor_score → fit_score
    assert "cv_tailor_score" not in rec     # old name removed
    assert "grounding_score" not in rec     # dropped silently (no destination field)


# --- index row -----------------------------------------------------------------

def test_index_row_has_cv_tailor_section():
    scores = {"sha256:j1": _score("sha256:j1")}
    workflow = {"sha256:j1": _default_state()}
    rows = build_index_rows(scores, {}, {}, workflow)
    assert rows[0]["cv_tailor"] == {"has_output": False}


def test_index_row_embeds_cv_tailor_link():
    scores = {"sha256:j1": _score("sha256:j1")}
    workflow = {"sha256:j1": _default_state()}
    links = {"sha256:j1": _link("sha256:j1", ts="2026-06-11T12:00:00Z", run="run_1")}
    rows = build_index_rows(scores, {}, {}, workflow, cv_tailor_links=links)
    cv = rows[0]["cv_tailor"]
    assert cv["has_output"] is True
    assert cv["run_id"] == "run_1"
    assert cv["fit_score"] == 0.56 and cv["coverage_score"] == 0.35 and cv["cv_quality_score"] == 8.1
    assert "grounding_score" not in cv and "cv_score" not in cv
    assert cv["cvcm_enabled"] is True and cv["tailoring_mode"] == "full"


def test_index_row_migrates_old_link_fields():
    # An old-format link (cv_tailor_score) reaches the view → surfaces as fit_score.
    scores = {"sha256:j1": _score("sha256:j1")}
    workflow = {"sha256:j1": _default_state()}
    links = {"sha256:j1": {"cv_tailor_run_id": "run_old", "cv_tailor_score": 0.72,
                           "coverage_score": 0.81, "grounding_score": 0.96}}
    cv = build_index_rows(scores, {}, {}, workflow, cv_tailor_links=links)[0]["cv_tailor"]
    assert cv["fit_score"] == 0.72 and cv["cv_quality_score"] is None
