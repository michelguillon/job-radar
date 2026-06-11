"""api/routers/annotations.py — gated scoring-flag writes (job_radar_SPEC §10.4, §10.2).

A field-level scoring/extraction flag. It NEVER mutates an extraction — it records that
the owner disagrees with one, with the scorer's verdict at flag time captured for later
calibration (Phase 7). Appends to corpus/annotations.jsonl (a separate sink from the
activity log — different purpose, different future consumer). Gated on the capability
cookie; 404s an unknown job_id; validated against ANNOTATION_TYPE before append.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.security import require_unlocked
from api.settings import Settings, get_settings
from cli.track import _clock, append_event, load_events, load_scores
from models.record import ANNOTATION_LOG_VERSION, validate_annotation_event

router = APIRouter(prefix="/api", tags=["annotations"], dependencies=[Depends(require_unlocked)])


class AnnotationRequest(BaseModel):
    job_id: str
    annotation_type: str
    field: str
    observed: Any = None
    expected: Any = None
    reason: str


@router.post("/annotations")
def flag(body: AnnotationRequest, settings: Settings = Depends(get_settings)) -> dict:
    """Append one scoring flag, capturing the scorer's current verdict for the job_id."""
    scores = load_scores(settings.scored_glob)
    score = scores.get(body.job_id)
    if score is None:
        raise HTTPException(status_code=404, detail=f"job_id not found in scored corpus: {body.job_id}")

    # Duplicate prevention (job_radar_SPEC §10.11 Feature 2): an exact duplicate is the
    # same job_id + annotation_type + field + reason. The UI warns client-side from the
    # embedded annotations; the server is the backstop (409). Append-only — never edits.
    for existing in load_events(settings.annotations_path):
        if (
            existing.get("job_id") == body.job_id
            and existing.get("annotation_type") == body.annotation_type
            and existing.get("field") == body.field
            and existing.get("reason") == body.reason
        ):
            raise HTTPException(status_code=409, detail="duplicate annotation: same job_id + type + field + reason")

    record = {
        "v": ANNOTATION_LOG_VERSION,
        "ts": _clock(),
        "job_id": body.job_id,
        "annotation_type": body.annotation_type,
        "field": body.field,
        "observed": body.observed,
        "expected": body.expected,
        "reason": body.reason,
        "scorer_label": score.fit_label,
        "scorer_fit_score": score.fit_score,
    }
    errors = validate_annotation_event(record)
    if errors:
        raise HTTPException(status_code=422, detail=f"invalid annotation: {errors}")
    append_event(settings.annotations_path, record)
    return {"ok": True, "job_id": body.job_id, "annotation_type": body.annotation_type}
