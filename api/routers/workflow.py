"""api/routers/workflow.py — gated workflow writes (job_radar_SPEC §10.4).

Task-oriented endpoints (status / note / title) over the SAME append-only event model the
CLI uses. Each reuses cli.track: build_event (which runs validate_activity_event) →
append_event. The API adds nothing the CLI doesn't already do — it is one more write path
over corpus/activity_log.jsonl, not a second source of truth. Every endpoint is gated on
the capability cookie (require_unlocked) and 404s an unknown job_id (the CLI's --force
escape hatch is intentionally not exposed over HTTP).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.security import require_unlocked
from api.settings import Settings, get_settings
from cli.track import (
    _clock,
    _default_state,
    append_event,
    build_event,
    load_events,
    load_scores,
    project,
    transition_warning,
)

router = APIRouter(prefix="/api", tags=["workflow"], dependencies=[Depends(require_unlocked)])


class StatusRequest(BaseModel):
    job_id: str
    status: str
    notes: str | None = None


class NoteRequest(BaseModel):
    job_id: str
    text: str


class TitleRequest(BaseModel):
    job_id: str
    title: str


class OutcomeRequest(BaseModel):
    job_id: str
    outcome: str
    notes: str | None = None


def _require_scored(job_id: str, scored_glob: str) -> None:
    """404 unless the job_id is in the scored corpus (HTTP has no --force)."""
    if job_id not in load_scores(scored_glob):
        raise HTTPException(status_code=404, detail=f"job_id not found in scored corpus: {job_id}")


def _append(log_path: str, job_id: str, *, event: str, value, notes: str) -> dict:
    """Build (=validate) + append one event, or 422 on a vocab violation."""
    try:
        record = build_event(job_id, event=event, value=value, notes=notes, ts=_clock())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    append_event(log_path, record)
    return record


@router.post("/status")
def set_status(body: StatusRequest, settings: Settings = Depends(get_settings)) -> dict:
    """Move a job to a workflow status. Surfaces a (non-blocking) transition warning —
    real searches skip and backtrack stages (cli.track precedent: warn, never block)."""
    _require_scored(body.job_id, settings.scored_glob)
    current = project(load_events(settings.log_path)).get(body.job_id, _default_state())["status"]
    warning = transition_warning(current, body.status)
    _append(settings.log_path, body.job_id, event="status", value=body.status, notes=body.notes or "")
    return {"ok": True, "job_id": body.job_id, "status": body.status, "warning": warning}


@router.post("/note")
def add_note(body: NoteRequest, settings: Settings = Depends(get_settings)) -> dict:
    """Attach a pure note (no status change)."""
    _require_scored(body.job_id, settings.scored_glob)
    _append(settings.log_path, body.job_id, event="note", value=None, notes=body.text)
    return {"ok": True, "job_id": body.job_id}


@router.post("/title")
def set_title(body: TitleRequest, settings: Settings = Depends(get_settings)) -> dict:
    """Set a display-title override (presentation only — never scored)."""
    _require_scored(body.job_id, settings.scored_glob)
    _append(settings.log_path, body.job_id, event="title", value=body.title, notes="")
    return {"ok": True, "job_id": body.job_id, "title": body.title}


@router.post("/outcome")
def set_outcome(body: OutcomeRequest, settings: Settings = Depends(get_settings)) -> dict:
    """Record a terminal outcome (OUTCOME vocab — e.g. rejected_interview) with an optional
    reason. The granular outcome and the workflow status are orthogonal (model C): the UI
    also POSTs /api/status to move the lane. Invalid outcome → 422 (build_event validates)."""
    _require_scored(body.job_id, settings.scored_glob)
    _append(settings.log_path, body.job_id, event="outcome", value=body.outcome, notes=body.notes or "")
    return {"ok": True, "job_id": body.job_id, "outcome": body.outcome}
