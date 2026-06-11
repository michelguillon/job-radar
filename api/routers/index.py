"""api/routers/index.py — public reads (job_radar_SPEC §10.4).

No auth. Serves the joined read model (corpus/index.json), reports capabilities for the
UI to render the unlock affordance, and a health check.

The read model is pre-built by ``python -m cli.stats --export-index``, but workflow writes
land in ``activity_log.jsonl`` (and scoring flags in ``annotations.jsonl``) *after* that
export, so a naive file-serve looks stale right after a write. So ``GET /api/index`` serves
index.json **and re-projects the current logs over it** (cheap: load_events → project +
load_annotations) — status/outcome/application_date/notes/title, the fit override
(scorer-vs-user, §10.11 Feature 1), and the embedded annotations (§10.11 Feature 2) are all
live without a re-score. (Logged as a deviation — see CLAUDE.md.)
"""

from __future__ import annotations

import json
import os

from fastapi import APIRouter, Depends, Request

from api.security import verify_token, write_configured, WRITE_COOKIE
from api.settings import Settings, get_settings
from cli.stats import cv_tailor_view, load_annotations, load_cv_tailor_links
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


def overlay_workflow(
    index: dict,
    log_path: str,
    annotations_path: str | None = None,
    cv_tailor_links_path: str | None = None,
) -> dict:
    """Re-project the live activity log (+ annotations + cv-tailor links) over the read model
    so writes show on reload.

    Patches each record's status/outcome/application_date/notes by job_id, applies a live
    title override if one was set (mirrors cli.track._title_for's override priority), and
    re-resolves the fit override (display = user override or scorer value — the scorer value
    in ``scorer_fit_label`` is always preserved). When ``annotations_path`` is given, the
    embedded annotations are refreshed from the live log so a freshly submitted flag shows;
    likewise ``cv_tailor_links_path`` refreshes the ``cv_tailor`` section (job_radar_SPEC §11.3).
    """
    states = project(load_events(log_path))
    annotations = load_annotations(annotations_path) if annotations_path else None
    cv_tailor_links = load_cv_tailor_links(cv_tailor_links_path) if cv_tailor_links_path else None
    for rec in index.get("records", []):
        job_id = rec.get("job_id")
        if annotations is not None:
            ann = annotations.get(job_id, [])
            rec["annotations"] = ann
            rec["annotation_count"] = len(ann)
            rec["has_annotations"] = bool(ann)
        if cv_tailor_links is not None:
            rec["cv_tailor"] = cv_tailor_view(cv_tailor_links.get(job_id))
        state = states.get(job_id)
        if not state:
            continue
        rec["application_status"] = state["status"]
        rec["outcome"] = state["outcome"]
        rec["application_date"] = state["application_date"]
        rec["notes"] = state["notes"]
        if state.get("title_override"):
            rec["title"] = state["title_override"]
        # Fit override: recompute display from the preserved scorer value + live override.
        override = state.get("fit_override")
        scorer_label = rec.get("scorer_fit_label", rec.get("fit_label"))
        display_fit = override or scorer_label
        rec["user_fit_label"] = override
        rec["user_fit_reason"] = state.get("fit_override_reason")
        rec["has_fit_override"] = override is not None
        rec["display_fit_label"] = display_fit
        rec["fit_label"] = display_fit
    return index


@router.get("/index")
def get_index(settings: Settings = Depends(get_settings)) -> dict:
    """The joined read model with the live activity log + annotations + cv-tailor links overlaid (always current)."""
    return overlay_workflow(
        _read_index(settings.index_path),
        settings.log_path,
        settings.annotations_path,
        settings.cv_tailor_links_path,
    )


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
