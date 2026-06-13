"""api/main.py — the Job Radar FastAPI app (Phase 6, job_radar_SPEC §10.4).

A THIN HTTP layer that mediates browser writes over the same JSONL the CLI appends to.
It mounts the public-read router and the gated workflow/annotation write routers; it
imports cli.track + models.record and NEVER calls the scorer, labeller, or any pipeline
stage. Every write is: require_unlocked → validate → append → 200.

Run (compose): uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api import events
from api.routers import annotations, auth, cv_tailor, events as events_router, index, manual_ingest, reports, workflow


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Capture the running loop so sync (threadpool) write endpoints can publish SSE events
    onto it via call_soon_threadsafe (api/events.py)."""
    events.bind_loop(asyncio.get_running_loop())
    yield


app = FastAPI(
    title="job-radar",
    version="0.1.0",
    summary="Personal job-search intelligence — interactive UI backend (SPEC §10)",
    lifespan=lifespan,
)

# Dev CORS: the Vite dev server (:3000) and the nginx frontend (:8080) call the backend
# directly during development. In prod the frontend proxies /api same-origin, so this is
# dev-only breadth. Credentials are allowed so the capability cookie rides along.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8080", "http://127.0.0.1:8080",
        "http://localhost:3000", "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(index.router)
app.include_router(auth.router)
app.include_router(workflow.router)
app.include_router(annotations.router)
app.include_router(reports.router)
app.include_router(cv_tailor.router)
app.include_router(manual_ingest.router)
app.include_router(events_router.router)
