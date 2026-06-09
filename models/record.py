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

SCHEMA_VERSION = "1.2"

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
    """Raised when a record's schema_version does not match SCHEMA_VERSION."""


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
            "schema_version": SCHEMA_VERSION,
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
        if version != SCHEMA_VERSION:
            raise SchemaVersionError(
                f"schema_version {version!r} does not match {SCHEMA_VERSION!r}"
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
