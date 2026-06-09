"""Test helpers — build schema-valid JDRecord objects with overrides."""

from __future__ import annotations

from models.record import SCHEMA_VERSION, JDRecord


def base_envelope() -> dict:
    """A minimal, schema-valid JSONL envelope."""
    return {
        "schema_version": SCHEMA_VERSION,
        "id": "sha256:pending",
        "source_url": "unknown",
        "source_ats": "manual",
        "company": "Test Co",
        "collected_at": "2026-06-06",
        "tier": 4,
        "raw_html": None,
        "raw_text": "stored separately",
        "extraction": {
            "role_type": ["Product"],
            "seniority": "ic",
            "technical_depth": "hands_on",
            "years_experience_required": "not_stated",
            "required_technologies": [],
            "required_competencies": [],
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


def make_record(*, raw_html: str | None = None, raw_text: str = "stored separately", **top) -> JDRecord:
    """Build a JDRecord, overriding top-level identity/raw fields as needed."""
    env = base_envelope()
    env["raw_html"] = raw_html
    env["raw_text"] = raw_text
    env.update(top)
    return JDRecord.from_dict(env)
