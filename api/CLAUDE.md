# CLAUDE.md — api/ (Phase 6 interactive backend)

Thin FastAPI layer that mediates browser writes (job_radar_SPEC §10). It writes interactive
state to **SQLite** (`corpus/job_radar.db`) via `cli.db`, sharing the same event model and
validators as the CLI — never a second source of truth.

> **Phase 6.5 — SQLite is the interactive-state store (SPEC_DB_MIGRATION, ✅ complete).**
> Interactive state (`activity_log` / `annotations` / `cv_tailor_links`) lives in
> `corpus/job_radar.db`. As of **Step 6 (2026-06-19)** every write endpoint INSERTs into
> SQLite **only**, via the thin `cli/db.py` helpers (`write_activity_event` /
> `write_annotation` / `write_cv_tailor_link`) — the JSONL dual-write was removed after a
> clean 5-day production soak; the `*.jsonl` state files are frozen read-only audit archives
> (never deleted). The annotations **409 dedup comes from the SQLite UNIQUE index**
> (IntegrityError), not a JSONL scan. `cli.db` is the single home for the JSONL↔SQL row
> mapping; it is the one new import the routers take beyond `cli.track`/`models.record`.
> Reads come from SQLite via the auto-detecting loaders. Pipeline artefacts (scored/validated/
> meta/stats) stay JSONL forever. When you add a new interactive-state write endpoint, INSERT
> via the `cli.db.write_*` helpers (SQLite only) — do not re-introduce a JSONL append.

## Hard invariants

- **THIN layer.** Import `cli.track` (`build_event`, `load_events`, `load_activity_events`,
  `project`, `load_scores`, `transition_warning`, `_clock`, `_default_state`), the
  `cli.db.write_*` helpers, and `models.record` vocab/validators. **NEVER** call the scorer,
  labeller, or any pipeline stage. A write = `require_unlocked` → `build_event`/`validate_*` →
  `cli.db.write_*` (SQLite INSERT) → 200. (Step 6: JSONL appends removed — SQLite only.)
  **The one exception:** `POST /api/manual-ingest` (`routers/manual_ingest.py`, SPEC §11.1,
  deviation 44) DOES run the live pipeline — single-JD synchronous extract (`pipeline.label.
  extract_one`, Haiku 4.5) → `soft_validate` → `score` → append corpus files → rebuild
  `index.json`. It is the documented thick endpoint; do not copy its shape to the other (thin)
  write routes. **Soft validation (deviation 47):** it uses `models.record.soft_validate`, which
  runs the same checks as `validate` but returns `(hard_errors, warnings)`. Enum vocabulary gaps
  (off-vocabulary but right-type values) are advisory `warnings` — the role is stored regardless
  (a deliberate owner add is not subject to the closed-vocabulary gate) and they ride back in the
  200 body (empty list when clean). Structural type errors (wrong type / missing field) are
  `hard_errors` → **422** (they'd corrupt downstream stages). It also **never runs the
  prefilter** (pinned by tests — deviation 47).
  **Observability (deviation 46):** because manual ingest is its own synchronous path (not the
  batch CLIs), it emits its own `manual_ingest` Langfuse trace via `cli.telemetry.
  record_manual_ingest` — opt-in (`LANGFUSE_PUBLIC_KEY`), best-effort, fired AFTER the corpus is
  persisted so a tracing failure can never fail an ingest. It rides on the existing thick exception.
  **Phase C (deviation 50)** adds a second telemetry touch-point in the thin layer:
  `POST /api/cv-tailor-results` (cv_tailor.py) calls `cli.telemetry.on_cv_tailor_result` after
  persist to enrich the role's `role_scoring_decision` trace (same deterministic `job_id` seed)
  with cv-tailor's scores + the divergence delta — opt-in, best-effort, never fails the callback.
  These two are the only places the thin API touches `cli.telemetry`.
- **The scorer is LOCKED.** The API reads scores (`load_scores`), it never writes a scored
  file. Annotations record disagreement with a score — they never mutate an extraction.
- **Reuse, don't duplicate** write/validation logic. `build_event` runs
  `validate_activity_event`; annotations run `validate_annotation_event`. The CLI
  (`python -m cli.track`) stays a fully valid, equivalent write path over the same files.
- **Fail-closed security, gated per-route.** Every write endpoint carries
  `dependencies=[Depends(require_unlocked)]` **on the route** (not at the router level — see
  "Endpoint security" below, deviation 42). No `JR_WRITE_KEY` → all writes 403. The backend
  enforces — UI hiding is convenience only. Capability cookie `jr_write` is stdlib-HMAC signed
  (NOT `itsdangerous`), HttpOnly, SameSite=lax, Secure via `COOKIE_SECURE`, path `/api`.
  Copied/adapted from cv-tailor `api/security.py`.
- **404, not --force.** Unknown `job_id` → 404 on every write (the CLI's `--force` escape
  hatch is intentionally not exposed over HTTP).
- **Write endpoints** (all gated): `POST /api/status|note|title|outcome` (workflow.py →
  SQLite `activity_log`) + `POST /api/annotations` (annotations.py → SQLite `annotations`) +
  `POST /api/cv-tailor-results` (cv_tailor.py → SQLite `cv_tailor_links`) + `POST
  /api/manual-ingest` (manual_ingest.py — the one thick endpoint, writes `*_manual_{ts}.jsonl`
  *pipeline artefacts* + an `activity_log` SQLite note + rebuilds the index, deviation 44).
  Step 6: interactive-state writes are SQLite-only; the matching `*.jsonl` files are frozen
  audit archives. `outcome` validates against `OUTCOME`; the UI pairs it with a `/api/status`
  call to move the workflow lane (the two are orthogonal under model C).
- **SSE live-update bus (deviation 48).** `GET /api/events` (events.py — **public**,
  `text/event-stream`, no auth) emits an `index_updated` frame after every write so the UI
  re-fetches `/api/index` instead of going stale. The bus is `api/events.py` (in-process set of
  per-connection `asyncio.Queue`s — NO Redis). After a successful write, call
  `emit_index_updated()` (it's safe from a sync/threadpool endpoint — hops onto the startup-bound
  loop via `call_soon_threadsafe`, no-op if no loop/subscribers). Emitted by **every** write that
  changes the read model: status / note / title / outcome / fit-override / annotations /
  cv-tailor-results / manual-ingest. When you add a new write endpoint, decide whether it changes
  the read model; if so, `emit_index_updated()` after the append.

## Endpoint security — per-route gating rule

Every write endpoint (POST / future PUT / future PATCH) that modifies a
corpus file or could kick off a pipeline stage MUST have
`dependencies=[Depends(require_unlocked)]` declared on the route itself,
not at the router level.

Read endpoints (GET) that are intentionally public must have NO dependency.
This makes the security decision visible at the point of definition.

When adding a new endpoint, always ask: should this be public or
owner-only? If the spec does not explicitly state "public", the endpoint
is owner-only by default. If the spec says "public", add a comment:
`# public — no auth required (see SPEC §X.X)`

The data model is append-only for the three **event** sinks (activity_log /
annotations / cv_tailor_links) — writes append, never mutate. There is **one**
PATCH endpoint: `PATCH /api/companies/{name}` (`routers/companies.py`, deviation
55). It is the deliberate exception, not a precedent: the `company_seeds` table
is mutable *reference data* (fit_hypothesis/action/notes change as evidence
accumulates), not an event log, so UPDATE-in-place is correct there. For
anything that is an event/observation, still push back on PUT/PATCH: can it be
modelled as an append instead? The PATCH carries `Depends(require_unlocked)`
per-route like every other write. In `routers/companies.py`, `GET /api/companies`
(list) is the lone public read; **everything else is owner-gated**, including
`GET /api/companies/export` (it downloads the whole universe).

## Read-only report downloads

`GET /api/report/yield` (reports.py) returns the company yield report
(BACKLOG_YIELD_TRACKING) as a `text/plain` attachment. **No auth** (read-only, like
`/api/index`). It imports and calls the *same* `cli.analyse` pure functions the CLI uses
(`build_yield_report` + `format_yield`) — never a reimplementation — over the
settings-resolved corpus paths. New settings: `seeds_path` (`JR_SEEDS_PATH`) + `stats_path`
(`JR_STATS_PATH`), defaulted to the CLI constants.

## Live overlay (the one non-obvious read)

`GET /api/index` serves the pre-built `corpus/index.json` (the heavy scoring+extraction
join from `cli.stats --export-index`) **and re-projects the live interactive state over it**
(`load_activity_events` → `project`, cheap), patching `application_status`/`outcome`/
`application_date`/`notes`/`title` + annotations + cv-tailor per `job_id`. A write therefore
shows on reload without a re-score/re-export.

> **Phase 6.5 read source (Step 5).** The overlay reads interactive state via the
> *auto-detecting* loaders (`cli.track.load_activity_events`,
> `cli.stats.load_{annotations,cv_tailor_links}_auto`): SQLite when the DB exists, else
> JSONL. So once the DB is backfilled, the overlay reads SQLite; on a fresh host it
> still serves correct JSONL state. The bare `load_*` stay pure JSONL (the `--source
> both` comparison baseline) — use the `_auto` variants in API read paths.

## Paths

All corpus paths resolve through `api/settings.py` (`get_settings` FastAPI dependency),
defaulting to the `cli.track`/`cli.stats` constants. Tests override `get_settings` via
`app.dependency_overrides` to point at `tmp_path` — nothing in a test touches the real
corpus. New Phase-6 sink: `corpus/annotations.jsonl` (gitignored, append-only).

## Env

- `JR_WRITE_KEY` — owner unlock secret + HMAC signing key. Unset = read-only deployment.
- `COOKIE_SECURE` — `true` in prod (HTTPS leg); off for localhost http.
- `JR_LOG_PATH` / `JR_SCORED_GLOB` / `JR_VALIDATED_GLOB` / `JR_META_GLOB` / `JR_INDEX_PATH`
  / `JR_ANNOTATIONS_PATH` / `JR_STATS_PATH` / `JR_PROFILE_PATH` — path overrides (defaults = CLI
  constants; `JR_PROFILE_PATH` defaults to `candidate_profile.yaml`, used by manual-ingest scoring).

## Run

`docker compose --profile ui up` → API on `:8000` (OpenAPI docs at `/docs`). The `api`
service reuses the `job-radar` image (already installs fastapi/uvicorn) — no separate
Dockerfile. Tests: FastAPI `TestClient` in `tests/test_api.py` + `tests/test_annotation_vocab.py`.
