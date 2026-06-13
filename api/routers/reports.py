"""api/routers/reports.py — read-only report downloads (job_radar_SPEC §11.1).

The yield + cv-tailor calibration reports as downloadable text files. Each is the
exact same terminal report the CLI prints (`python -m cli.analyse --report yield` /
`--report cv_tailor`) — these endpoints import and call the *same* pure aggregation/
format functions, never a reimplementation. No auth: they are read-only, like
`GET /api/index`. The browser downloads them via the ``Content-Disposition:
attachment`` header.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse

from api.settings import Settings, get_settings
from cli.analyse import (
    build_cv_tailor_report,
    build_yield_report,
    format_cv_tailor,
    format_yield,
    load_cost_and_jobs,
    load_yield_seeds,
)
from cli.stats import load_all_cv_tailor_links_auto, load_annotations_auto
from cli.track import load_activity_events, load_jdrecords, load_meta, load_scores, project

router = APIRouter(prefix="/api/report", tags=["reports"])


@router.get("/yield", response_class=PlainTextResponse)
def yield_report(settings: Settings = Depends(get_settings)) -> PlainTextResponse:
    """Build the company yield report and return it as a downloadable .txt file."""
    scores = load_scores(settings.scored_glob)
    jds = load_jdrecords(settings.validated_glob)
    workflow = project(load_activity_events(settings.log_path))
    annotations = load_annotations_auto(settings.annotations_path)
    seeds = load_yield_seeds(settings.seeds_path)

    cost, jobs = load_cost_and_jobs(settings.stats_path)
    cost_per_job = (cost / jobs) if (cost is not None and jobs) else None

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    data = build_yield_report(seeds, scores, jds, workflow, annotations, cost_per_job=cost_per_job)
    text = format_yield(data, today=today)

    return PlainTextResponse(
        text,
        headers={"Content-Disposition": f'attachment; filename="yield_report_{today}.txt"'},
    )


@router.get("/cv_tailor", response_class=PlainTextResponse)
def cv_tailor_report(settings: Settings = Depends(get_settings)) -> PlainTextResponse:
    """Build the cv-tailor calibration report and return it as a downloadable .txt file."""
    scores = load_scores(settings.scored_glob)
    jds = load_jdrecords(settings.validated_glob)
    metas = load_meta(settings.meta_glob)
    workflow = project(load_activity_events(settings.log_path))
    cv_tailor_links = load_all_cv_tailor_links_auto(settings.cv_tailor_links_path)

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    data = build_cv_tailor_report(cv_tailor_links, scores, jds, metas, workflow)
    text = format_cv_tailor(data, today=today)

    return PlainTextResponse(
        text,
        headers={"Content-Disposition": f'attachment; filename="cv_tailor_report_{today}.txt"'},
    )
