"""JDRecord dataclass, schema version, and (de)serialisation + validation.

Schema is locked at v1.2 — see docs/CORPUS_FINDINGS.md §1.1 for the definitive
definition and docs/SPEC_JD_REFINERY.md §4 for the JSONL envelope (§4.2).

The dataclass is flat (one attribute per field). The JSONL envelope groups the
Claude-populated fields under ``extraction`` and the human-only fields under
``annotation``; ``to_jsonl``/``from_jsonl`` translate between the two shapes.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

# Current project schema version. Phase 2 (Option A) added ApplicationRecord,
# so the project version is now 1.3. JDRecord's on-disk envelope is NOT migrated
# (CLAUDE.md: append-only, never migrate in place) — it stays frozen at the
# version it was authored under. New record types are versioned at SCHEMA_VERSION.
SCHEMA_VERSION = "1.3"

# JDRecord serialises/validates against its own frozen version. The existing
# v1.2 corpus on disk must keep loading and round-tripping unchanged.
JDRECORD_SCHEMA_VERSION = "1.2"

# --- Allowed values (closed enums from docs/CORPUS_FINDINGS.md §1.1) ---

SOURCE_ATS = frozenset(
    {"greenhouse", "lever", "ashby", "vc_board", "manual"}
)
TIERS = frozenset({1, 2, 3, 4})
SENIORITY = frozenset(
    {"ic", "senior_ic", "lead", "manager", "director", "vp", "exec"}
)
TECHNICAL_DEPTH = frozenset({"hands_on", "hybrid", "leadership"})
REMOTE_POLICY = frozenset({"remote", "hybrid", "onsite", "not_stated"})
COMPANY_SIZE_SIGNAL = frozenset(
    {"startup", "scale_up", "enterprise", "not_stated"}
)
COMPANY_STAGE = frozenset(
    {
        "seed",
        "series_a",
        "series_b",
        "series_c_plus",
        "pre_ipo",
        "listed",
        "not_stated",
    }
)
ROLE_TYPE = frozenset(
    {
        "Solutions Engineering",
        "Solutions Consulting",
        "Solutions Architecture",
        "AI Delivery",
        "Delivery Leadership",
        "Pre-Sales",
        "Strategic Pursuits",
        "Partner SA",
        "Product",
        "GTM",
    }
)
DOMAIN = frozenset(
    {
        "AI Platform",
        "AI/ML",
        "Data & Analytics",
        "FinTech",
        "Payments",
        "Financial Services",
        "Product Design",
        "SaaS",
        "Enterprise Software",
        "Consulting",
        "AdTech",
        "Infrastructure",
        "Developer Tools",
        "Customer Experience",
        "Revenue Technology",
    }
)
DELIVERY_MOTION = frozenset(
    {
        "pre_sales",
        "direct_delivery",
        "partner_delivery",
        "partner_enablement",
        "customer_success",
        "professional_services",
    }
)
APPLICATION_DECISION = frozenset(
    {
        "applied",
        "want_to_apply",
        "pending",
        "not_applied_fit",
        "not_applied_structural",
        "not_applied_timing",
    }
)
LOCATION_WORKABLE = frozenset({"yes", "no", "conditional", "unknown"})
DOMAIN_DISTANCE = frozenset({"low", "medium", "high", "not_assessed"})

# --- ApplicationRecord enums (Phase 2, schema v1.3) ---
# Stage-3 opportunity classification (scoring/scorer.py, job_radar_SPEC §6.2).
FIT_LABEL = frozenset(
    {
        "strong_fit",
        "good_fit",
        "stretch",
        "blocked_fit",
        "interview_practice",
        "income_bridge",
    }
)
# Application lifecycle (Phase 3 tracker, job_radar_SPEC §7.2). The scorer
# always emits "new"; later states are set by the tracker.
APPLICATION_STATUS = frozenset(
    {
        "new",
        "review",
        "shortlisted",
        "applied",
        "interviewing",
        "offer",
        "rejected",
        "archived",
    }
)

# --- Activity log vocabulary (Phase 3 tracker, job_radar_SPEC §7.4) ---
# The Job Tracker keeps workflow state in an append-only event log
# (corpus/activity_log.jsonl), NOT on ApplicationRecord, so the pure scorer can
# regenerate scored records without wiping human state (see CLAUDE.md deviation
# 23 + job_radar_TRACKER_PLAN.md model C). These are vocabulary constants only —
# they do not touch any record dataclass and do not bump SCHEMA_VERSION.
ACTIVITY_LOG_VERSION = 1

# Event kinds in the activity log.
#  status  — value is an APPLICATION_STATUS the human moved the job to.
#  outcome — value is a terminal OUTCOME (job_radar_SPEC §7.3).
#  note    — value is null; the comment text lives in ``notes``.
#  title   — value is a human-set display title override (the schema-locked
#            JDRecord has no title field; the sidecar is keyed by source_url and
#            collides on legacy "unknown" URLs, so this is the per-job_id escape
#            hatch). Latest title event wins; presentation only, never scored.
ACTIVITY_EVENT = frozenset({"status", "outcome", "note", "title"})

# Terminal outcomes (job_radar_SPEC §7.3). Derived from the log at read time;
# never persisted on ApplicationRecord (model C / Log-only — TRACKER_PLAN fork).
OUTCOME = frozenset(
    {
        "rejected_pre_screen",
        "rejected_post_screen",
        "rejected_interview",
        "rejected_final",
        "offer_declined",
        "offer_accepted",
        "withdrew",
    }
)


def validate_activity_event(event: dict) -> list[str]:
    """Return a list of validation error strings for one activity-log event.

    Vocabulary check only — the tracker enforces transition *order* loosely
    (warn, never block); this guards the closed enums and required fields so a
    malformed line never enters the append-only log.
    """
    errors: list[str] = []
    for name in ("ts", "job_id"):
        value = event.get(name)
        if not isinstance(value, str) or not value:
            errors.append(f"{name}: must be a non-empty string")
    if not isinstance(event.get("notes", ""), str):
        errors.append("notes: must be a string")

    kind = event.get("event")
    if kind not in ACTIVITY_EVENT:
        errors.append(f"event: {kind!r} not in {sorted(ACTIVITY_EVENT)}")
        return errors

    value = event.get("value")
    if kind == "status":
        _check_enum(errors, "value", value, APPLICATION_STATUS)
    elif kind == "outcome":
        _check_enum(errors, "value", value, OUTCOME)
    elif kind == "title":
        if not isinstance(value, str) or not value.strip():
            errors.append("value: must be a non-empty string for a title event")
    elif kind == "note" and value is not None:
        errors.append("value: must be null for a note event")
    return errors

ROLE_TYPE_MAX = 3

# Field groupings used for envelope (de)serialisation.
_EXTRACTION_FIELDS = (
    "role_type",
    "seniority",
    "technical_depth",
    "years_experience_required",
    "required_technologies",
    "required_competencies",
    "nice_to_have_technologies",
    "nice_to_have_competencies",
    "domain",
    "remote_policy",
    "location",
    "delivery_motion",
    "leadership_geography",
    "company_size_signal",
    "company_stage",
    "culture_signals",
    "raw_observations",
)
_ANNOTATION_FIELDS = (
    "fit_score",
    "applied",
    "application_date",
    "application_decision",
    "application_decision_notes",
    "location_workable",
    "location_notes",
    "domain_distance",
    "blocking_constraints",
    "notes",
)


class SchemaVersionError(ValueError):
    """Raised when a record's schema_version does not match the expected one."""


@dataclass
class JDRecord:
    # --- Identity ---
    id: str
    source_url: str
    source_ats: str
    company: str
    collected_at: str
    tier: int

    # --- Raw content ---
    raw_html: str | None
    raw_text: str

    # --- Extraction schema (Claude-populated Tier 3+, human-structured Tier 1-2) ---
    role_type: list[str]
    seniority: str
    technical_depth: str
    years_experience_required: str
    required_technologies: list[str]
    required_competencies: list[str]
    nice_to_have_technologies: list[str]
    nice_to_have_competencies: list[str]
    domain: list[str]
    remote_policy: str
    location: str
    delivery_motion: list[str]
    leadership_geography: list[str]
    company_size_signal: str
    company_stage: str
    culture_signals: list[str]
    raw_observations: str

    # --- Annotation schema (human-only, never extraction targets) ---
    fit_score: int | None
    applied: bool
    application_date: str | None
    application_decision: str
    application_decision_notes: str
    location_workable: str
    location_notes: str
    domain_distance: str
    blocking_constraints: list[str]
    notes: str

    def to_dict(self) -> dict:
        """Return the nested JSONL envelope (docs/SPEC_JD_REFINERY.md §4.2)."""
        return {
            "schema_version": JDRECORD_SCHEMA_VERSION,
            "id": self.id,
            "source_url": self.source_url,
            "source_ats": self.source_ats,
            "company": self.company,
            "collected_at": self.collected_at,
            "tier": self.tier,
            "raw_html": self.raw_html,
            "raw_text": self.raw_text,
            "extraction": {f: getattr(self, f) for f in _EXTRACTION_FIELDS},
            "annotation": {f: getattr(self, f) for f in _ANNOTATION_FIELDS},
        }

    def to_jsonl(self) -> str:
        """Serialise to a single JSONL line (no trailing newline)."""
        return json.dumps(self.to_dict(), ensure_ascii=False)

    @classmethod
    def from_dict(cls, d: dict) -> "JDRecord":
        version = d.get("schema_version")
        if version != JDRECORD_SCHEMA_VERSION:
            raise SchemaVersionError(
                f"schema_version {version!r} does not match {JDRECORD_SCHEMA_VERSION!r}"
            )
        try:
            extraction = d["extraction"]
            annotation = d["annotation"]
            return cls(
                id=d["id"],
                source_url=d["source_url"],
                source_ats=d["source_ats"],
                company=d["company"],
                collected_at=d["collected_at"],
                tier=d["tier"],
                raw_html=d["raw_html"],
                raw_text=d["raw_text"],
                **{f: extraction[f] for f in _EXTRACTION_FIELDS},
                **{f: annotation[f] for f in _ANNOTATION_FIELDS},
            )
        except KeyError as exc:
            raise ValueError(f"missing required field: {exc.args[0]}") from exc

    @classmethod
    def from_jsonl(cls, line: str) -> "JDRecord":
        """Parse one JSONL line. Raises SchemaVersionError on version mismatch."""
        return cls.from_dict(json.loads(line))


def _check_enum(errors: list[str], name: str, value, allowed: frozenset) -> None:
    if value not in allowed:
        errors.append(f"{name}: {value!r} not in allowed values")


def _check_str_list(errors: list[str], name: str, value) -> None:
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        errors.append(f"{name}: must be a list of strings")


def _check_subset(errors: list[str], name: str, value, allowed: frozenset) -> None:
    if not isinstance(value, list):
        errors.append(f"{name}: must be a list")
        return
    bad = [v for v in value if v not in allowed]
    if bad:
        errors.append(f"{name}: {bad!r} not in allowed values")


def validate(record: JDRecord) -> list[str]:
    """Return a list of validation error strings; empty list means valid."""
    errors: list[str] = []

    # --- Identity / raw ---
    for name in ("id", "source_url", "company", "collected_at", "raw_text"):
        if not isinstance(getattr(record, name), str):
            errors.append(f"{name}: must be a string")
    _check_enum(errors, "source_ats", record.source_ats, SOURCE_ATS)
    if record.tier not in TIERS:
        errors.append(f"tier: {record.tier!r} not in {sorted(TIERS)}")
    if record.raw_html is not None and not isinstance(record.raw_html, str):
        errors.append("raw_html: must be a string or null")

    # --- Extraction enums ---
    _check_subset(errors, "role_type", record.role_type, ROLE_TYPE)
    if isinstance(record.role_type, list) and len(record.role_type) > ROLE_TYPE_MAX:
        errors.append(f"role_type: max {ROLE_TYPE_MAX} values, got {len(record.role_type)}")
    _check_enum(errors, "seniority", record.seniority, SENIORITY)
    _check_enum(errors, "technical_depth", record.technical_depth, TECHNICAL_DEPTH)
    if not isinstance(record.years_experience_required, str):
        errors.append("years_experience_required: must be a string")
    _check_subset(errors, "domain", record.domain, DOMAIN)
    _check_enum(errors, "remote_policy", record.remote_policy, REMOTE_POLICY)
    if not isinstance(record.location, str):
        errors.append("location: must be a string")
    _check_subset(errors, "delivery_motion", record.delivery_motion, DELIVERY_MOTION)
    _check_enum(errors, "company_size_signal", record.company_size_signal, COMPANY_SIZE_SIGNAL)
    _check_enum(errors, "company_stage", record.company_stage, COMPANY_STAGE)

    # --- Free-form list / text extraction fields ---
    for name in (
        "required_technologies",
        "required_competencies",
        "nice_to_have_technologies",
        "nice_to_have_competencies",
        "leadership_geography",
        "culture_signals",
    ):
        _check_str_list(errors, name, getattr(record, name))
    if not isinstance(record.raw_observations, str):
        errors.append("raw_observations: must be a string")

    # --- Annotation ---
    if record.fit_score is not None and (
        not isinstance(record.fit_score, int)
        or isinstance(record.fit_score, bool)
        or not (1 <= record.fit_score <= 10)
    ):
        errors.append("fit_score: must be null or an integer 1-10")
    if not isinstance(record.applied, bool):
        errors.append("applied: must be a boolean")
    if record.application_date is not None and not isinstance(record.application_date, str):
        errors.append("application_date: must be a string or null")
    _check_enum(errors, "application_decision", record.application_decision, APPLICATION_DECISION)
    _check_enum(errors, "location_workable", record.location_workable, LOCATION_WORKABLE)
    _check_enum(errors, "domain_distance", record.domain_distance, DOMAIN_DISTANCE)
    _check_str_list(errors, "blocking_constraints", record.blocking_constraints)
    for name in ("application_decision_notes", "location_notes", "notes"):
        if not isinstance(getattr(record, name), str):
            errors.append(f"{name}: must be a string")

    return errors


# ---------------------------------------------------------------------------
# ApplicationRecord — Phase 2 scoring output (schema v1.3, Option A).
#
# Personal-assessment / workflow-state layer (job_radar_SPEC §3.3, §4.2).
# Produced by scoring/scorer.py, one per JDRecord, written to corpus/scored/.
# The scorer reads JDRecord *extraction* fields only — never JDRecord's legacy
# annotation stub, and never writes back to it (PHASE2_PLAN locked decision).
#
# This record is single-owner, so it serialises as a flat envelope (no
# extraction/annotation grouping like JDRecord).
# ---------------------------------------------------------------------------

_APPLICATION_FIELDS = (
    "job_id",
    "profile_version",
    "scored_at",
    "fit_score",
    "fit_label",
    "fit_label_reason",
    "requirement_gaps",
    "blocking_constraints",
    "priority_score",
    "application_status",
    "notes",
)


@dataclass
class ApplicationRecord:
    """Personal assessment + workflow state for one scored opportunity."""

    job_id: str               # links to JDRecord.id
    profile_version: str      # candidate_profile.yaml profile_version used
    scored_at: str            # ISO datetime the score was produced
    fit_score: int            # 1–10 (Stage 1, structural fit)
    fit_label: str            # FIT_LABEL (Stage 3 classification)
    fit_label_reason: str     # one sentence, shown in UI
    requirement_gaps: list[str]
    blocking_constraints: list[str]
    priority_score: int       # 1–10 (fit + urgency adjustments)
    application_status: str   # APPLICATION_STATUS; scorer always emits "new"
    notes: str                # free-form, "" from scorer

    def to_dict(self) -> dict:
        """Return the flat JSONL envelope (schema_version + all fields)."""
        return {
            "schema_version": SCHEMA_VERSION,
            **{f: getattr(self, f) for f in _APPLICATION_FIELDS},
        }

    def to_jsonl(self) -> str:
        """Serialise to a single JSONL line (no trailing newline)."""
        return json.dumps(self.to_dict(), ensure_ascii=False)

    @classmethod
    def from_dict(cls, d: dict) -> "ApplicationRecord":
        version = d.get("schema_version")
        if version != SCHEMA_VERSION:
            raise SchemaVersionError(
                f"schema_version {version!r} does not match {SCHEMA_VERSION!r}"
            )
        try:
            return cls(**{f: d[f] for f in _APPLICATION_FIELDS})
        except KeyError as exc:
            raise ValueError(f"missing required field: {exc.args[0]}") from exc

    @classmethod
    def from_jsonl(cls, line: str) -> "ApplicationRecord":
        """Parse one JSONL line. Raises SchemaVersionError on version mismatch."""
        return cls.from_dict(json.loads(line))


def _check_int_range(errors: list[str], name: str, value, lo: int, hi: int) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or not (lo <= value <= hi):
        errors.append(f"{name}: must be an integer {lo}-{hi}")


def validate_application_record(record: ApplicationRecord) -> list[str]:
    """Return a list of validation error strings; empty list means valid."""
    errors: list[str] = []

    for name in ("job_id", "profile_version", "scored_at", "fit_label_reason", "notes"):
        if not isinstance(getattr(record, name), str):
            errors.append(f"{name}: must be a string")
    _check_int_range(errors, "fit_score", record.fit_score, 1, 10)
    _check_int_range(errors, "priority_score", record.priority_score, 1, 10)
    _check_enum(errors, "fit_label", record.fit_label, FIT_LABEL)
    _check_enum(errors, "application_status", record.application_status, APPLICATION_STATUS)
    _check_str_list(errors, "requirement_gaps", record.requirement_gaps)
    _check_str_list(errors, "blocking_constraints", record.blocking_constraints)

    return errors
