# Learning Notes — Langfuse Observability

The companion file to `SPEC_LANGFUSE_DEPLOYMENT.md` and
`SPEC_LANGFUSE_INSTRUMENTATION.md`. The specs capture *what* the system
does and *how* it is built. This file captures *why* — the intuition
behind each architectural decision, the deployment discoveries, and the
findings that emerge once the stack meets a real server.

Entries are append-only and ordered chronologically. Each entry is short
and stands on its own.

```
## N. Short decision title

**Context.** What problem was being solved or what was being learned.

**What we found / decided.** The substance of the learning.

**What it teaches.** The generalisable lesson — one or two sentences.

**Interview angle.** How to use this in a hiring conversation.
```

---

## 1. ClickHouse is columnar analytics — the same family as Vertica

**Context.**
Langfuse v3 uses two databases: PostgreSQL for metadata (users, projects,
API keys) and ClickHouse for trace data (every LLM call, span, score,
token count). The split raised the question: why not just use PostgreSQL
for everything?

**What we found.**
ClickHouse is a columnar analytical database — the same architectural
family as Vertica, which was used in a previous enterprise context for BI
and reporting workloads. The trade-off is deliberate: PostgreSQL is built
for transactional workloads (fetch one row, update a record), ClickHouse
is built for analytical workloads (scan millions of rows, aggregate fast).
Trace data is append-only, never updated, and queried analytically —
exactly the workload ClickHouse is designed for. Using PostgreSQL for
traces would make the UI slow at any meaningful volume.

The same pattern appears at enterprise scale in data warehousing: one
system for OLTP (transactions), a separate system for OLAP (analytics).
Langfuse applies the same architecture at hobby scale.

**What it teaches.**
Picking the right database for the workload isn't an enterprise concern —
it applies at every scale. The decision to split PostgreSQL (metadata) and
ClickHouse (traces) in Langfuse is the same architectural decision as
splitting an OLTP database from a data warehouse in an enterprise system.
The vocabulary transfers: columnar storage, append-only writes, analytical
queries.

**Interview angle.**
"I've worked with columnar databases at enterprise scale with Vertica. When
I set up self-hosted Langfuse for my observability stack, I recognised the
same OLTP/OLAP split — PostgreSQL for transactional metadata, ClickHouse
for the append-only trace analytics store. The architecture was familiar;
the scale was just different."

---

## 2. Specs written against old versions will lie to you — always verify against live docs

**Context.**
The deployment spec was written before actual deployment. When the stack
was brought up, `langfuse-web` and `langfuse-worker` crash-looped repeatedly
with a sequence of different errors before stabilising.

**What we found.**
The spec was written against a Langfuse v2-era compose example. By the time
of deployment, Langfuse v3 had changed several env var names and added new
required vars. The errors surfaced one at a time in this order:

1. `CLICKHOUSE_MIGRATION_URL is not configured` — missing entirely from spec
2. `CLICKHOUSE_USER is not set` — ClickHouse now requires explicit credentials on both the container and the clients
3. `There is no Zookeeper configuration` — v3 defaults to cluster mode; single-server deployments need `CLICKHOUSE_CLUSTER_ENABLED: "false"`
4. `LANGFUSE_S3_EVENT_UPLOAD_BUCKET` invalid — S3 var names changed from `LANGFUSE_S3_*` to `LANGFUSE_S3_EVENT_UPLOAD_*`
5. `CLICKHOUSE_MIGRATION_URL` protocol wrong — spec used `http://` on port 8123; v3 requires `clickhouse://` on port 9000

Each fix was verified against the live Langfuse v3 docs rather than guessing.
The final working compose file differed substantially from the original spec.

**What it teaches.**
A spec written without a live deployment is a hypothesis, not a reference.
Open source projects move fast — env var names, required fields, and default
behaviours change between major versions. The right response to a
crash-looping container is to read the error message carefully, check the
current official docs, and fix one thing at a time. Guessing wastes time.

**Interview angle.**
"When I deployed Langfuse v3, the spec I'd written was based on v2 examples
and broke in five different ways on first boot. I worked through each error
systematically against the live docs — missing env vars, credential changes,
protocol differences — and updated the spec to reflect what actually works.
That's the difference between a spec as a plan and a spec as a record of truth."

---

## 3. Cloudflare Tunnel + Caddy requires `http://` prefix on all Caddyfile blocks

**Context.**
After the stack came up cleanly, the Langfuse UI was unreachable —
`ERR_TOO_MANY_REDIRECTS`. All other apps on the same server were working fine.

**What we found.**
The architecture uses Cloudflare Tunnel for TLS termination. Cloudflare
handles HTTPS from the browser, then forwards plain HTTP into the server.
Caddy receives plain HTTP and reverse-proxies to the app container.

All working app blocks in the Caddyfile use an explicit `http://` prefix,
which tells Caddy: "this is HTTP-only, don't issue a cert, don't redirect."
The Langfuse block was added without that prefix, so Caddy tried to handle
HTTPS itself — issuing its own cert and adding an HTTP→HTTPS redirect.
Cloudflare was also redirecting. The result was an infinite redirect loop.

Fix: add `http://` prefix to the Caddyfile block. `NEXTAUTH_URL` in the
compose file correctly stays as `https://` — that's the public-facing URL
the browser sees, which is genuinely HTTPS thanks to Cloudflare.

**What it teaches.**
When TLS is terminated upstream (by a CDN or tunnel), the internal stack
must be consistently HTTP-only. Mixing TLS responsibilities between Cloudflare
and Caddy causes redirect loops. The `http://` prefix in Caddy is not a
security downgrade — it's an accurate description of what the internal
network is doing.

**Interview angle.**
"My home server stack uses Cloudflare Tunnel for TLS termination with Caddy
as an internal reverse proxy. When I added Langfuse, I hit an infinite
redirect loop because Caddy tried to handle HTTPS itself. The fix was
understanding where TLS responsibility lives in the stack — Cloudflare owns
it externally, Caddy just proxies internally. Getting that boundary wrong
breaks everything."

---

## 4. MinIO pre-initialisation via `mc` client is unnecessary in v3

**Context.**
The original spec included a first-run step to create the MinIO bucket
manually using the `mc` (MinIO client) CLI before starting the full stack.

**What we found.**
The `mc` client is not included in the MinIO server image — the command
would have failed immediately. More importantly, Langfuse v3 auto-creates
the required bucket on first write. No pre-initialisation step is needed.
The spec step was removed entirely.

**What it teaches.**
Pre-init steps in specs should be verified against the actual image contents.
Many modern tools handle their own bootstrapping — adding manual setup steps
for things that auto-configure adds complexity and failure points.

**Interview angle.**
"Part of good deployment documentation is distinguishing between setup steps
that are genuinely required versus ones inherited from older examples. In
this case, the MinIO bucket init step would have failed silently and wasted
time debugging the wrong thing."

---

## 5. Five stacked silent failures — and the debug toolkit that collapses them

**Context.**
After the stack was deployed and cv-tailor was instrumented, traces didn't
appear in the Langfuse UI. No errors in the backend logs. No export errors
in the Langfuse web logs. Each failure looked identical from the outside:
"no traces."

**What we found.**
Five separate causes, four config/infrastructure and one code bug, stacked
on top of each other. In order:

1. **S3/MinIO bucket never created.** The ingest API returned 200 but the
   server logged `Failed to upload JSON to S3 — NoSuchBucket`. Lesson: a
   "healthy" check must persist a span end-to-end, not just probe API
   liveness. Fix: `mc mb local/langfuse` inside the MinIO container.

2. **Backend used the public URL it couldn't reach from inside Docker.**
   The Cloudflare Tunnel architecture means containers can't hairpin to
   `https://langfuse.michel-portfolio.co.uk` — the request leaves the
   server, hits Cloudflare, and times out. Fix: `LANGFUSE_BASE_URL=http://
   langfuse-langfuse-web-1:3000` using the internal container name over
   the shared `tracing` Docker network.

3. **`auth_check()` in the FastAPI lifespan hung startup.** A synchronous,
   no-timeout HTTP call to Langfuse during app startup blocked uvicorn from
   binding port 8000. The backend refused all connections with
   `ConnectionRefusedError [111]`. Fix: `init_langfuse()` only constructs
   the client (fast, no network); `auth_check()` moved to the debug
   endpoint (request-time).

4. **Shared API key pair across projects.** cv-tailor and Job Radar
   temporarily shared the same `pk-lf/sk-lf` pair. `auth_check` returned
   `true` (keys are valid) but traces landed in the wrong project's
   dashboard. Fix: each app uses its own project's keys.

5. **Unflushed root span (the one real code bug).** After 1–4 were fixed,
   the debug endpoint worked but real runs still didn't. `attach_scores()`
   (which calls `flush()`) ran *inside* the `with run_trace` block —
   flushing while the root span was still open. The run thread exited before
   the periodic exporter fired. The debug endpoint never hit this because it
   flushes *after* its span closes. Fix: `run_trace` flushes in a `finally`
   after the root span closes.

**What it teaches.**
Silent observability failures are the hardest kind — each one looks the same
from the outside. The right response is a zero-cost debug tool that exercises
the full path and returns a verdict as data, not logs. Build it first, not
after you've wasted hours.

App-logger INFO is invisible under uvicorn — `tailor.*` logs propagate to
the root last-resort handler (WARNING+ only). `grep langfuse` on docker logs
returns empty even when tracing works. Put decisive signals in the response
body, not logs. Any always-on per-run confirmation should be WARNING level.

**Interview angle.**
"When I added Langfuse observability to cv-tailor, traces silently didn't
appear — five separate causes stacked on each other. I built a zero-cost
debug endpoint that creates a trace with no LLM call, flushes, and returns
`{enabled, auth_check, trace_id, error}`. That collapsed a multi-layer
silent failure into a 5-second triage. The lesson: build your observability
debug tool before you need it, and make it self-diagnosing."

---

## 6. Cross-compose Docker networking — the `tracing` network pattern

**Context.**
cv-tailor and Langfuse are separate Docker Compose projects. The cv-tailor
backend needed to reach the Langfuse web container directly to send traces,
without going through the public URL.

**What we found.**
Docker DNS only resolves service names within the same compose project.
Cross-project, you need a shared external network. Three options were
considered:

1. Put cv-tailor-backend on the `caddy` network — works but semantically
   wrong. The caddy network is for reverse proxy routing, not service
   communication.
2. Create a dedicated `tracing` network — explicit, purpose-named, doesn't
   conflate concerns.
3. Use the host IP — fragile, breaks if IP changes on restart.

Option 2 was chosen. The pattern:

```bash
docker network create tracing
```

In Langfuse compose: add `langfuse-web` to the `tracing` network.
In cv-tailor compose: add `cv-tailor-backend` to the `tracing` network.
Both declare `tracing` as `external: true`.

One additional fix was needed: `HOSTNAME: "0.0.0.0"` on the Langfuse web
container to force Next.js to bind on all interfaces, not just the caddy
network interface.

**What it teaches.**
When two separate Docker Compose projects need to communicate, create a
named external network with a purpose-describing name. Don't reuse existing
networks for unrelated concerns. Always verify with
`docker network inspect <network> --format '{{range .Containers}}{{.Name}} {{end}}'`
that both containers are actually on the network after deployment.

**Interview angle.**
"My observability stack is a separate Docker Compose project from the apps
it monitors. Rather than putting application containers on the reverse proxy
network, I created a dedicated `tracing` network — each service that sends
traces joins it. It's explicit about what the network is for and doesn't
conflate reverse proxy routing with service communication."

---

## 7. Span flush timing — a span isn't exported until it's ended

**Context.**
After fixing all infrastructure issues, the debug endpoint created traces
but real cv-tailor runs still didn't. Same symptom, different cause.

**What we found.**
In `api/runner.target()`, `attach_scores()` (which calls `flush()`) ran
*inside* the `with run_trace` block — flushing while the root span was still
open. A span in OTel is not exported until it is *ended*. The flush fired
before the root span closed, so the completed root span depended on the
periodic background exporter — but the daemon run-thread exited immediately
after the `with` block, before the exporter fired.

The debug endpoint never hit this because it flushes *after* its span closes.

Fix: `run_trace` flushes in a `finally` block after the root span has closed.

This maps directly to the Job Radar Batch API pattern: create the post-hoc
span → end it → `flush()`. The CLI process exits immediately after, so there
is no periodic exporter to fall back on.

**What it teaches.**
Always flush *after* the root scope closes, not inside it. This matters
especially for short-lived threads and CLI processes that exit immediately
after work completes. The periodic background exporter is not a reliable
fallback when the thread is about to die.

**Interview angle.**
"I hit a subtle OTel bug: flushing inside the root span's context manager
meant the span wasn't yet ended when the flush fired, so it never exported.
The fix was moving the flush to a `finally` block outside the root span.
Lesson: a span isn't exported until it's ended — flush after the root closes,
not before."

---

## 8. Job Radar (Phase B) — reuse the proven SDK surface, not the spec sketch

**Context.**
With cv-tailor instrumented and verified live, Job Radar was next. The
instrumentation spec's §3 carried a Job-Radar code sketch — but it used a
different langfuse API shape than the cv-tailor module that was actually
working against the same server (`lf.trace()` / `lf.score()` /
`lf.api.scores.create()` in the sketch vs `create_trace_id` /
`start_as_current_observation` / `create_score` proven in `tailor/telemetry.py`).

**What we found / decided.**
The proven module wins over the spec sketch. The sketch was written against an
earlier API reading; `tailor/telemetry.py` is what verifiably exported traces
to this exact Langfuse v4.7.1 server. Job Radar's `cli/telemetry.py` mirrors its
proven choices: deterministic trace id via `Langfuse.create_trace_id(seed=…)`,
the root span claiming it via `trace_context`, `create_score(trace_id=,
observation_id=, data_type="NUMERIC")` for per-JD scores, lazy in-function SDK
imports, and the `is_enabled()` no-op gate. Before wiring, the real SDK surface
was introspected in-container (`inspect.signature`) to confirm every method and
keyword exists in 4.7.1 — `create_score` does take `observation_id`,
`start_as_current_observation` does take `trace_context`/`as_type`/`model`/
`usage_details`. Guards make a wrong call non-fatal, but verifying first means
the happy path actually works rather than silently logging and continuing.

The one genuine Job-Radar difference from cv-tailor is structural, not API: the
**Batch API is async**, so spans are post-hoc (built from downloaded results
after the batch ends), and the CLI exits immediately with no periodic exporter —
so §7's flush-after-root-closes rule is not a nicety here, it is the only thing
that exports the trace. The two recorders (`record_extraction_batch`,
`record_scoring_run`) each build their whole tree inside one `with`, let it
close, then `flush()`. Trace rows are assembled by **pure** builders
(`build_trace_rows`, `build_scoring_rows`) that re-derive the scorer breakdown
with `stage1_fit` (read-only) — no business logic, prompt, or schema touched, and
the builders are unit-testable without the SDK.

**What it teaches.**
When a spec and a verified implementation disagree on an API, trust the artifact
that actually ran (the same tie-break rule this repo applies to its own schema).
And introspect the live SDK before relying on a method signature — a five-second
`inspect.signature` in the target image beats a guarded call that fails silently
in production.

**Interview angle.**
"Instrumenting the second app, the spec's code sketch used a different langfuse
API than the module I'd already verified live against the same server. I treated
the working code as the source of truth, introspected the installed SDK to
confirm every signature, and only then wired it in. The app-specific twist was
the Batch API: results are async, so spans are post-hoc and the CLI dies before
any background exporter runs — which makes 'flush after the root span closes' the
difference between traces existing and not."

---
