"""Tests for scoring.scorer — the pure 3-stage rule-based scoring model."""

from pathlib import Path

import pytest

from models.record import JDRecord, validate_application_record
from scoring.profile import Profile, load_profile
from scoring.scorer import (
    priority_score,
    score,
    stage1_fit,
    stage2_constraints,
    stage3_label,
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


def test_role_match_is_binary():
    p = make_profile()
    assert stage1_fit(jd(role_type=["Product"]), p)[1].role == 2
    assert stage1_fit(jd(role_type=["GTM"]), p)[1].role == 0


def test_seniority_exact_near_and_gap():
    p = make_profile(target_seniority=frozenset({"director"}))
    assert stage1_fit(jd(seniority="director"), p)[1].seniority == 2  # exact
    assert stage1_fit(jd(seniority="vp"), p)[1].seniority == 1        # one rank away
    assert stage1_fit(jd(seniority="ic"), p)[1].seniority == 0        # far


def test_technical_depth_target_acceptable_mismatch():
    p = make_profile()
    assert stage1_fit(jd(technical_depth="hybrid"), p)[1].technical_depth == 2
    assert stage1_fit(jd(technical_depth="hands_on"), p)[1].technical_depth == 1
    p2 = make_profile(acceptable_technical_depth=frozenset())
    assert stage1_fit(jd(technical_depth="hands_on"), p2)[1].technical_depth == 0


def test_domain_strong_adjacent_lower_none():
    p = make_profile()
    assert stage1_fit(jd(domain=["AdTech"]), p)[1].domain == 2
    assert stage1_fit(jd(domain=["AI/ML"]), p)[1].domain == 1
    assert stage1_fit(jd(domain=["Revenue Technology"]), p)[1].domain == 0.5
    assert stage1_fit(jd(domain=["Payments"]), p)[1].domain == 0


def test_location_dimension():
    p = make_profile()
    assert stage1_fit(jd(remote_policy="remote", location="anywhere"), p)[1].location == 2
    assert stage1_fit(jd(remote_policy="onsite", location="London"), p)[1].location == 2  # base city
    assert stage1_fit(jd(remote_policy="onsite", location="Berlin"), p)[1].location == 0
    assert stage1_fit(jd(remote_policy="hybrid", location="not_stated"), p)[1].location == 1
    assert stage1_fit(jd(remote_policy="hybrid", location="Paris"), p)[1].location == 0


def test_fit_score_clamped_and_rounded():
    p = make_profile()
    # Perfect across the board → 10.
    perfect = jd(role_type=["Product"], seniority="director", technical_depth="hybrid",
                 domain=["AdTech"], remote_policy="remote")
    assert stage1_fit(perfect, p)[0] == 10
    # Nothing matches → clamped up to the 1 floor, not 0.
    nothing = jd(role_type=["GTM"], seniority="exec", technical_depth="hands_on",
                 domain=["Payments"], remote_policy="onsite", location="Berlin")
    p2 = make_profile(acceptable_technical_depth=frozenset(), target_seniority=frozenset({"ic"}))
    assert stage1_fit(nothing, p2)[0] == 1


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
    labels = set()
    lines = [ln for ln in MANUAL_JSONL.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) == 10
    for line in lines:
        record = JDRecord.from_jsonl(line)
        result = score(record, profile, SCORED_AT)
        assert validate_application_record(result) == [], result
        assert result.job_id == record.id
        labels.add(result.fit_label)
    # A curated corpus of relevant roles → at least strong_fit and good_fit present.
    assert {"strong_fit", "good_fit"} <= labels
