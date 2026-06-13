# CLAUDE.md — api/ (Phase 6 interactive backend)

Thin FastAPI layer that mediates browser writes (job_radar_SPEC §10). It is **one more
write path over the same JSONL the CLI appends to** — never a second source of truth.

## Hard invariants

- **THIN layer.** Import `cli.track` (`build_event`, `append_event`, `load_events`,
  `project`, `load_scores`, `transition_warning`, `_clock`, `_default_state`) and
  `models.record` vocab/validators. **NEVER** call the scorer, labeller, or any pipeline
  stage. A write = `require_unlocked` → `build_event`/`validate_*` → `append_event` → 200.
  **The one exception:** `POST /api/manual-ingest` (`routers/manual_ingest.py`, SPEC §11.1,
  deviation 44) DOES run the live pipeline — single-JD synchronous extract (`pipeline.label.
  extract_one`, Haiku 4.5) → `soft_validate` → `score` → append corpus files → rebuild
  `index.json`. It is the documented thick endpoint; do not copy its shape to the other (thin)
  write routes. **Soft validation (deviation 47):** it uses `models.record.soft_validate` (same
  checks as `validate`, but advisory) and stores the role regardless of enum violations — a
  deliberate owner add is not subject to the closed-vocabulary gate. Findings ride back as
  `warnings` in the 200 body (empty list when clean); it also **never runs the prefilter**.
  **Observability (deviation 46):** because manual ingest is its own synchronous path (not the
  batch CLIs), it emits its own `manual_ingest` Langfuse trace via `cli.telemetry.
  record_manual_ingest` — opt-in (`LANGFUSE_PUBLIC_KEY`), best-effort, fired AFTER the corpus is
  persisted so a tracing failure can never fail an ingest. This is the only place the thin API
  touches `cli.telemetry`/`cli.score.build_scoring_rows`; it rides on the existing thick exception.
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
- **Write endpoints** (all gated): `POST /api/status|note|title|outcome` (workflow.py,
  append to `activity_log.jsonl`) + `POST /api/annotations` (annotations.py →
  `annotations.jsonl`) + `POST /api/manual-ingest` (manual_ingest.py — the one thick endpoint,
  writes `*_manual_{ts}.jsonl` + rebuilds the index, deviation 44). `outcome` validates against
  `OUTCOME`; the UI pairs it with a `/api/status` call to move the workflow lane (the two are
  orthogonal under model C).

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

There are currently no PUT or PATCH endpoints in this API. The data model
is append-only — writes always append new records, never mutate existing
ones. If a PUT or PATCH is ever proposed, push back: can it be modelled
as an append event instead?

## Read-only report downloads

`GET /api/report/yield` (reports.py) returns the company yield report
(BACKLOG_YIELD_TRACKING) as a `text/plain` attachment. **No auth** (read-only, like
`/api/index`). It imports and calls the *same* `cli.analyse` pure functions the CLI uses
(`build_yield_report` + `format_yield`) — never a reimplementation — over the
settings-resolved corpus paths. New settings: `seeds_path` (`JR_SEEDS_PATH`) + `stats_path`
(`JR_STATS_PATH`), defaulted to the CLI constants.

## Live overlay (the one non-obvious read)

`GET /api/index` serves the pre-built `corpus/index.json` (the heavy scoring+extraction
join from `cli.stats --export-index`) **and re-projects the live activity log over it**
(`load_events` → `project`, cheap), patching `application_status`/`outcome`/
`application_date`/`notes`/`title` per `job_id`. A write therefore shows on reload without
a re-score/re-export. Annotations do **not** affect the read model.

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
