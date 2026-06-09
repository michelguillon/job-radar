"""Tests for scoring.scorer — the pure 3-stage rule-based scoring model."""

from pathlib import Path

import pytest

from models.record import JDRecord, validate_application_record
from scoring.profile import Profile, load_profile
from scoring.scorer import (
    capability_blocker,
    priority_score,
    score,
    stage1_fit,
    stage2_constraints,
    stage3_label,
    unmet_required_technologies,
)
from tests.factories import make_record

MANUAL_JSONL = (
    Path(__file__).resolve().parents[1] / "corpus" / "manual" / "manual_20260606.jsonl"
)
SCORED_AT = "2026-06-09T12:00:00Z"


def jd(**fields) -> JDRecord:
    """A schema-valid JDRecord with extraction fields overridden by keyword."""
    record = make_record()
    for key, value in fields.items():
        setattr(record, key, value)
    return record


def make_profile(**over) -> Profile:
    base = dict(
        profile_version="1.0",
        search_mode="selective",
        target_roles=frozenset({"Product", "Solutions Engineering"}),
        target_seniority=frozenset({"director", "manager", "lead", "senior_ic"}),
        target_delivery_motion=frozenset({"pre_sales"}),
        target_technical_depth=frozenset({"hybrid", "leadership"}),
        acceptable_technical_depth=frozenset({"hands_on"}),
        location_base="London",
        acceptable_remote_policy=frozenset({"hybrid", "remote"}),
        relocation=False,
        domains_strong=frozenset({"AdTech", "Enterprise Software"}),
        domains_adjacent=frozenset({"AI Platform", "AI/ML"}),
        domains_lower=frozenset({"Revenue Technology"}),
        requirement_gap_watchlist=["deep Salesforce administration"],
        positive_signals=[],
        negative_signals=[],
    )
    base.update(over)
    return Profile(**base)


# --- Stage 1: per-dimension scoring ---


# Signal dimensions (role, domain, technical_depth) carry the 0–10 scale.


def test_role_match_is_binary():
    p = make_profile()
    assert stage1_fit(jd(role_type=["Product"]), p)[1].role == 2
    assert stage1_fit(jd(role_type=["GTM"]), p)[1].role == 0


def test_technical_depth_target_acceptable_mismatch():
    p = make_profile()
    assert stage1_fit(jd(technical_depth="hybrid"), p)[1].technical_depth == 2
    assert stage1_fit(jd(technical_depth="hands_on"), p)[1].technical_depth == 0.5  # acceptable (Option B)
    p2 = make_profile(acceptable_technical_depth=frozenset())
    assert stage1_fit(jd(technical_depth="hands_on"), p2)[1].technical_depth == 0


def test_domain_strong_adjacent_lower_none():
    p = make_profile()
    assert stage1_fit(jd(domain=["AdTech"]), p)[1].domain == 2
    assert stage1_fit(jd(domain=["AI/ML"]), p)[1].domain == 1
    assert stage1_fit(jd(domain=["Revenue Technology"]), p)[1].domain == 0.5
    assert stage1_fit(jd(domain=["Payments"]), p)[1].domain == 0


def test_signal_weighting_role_and_domain_primary():
    # role+domain are weighted ×2 (primary), technical_depth ×1 (secondary).
    p = make_profile()
    perfect = jd(role_type=["Product"], domain=["AdTech"], technical_depth="hybrid")
    assert stage1_fit(perfect, p)[1].signal == 10  # 2*2 + 2*2 + 2*1
    # Losing the domain (4 pts) hurts more than dropping to acceptable depth (1.5 pts).
    no_domain = jd(role_type=["Product"], domain=["Payments"], technical_depth="hybrid")
    weak_depth = jd(role_type=["Product"], domain=["AdTech"], technical_depth="hands_on")
    assert stage1_fit(no_domain, p)[1].signal < stage1_fit(weak_depth, p)[1].signal


# Gates (seniority, location) only ever subtract — a hit contributes 0.


def test_seniority_gate_is_binary():
    p = make_profile(target_seniority=frozenset({"director", "manager"}))
    g_pass = stage1_fit(jd(seniority="director"), p)[1]
    assert g_pass.seniority_gate == "pass" and g_pass.seniority_penalty == 0
    g_miss = stage1_fit(jd(seniority="vp"), p)[1]  # one rank away is still a miss now
    assert g_miss.seniority_gate == "miss" and g_miss.seniority_penalty == 3


def test_location_gate_pass_unclear_fail():
    p = make_profile()
    remote = stage1_fit(jd(remote_policy="remote", location="anywhere"), p)[1]
    base = stage1_fit(jd(remote_policy="onsite", location="London HQ"), p)[1]
    unclear = stage1_fit(jd(remote_policy="hybrid", location="not_stated"), p)[1]
    onsite_far = stage1_fit(jd(remote_policy="onsite", location="Berlin"), p)[1]
    hybrid_far = stage1_fit(jd(remote_policy="hybrid", location="Paris"), p)[1]
    assert (remote.location_gate, remote.location_penalty) == ("pass", 0)
    assert (base.location_gate, base.location_penalty) == ("pass", 0)  # base city, any policy
    assert (unclear.location_gate, unclear.location_penalty) == ("unclear", 1)
    assert (onsite_far.location_gate, onsite_far.location_penalty) == ("fail", 3)
    assert (hybrid_far.location_gate, hybrid_far.location_penalty) == ("fail", 3)


def test_gate_miss_lowers_an_otherwise_perfect_score():
    p = make_profile()
    perfect = jd(role_type=["Product"], seniority="director", technical_depth="hybrid",
                 domain=["AdTech"], remote_policy="remote", location="anywhere")
    assert stage1_fit(perfect, p)[0] == 10
    # Same role/domain/depth, but a seniority miss + location blocker pull it down.
    gated = jd(role_type=["Product"], seniority="exec", technical_depth="hybrid",
               domain=["AdTech"], remote_policy="onsite", location="Berlin")
    assert stage1_fit(gated, p)[0] == 4  # 10 - 3 (seniority) - 3 (location)


def test_fit_score_clamped_to_floor():
    # Nothing matches and both gates miss → clamped up to the 1 floor, not below.
    p2 = make_profile(acceptable_technical_depth=frozenset(), target_seniority=frozenset({"ic"}))
    nothing = jd(role_type=["GTM"], seniority="exec", technical_depth="hands_on",
                 domain=["Payments"], remote_policy="onsite", location="Berlin")
    assert stage1_fit(nothing, p2)[0] == 1


def test_round_half_up():
    # A hands_on (acceptable, 0.5) depth produces x.5 raws; halves round up.
    p = make_profile()
    rec = jd(role_type=["Product"], domain=["AI/ML"], technical_depth="hands_on",
             seniority="director", remote_policy="remote")
    # signal = 4 + 2 + 0.5 = 6.5, no penalties → 7, not 6.
    assert stage1_fit(rec, p)[0] == 7


# --- Stage 2: blocking constraints + requirement gaps ---


def test_blocking_security_clearance():
    p = make_profile()
    gaps, blocks = stage2_constraints(jd(raw_text="Active security clearance required."), p)
    assert any("clearance" in b for b in blocks)


def test_blocking_native_language():
    p = make_profile()
    _, blocks = stage2_constraints(jd(raw_text="Must be a native German speaker."), p)
    assert any("language" in b for b in blocks)


def test_blocking_language_is_conservative():
    # "French market" must NOT trip the native/fluent language rule.
    p = make_profile()
    _, blocks = stage2_constraints(jd(raw_text="Experience selling into the French market."), p)
    assert not any("language" in b for b in blocks)


def test_blocking_sponsorship():
    p = make_profile()
    _, blocks = stage2_constraints(jd(raw_text="We do not offer visa sponsorship."), p)
    assert blocks


def test_requirement_gap_from_watchlist():
    p = make_profile(requirement_gap_watchlist=["deep Salesforce administration"])
    gaps, _ = stage2_constraints(jd(required_technologies=["Salesforce administration"]), p)
    assert "deep Salesforce administration" in gaps


def test_gap_not_emitted_when_not_in_watchlist():
    p = make_profile(requirement_gap_watchlist=[])  # empty watchlist
    gaps, _ = stage2_constraints(jd(required_technologies=["Salesforce administration"]), p)
    assert gaps == []


# --- Capability blocker: Stage 2 overrides a misleadingly high Stage 1 ---

PROFICIENT = frozenset({"python", "llm apis", "rag pipelines", "api platforms"})


def test_capability_blocker_fires_on_hands_on_specialist_stack():
    # The Databricks calibration case.
    p = make_profile(proficient_technologies=PROFICIENT)
    databricks = jd(
        technical_depth="hands_on",
        required_technologies=["Python", "SQL", "Apache Spark", "Databricks platform", "AWS", "Azure", "GCP"],
    )
    assert len(unmet_required_technologies(databricks, p)) == 6  # all but Python
    assert capability_blocker(databricks, p) is not None


def test_capability_blocker_needs_hands_on_depth():
    # Same heavy unmet stack, but a hybrid/leadership role → the candidate leads,
    # not executes, so it is NOT blocked (the Writer / Fin case).
    p = make_profile(proficient_technologies=PROFICIENT)
    hybrid_role = jd(
        technical_depth="hybrid",
        required_technologies=["SQL", "Apache Spark", "Databricks platform", "AWS", "Azure"],
    )
    assert capability_blocker(hybrid_role, p) is None


def test_capability_blocker_respects_threshold():
    # Below the unmet threshold → no blocker (the JP Morgan / Mistral case).
    p = make_profile(proficient_technologies=PROFICIENT)
    light = jd(technical_depth="hands_on", required_technologies=["Python", "SQL", "LLM APIs"])
    assert len(unmet_required_technologies(light, p)) == 1
    assert capability_blocker(light, p) is None


def test_capability_blocker_skipped_for_hands_on_candidate():
    # A candidate who targets hands_on is not blocked by a specialist stack.
    p = make_profile(
        proficient_technologies=PROFICIENT,
        target_technical_depth=frozenset({"hands_on", "hybrid"}),
    )
    databricks = jd(
        technical_depth="hands_on",
        required_technologies=["SQL", "Apache Spark", "Databricks platform", "AWS"],
    )
    assert capability_blocker(databricks, p) is None


def test_capability_blocker_demotes_label_via_stage2():
    # End-to-end: high structural fit + capability blocker → blocked_fit, not good_fit.
    p = make_profile(proficient_technologies=PROFICIENT)
    databricks = jd(
        role_type=["Solutions Engineering"], seniority="lead", technical_depth="hands_on",
        domain=["AI Platform"], remote_policy="hybrid", location="London",
        required_technologies=["Python", "SQL", "Apache Spark", "Databricks platform", "AWS", "Azure", "GCP"],
    )
    rec = score(databricks, p, SCORED_AT)
    assert rec.blocking_constraints  # the capability blocker is present
    assert rec.fit_label == "blocked_fit"
    assert rec.priority_score == rec.fit_score - 2  # blocker priority penalty


# --- Stage 3: classification ---


@pytest.mark.parametrize(
    "fit,has_block,expected",
    [
        (9, False, "strong_fit"),
        (8, False, "strong_fit"),
        (7, False, "good_fit"),
        (6, False, "good_fit"),
        (8, True, "blocked_fit"),   # high fit + blocker
        (7, True, "blocked_fit"),
        (6, True, "stretch"),       # 6 with a blocker drops to stretch
        (5, False, "stretch"),
        (4, False, "interview_practice"),
        (3, False, "interview_practice"),
        (2, False, "income_bridge"),
        (1, False, "income_bridge"),
    ],
)
def test_stage3_label(fit, has_block, expected):
    blocking = ["something"] if has_block else []
    assert stage3_label(fit, blocking) == expected


# --- Priority ---


def test_priority_early_stage_bonus():
    p = make_profile()
    assert priority_score(7, jd(company_stage="seed"), [], "selective") == 8
    assert priority_score(7, jd(company_stage="listed"), [], "selective") == 7


def test_priority_blocking_penalty_and_clamp():
    assert priority_score(8, jd(), ["block"], "selective") == 6
    assert priority_score(1, jd(), ["block"], "selective") == 1  # clamps at floor


def test_priority_broad_mode_elevates_low_fit():
    assert priority_score(3, jd(), [], "broad") == 4
    assert priority_score(3, jd(), [], "selective") == 3


# --- Public entry point + integration ---


def test_score_returns_valid_new_application_record():
    p = make_profile()
    rec = score(jd(role_type=["Product"], seniority="director"), p, SCORED_AT)
    assert validate_application_record(rec) == []
    assert rec.application_status == "new"
    assert rec.scored_at == SCORED_AT
    assert rec.profile_version == "1.0"
    assert rec.notes == ""


def test_all_manual_records_score_and_validate():
    profile = load_profile()
    by_company = {}
    lines = [ln for ln in MANUAL_JSONL.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) == 10
    fit_scores = []
    for line in lines:
        record = JDRecord.from_jsonl(line)
        result = score(record, profile, SCORED_AT)
        assert validate_application_record(result) == [], result
        assert result.job_id == record.id
        by_company[record.company] = result
        fit_scores.append(result.fit_score)
    # The gates+signal model must actually discriminate on a curated corpus —
    # not collapse everything into strong_fit (the calibration goal).
    assert len(set(fit_scores)) >= 4, f"too little spread: {sorted(fit_scores)}"


def test_databricks_is_a_blocked_fit_calibration_anchor():
    # Databricks: strong SA/AI-Platform enums, but mandatory hands-on Spark/SQL/
    # Databricks/multi-cloud → not feasible. Must NOT surface as strong/good fit.
    profile = load_profile()
    for line in MANUAL_JSONL.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = JDRecord.from_jsonl(line)
        if record.company == "Databricks":
            result = score(record, profile, SCORED_AT)
            assert result.fit_label == "blocked_fit", result.fit_label_reason
            assert result.blocking_constraints
            return
    raise AssertionError("Databricks record not found in the manual corpus")
