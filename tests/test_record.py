"""Tests for models.record — round-trip serialisation and schema validation.

The 10 hand-authored Tier 1/2 records in corpus/manual/manual_20260606.jsonl are
used as real fixtures: every one must deserialise, validate clean, and re-serialise
without data loss.
"""

import json
from pathlib import Path

import pytest

from models.record import (
    SCHEMA_VERSION,
    JDRecord,
    SchemaVersionError,
    validate,
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
        "schema_version": SCHEMA_VERSION,
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
