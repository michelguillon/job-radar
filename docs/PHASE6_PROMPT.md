# Phase 6 — Interactive UI (kickoff)

Build Phase 6 as specified. Read **`docs/job_radar_SPEC.md` §10** and
**`docs/job_radar_PHASE6_PLAN.md`** in full before writing any code, plus
`CLAUDE.md` (build conventions) and the nested `cli/`, `scoring/` CLAUDE.md.

Reference implementation to copy/adapt (sibling repo): **cv-tailor** at
`../cv-tailor` — `api/security.py`, `api/main.py`, `api/routers/full_mode.py`,
and `frontend/` (`src/components/UnlockProvider.tsx`, `src/lib/api.ts`,
`vite.config.ts`, `nginx.conf`, `Dockerfile.dev/prod`, Tailwind config).

## Hard rules
- The FastAPI layer is THIN: import `cli.track` (`build_event`, `append_event`,
  `load_events`, `project`, `load_scores`, `transition_warning`, `_title_for`)
  and `models.record` vocab/validators. NEVER call the scorer, labeller, or any
  pipeline stage. Every write = validate → append → 200.
- Reuse, don't duplicate, all write/validation logic. The CLI stays a valid
  write path; the scorer is LOCKED.
- Security: copy cv-tailor's **stdlib-HMAC** capability cookie (NOT itsdangerous).
  Cookie `jr_write`, HttpOnly, SameSite=lax, Secure via `COOKIE_SECURE`, key env
  `JR_WRITE_KEY`. Gate every write with `require_unlocked`. Fail-closed (no key →
  all writes 403).
- `GET /api/index` serves `corpus/index.json` but re-projects the live activity
  log over it (status/outcome/application_date/notes/title) so writes show on
  reload without a re-score.
- No database. JSONL all the way down. `models.record.SCHEMA_VERSION` unchanged
  (`ANNOTATION_TYPE` is constants-only).
- Docs are part of every commit (SPEC §10/§2, CLAUDE.md, LEARNINGS 29) — not later.

## Milestone 1 — backend (do this first, then STOP for verification)
Plan steps 1.1–1.11: `ANNOTATION_TYPE` + `validate_annotation_event` in
`models/record.py`; requirements (`fastapi`, `uvicorn[standard]`, `httpx`);
`api/security.py`; `api/settings.py`; `api/main.py`; routers
index/auth/workflow/annotations; FastAPI `TestClient` tests for every endpoint
incl. 403-without-cookie and the live overlay; add the `api` compose service.

Verify the M1 checkpoint (`curl` health; write without cookie → 403; with
`JR_WRITE_KEY`: unlock → write → `python -m cli.track list` reflects it;
`annotations.jsonl` written; `pytest` green), report results, and **WAIT** before
starting M2.

## Milestone 2 — frontend
Plan steps 2.1–2.5: scaffold `frontend/` (React + TS + Vite + Tailwind +
shadcn-style `ui/`), port the Phase 5 browse/pipeline/detail logic to React, add
owner-only write controls + flag-issue form (spec §10.6), `UnlockProvider`,
Dockerfiles + nginx, replace the `ui` compose service with `frontend`, delete the
old `ui/` static files.

## Definition of Done
SPEC §10.8 list (frontend `:8080` + API `:8000`; public read-only; owner unlock →
write controls; UI status write lands in `activity_log.jsonl` verified by
`python -m cli.track list`; annotation lands in `annotations.jsonl`; `curl` write
without cookie → 403; all tests pass) + headless-browser screenshots of
browse / pipeline / detail / unlock.

Deployment (§10.9) is a separate follow-up — do not attempt it here.
