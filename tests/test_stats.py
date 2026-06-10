"""Tests for stats.py — JDRecord summary aggregation and the joined UI index export.

The index export is no longer a bare JDRecord array (SPEC §9.4 / CLAUDE.md
deviation 27): it joins the latest score per job_id with the JDRecord extraction,
the metadata sidecar, and the activity-log projection, then wraps a small stats
block so the single mounted file is self-contained for the UI.
"""

import json

import cli.stats as stats
from models.record import ApplicationRecord
from tests.factories import make_record


def _rec(*, tier, role_type, domain, decision, fit, applied):
    r = make_record(raw_text="x", tier=tier)
    r.role_type = role_type
    r.domain = domain
    r.application_decision = decision
    r.fit_score = fit
    r.applied = applied
    return r


def _corpus():
    return [
        _rec(tier=1, role_type=["Solutions Engineering"], domain=["FinTech"], decision="applied", fit=7, applied=True),
        _rec(tier=2, role_type=["Pre-Sales", "Solutions Consulting"], domain=["SaaS"], decision="want_to_apply", fit=8, applied=False),
        _rec(tier=4, role_type=["GTM"], domain=["SaaS"], decision="pending", fit=None, applied=False),
    ]


def _score(job_id, *, fit=7, label="good_fit", priority=7, scored_at="2026-06-10T08:00:00Z"):
    return ApplicationRecord(
        job_id=job_id,
        profile_version="1.2",
        scored_at=scored_at,
        fit_score=fit,
        fit_label=label,
        fit_label_reason=f"reason for {job_id}",
        requirement_gaps=["gap-x"],
        blocking_constraints=[],
        priority_score=priority,
        application_status="new",
        notes="",
    )


# --- JDRecord summary (unchanged) ---------------------------------------------

def test_summarize_counts():
    s = stats.summarize(_corpus())
    assert s["total"] == 3
    assert s["by_tier"] == {1: 1, 2: 1, 4: 1}
    assert s["by_role_type"]["Pre-Sales"] == 1
    assert s["by_domain"]["SaaS"] == 2  # counted across two records
    assert s["by_application_decision"]["applied"] == 1
    assert s["applied_count"] == 1
    assert s["fit_score"] == {"n": 2, "mean": 7.5, "min": 7, "max": 8}


def test_load_records_reads_glob(tmp_path):
    f = tmp_path / "a.jsonl"
    f.write_text("\n".join(r.to_jsonl() for r in _corpus()) + "\n", encoding="utf-8")
    loaded = stats.load_records(str(tmp_path / "*.jsonl"))
    assert len(loaded) == 3


# --- joined index rows --------------------------------------------------------

def test_build_index_rows_joins_score_jd_and_workflow():
    jd = make_record(raw_text="Solutions Engineer\nlead the team", tier=1)
    jd.company = "Acme"
    jd.role_type = ["Solutions Engineering"]
    jd.domain = ["FinTech"]
    jd.culture_signals = ["fast-paced"]
    scores = {jd.id: _score(jd.id, fit=8, label="strong_fit", priority=9)}
    metas = {jd.source_url: {"source_url": jd.source_url, "title": "Solutions Engineer", "location_str": "London, UK"}}
    workflow = {jd.id: {"status": "applied", "outcome": None, "application_date": "2026-06-10", "notes": "applied online", "title_override": None}}

    rows = stats.build_index_rows(scores, {jd.id: jd}, metas, workflow)
    assert len(rows) == 1
    row = rows[0]
    # scoring
    assert row["fit_score"] == 8 and row["fit_label"] == "strong_fit" and row["priority_score"] == 9
    assert row["requirement_gaps"] == ["gap-x"]
    # workflow projection wins over the scorer's baseline "new"
    assert row["application_status"] == "applied"
    assert row["application_date"] == "2026-06-10"
    # join detail
    assert row["company"] == "Acme"
    assert row["title"] == "Solutions Engineer"
    assert row["location"] == "London, UK"
    assert row["location_workable"] == "yes"
    assert row["domain"] == ["FinTech"]
    assert row["culture_signals"] == ["fast-paced"]
    assert "Solutions Engineer" in row["raw_text"]


def test_build_index_rows_defaults_when_jd_missing():
    scores = {"sha256:orphan": _score("sha256:orphan")}
    rows = stats.build_index_rows(scores, {}, {}, {})
    row = rows[0]
    assert row["company"] == "?" and row["domain"] == [] and row["seniority"] == ""
    assert row["application_status"] == "new"  # default projection state


def test_index_stats_block():
    rows = [
        {"fit_score": 8, "fit_label": "strong_fit", "application_status": "new"},
        {"fit_score": 8, "fit_label": "good_fit", "application_status": "applied"},
        {"fit_score": 5, "fit_label": "stretch", "application_status": "new"},
    ]
    s = stats.index_stats(rows, cost_to_date=1.23)
    assert s["total"] == 3
    assert s["by_fit_label"]["strong_fit"] == 1
    assert s["by_application_status"]["new"] == 2
    assert s["fit_score_distribution"] == {"5": 1, "8": 2}
    assert s["cost_to_date_usd"] == 1.23


def test_load_cost_to_date(tmp_path):
    ledger = tmp_path / "stats.json"
    ledger.write_text(json.dumps([{"cost_usd": 0.2}, {"cost_usd": 0.8}, {}]), encoding="utf-8")
    assert stats.load_cost_to_date(str(ledger)) == 1.0


def test_load_cost_to_date_missing_file(tmp_path):
    assert stats.load_cost_to_date(str(tmp_path / "nope.json")) == 0.0


def test_export_index_shape(tmp_path):
    rows = stats.build_index_rows({"sha256:a": _score("sha256:a")}, {}, {}, {})
    s = stats.index_stats(rows, cost_to_date=0.5)
    path = str(tmp_path / "index.json")
    stats.export_index(rows, s, path=path, generated_at="2026-06-10T09:00:00Z")

    data = json.loads(open(path, encoding="utf-8").read())
    assert isinstance(data, dict)
    assert data["schema_version"]
    assert data["generated_at"] == "2026-06-10T09:00:00Z"
    assert data["stats"]["cost_to_date_usd"] == 0.5
    assert isinstance(data["records"], list) and len(data["records"]) == 1
    # records are denormalised (no nested extraction/annotation envelope)
    assert "extraction" not in data["records"][0]
