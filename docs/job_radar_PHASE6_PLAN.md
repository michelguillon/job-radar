# Phase 6 — Interactive UI: implementation plan

Companion to `docs/job_radar_SPEC.md` §10. Kickoff prompt: `docs/PHASE6_PROMPT.md`.
Build it in a fresh conversation from that prompt — this file is the detailed map.

## Context

Job Radar is v1 feature-complete through Phase 5 (a static, read-only UI over
`corpus/index.json`). Phase 5 works but creates daily friction: every status
change, note, and title fix needs a terminal (`python -m cli.track …`). Phase 6
removes that friction with an **interactive UI**: a thin FastAPI backend mediates
browser writes, and a React/TypeScript frontend replaces the vanilla-JS static
page. Writes append to the same JSONL the CLI appends to
(`corpus/activity_log.jsonl` + a new `corpus/annotations.jsonl`) — same event
model, same validation, no database. The CLI stays a fully valid write path; the
scorer/pipeline are untouched.

Reference implementation (sibling repo, proven in production): **cv-tailor** at
`../cv-tailor` — `api/security.py`, `api/main.py`, `api/routers/full_mode.py`,
and `frontend/` (`src/components/UnlockProvider.tsx`, `src/lib/api.ts`,
`vite.config.ts`, `nginx.conf`, `Dockerfile.dev/prod`, Tailwind config).

## Decisions

- **Frontend = cv-tailor's stack, verbatim where possible.** React 18 + TS + Vite
  5 + Tailwind 3 + shadcn-style `ui/` components + lucide-react, in a new
  `frontend/` dir. Reuse cv-tailor's `UnlockProvider.tsx`, `lib/api.ts` (+
  `ApiError`), `vite.config.ts` proxy, `nginx.conf`, `Dockerfile.dev/prod`.
- **Two milestones.** M1 backend (verifiable via `curl` + `cli.track list`) →
  checkpoint → M2 frontend.
- **Testing = API pytest (FastAPI `TestClient`) + browser verify.** No JS test
  toolchain (matches the repo's Python-pytest culture + Phase 5 precedent).
- **Spec contradiction resolved — stdlib HMAC, not `itsdangerous`.** §10.8 step 8
  lists `itsdangerous`, but step 2 says "copy `api/security.py` from cv-tailor,"
  and cv-tailor's proven `security.py` uses **stdlib `hmac` + `hashlib`**
  (zero-dep). Copy cv-tailor → drop `itsdangerous`. (Log as a deviation.)
- **Spec clarification — live workflow overlay on `GET /api/index`.** §13.4 keeps
  `index.json` as the read model, but workflow writes land in
  `activity_log.jsonl`, so a naive file-serve looks stale right after a write.
  The API serves `corpus/index.json` (the heavy scoring+extraction join) **and
  re-projects the current activity log over it** (`load_events` → `project`,
  cheap) so status/outcome/application_date/notes/title are always live without a
  re-score. Annotations don't affect the read model. (Log as a deviation.)
- **Reuse the existing Docker image for the API** (its `Dockerfile` already
  `pip install`s `requirements.txt` + bind-mounts source) rather than a separate
  `Dockerfile.api` as §10.4 sketches — the `api` compose service just runs
  `uvicorn`. Only the frontend gets its own Dockerfiles. (Log as a deviation.)
- **Endpoint names follow the job-radar spec** (§10.4): `/api/unlock`,
  `/api/lock`, `/api/capabilities` → `{write_configured, write_unlocked}` —
  adapted from cv-tailor's `full-mode/*`. Cookie: `jr_write`. Owner key env:
  `JR_WRITE_KEY` (+ `COOKIE_SECURE`).
- **Retire the Phase 5 static `ui/`.** The `frontend/` service replaces the `ui`
  nginx service on `:8080` / `profiles:["ui"]`. Delete `ui/{index.html,app.js,
  style.css,.gitignore}` (git history preserves them); fold conventions into a
  new `frontend/CLAUDE.md`. SPEC §9 stays as the historical Phase-5 record.

---

## Milestone 1 — FastAPI backend (verifiable headless)

Thin HTTP layer over existing, tested logic. Every write = validate → append →
200. The API imports `cli.track` + `models.record`; it never calls the scorer,
labeller, or any pipeline stage.

### 1.1 Vocab + validator — `models/record.py`
Add (constants only, **no `SCHEMA_VERSION` bump** — same pattern as `OUTCOME`):
- `ANNOTATION_LOG_VERSION = 1`
- `ANNOTATION_TYPE = frozenset({ "role_type_incorrect", "domain_incorrect",
  "seniority_incorrect", "technical_depth_incorrect", "fit_score_disagree",
  "should_be_blocked", "false_block", "extraction_other" })` (spec §10.2 table)
- `validate_annotation_event(event: dict) -> list[str]` — mirror
  `validate_activity_event` (`models/record.py:167`): require non-empty `ts`,
  `job_id`, `reason`; `annotation_type ∈ ANNOTATION_TYPE`; `field` a string;
  `observed`/`expected` present; `scorer_label`/`scorer_fit_score` str/int.

### 1.2 `requirements.txt`
Add `fastapi>=0.110`, `uvicorn[standard]>=0.30`, `httpx>=0.27` (TestClient).
**Not** `itsdangerous`.

### 1.3 `api/security.py` — copy from `cv-tailor/api/security.py`, adapt
Same stdlib HMAC-SHA256 capability-cookie pattern. Rename: key env →
`JR_WRITE_KEY`, cookie `cv_full_mode` → `jr_write`, `COOKIE_PATH="/api"`. Keep
`issue_token`, `verify_token`, `key_matches` (constant-time
`hmac.compare_digest`), `write_configured` (was `full_mode_configured`),
`cookie_secure`, `require_unlocked` (FastAPI dependency, raises 403).
Fail-closed throughout (no key → not unlockable → writes 403).

### 1.4 `api/settings.py` — path resolution (test-injectable)
Resolve corpus paths from env with defaults = `cli.track` constants (`LOG_PATH`,
`SCORED_GLOB`, `VALIDATED_GLOB`, `META_GLOB`) + `INDEX_PATH` (`cli.stats`) + new
`ANNOTATIONS_PATH = "corpus/annotations.jsonl"`. Tests point these at `tmp_path`
via env or `app.dependency_overrides`.

### 1.5 `api/main.py` — copy cv-tailor structure
`FastAPI(...)`, `CORSMiddleware` for dev (`http://localhost:8080` / `:3000`),
`include_router` for the routers below. `GET /api/health` →
`{status, records, last_indexed}`.

### 1.6 `api/routers/index.py` — public reads
- `GET /api/index` — read `corpus/index.json`, then **overlay live workflow**:
  `project(load_events(LOG_PATH))` and patch each record's
  `application_status/outcome/application_date/notes/title` by `job_id` (reuse
  `cli.track.project` + `_title_for`). Otherwise return the object unchanged.
- `GET /api/capabilities` — `{write_configured, write_unlocked}` (cv-tailor
  `full_mode.py:capabilities` shape, renamed).
- `GET /api/health`.

### 1.7 `api/routers/auth.py` — copy cv-tailor `full_mode.py`
- `POST /api/unlock` `{key}` → validate → set signed HttpOnly `jr_write` cookie.
- `POST /api/lock` → clear cookie.

### 1.8 `api/routers/workflow.py` — gated writes, reuse `cli.track`
All `dependencies=[Depends(require_unlocked)]`. Each: confirm `job_id` in
`load_scores(SCORED_GLOB)` else 404; `build_event(...)` (validates via
`validate_activity_event`); `append_event(LOG_PATH, …)`; return 200.
- `POST /api/status` `{job_id, status, notes?}` → `event="status"`,
  `value=status`, `notes`. Include `transition_warning(current,new)` (compute
  `current` from `project`) in the response (warn, never block — track precedent).
- `POST /api/note` `{job_id, text}` → `event="note", value=None, notes=text`.
- `POST /api/title` `{job_id, title}` → `event="title", value=title`.

### 1.9 `api/routers/annotations.py` — gated, new sink
`POST /api/annotations` `{job_id, annotation_type, field, observed, expected,
reason}` → gate + 404-check; capture `scorer_label`/`scorer_fit_score` from
`load_scores()[job_id]` at flag time (spec §10.4 record shape); validate via
`validate_annotation_event`; append to `corpus/annotations.jsonl` (tiny
`append_annotation`, or reuse the append idiom at `cli/track.py:287`).

### 1.10 Tests — `tests/test_api_*.py` (FastAPI `TestClient`)
Fold into the existing suite. `tmp_path` for log/scored/annotations/index; build
scored lines with `test_track.py`'s `_scored_line`, JDRecords with
`tests/factories.make_record`. Cover:
- capabilities matrix (not-configured / configured-locked / unlocked); unlock
  correct+incorrect key; fail-closed (no key → writes 403); lock.
- status/note/title append the correct event (assert via `load_events`); unknown
  `job_id` → 404; `transition_warning` surfaced.
- annotations append correct record; bad `annotation_type` → 4xx.
- **403 without cookie on every write endpoint** (backend enforces).
- `GET /api/index` shape + live overlay (write status → reload shows it without
  re-export).
- `models` tests: `ANNOTATION_TYPE`, `validate_annotation_event`.

### 1.11 Docker — `docker-compose.yml`
Add `api` service (existing `job-radar` image,
`command: uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload`, ports
`8000:8000`, `profiles:["ui"]`, `env_file .env`). Leave the Phase 5 `ui` service
for now (M2 replaces it).

### M1 checkpoint (verify before M2)
- `curl localhost:8000/api/health` ok.
- `curl -X POST .../api/status` **without** cookie → 403.
- with `JR_WRITE_KEY` set: `POST /api/unlock` → cookie; `POST /api/status`
  appends; `python -m cli.track list` shows the new state. `POST /api/annotations`
  writes `annotations.jsonl`.
- `docker compose run --rm job-radar python -m pytest -q` green (all prior + new).

---

## Milestone 2 — React/TypeScript frontend

Scaffold `frontend/` mirroring cv-tailor. Reuse its `UnlockProvider`, `lib/api.ts`
(+`ApiError`), `vite.config.ts` proxy, `nginx.conf`, `Dockerfile.dev/prod`,
Tailwind/postcss config, `components/ui/` primitives.

### 2.1 Scaffold + tooling
`frontend/package.json` (React 18, Vite 5, TS 5, Tailwind 3, lucide-react, cva,
clsx, tailwind-merge — cv-tailor's exact versions), `tsconfig.json`,
`vite.config.ts` (proxy `/api` → `http://api:8000`, `@`→`src`),
`tailwind.config.js`, `postcss.config.js`, `index.css`.

### 2.2 `src/lib/api.ts` — typed client (adapt cv-tailor)
`BASE="/api"`, `get/post` helpers, `ApiError{status}`, typed
`IndexResponse`/`Capabilities`/`Job`. Methods: `index()`, `capabilities()`,
`unlock(key)`, `lock()`, `setStatus(jobId,status,notes?)`, `addNote(jobId,text)`,
`setTitle(jobId,title)`, `flagAnnotation(payload)`. Same-origin, `credentials:
"include"` for the cookie.

### 2.3 `src/components/UnlockProvider.tsx` — copy cv-tailor
`useUnlock()` → `{caps, write_configured, write_unlocked, requestUnlock(),
lock()}`; one modal unlock dialog; raw key never retained. Write controls gate on
`if (await requestUnlock()) …`.

### 2.4 Views (port Phase 5 `ui/app.js` logic to React)
- `App.tsx` — Browse/Pipeline tabs (keep `#browse`/`#pipeline` hash routing),
  stats bar, `useIndex` hook (fetch `api.index()`), filter state.
- `BrowseView` — filterable table (port filters/sort/badges/`blocked_fit` muting
  from `ui/style.css` + `app.js`); row click → `DetailPanel`.
- `PipelineView` — cards grouped by `application_status`, priority-sorted.
- `DetailPanel` — read fields **plus owner-only write controls** (spec §10.6):
  Status quick-buttons (Review/Shortlist/Apply/Archive — Archive confirms), Notes
  save, Title override, and a "Flag scoring issue" form (`annotation_type`
  dropdown, observed prefilled, expected/reason). On success: optimistic local
  update + `useIndex` refetch.
- `UnlockDialog` (via provider), owner indicator + lock affordance.

### 2.5 Docker + compose
`frontend/Dockerfile.dev` (vite dev) + `Dockerfile.prod` (node:20 build →
nginx:alpine serve) + `nginx.conf` (SPA fallback; proxy `/api/` → `api:8000`).
In `docker-compose.yml`: **replace the `ui` service** with `frontend` (build
`./frontend/Dockerfile.dev`, ports `8080:…`, `depends_on:[api]`,
`profiles:["ui"]`). Delete `ui/{index.html,app.js,style.css,.gitignore}`.

### M2 / Phase 6 Definition of Done (spec §10.8)
1. `docker compose --profile ui up` → frontend `:8080`, API `:8000`.
2. Public visitor: read-only browse, **no write controls visible**.
3. Owner unlock: key → cookie → write controls appear.
4. `POST /api/status` from UI appends correct event to `activity_log.jsonl`,
   confirmed by `python -m cli.track list`.
5. `POST /api/annotations` from UI appends correct record to `annotations.jsonl`.
6. `curl -X POST /api/status` without cookie → 403.
7. All prior tests + new API tests pass (pipeline untouched).
8. Browser verify (headless Edge screenshots, Phase 5 precedent): browse,
   pipeline, detail write controls, unlock dialog.

---

## Docs (same commits as code — definition of done, every task)
- **SPEC** §2 phase table → Phase 6 ✅; §10 → mark built (+ the 3 deviations).
- **CLAUDE.md** Phase 6 row → ✅; add deviations (next numbers after 27); note new
  `api/` + `frontend/` areas and `JR_WRITE_KEY`/`COOKIE_SECURE` env. Hierarchy:
  add `api/CLAUDE.md` + `frontend/CLAUDE.md`.
- **LEARNINGS** → append Learning 29 (stdlib-HMAC vs spec's itsdangerous, the
  staleness/overlay design, reusing the CLI write path under HTTP).
- New `api/CLAUDE.md` (thin-layer rule: import `cli.track`/`models.record`, never
  the scorer; gate every write with `require_unlocked`; fail-closed) +
  `frontend/CLAUDE.md` (port of `ui/CLAUDE.md` conventions for React).
- **README** — update the "Browse the corpus" run section + phases.
- **`.gitignore`** — `corpus/annotations.jsonl` already covered by `*.jsonl` +
  `corpus/**/*` (confirm). Add `frontend/node_modules`, `dist/`.

## Deployment
§10.9 is an explicit TODO (M720q, Michel's established cv-tailor/RFI flow —
shared `caddy` network, `docker-compose.prod.yml` overlay). Out of scope for the
build; a follow-up after local verification.

---

## Reuse map (don't re-derive — import these)

| Need | Reuse | Path |
|---|---|---|
| Build/validate an activity event | `build_event`, `validate_activity_event` | `cli/track.py:76`, `models/record.py:167` |
| Append an event | `append_event` | `cli/track.py:287` |
| Live workflow state per job_id | `project`, `load_events` | `cli/track.py:124`, `:272` |
| job_id existence / scorer label | `load_scores` | `cli/track.py:293` |
| Display title resolution | `_title_for` | `cli/track.py:181` |
| Transition warning | `transition_warning` | `cli/track.py:92` |
| Read model + stats shape | `build_index`, `index_stats` | `cli/stats.py` |
| Vocab enums | `APPLICATION_STATUS`, `OUTCOME`, `ACTIVITY_EVENT` | `models/record.py` |
| Capability cookie (copy/adapt) | whole module | `../cv-tailor/api/security.py` |
| Unlock/capabilities router (copy) | `full_mode.py` | `../cv-tailor/api/routers/full_mode.py` |
| Frontend unlock + API client (copy) | `UnlockProvider.tsx`, `lib/api.ts` | `../cv-tailor/frontend/src/` |
| Dev proxy / prod nginx (copy) | `vite.config.ts`, `nginx.conf`, Dockerfiles | `../cv-tailor/frontend/` |
