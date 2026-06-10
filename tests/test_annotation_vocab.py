"""Tests for the Phase 6 scoring-annotation vocabulary (models/record.py, SPEC §10.2)."""

from __future__ import annotations

from models.record import (
    ANNOTATION_LOG_VERSION,
    ANNOTATION_TYPE,
    SCHEMA_VERSION,
    validate_annotation_event,
)


def _valid() -> dict:
    return {
        "v": ANNOTATION_LOG_VERSION,
        "ts": "2026-06-10T09:00:00Z",
        "job_id": "sha256:abc",
        "annotation_type": "domain_incorrect",
        "field": "domain",
        "observed": ["Enterprise Software"],
        "expected": [],
        "reason": "catch-all, nothing points to Enterprise Software",
        "scorer_label": "strong_fit",
        "scorer_fit_score": 9,
    }


def test_annotation_type_is_the_spec_set():
    assert ANNOTATION_TYPE == frozenset({
        "role_type_incorrect", "domain_incorrect", "seniority_incorrect",
        "technical_depth_incorrect", "fit_score_disagree", "should_be_blocked",
        "false_block", "extraction_other",
    })


def test_constants_only_no_schema_bump():
    # Phase 6 adds vocab constants only — the project schema stays at 1.3.
    assert SCHEMA_VERSION == "1.3"
    assert ANNOTATION_LOG_VERSION == 1


def test_valid_event_passes():
    assert validate_annotation_event(_valid()) == []


def test_bad_annotation_type_fails():
    ev = _valid() | {"annotation_type": "nope"}
    assert any("annotation_type" in e for e in validate_annotation_event(ev))


def test_missing_reason_fails():
    ev = _valid() | {"reason": ""}
    assert any("reason" in e for e in validate_annotation_event(ev))


def test_missing_observed_expected_fails():
    ev = _valid()
    del ev["observed"]
    del ev["expected"]
    errors = validate_annotation_event(ev)
    assert any("observed" in e for e in errors)
    assert any("expected" in e for e in errors)


def test_scorer_fields_may_be_null():
    ev = _valid() | {"scorer_label": None, "scorer_fit_score": None}
    assert validate_annotation_event(ev) == []


def test_bad_scorer_fit_score_type_fails():
    ev = _valid() | {"scorer_fit_score": "high"}
    assert any("scorer_fit_score" in e for e in validate_annotation_event(ev))


def test_field_must_be_string():
    ev = _valid() | {"field": 123}
    assert any("field" in e for e in validate_annotation_event(ev))
