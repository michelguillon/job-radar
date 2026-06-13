"""api/routers/annotations.py — gated scoring-flag writes (job_radar_SPEC §10.4, §10.2).

A field-level scoring/extraction flag. It NEVER mutates an extraction — it records that
the owner disagrees with one, with the scorer's verdict at flag time captured for later
calibration (Phase 7). Appends to corpus/annotations.jsonl (a separate sink from the
activity log — different purpose, different future consumer). Gated on the capability
cookie **per-route** (`dependencies=[Depends(require_unlocked)]` on the POST, not at the
router level — api/CLAUDE.md "per-route gating rule", deviation 42); 404s an unknown
job_id; validated against ANNOTATION_TYPE before append.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.events import emit_index_updated
from api.security import require_unlocked
from api.settings import Settings, get_settings
from cli.db import write_annotation
from cli.track import _clock, append_event, load_scores
from models.record import ANNOTATION_LOG_VERSION, REJECTION_REASON, validate_annotation_event

router = APIRouter(prefix="/api", tags=["annotations"])


class AnnotationRequest(BaseModel):
    job_id: str
    annotation_type: str
    field: str | None = None  # null for a rejection_reason (about the role, not a field)
    observed: Any = None
    expected: Any = None
    reason: str


@router.post("/annotations", dependencies=[Depends(require_unlocked)])
def flag(body: AnnotationRequest, settings: Settings = Depends(get_settings)) -> dict:
    """Append one scoring flag, capturing the scorer's current verdict for the job_id."""
    scores = load_scores(settings.scored_glob)
    score = scores.get(body.job_id)
    if score is None:
        raise HTTPException(status_code=404, detail=f"job_id not found in scored corpus: {body.job_id}")

    # A rejection_reason reuses this sink to record *why a role wasn't pursued* (BACKLOG §2):
    # its `reason` is a structured REJECTION_REASON value, not free text — validate it here
    # (the only type-specific server validation; all other types keep `reason` free-form).
    if body.annotation_type == "rejection_reason" and body.reason not in REJECTION_REASON:
        raise HTTPException(status_code=422, detail=f"reason must be one of {sorted(REJECTION_REASON)}")

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

    # Duplicate prevention (job_radar_SPEC §10.11 Feature 2): an exact duplicate is the
    # same job_id + annotation_type + field + reason. Phase 6.5 Step 4: the Python "load
    # the JSONL and scan" check is replaced by the SQLite UNIQUE(job_id, type,
    # IFNULL(field,''), reason) index — a duplicate raises IntegrityError -> 409. SQLite is
    # written FIRST so the constraint rejects the dup before any JSONL append (no orphan
    # line). The JSONL append remains the dual-write safety net + audit archive.
    try:
        write_annotation(record)
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail="duplicate annotation: same job_id + type + field + reason")
    append_event(settings.annotations_path, record)
    emit_index_updated()
    return {"ok": True, "job_id": body.job_id, "annotation_type": body.annotation_type}
