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

if os.getenv("JR_TRACE_TESTS") != "1":
    os.environ.pop("LANGFUSE_PUBLIC_KEY", None)
    os.environ.pop("LANGFUSE_SECRET_KEY", None)
