"""Root conftest — presence puts the repo root on sys.path so tests can do
`from models.record import ...` regardless of pytest's import mode.

**Tracing off for the whole suite.** `docker-compose.yml` loads `.env` (which in a
deployed/instrumented checkout carries the real `LANGFUSE_PUBLIC_KEY`) into the container,
so without this the suite would run *traced* — exporting mock-data spans to the production
Langfuse server and coupling tests to its reachability. Langfuse instrumentation is opt-in
by `LANGFUSE_PUBLIC_KEY` (`cli/telemetry.is_enabled`), so unsetting it once here makes every
`telemetry.*` call a clean no-op for the run — the instrumentation spec's "tests run with no
key" contract (SPEC_LANGFUSE_INSTRUMENTATION §4/§7).

Escape hatch: set `JR_TRACE_TESTS=1` to KEEP the key and run the suite *traced* — used to
validate the enabled instrumentation path end-to-end against a real Langfuse server.
"""

import os

import pytest

if os.getenv("JR_TRACE_TESTS") != "1":
    os.environ.pop("LANGFUSE_PUBLIC_KEY", None)
    os.environ.pop("LANGFUSE_SECRET_KEY", None)


@pytest.fixture(autouse=True)
def _isolate_db(tmp_path, monkeypatch):
    """Point JR_DB_PATH at a per-test tmp SQLite DB (Phase 6.5).

    Dual-write API endpoints (and any code calling ``cli.db.get_db``) resolve the DB from
    ``JR_DB_PATH``, which is NOT covered by the API tests' ``Settings`` override (that only
    redirects the JSONL paths). Without this, a test write would hit the real
    ``corpus/job_radar.db`` and could 409/contaminate across runs. Tests that manage their
    own DB path (test_db*, test_dual_read) call ``monkeypatch.setenv`` again, which runs
    after this autouse fixture and wins.
    """
    monkeypatch.setenv("JR_DB_PATH", str(tmp_path / "job_radar.db"))
