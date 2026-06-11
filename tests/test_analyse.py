"""Tests for analyse.py — read-only corpus reports (SPEC §11.1).

Covers the pure aggregation functions (label/score/status/company/gap counts +
the min-sample rate guard) and an integration smoke test that runs all four
reports against the live corpus (skipped when the corpus is empty, e.g. a fresh
checkout — corpus data is gitignored). Nothing here writes to any corpus file.
"""

from __future__ import annotations

from datetime import datetime, timezone

import cli.analyse as analyse
import cli.track as track
from models.record import ApplicationRecord
from tests.factories import make_record


def _now_dt() -> datetime:
    return datetime(2026, 6, 11, 9, 0, 0, tzinfo=timezone.utc)


def _score(job_id, *, fit=7, label="good_fit", priority=7, gaps=None, blockers=None,
           scored_at="2026-06-10T08:00:00Z") -> ApplicationRecord:
    return ApplicationRecord(
        job_id=job_id, profile_version="1.2", scored_at=scored_at, fit_score=fit,
        fit_label=label, fit_label_reason="reason", requirement_gaps=gaps or [],
        blocking_constraints=blockers or [], priority_score=priority,
        application_status="new", notes="",
    )


def _state(status="new", *, application_date=None):
    return {**track._default_state(), "status": status, "application_date": application_date}


# --- score distribution --------------------------------------------------------

def test_score_distribution_counts():
    scores = {
        "a": _score("a", label="strong_fit", fit=10),
        "b": _score("b", label="strong_fit", fit=9),
        "c": _score("c", label="blocked_fit", fit=4),
        "d": _score("d", label="stretch", fit=6),
    }
    labels = analyse.fit_label_counts(scores)
    assert labels["strong_fit"] == 2
    assert labels["blocked_fit"] == 1
    assert labels["income_bridge"] == 0          # absent label still present at 0
    assert list(labels) == analyse.FIT_LABEL_ORDER  # canonical order preserved

    sc = analyse.fit_score_counts(scores)
    assert sc[10] == 1 and sc[9] == 1 and sc[6] == 1 and sc[1] == 0
    assert set(sc) == set(range(1, 11))


def test_company_label_counts():
    scores = {"a": _score("a", label="strong_fit"), "b": _score("b", label="strong_fit"),
              "c": _score("c", label="blocked_fit")}
    by_job = {"a": "Mistral", "b": "Mistral", "c": "Databricks"}
    strong = analyse.company_label_counts(scores, by_job, "strong_fit")
    assert strong["Mistral"] == 2 and "Databricks" not in strong


# --- status --------------------------------------------------------------------

def test_status_report_counts():
    scores = {f"j{i}": _score(f"j{i}") for i in range(6)}
    workflow = {
        "j0": _state("new"), "j1": _state("review"), "j2": _state("shortlisted"),
        "j3": _state("applied"), "j4": _state("rejected"), "j5": _state("archived"),
    }
    counts = analyse.status_counts(scores, workflow)
    assert counts["new"] == 1 and counts["shortlisted"] == 1 and counts["archived"] == 1
    assert sum(counts.values()) == 6

    rates = analyse.review_rates(counts)
    # reviewed = total - new - archived = 6 - 1 - 1 = 4 (review/shortlisted/applied/rejected)
    assert rates["reviewed"] == 4
    assert rates["shortlisted"] == 1 and rates["applied"] == 1
    assert rates["review_rate"] == analyse._pct(4, 6)
    assert rates["shortlist_rate"] == analyse._pct(1, 4)


def test_review_rates_no_division_by_zero():
    counts = {s: 0 for s in analyse.STATUS_ORDER}
    rates = analyse.review_rates(counts)
    assert rates["review_rate"] == 0 and rates["shortlist_rate"] == 0 and rates["apply_rate"] == 0


def test_stale_applications_flags_old_applied_only():
    scores = {"old": _score("old"), "fresh": _score("fresh"), "review": _score("review")}
    jds = {"old": make_record(id="old", company="Fin"), "fresh": make_record(id="fresh", company="X")}
    workflow = {
        "old": _state("applied", application_date="2026-05-01"),    # 41 days before _now_dt
        "fresh": _state("applied", application_date="2026-06-05"),  # 6 days → not stale
        "review": _state("review", application_date=None),
    }
    stale = analyse.stale_applications(scores, jds, {}, workflow, now=_now_dt())
    assert [r["company"] for r in stale] == ["Fin"]
    assert stale[0]["days"] == 41


# --- companies (min-sample rate guard) -----------------------------------------

def test_company_report_min_sample_guard():
    # Small company (3 jobs, 1 shortlisted) must NOT appear in the shortlist-rate
    # ranking; a 5+-reviewed company should. Counts still show in the table.
    scores = {}
    workflow = {}
    by_job = {}
    for i in range(3):  # Small: 3 scored, 1 shortlisted
        jid = f"s{i}"
        scores[jid] = _score(jid)
        by_job[jid] = "Small"
        workflow[jid] = _state("shortlisted" if i == 0 else "review")
    for i in range(6):  # Big: 6 scored, all reviewed, 2 shortlisted
        jid = f"b{i}"
        scores[jid] = _score(jid)
        by_job[jid] = "Big"
        workflow[jid] = _state("shortlisted" if i < 2 else "applied")

    rows = {r["company"]: r for r in analyse.company_report(scores, by_job, workflow)}
    assert rows["Small"]["jobs"] == 3 and rows["Small"]["shortlisted"] == 1
    assert rows["Big"]["reviewed"] == 6 and rows["Big"]["shortlisted"] == 2

    text = analyse.format_companies(scores, by_job, workflow, today="2026-06-11")
    rate_section = text.split("Top by shortlist rate")[1]
    assert "Big" in rate_section          # 6 reviewed ≥ 5 → ranked
    assert "Small" not in rate_section    # 2 reviewed < 5 → suppressed (no rate)


def test_company_zero_shortlist_section():
    scores = {f"c{i}": _score(f"c{i}") for i in range(5)}
    by_job = {f"c{i}": "CoreWeave" for i in range(5)}
    workflow = {f"c{i}": _state("review") for i in range(5)}  # reviewed but never shortlisted
    text = analyse.format_companies(scores, by_job, workflow, today="2026-06-11")
    zero_section = text.split("Zero shortlists")[1]
    assert "CoreWeave" in zero_section and "5 scored, 0 shortlisted" in zero_section


# --- gaps ----------------------------------------------------------------------

def test_gaps_report_aggregation():
    scores = {
        "a": _score("a", label="blocked_fit", blockers=["hands-on specialist stack required"]),
        "b": _score("b", label="blocked_fit", blockers=["hands-on specialist stack required", "language requirement"]),
        "c": _score("c", label="strong_fit", gaps=["deployment methodology"]),
        "d": _score("d", label="good_fit", gaps=["deployment methodology", "system integrators"]),
    }
    g = analyse.gaps_report(scores)
    assert g["blocked_role_count"] == 2
    assert g["blocking_constraints"]["hands-on specialist stack required"] == 2
    assert g["blocking_constraints"]["language requirement"] == 1
    # requirement gaps span ALL scored roles
    assert g["requirement_gaps"]["deployment methodology"] == 2
    assert g["requirement_gaps"]["system integrators"] == 1
    # strong-fit gaps scoped to strong_fit roles only
    assert g["strong_role_count"] == 1
    assert g["strong_fit_gaps"]["deployment methodology"] == 1


# --- rejection reasons (gaps report section) -----------------------------------

def _rej(job_id, reason):
    return {"annotation_type": "rejection_reason", "field": None, "reason": reason}


def test_rejection_report_aggregates_reasons_and_companies():
    annotations = {
        "j1": [_rej("j1", "too_salesy")],
        "j2": [_rej("j2", "too_salesy"), {"annotation_type": "domain_incorrect", "reason": "x"}],
        "j3": [_rej("j3", "wrong_function")],
    }
    by_job = {"j1": "CoreWeave", "j2": "CoreWeave", "j3": "xAI"}
    rep = analyse.rejection_report(annotations, by_job)
    assert rep["total"] == 3              # the domain_incorrect annotation is not counted
    assert rep["role_count"] == 3
    assert rep["reasons"]["too_salesy"] == 2
    assert rep["company_counts"]["CoreWeave"] == 2
    assert rep["company_reasons"]["CoreWeave"]["too_salesy"] == 2


def test_gaps_report_includes_rejection_reasons():
    scores = {"j1": _score("j1", label="strong_fit"), "j2": _score("j2", label="good_fit")}
    annotations = {"j1": [_rej("j1", "too_salesy")], "j2": [_rej("j2", "domain_not_interesting")]}
    by_job = {"j1": "Mistral", "j2": "Stripe"}
    text = analyse.format_gaps(scores, today="2026-06-11", annotations=annotations, by_job=by_job)
    assert "REJECTION REASONS — 2 recorded across 2 rejected roles" in text
    assert "too_salesy" in text and "domain_not_interesting" in text
    assert "Most-rejected companies:" in text


def test_gaps_report_omits_rejection_section_when_none():
    scores = {"j1": _score("j1", label="blocked_fit", blockers=["x"])}
    text = analyse.format_gaps(scores, today="2026-06-11", annotations={}, by_job={"j1": "Acme"})
    assert "REJECTION REASONS" not in text
    # the rest of the gaps report still renders
    assert "REQUIREMENT GAPS & BLOCKERS" in text


# --- company yield (BACKLOG_YIELD_TRACKING) -----------------------------------

def _seed(name, *, ats="ashby", slug=None, domain="frontier_ai", fit="high", action="keep", notes=""):
    return {"name": name, "ats": ats, "slug": slug or name.lower(), "domain": domain,
            "fit_hypothesis": fit, "action": action, "notes": notes}


def _yield_scenario():
    """A small corpus: Mistral (6 scored, reviewed mix) + Hebbia (2 scored, tiny sample)."""
    scores, jds, workflow = {}, {}, {}
    # Mistral: 6 scored — 2 shortlisted, 1 applied, 1 high-score rejected, 1 review, 1 new
    layout = [("shortlisted", 8), ("shortlisted", 9), ("applied", 7), ("rejected", 8),
              ("review", 6), ("new", 5)]
    for i, (status, fit) in enumerate(layout):
        jid = f"m{i}"
        scores[jid] = _score(jid, fit=fit)
        jds[jid] = make_record(id=jid, company="Mistral AI")
        workflow[jid] = _state(status)
    # Hebbia: 2 scored, 1 shortlisted — below the 5-job rate guard
    for i, status in enumerate(["shortlisted", "review"]):
        jid = f"h{i}"
        scores[jid] = _score(jid, fit=6)
        jds[jid] = make_record(id=jid, company="Hebbia")
        workflow[jid] = _state(status)
    return scores, jds, workflow


def test_yield_report_basic():
    scores, jds, workflow = _yield_scenario()
    seeds = [_seed("Mistral AI", ats="lever", domain="frontier_ai"),
             _seed("Hebbia", ats="ashby", domain="ai_application_platform"),
             _seed("Quiet Co", ats="greenhouse", domain="frontier_ai")]  # seeded, no corpus
    data = analyse.build_yield_report(seeds, scores, jds, workflow, {}, cost_per_job=0.03)
    rows = {r["company"]: r for r in data["companies"]}

    assert rows["Mistral AI"]["jobs_scored"] == 6
    assert rows["Mistral AI"]["shortlisted"] == 2 and rows["Mistral AI"]["applied"] == 1
    assert rows["Mistral AI"]["high_score_rejected"] == 1   # fit 8 + rejected
    assert rows["Mistral AI"]["shortlist_rate"] is not None  # 6 ≥ 5 → derived
    assert rows["Mistral AI"]["estimated_cost_usd"] == 6 * 0.03

    text = analyse.format_yield(data, today="2026-06-11")
    assert "COMPANY YIELD REPORT — 2026-06-11" in text
    for section in ("Best performers", "High-volume noise", "High false-positive rate",
                    "No live jobs", "Actions flagged", "Domain rollup", "ATS rollup"):
        assert section in text, section
    assert "Quiet Co" in text  # seeded company with zero validated records is surfaced


def test_yield_min_sample_guard():
    scores, jds, workflow = _yield_scenario()
    data = analyse.build_yield_report([_seed("Hebbia")], scores, jds, workflow, {}, cost_per_job=0.03)
    hebbia = next(r for r in data["companies"] if r["company"] == "Hebbia")
    assert hebbia["jobs_scored"] == 2
    assert hebbia["shortlist_rate"] is None  # < 5 scored → suppressed
    # and it renders as an em dash in the main table row
    text = analyse.format_yield(data, today="2026-06-11")
    hebbia_line = next(l for l in text.splitlines() if l.startswith("Hebbia"))
    assert "—" in hebbia_line


def test_yield_action_flagged():
    scores, jds, workflow = _yield_scenario()
    seeds = [_seed("Mistral AI", action="keep"),
             _seed("Hebbia", action="pause", notes="quiet board")]
    data = analyse.build_yield_report(seeds, scores, jds, workflow, {}, cost_per_job=0.03)
    text = analyse.format_yield(data, today="2026-06-11")
    actions = text.split("Actions flagged")[1]
    assert "Hebbia" in actions and "pause" in actions and "quiet board" in actions
    assert "Mistral AI" not in actions  # action=keep is not flagged


def test_yield_domain_rollup():
    scores, jds, workflow = _yield_scenario()
    seeds = [_seed("Mistral AI", domain="frontier_ai"),
             _seed("Hebbia", domain="ai_application_platform")]
    data = analyse.build_yield_report(seeds, scores, jds, workflow, {}, cost_per_job=0.03)
    rollup = {g["key"]: g for g in data["domain_rollup"]}
    assert rollup["frontier_ai"]["jobs_scored"] == 6 and rollup["frontier_ai"]["companies"] == 1
    assert rollup["ai_application_platform"]["jobs_scored"] == 2
    # est cost sums per domain
    assert rollup["frontier_ai"]["estimated_cost_usd"] == 6 * 0.03


def test_yield_manual_ats_no_error():
    scores, jds, workflow = _yield_scenario()
    seeds = [_seed("Jack & Jill AI", ats="manual", slug=None, action="investigate_ats",
                   notes="apply directly")]
    # A manual watch entry (slug: null, no corpus rows) must not raise.
    data = analyse.build_yield_report(seeds, scores, jds, workflow, {}, cost_per_job=0.03)
    text = analyse.format_yield(data, today="2026-06-11")
    assert "Jack & Jill AI" in text
    assert "manual watch" in text  # surfaced under No live jobs with the manual tag


def test_yield_cost_per_job_none_degrades():
    """Missing stats (cost_per_job=None) → no cost columns crash; rows still build."""
    scores, jds, workflow = _yield_scenario()
    data = analyse.build_yield_report([_seed("Mistral AI")], scores, jds, workflow, {}, cost_per_job=None)
    mistral = next(r for r in data["companies"] if r["company"] == "Mistral AI")
    assert mistral["estimated_cost_usd"] is None
    text = analyse.format_yield(data, today="2026-06-11")
    assert "COST_PER_JOB n/a" in text


# --- cost ----------------------------------------------------------------------

def test_load_cost_and_jobs(tmp_path):
    import json
    ledger = tmp_path / "stats.json"
    ledger.write_text(json.dumps([
        {"step": "label", "labelled": 13, "cost_usd": 0.2},
        {"step": "label", "labelled": 44, "cost_usd": 0.8},
        {"step": "score", "cost_usd": 0},  # non-label run ignored for the job count
    ]), encoding="utf-8")
    cost, jobs = analyse.load_cost_and_jobs(str(ledger))
    assert cost == 1.0 and jobs == 57


def test_load_cost_and_jobs_missing_file(tmp_path):
    assert analyse.load_cost_and_jobs(str(tmp_path / "none.json")) == (None, 0)


# --- integration: run all reports against the live corpus ----------------------

def test_all_reports_run_against_real_corpus(capsys):
    """Run all four reports against the live corpus, asserting no exceptions and
    non-empty output (mirrors test_digest's end-to-end shape). Skips on a fresh
    checkout where the (gitignored) corpus is absent."""
    import glob
    if not glob.glob(track.SCORED_GLOB):
        import pytest
        pytest.skip("no scored corpus present (gitignored) — integration test skipped")
    rc = analyse.cmd_analyse(["--report", "all"], now=_now_dt)
    assert rc == 0
    out = capsys.readouterr().out
    assert "SCORE DISTRIBUTION REPORT" in out
    assert "APPLICATION STATUS REPORT" in out
    assert "COMPANY REPORT" in out
    assert "REQUIREMENT GAPS & BLOCKERS" in out
    assert "COMPANY YIELD REPORT" in out   # yield is the fifth report in --report all
    assert len(out.strip()) > 0
