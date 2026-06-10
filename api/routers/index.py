"""api/routers/index.py — public reads (job_radar_SPEC §10.4).

No auth. Serves the joined read model (corpus/index.json), reports capabilities for the
UI to render the unlock affordance, and a health check.

The read model is pre-built by ``python -m cli.stats --export-index``, but workflow writes
land in ``activity_log.jsonl`` *after* that export, so a naive file-serve looks stale right
after a write. So ``GET /api/index`` serves index.json **and re-projects the current
activity log over it** (cheap: load_events → project) — status/outcome/application_date/
notes/title are always live without a re-score. Annotations don't affect the read model.
(Logged as a deviation — see CLAUDE.md.)
"""

from __future__ import annotations

import json
import os

from fastapi import APIRouter, Depends, Request

from api.security import verify_token, write_configured, WRITE_COOKIE
from api.settings import Settings, get_settings
from cli.track import load_events, project

router = APIRouter(prefix="/api", tags=["index"])


def _read_index(path: str) -> dict:
    """Read the pre-built index.json, or an empty shell if it has not been exported yet."""
    if not os.path.exists(path):
        return {
            "schema_version": None,
            "jdrecord_schema_version": None,
            "generated_at": None,
            "stats": {"total": 0},
            "records": [],
        }
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def overlay_workflow(index: dict, log_path: str) -> dict:
    """Re-project the live activity log over the read model so writes show on reload.

    Patches each record's status/outcome/application_date/notes by job_id, and applies a
    live title override if one was set (mirrors cli.track._title_for's override priority).
    """
    states = project(load_events(log_path))
    for rec in index.get("records", []):
        state = states.get(rec.get("job_id"))
        if not state:
            continue
        rec["application_status"] = state["status"]
        rec["outcome"] = state["outcome"]
        rec["application_date"] = state["application_date"]
        rec["notes"] = state["notes"]
        if state.get("title_override"):
            rec["title"] = state["title_override"]
    return index


@router.get("/index")
def get_index(settings: Settings = Depends(get_settings)) -> dict:
    """The joined read model with the live activity log overlaid (always current)."""
    return overlay_workflow(_read_index(settings.index_path), settings.log_path)


@router.get("/capabilities")
def capabilities(request: Request) -> dict:
    """Drives UI rendering: is owner-write configured server-side, and is THIS browser
    session unlocked (valid capability cookie)? (job_radar_SPEC §10.5 table.)"""
    configured = write_configured()
    return {
        "write_configured": configured,
        "write_unlocked": configured and verify_token(request.cookies.get(WRITE_COOKIE)),
    }


@router.get("/health")
def health(settings: Settings = Depends(get_settings)) -> dict:
    """Liveness + a count of indexed records and the last export time (cheap smoke test)."""
    index = _read_index(settings.index_path)
    return {
        "status": "ok",
        "service": "job-radar",
        "records": len(index.get("records", [])),
        "last_indexed": index.get("generated_at"),
    }
