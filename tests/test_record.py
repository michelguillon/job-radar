"""Tests for models.record — round-trip serialisation and schema validation.

The 10 hand-authored Tier 1/2 records in corpus/manual/manual_20260606.jsonl are
used as real fixtures: every one must deserialise, validate clean, and re-serialise
without data loss.
"""

import json
from pathlib import Path

import pytest

from models.record import (
    ACTIVITY_EVENT,
    ANNOTATION_TYPE,
    APPLICATION_STATUS,
    JDRECORD_SCHEMA_VERSION,
    OUTCOME,
    REJECTION_REASON,
    SCHEMA_VERSION,
    ApplicationRecord,
    JDRecord,
    SchemaVersionError,
    validate,
    validate_activity_event,
    validate_application_record,
)

MANUAL_JSONL = (
    Path(__file__).resolve().parents[1] / "corpus" / "manual" / "manual_20260606.jsonl"
)


def _manual_lines() -> list[str]:
    lines = [ln for ln in MANUAL_JSONL.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert lines, f"no records found in {MANUAL_JSONL}"
    return lines


def _valid_dict() -> dict:
    """A minimal, schema-valid envelope used to build known-bad mutations."""
    return {
        "schema_version": JDRECORD_SCHEMA_VERSION,
        "id": "sha256:pending",
        "source_url": "unknown",
        "source_ats": "manual",
        "company": "Test Co",
        "collected_at": "2026-06-06",
        "tier": 1,
        "raw_html": None,
        "raw_text": "stored separately",
        "extraction": {
            "role_type": ["Product"],
            "seniority": "ic",
            "technical_depth": "hands_on",
            "years_experience_required": "not_stated",
            "required_technologies": ["Python"],
            "required_competencies": ["communication"],
            "nice_to_have_technologies": [],
            "nice_to_have_competencies": [],
            "domain": ["SaaS"],
            "remote_policy": "remote",
            "location": "Remote",
            "delivery_motion": ["direct_delivery"],
            "leadership_geography": [],
            "company_size_signal": "startup",
            "company_stage": "not_stated",
            "culture_signals": [],
            "raw_observations": "",
        },
        "annotation": {
            "fit_score": None,
            "applied": False,
            "application_date": None,
            "application_decision": "pending",
            "application_decision_notes": "",
            "location_workable": "yes",
            "location_notes": "",
            "domain_distance": "not_assessed",
            "blocking_constraints": [],
            "notes": "",
        },
    }


# --- Fixtures from the real corpus ---


def test_all_manual_records_load_and_validate():
    lines = _manual_lines()
    assert len(lines) == 10
    for ln in lines:
        record = JDRecord.from_jsonl(ln)
        errors = validate(record)
        assert errors == [], f"{record.company} failed validation: {errors}"


def test_manual_records_round_trip_without_loss():
    for ln in _manual_lines():
        record = JDRecord.from_jsonl(ln)
        # Compare as parsed dicts so key ordering / whitespace is irrelevant.
        assert json.loads(record.to_jsonl()) == json.loads(ln)


def test_round_trip_is_idempotent():
    for ln in _manual_lines():
        once = JDRecord.from_jsonl(ln)
        twice = JDRecord.from_jsonl(once.to_jsonl())
        assert once == twice


# --- The minimal valid dict is itself valid ---


def test_valid_dict_passes():
    assert validate(JDRecord.from_dict(_valid_dict())) == []


# --- Schema version handling ---


def test_wrong_schema_version_raises():
    bad = _valid_dict()
    bad["schema_version"] = "1.1"
    with pytest.raises(SchemaVersionError):
        JDRecord.from_dict(bad)


def test_missing_schema_version_raises():
    bad = _valid_dict()
    del bad["schema_version"]
    with pytest.raises(SchemaVersionError):
        JDRecord.from_dict(bad)


def test_missing_field_raises_value_error():
    bad = _valid_dict()
    del bad["extraction"]["seniority"]
    with pytest.raises(ValueError):
        JDRecord.from_dict(bad)


# --- Known-bad records fail validation ---


@pytest.mark.parametrize(
    "section,field,value,needle",
    [
        ("top", "source_ats", "linkedin", "source_ats"),
        ("top", "tier", 5, "tier"),
        ("extraction", "seniority", "principal", "seniority"),
        ("extraction", "technical_depth", "wizard", "technical_depth"),
        ("extraction", "remote_policy", "anywhere", "remote_policy"),
        ("extraction", "company_size_signal", "huge", "company_size_signal"),
        ("extraction", "company_stage", "series_z", "company_stage"),
        ("extraction", "role_type", ["Not A Role"], "role_type"),
        ("extraction", "domain", ["Crypto"], "domain"),
        ("extraction", "delivery_motion", ["telepathy"], "delivery_motion"),
        ("annotation", "application_decision", "maybe", "application_decision"),
        ("annotation", "location_workable", "perhaps", "location_workable"),
        ("annotation", "domain_distance", "far", "domain_distance"),
        ("annotation", "fit_score", 0, "fit_score"),
        ("annotation", "fit_score", 11, "fit_score"),
        ("annotation", "fit_score", "high", "fit_score"),
    ],
)
def test_known_bad_values_fail_validation(section, field, value, needle):
    d = _valid_dict()
    if section == "top":
        d[field] = value
    else:
        d[section][field] = value
    record = JDRecord.from_dict(d)
    errors = validate(record)
    assert any(needle in e for e in errors), f"expected error on {field}, got {errors}"


def test_role_type_max_three():
    d = _valid_dict()
    d["extraction"]["role_type"] = [
        "Product",
        "GTM",
        "Pre-Sales",
        "AI Delivery",
    ]
    errors = validate(JDRecord.from_dict(d))
    assert any("role_type" in e and "max" in e for e in errors)


def test_fit_score_none_is_valid():
    d = _valid_dict()
    d["annotation"]["fit_score"] = None
    assert validate(JDRecord.from_dict(d)) == []


def test_applied_must_be_bool_not_int():
    d = _valid_dict()
    d["annotation"]["applied"] = 1
    errors = validate(JDRecord.from_dict(d))
    assert any("applied" in e for e in errors)


# --- ApplicationRecord (Phase 2, schema v1.3) ---


def _valid_application() -> ApplicationRecord:
    return ApplicationRecord(
        job_id="sha256:abc123",
        profile_version="1.0",
        scored_at="2026-06-09T12:00:00Z",
        fit_score=8,
        fit_label="strong_fit",
        fit_label_reason="Strong role and seniority match in an adjacent domain.",
        requirement_gaps=["preferred Salesforce experience"],
        blocking_constraints=[],
        priority_score=8,
        application_status="new",
        notes="",
    )


def test_application_record_is_v13_not_jdrecord_version():
    # The version split is the whole point of Option A: JDRecord stays 1.2.
    assert SCHEMA_VERSION == "1.3"
    assert JDRECORD_SCHEMA_VERSION == "1.2"
    assert _valid_application().to_dict()["schema_version"] == "1.3"


def test_application_record_round_trips():
    rec = _valid_application()
    assert ApplicationRecord.from_jsonl(rec.to_jsonl()) == rec


def test_application_record_validates_clean():
    assert validate_application_record(_valid_application()) == []


def test_application_record_wrong_version_raises():
    d = _valid_application().to_dict()
    d["schema_version"] = JDRECORD_SCHEMA_VERSION  # a JDRecord must not load as one
    with pytest.raises(SchemaVersionError):
        ApplicationRecord.from_dict(d)


def test_application_record_missing_field_raises():
    d = _valid_application().to_dict()
    del d["fit_label"]
    with pytest.raises(ValueError):
        ApplicationRecord.from_dict(d)


@pytest.mark.parametrize(
    "field,value,needle",
    [
        ("fit_label", "amazing_fit", "fit_label"),
        ("application_status", "pending", "application_status"),
        ("fit_score", 0, "fit_score"),
        ("fit_score", 11, "fit_score"),
        ("fit_score", True, "fit_score"),  # bool is not a valid score
        ("priority_score", 0, "priority_score"),
        ("requirement_gaps", "not a list", "requirement_gaps"),
        ("blocking_constraints", [1, 2], "blocking_constraints"),
    ],
)
def test_application_record_known_bad_values_fail(field, value, needle):
    rec = _valid_application()
    setattr(rec, field, value)
    errors = validate_application_record(rec)
    assert any(needle in e for e in errors), f"expected error on {field}, got {errors}"


# --- activity-log event validation (Phase 3 tracker, §7.4) ---------------------


def _status_event(**over) -> dict:
    event = {
        "v": 1,
        "ts": "2026-06-10T09:00:00Z",
        "job_id": "sha256:abc",
        "event": "status",
        "value": "applied",
        "notes": "",
    }
    event.update(over)
    return event


def test_outcome_and_activity_event_vocab_are_closed():
    assert "rejected_post_screen" in OUTCOME
    assert ACTIVITY_EVENT == {"status", "outcome", "note", "title", "fit_override"}


def test_rejection_reason_in_annotation_type():
    assert "rejection_reason" in ANNOTATION_TYPE


def test_rejection_reason_vocab_complete():
    assert REJECTION_REASON == frozenset({
        "wrong_level", "wrong_function", "too_salesy", "too_research_heavy",
        "too_delivery_consulting", "domain_not_interesting", "company_not_fit",
        "seniority_mismatch", "requirement_mismatch", "location_mismatch",
        "applied_elsewhere_same_company", "other",
    })
    assert len(REJECTION_REASON) == 12


def test_applied_elsewhere_in_rejection_reason():
    # SPEC_ACTIVE_COMPANY_FILTER §6: sibling roles at a company you're already in play with
    # aren't real rejections — a dedicated reason keeps them out of the will_not_apply noise.
    assert "applied_elsewhere_same_company" in REJECTION_REASON


def test_will_not_apply_in_application_status():
    # SPEC_WORKFLOW_UPDATE §8: a conscious "I decided no" terminal state, distinct from
    # rejected (they decided) and archived (passive cleanup). Constants only — no schema bump.
    assert "will_not_apply" in APPLICATION_STATUS


def test_will_not_apply_is_a_valid_status_event():
    assert validate_activity_event(_status_event(value="will_not_apply")) == []


@pytest.mark.parametrize(
    "event",
    [
        _status_event(),
        _status_event(value="interviewing", notes="R1 booked"),
        _status_event(event="outcome", value="rejected_interview"),
        _status_event(event="note", value=None, notes="recruiter emailed"),
        _status_event(event="title", value="Solutions Engineer"),
        _status_event(event="fit_override", value="good_fit", notes="depth gap"),
        _status_event(event="fit_override", value=None),  # null clears a prior override
    ],
)
def test_valid_activity_events_pass(event):
    assert validate_activity_event(event) == []


@pytest.mark.parametrize(
    "event,needle",
    [
        (_status_event(value="amazing"), "value"),          # not an APPLICATION_STATUS
        (_status_event(event="outcome", value="rejected"), "value"),  # not an OUTCOME
        (_status_event(event="promote"), "event"),          # unknown event kind
        (_status_event(event="note", value="should be null"), "value"),
        (_status_event(event="title", value=""), "value"),     # title must be non-empty
        (_status_event(event="title", value=None), "value"),
        (_status_event(event="fit_override", value="amazing"), "value"),  # not a FIT_LABEL
        (_status_event(ts=""), "ts"),
        (_status_event(job_id=None), "job_id"),
        (_status_event(notes=5), "notes"),
    ],
)
def test_bad_activity_events_fail(event, needle):
    errors = validate_activity_event(event)
    assert any(needle in e for e in errors), f"expected error on {needle}, got {errors}"
