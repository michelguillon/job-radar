# CLAUDE.md — api/ (Phase 6 interactive backend)

Thin FastAPI layer that mediates browser writes (job_radar_SPEC §10). It is **one more
write path over the same JSONL the CLI appends to** — never a second source of truth.

## Hard invariants

- **THIN layer.** Import `cli.track` (`build_event`, `append_event`, `load_events`,
  `project`, `load_scores`, `transition_warning`, `_clock`, `_default_state`) and
  `models.record` vocab/validators. **NEVER** call the scorer, labeller, or any pipeline
  stage. A write = `require_unlocked` → `build_event`/`validate_*` → `append_event` → 200.
- **The scorer is LOCKED.** The API reads scores (`load_scores`), it never writes a scored
  file. Annotations record disagreement with a score — they never mutate an extraction.
- **Reuse, don't duplicate** write/validation logic. `build_event` runs
  `validate_activity_event`; annotations run `validate_annotation_event`. The CLI
  (`python -m cli.track`) stays a fully valid, equivalent write path over the same files.
- **Fail-closed security.** Every write router carries
  `dependencies=[Depends(require_unlocked)]`. No `JR_WRITE_KEY` → all writes 403. The
  backend enforces — UI hiding is convenience only. Capability cookie `jr_write` is
  stdlib-HMAC signed (NOT `itsdangerous`), HttpOnly, SameSite=lax, Secure via
  `COOKIE_SECURE`, path `/api`. Copied/adapted from cv-tailor `api/security.py`.
- **404, not --force.** Unknown `job_id` → 404 on every write (the CLI's `--force` escape
  hatch is intentionally not exposed over HTTP).
- **Write endpoints** (all gated): `POST /api/status|note|title|outcome` (workflow.py,
  append to `activity_log.jsonl`) + `POST /api/annotations` (annotations.py →
  `annotations.jsonl`). `outcome` validates against `OUTCOME`; the UI pairs it with a
  `/api/status` call to move the workflow lane (the two are orthogonal under model C).

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
  / `JR_ANNOTATIONS_PATH` — path overrides (defaults = CLI constants).

## Run

`docker compose --profile ui up` → API on `:8000` (OpenAPI docs at `/docs`). The `api`
service reuses the `job-radar` image (already installs fastapi/uvicorn) — no separate
Dockerfile. Tests: FastAPI `TestClient` in `tests/test_api.py` + `tests/test_annotation_vocab.py`.
