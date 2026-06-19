"""api/routers/cv_tailor.py — cv-tailor integration Phase 1–3 (job_radar_SPEC §11.3).

Two endpoints:

- ``POST /api/cv-tailor-results`` — append a cv-tailor run snapshot for a scored role by
  INSERTing into the SQLite ``cv_tailor_links`` table (Phase 6.5 Step 6: SQLite is the sole
  write destination; ``corpus/cv_tailor_links.jsonl`` is a read-only audit archive). It NEVER
  mutates a JDRecord, an ApplicationRecord, or a cv-tailor output file — a side snapshot keyed
  by job_id.
  **Dual auth (deviation 43):** accepts the owner capability cookie (Phase 1, browser) OR a
  ``CV_TAILOR_SERVICE_KEY`` Bearer token (Phase 3, cv-tailor's machine-to-machine callback).
  Validated against ``validate_cv_tailor_link``; 404s an unknown job_id; 422s a bad score.
- ``GET /api/jobs/{job_id}`` (public, no auth) — job detail (scored ⨝ JD extraction ⨝
  sidecar) including ``raw_text`` for the Phase 2 cv-tailor handoff. The JD text is already
  visible in the public detail panel, so this exposes nothing new. **Phase 4 Step 1
  (INTEGRATION_SPEC §7):** it now also returns two nested objects — ``extraction`` (the
  JDRecord extraction fields cv-tailor's Phase-0 bypass needs) and ``assessment`` (Job
  Radar's verdict + the owner's live workflow state: fit override, owner status,
  annotations, notes). Both are pure joins over data that already exists; no auth change.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from api.events import emit_index_updated
from api.security import WRITE_COOKIE, has_valid_service_token, verify_token
from api.settings import Settings, get_settings
from cli import telemetry
from cli.db import write_cv_tailor_link
from cli.stats import _location_for, load_annotations_auto
from cli.track import (
    _clock,
    load_activity_events,
    load_jdrecords,
    load_meta,
    load_scores,
    project,
    _title_for,
)
from models.record import CV_TAILOR_LINK_VERSION, validate_cv_tailor_link

router = APIRouter(prefix="/api", tags=["cv-tailor"])


class CvTailorResultRequest(BaseModel):
    job_id: str
    cv_tailor_run_id: str
    fit_score: float | None = None          # 0.0–1.0 (was cv_tailor_score)
    coverage_score: float | None = None     # 0.0–1.0
    cv_quality_score: float | None = None   # 0.0–10.0 — raw rubric score, NOT normalised
    cvcm_enabled: bool | None = None
    tailoring_mode: str | None = None
    output_link: str | None = None
    notes: str | None = None
    source: str = "manual"


@router.post("/cv-tailor-results")
def record_cv_tailor_result(
    request: Request, body: CvTailorResultRequest, settings: Settings = Depends(get_settings)
) -> dict:
    """Append one cv-tailor run snapshot for a scored role.

    Authorised by EITHER the owner capability cookie (Phase 1, browser) OR a valid
    ``CV_TAILOR_SERVICE_KEY`` Bearer token (Phase 3, cv-tailor callback). Both fail closed —
    no cookie and no/invalid token (or an unconfigured key) → 403."""
    if not (
        verify_token(request.cookies.get(WRITE_COOKIE))
        or has_valid_service_token(request, settings.cv_tailor_service_key)
    ):
        raise HTTPException(status_code=403, detail="not authorised — owner unlock or service token required")
    scores = load_scores(settings.scored_glob)
    if body.job_id not in scores:
        raise HTTPException(status_code=404, detail=f"job_id not found in scored corpus: {body.job_id}")

    record = {
        "v": CV_TAILOR_LINK_VERSION,
        "ts": _clock(),
        "job_id": body.job_id,
        "cv_tailor_run_id": body.cv_tailor_run_id,
        "fit_score": body.fit_score,
        "coverage_score": body.coverage_score,
        "cv_quality_score": body.cv_quality_score,
        "cvcm_enabled": body.cvcm_enabled,
        "tailoring_mode": body.tailoring_mode,
        "output_link": body.output_link,
        "notes": body.notes,
        "source": body.source,
    }
    errors = validate_cv_tailor_link(record)
    if errors:
        raise HTTPException(status_code=422, detail=f"invalid cv-tailor link: {errors}")
    # Phase 6.5 Step 6: SQLite is the sole write destination (JSONL dual-write removed after a
    # clean 5-day production soak). No dedup — multiple runs per job_id are kept as history.
    # JSONL archived at corpus/cv_tailor_links.jsonl (read-only audit trail)
    write_cv_tailor_link(record)
    emit_index_updated()
    # Phase C: enrich the role_scoring_decision trace (same job_id seed) with cv-tailor's
    # verdict + the JR↔cv-tailor divergence. Opt-in, best-effort, fired AFTER persist so a
    # tracing failure can never fail the callback (mirrors manual_ingest, deviation 46).
    telemetry.on_cv_tailor_result(
        job_id=body.job_id,
        fit_score=body.fit_score,
        coverage_score=body.coverage_score,
        cv_quality_score=body.cv_quality_score,
        job_radar_fit_score=scores[body.job_id].fit_score,
    )
    return record


# The JDRecord extraction fields cv-tailor's Phase-0 bypass consumes (INTEGRATION_SPEC §7,
# Phase 4 Step 1). A pure projection of JDRecord attributes — no derivation, no scoring.
_EXTRACTION_VIEW_FIELDS = (
    "role_type",
    "seniority",
    "domain",
    "technical_depth",
    "delivery_motion",
    "required_technologies",
    "required_competencies",
    "nice_to_have_technologies",
    "nice_to_have_competencies",
    "remote_policy",
    "leadership_geography",
)


def _extraction_view(jd) -> dict | None:
    """The ``extraction`` block from a JDRecord, or ``None`` when there is no JDRecord
    (some manually-ingested roles may have only a partial extraction)."""
    if jd is None:
        return None
    return {field: getattr(jd, field) for field in _EXTRACTION_VIEW_FIELDS}


def _assessment_view(score, state: dict | None, events: list[dict], annotations: list[dict],
                     job_id: str) -> dict:
    """The ``assessment`` block: Job Radar's scorer verdict + the owner's live workflow state.

    ``score`` is the ApplicationRecord (always present — the caller 404s when not scored).
    ``state`` is ``project()``'s folded state for this job_id (None when no events exist).
    The fit override / owner status / notes are read from the SAME projected event log the
    ``GET /api/index`` overlay uses (deviation 49: API read paths use the auto-detecting
    loaders, not raw SQLite), and ``annotations`` is the per-job_id annotation view list.
    """
    state = state or {}
    override = state.get("fit_override")
    fit_override = (
        {"label": override, "reason": state.get("fit_override_reason")} if override else None
    )
    notes = [
        {"ts": e.get("ts"), "text": e.get("notes")}
        for e in events
        if e.get("job_id") == job_id and e.get("event") == "note"
    ]
    return {
        "fit_label": score.fit_label,
        "fit_score": score.fit_score,
        "priority_score": score.priority_score,
        "blocking_constraints": score.blocking_constraints,
        "requirement_gaps": score.requirement_gaps,
        "fit_override": fit_override,
        # owner_status: the live projected status (default "new" once any event exists),
        # None when the job has no activity-log events at all.
        "owner_status": state.get("status"),
        "annotations": [
            {"type": a.get("annotation_type"), "field": a.get("field"), "reason": a.get("reason")}
            for a in annotations
        ],
        "notes": notes,
    }


@router.get("/jobs/{job_id}")
def get_job_detail(job_id: str, settings: Settings = Depends(get_settings)) -> dict:
    """Public job detail for the cv-tailor handoff: scored ⨝ JD extraction ⨝ sidecar, plus
    (Phase 4 Step 1) nested ``extraction`` + ``assessment`` blocks. Includes ``raw_text``
    (already public in the UI detail panel). 404 if not scored."""
    score = load_scores(settings.scored_glob).get(job_id)
    if score is None:
        raise HTTPException(status_code=404, detail=f"job_id not found in scored corpus: {job_id}")

    jd = load_jdrecords(settings.validated_glob).get(job_id)
    meta = load_meta(settings.meta_glob).get(jd.source_url) if jd else None

    # Live interactive state via the auto-detecting loaders (SQLite if present, else JSONL) —
    # same source the GET /api/index overlay reads, so the detail view never goes stale.
    events = load_activity_events(settings.log_path)
    state = project(events).get(job_id)
    annotations = load_annotations_auto(settings.annotations_path).get(job_id, [])

    return {
        "job_id": job_id,
        "company": jd.company if jd else "",
        "title": _title_for(jd, meta, None),
        "source_url": jd.source_url if jd else "",
        "location": _location_for(jd, meta),
        "fit_label": score.fit_label,
        "fit_score": score.fit_score,
        "priority_score": score.priority_score,
        "raw_text": jd.raw_text if jd else "",
        "extraction": _extraction_view(jd),
        "assessment": _assessment_view(score, state, events, annotations, job_id),
    }
