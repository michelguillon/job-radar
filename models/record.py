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
        "will_not_apply",  # conscious owner decision not to pursue (vs rejected = they
        # decided, archived = passive cleanup); SPEC_WORKFLOW_UPDATE §2
        "archived",
    }
)

# --- Activity log vocabulary (Phase 3 tracker, job_radar_SPEC §7.4) ---
# The Job Tracker keeps workflow state in an append-only event log
# (corpus/activity_log.jsonl), NOT on ApplicationRecord, so the pure scorer can
# regenerate scored records without wiping human state (see CLAUDE.md deviation
# 23 + job_radar_SPEC.md §7.4, model C). These are vocabulary constants only —
# they do not touch any record dataclass and do not bump SCHEMA_VERSION.
ACTIVITY_LOG_VERSION = 1

# Event kinds in the activity log.
#  status       — value is an APPLICATION_STATUS the human moved the job to.
#  outcome      — value is a terminal OUTCOME (job_radar_SPEC §7.3).
#  note         — value is null; the comment text lives in ``notes``.
#  title        — value is a human-set display title override (the schema-locked
#                 JDRecord has no title field; the sidecar is keyed by source_url and
#                 collides on legacy "unknown" URLs, so this is the per-job_id escape
#                 hatch). Latest title event wins; presentation only, never scored.
#  fit_override — value is a FIT_LABEL the owner asserts over the scorer's verdict
#                 (job_radar_SPEC §10.11 Feature 1), or null to clear a prior override;
#                 the reason lives in ``notes``. A workflow decision ("treat this role
#                 as X today") — it NEVER mutates the scored ApplicationRecord, so the
#                 scorer's value is preserved for corpus quality analysis. Latest wins.
ACTIVITY_EVENT = frozenset({"status", "outcome", "note", "title", "fit_override"})

# Terminal outcomes (job_radar_SPEC §7.3). Derived from the log at read time;
# never persisted on ApplicationRecord (model C / Log-only — job_radar_SPEC.md §7.4).
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

# --- Scoring-annotation vocabulary (Phase 6 interactive UI, job_radar_SPEC §10.2) ---
# The interactive UI lets the owner flag field-level scoring/extraction issues from
# the detail panel. Flags append to corpus/annotations.jsonl (separate sink from the
# activity log — different purpose, future Phase-7 fine-tuning consumer). Like the
# activity-log vocab above these are constants ONLY — they touch no record dataclass
# and do NOT bump SCHEMA_VERSION (same pattern as OUTCOME).
ANNOTATION_LOG_VERSION = 1

# What a flag asserts is wrong (job_radar_SPEC §10.2 table). ``rejection_reason`` is a
# parallel use of the same sink (job_radar_SPEC §11.1 / BACKLOG §2): not a scorer
# disagreement but *why the owner didn't pursue a role despite the score* — the
# structured reason travels in the annotation's ``reason`` field (a REJECTION_REASON value).
ANNOTATION_TYPE = frozenset(
    {
        "role_type_incorrect",
        "domain_incorrect",
        "seniority_incorrect",
        "technical_depth_incorrect",
        "fit_score_disagree",
        "should_be_blocked",
        "false_block",
        "extraction_other",
        "rejection_reason",  # why I didn't pursue despite the score
    }
)

# Structured reasons for a ``rejection_reason`` annotation (BACKLOG §2). Used for
# client-side UI validation and cli.analyse reporting; the API validates it for the
# rejection_reason type only (otherwise ``reason`` stays free text).
REJECTION_REASON = frozenset(
    {
        "wrong_level",
        "wrong_function",
        "too_salesy",
        "too_research_heavy",
        "too_delivery_consulting",
        "domain_not_interesting",
        "company_not_fit",
        "seniority_mismatch",
        "requirement_mismatch",  # under-qualified on a hard requirement (technical depth,
        # years of experience, specific skills) — distinct from seniority/level mismatch
        "location_mismatch",
        "applied_elsewhere_same_company",  # already in play at this company on another role —
        # noise from monitoring multiple roles per company, not a real rejection
        # (SPEC_ACTIVE_COMPANY_FILTER §6)
        "other",
    }
)


# --- cv-tailor link vocabulary (cv-tailor integration Phase 1, job_radar_SPEC §11.3) ---
# A manual (Phase 1) or machine (Phase 3) snapshot of a cv-tailor run's metrics against a
# Job Radar role. Append-only sink corpus/cv_tailor_links.jsonl — NEVER mutates JDRecord,
# ApplicationRecord, or any cv-tailor output file. The cv-tailor run ID is the source of
# truth; the scores here are a summary snapshot tied to cv-tailor's current rubric (which
# may drift). Constants ONLY — they touch no record dataclass and do NOT bump SCHEMA_VERSION
# (same pattern as OUTCOME / ANNOTATION_TYPE).
CV_TAILOR_LINK_VERSION = 1

# Who recorded the link: "manual" (Phase 1, owner via the detail panel) or "cv_tailor_api"
# (Phase 3, cv-tailor's machine-to-machine callback).
CV_TAILOR_SOURCE = frozenset({"manual", "cv_tailor_api"})


def validate_cv_tailor_link(record: dict) -> list[str]:
    """Return a list of validation error strings for one cv-tailor link record.

    A vocabulary + required-field guard so a malformed line never enters the append-only
    ``corpus/cv_tailor_links.jsonl``. ``v``/``ts``/``job_id`` are required; every metric is
    optional but, when present, must be in range (cvcm a bool, source a known value). The
    three metrics mirror the cv-tailor UI: ``fit_score`` + ``coverage_score`` are normalised
    0.0–1.0 (shown as %), ``cv_quality_score`` is the raw 0.0–10.0 rubric score (shown as
    X.X/10 — NOT normalised). The link never mutates an extraction or a score — it is a side
    snapshot. (Field names cleaned up before Phase 3 — deviation 43: ``cv_tailor_score`` →
    ``fit_score``, ``grounding_score`` dropped, ``cv_quality_score`` added.)
    """
    errors: list[str] = []
    for name in ("ts", "job_id"):
        value = record.get(name)
        if not isinstance(value, str) or not value:
            errors.append(f"{name}: must be a non-empty string")

    def _check_float(name: str, lo: float, hi: float) -> None:
        if name in record and record[name] is not None:
            value = record[name]
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not (lo <= value <= hi)
            ):
                errors.append(f"{name}: must be a float {lo}-{hi}")

    _check_float("fit_score", 0.0, 1.0)
    _check_float("coverage_score", 0.0, 1.0)
    _check_float("cv_quality_score", 0.0, 10.0)  # raw rubric score, NOT normalised
    cvcm = record.get("cvcm_enabled")
    if cvcm is not None and not isinstance(cvcm, bool):
        errors.append("cvcm_enabled: must be a boolean")
    source = record.get("source")
    if source is not None and source not in CV_TAILOR_SOURCE:
        errors.append(f"source: {source!r} not in {sorted(CV_TAILOR_SOURCE)}")
    return errors


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
    elif kind == "fit_override":
        # null clears a prior override; otherwise it must name a valid fit_label.
        if value is not None:
            _check_enum(errors, "value", value, FIT_LABEL)
    elif kind == "note" and value is not None:
        errors.append("value: must be null for a note event")
    return errors


def validate_annotation_event(event: dict) -> list[str]:
    """Return a list of validation error strings for one scoring-annotation event.

    Mirrors ``validate_activity_event``: a vocabulary + required-field guard so a
    malformed flag never enters the append-only ``corpus/annotations.jsonl``. The
    annotation never mutates an extraction — it only records that the human disagrees
    with one, with the scorer's verdict at flag time preserved for later calibration.
    """
    errors: list[str] = []
    for name in ("ts", "job_id", "reason"):
        value = event.get(name)
        if not isinstance(value, str) or not value:
            errors.append(f"{name}: must be a non-empty string")
    atype = event.get("annotation_type")
    if atype not in ANNOTATION_TYPE:
        errors.append(f"annotation_type: {atype!r} not in {sorted(ANNOTATION_TYPE)}")
    # field is the extraction field a flag is about; a rejection_reason is about the whole
    # role, not a field, so it carries null. Allow str or None (a wrong *type* still fails).
    field = event.get("field")
    if field is not None and not isinstance(field, str):
        errors.append("field: must be a string or null")
    for name in ("observed", "expected"):
        if name not in event:
            errors.append(f"{name}: required")
    scorer_label = event.get("scorer_label")
    if scorer_label is not None and not isinstance(scorer_label, str):
        errors.append("scorer_label: must be a string or null")
    scorer_fit_score = event.get("scorer_fit_score")
    if scorer_fit_score is not None and (
        not isinstance(scorer_fit_score, int) or isinstance(scorer_fit_score, bool)
    ):
        errors.append("scorer_fit_score: must be an integer or null")
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


# A ``validate`` finding ending with this is a pure *enum vocabulary gap*: the field is
# present and the right type, its value is just outside the closed vocabulary. Only
# ``_check_enum`` and ``_check_subset``'s bad-values branch emit it — every structural
# (wrong-type / not-a-list) finding has a different, "must be a …"-shaped message.
_ENUM_GAP_SUFFIX = "not in allowed values"


def soft_validate(record: JDRecord) -> tuple[list[str], list[str]]:
    """Run the SAME checks as ``validate`` but split them into ``(hard_errors, warnings)``.

    ``validate``'s callers (batch labelling, ``cli.validate``, prefilter output) treat a
    non-empty list as a hard failure — the closed-vocabulary enum gate keeps the automated
    corpus clean. **Manual ingest is a deliberate human decision** (the owner has chosen to
    add this exact role), so the *enum* gate must not block it: an extraction like
    ``role_type: ["Customer Success"]`` (not in ``ROLE_TYPE``) is stored as-is, surfaced as a
    *warning*. But a **structural** error (a field of the wrong type — ``domain`` a string
    instead of a list, ``fit_score`` a string instead of an int — or a missing required field)
    must STILL hard-fail even in manual ingest: the scorer and serialiser tolerate unknown
    enum values, but a malformed type silently corrupts every downstream stage. So:

    - ``hard_errors`` — structural type errors / missing fields. The caller should 422.
    - ``warnings`` — enum vocabulary gaps. The caller stores the record as-is, advisory only.

    This is a thin, intentionally-named seam over ``validate`` so the bypass is explicit at the
    call site — the checks (and their wording) stay in one place; ``soft_validate`` only
    *classifies* their output. Never raises; ``([], [])`` means clean. (CLAUDE.md deviation 47.)
    """
    hard_errors: list[str] = []
    warnings: list[str] = []
    for finding in validate(record):
        (warnings if finding.endswith(_ENUM_GAP_SUFFIX) else hard_errors).append(finding)
    return hard_errors, warnings


# ---------------------------------------------------------------------------
# ApplicationRecord — Phase 2 scoring output (schema v1.3, Option A).
#
# Personal-assessment / workflow-state layer (job_radar_SPEC §3.3, §4.2).
# Produced by scoring/scorer.py, one per JDRecord, written to corpus/scored/.
# The scorer reads JDRecord *extraction* fields only — never JDRecord's legacy
# annotation stub, and never writes back to it (Option A — job_radar_SPEC.md §6.9).
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
