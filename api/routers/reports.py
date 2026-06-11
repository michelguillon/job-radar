"""api/routers/reports.py — read-only report downloads (job_radar_SPEC §11.1).

The yield report (BACKLOG_YIELD_TRACKING) as a downloadable text file. It is the
exact same terminal report the CLI prints (`python -m cli.analyse --report yield`) —
this endpoint imports and calls the *same* pure aggregation/format functions, never
a reimplementation. No auth: it is read-only, like `GET /api/index`. The browser
downloads it via the ``Content-Disposition: attachment`` header.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse

from api.settings import Settings, get_settings
from cli.analyse import build_yield_report, format_yield, load_cost_and_jobs, load_yield_seeds
from cli.stats import load_annotations
from cli.track import load_events, load_jdrecords, load_scores, project

router = APIRouter(prefix="/api/report", tags=["reports"])


@router.get("/yield", response_class=PlainTextResponse)
def yield_report(settings: Settings = Depends(get_settings)) -> PlainTextResponse:
    """Build the company yield report and return it as a downloadable .txt file."""
    scores = load_scores(settings.scored_glob)
    jds = load_jdrecords(settings.validated_glob)
    workflow = project(load_events(settings.log_path))
    annotations = load_annotations(settings.annotations_path)
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
