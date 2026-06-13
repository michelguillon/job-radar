"""api/routers/events.py — GET /api/events, the live-update SSE stream (job_radar_SPEC §11.1).

Public, read-only: it carries no corpus data, only "the index changed" notices, so the browser
can re-fetch ``GET /api/index`` instead of polling or making the user refresh. The write
endpoints publish onto the in-process bus (``api.events.emit_index_updated``); this endpoint
streams it back out. See ``api/events.py`` for the bus + thread-safety notes.
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from api.events import event_stream

router = APIRouter(prefix="/api", tags=["events"])


@router.get("/events")  # public — no auth required (read-only "something changed" stream, SPEC §11.1)
def events() -> StreamingResponse:
    """Server-Sent-Events stream emitting an ``index_updated`` event after every write."""
    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # disable nginx/proxy buffering so events flush immediately
        },
    )
