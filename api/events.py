"""api/events.py — in-process Server-Sent-Events bus for live UI updates (job_radar_SPEC §11.1).

A write operation (status / manual ingest / cv-tailor result / fit override / outcome /
annotation) makes the read model stale until the user manually refreshes. This bus closes that
gap: each write calls ``emit_index_updated()``; every open ``GET /api/events`` connection
receives an ``index_updated`` frame and re-fetches ``GET /api/index``.

**No Redis / no external pub-sub** — this is a single-process FastAPI app, so the bus is a set
of in-memory per-connection ``asyncio.Queue``s. When PostgreSQL/multi-process lands (SPEC §11.4/
§11.5) this is the one piece that needs a real broker; the ``GET /api/events`` *contract* stays
identical, so the (Cursor-rebuilt) frontend reconnects unchanged.

**Thread-safety:** the write endpoints are sync (`def`) path operations, which Starlette runs in
a threadpool — they cannot touch an ``asyncio.Queue`` directly. ``emit_index_updated`` therefore
hops back onto the event loop via ``call_soon_threadsafe`` using the loop captured at app startup
(``bind_loop``). No loop bound yet, or nobody listening → a clean no-op, so a write never fails
because the bus isn't ready.
"""

from __future__ import annotations

import asyncio
from typing import AsyncGenerator

# One queue per open SSE connection; a write fans out to all of them.
_subscribers: set[asyncio.Queue] = set()
# The app event loop, captured at startup so sync (threadpool) writes can publish onto it.
_loop: asyncio.AbstractEventLoop | None = None

# SSE frames. An index_updated event carries an empty JSON object (the client re-fetches
# /api/index — the payload is just a "something changed" signal). A comment line is a keepalive.
_EVENT_FRAME = "event: index_updated\ndata: {}\n\n"
_KEEPALIVE_FRAME = ": keepalive\n\n"
_KEEPALIVE_SECONDS = 30


def bind_loop(loop: asyncio.AbstractEventLoop) -> None:
    """Capture the running event loop at app startup (see module docstring, thread-safety)."""
    global _loop
    _loop = loop


def _publish() -> None:
    """Push an index_updated notice onto every subscriber queue (runs on the loop thread)."""
    for queue in list(_subscribers):
        queue.put_nowait({"type": "index_updated"})


def emit_index_updated() -> None:
    """Notify every open SSE connection that the index changed.

    Safe to call from a sync endpoint (FastAPI runs those in a threadpool): it schedules the
    fan-out on the event loop thread. No-op when no loop is bound (e.g. some unit tests) so a
    write is never coupled to the bus being live."""
    loop = _loop
    if loop is None:
        return
    loop.call_soon_threadsafe(_publish)


async def event_stream() -> AsyncGenerator[str, None]:
    """SSE generator: one queue per connection, an index_updated frame per event, and a
    keepalive comment every 30s so proxies (Caddy/Cloudflare) don't cut an idle stream.

    Emits one frame on connect so a freshly-loaded client syncs immediately, then blocks on its
    queue. Always deregisters on disconnect (the ``finally``)."""
    queue: asyncio.Queue = asyncio.Queue()
    _subscribers.add(queue)
    try:
        yield _EVENT_FRAME  # sync once on connect
        while True:
            try:
                await asyncio.wait_for(queue.get(), timeout=_KEEPALIVE_SECONDS)
                yield _EVENT_FRAME
            except asyncio.TimeoutError:
                yield _KEEPALIVE_FRAME
    finally:
        _subscribers.discard(queue)
