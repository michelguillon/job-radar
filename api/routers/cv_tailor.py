"""api/routers/cv_tailor.py — cv-tailor integration Phase 1–3 (job_radar_SPEC §11.3).

Two endpoints:

- ``POST /api/cv-tailor-results`` — append a cv-tailor run snapshot for a scored role to the
  append-only ``corpus/cv_tailor_links.jsonl``. It NEVER mutates a JDRecord, an
  ApplicationRecord, or a cv-tailor output file — it is a side snapshot keyed by job_id.
  **Dual auth (deviation 43):** accepts the owner capability cookie (Phase 1, browser) OR a
  ``CV_TAILOR_SERVICE_KEY`` Bearer token (Phase 3, cv-tailor's machine-to-machine callback).
  Validated against ``validate_cv_tailor_link``; 404s an unknown job_id; 422s a bad score.
- ``GET /api/jobs/{job_id}`` (public, no auth) — job detail (scored ⨝ JD extraction ⨝
  sidecar) including ``raw_text`` for the Phase 2 cv-tailor handoff. The JD text is already
  visible in the public detail panel, so this exposes nothing new.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from api.events import emit_index_updated
from api.security import WRITE_COOKIE, has_valid_service_token, verify_token
from api.settings import Settings, get_settings
from cli.db import write_cv_tailor_link
from cli.stats import _location_for
from cli.track import (
    _clock,
    append_event,
    load_jdrecords,
    load_meta,
    load_scores,
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
    if body.job_id not in load_scores(settings.scored_glob):
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
    # Phase 6.5 Step 4: dual-write — JSONL (safety net + audit archive) AND SQLite. No
    # dedup here (multiple runs per job_id are kept as history). JSONL first; SQLite second.
    append_event(settings.cv_tailor_links_path, record)
    write_cv_tailor_link(record)
    emit_index_updated()
    return record


@router.get("/jobs/{job_id}")
def get_job_detail(job_id: str, settings: Settings = Depends(get_settings)) -> dict:
    """Public job detail for the Phase 2 cv-tailor handoff: scored ⨝ JD extraction ⨝ sidecar,
    including ``raw_text`` (already public in the UI detail panel). 404 if not scored."""
    score = load_scores(settings.scored_glob).get(job_id)
    if score is None:
        raise HTTPException(status_code=404, detail=f"job_id not found in scored corpus: {job_id}")

    jd = load_jdrecords(settings.validated_glob).get(job_id)
    meta = load_meta(settings.meta_glob).get(jd.source_url) if jd else None

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
    }
