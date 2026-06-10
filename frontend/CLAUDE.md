# CLAUDE.md — frontend/ (Phase 6 interactive UI)

React + TS + Vite + Tailwind SPA (job_radar_SPEC §10.7). Replaces the retired Phase 5
static `ui/`. Stack ported from cv-tailor's `frontend/` (`UnlockProvider`, `lib/api`,
`vite.config`, `nginx.conf`, Dockerfiles, shadcn-style `components/ui/`).

## Conventions

- **Read through `GET /api/index`, write through the task endpoints.** The browser never
  fetches a static file — it calls the API, which serves `index.json` with the **live
  activity-log overlay** (so a write shows on the next `useIndex` refetch without a
  re-score). All writes go through `lib/api.ts` (`setStatus`/`addNote`/`setTitle`/
  `flagAnnotation`), which the FastAPI layer validates + appends. Never write a JSONL file
  from here; never call a CLI/scorer.
- **`credentials: "include"` on every fetch.** The owner capability cookie (`jr_write`,
  HttpOnly) is same-origin via the dev proxy / prod nginx; the browser sends it
  automatically. The raw key is never stored in React state, localStorage, or a readable
  cookie — `UnlockProvider` exchanges it for the cookie and drops it.
- **Write controls gate on `useUnlock()`.** They render only when `write_configured`
  (hidden entirely otherwise — no dead buttons, SPEC §10.5 table). The first write calls
  `requestUnlock()`, which resolves `true` once unlocked (opening the dialog if locked) or
  `false` on cancel. Archive confirms; the other status moves are one-click (§10.6).
- **Visual design ported from Phase 5.** The badge/pill/grid/drawer/pipeline classes in
  `src/index.css` are copied from the old `ui/style.css`; `FIT_LABELS`/`STATUS_ORDER`/
  `LABEL_TEXT` in `src/lib/jobs.ts` mirror `models/record.py` enums. `blocked_fit` recedes
  by design (muted + struck-through) — don't restyle it to parity.
- **No JS test toolchain.** Backend is covered by pytest (`tests/test_api*.py`); the
  frontend is verified by headless-browser screenshots (Phase 5 precedent). Keep it that
  way unless a real need for component tests appears.

## Structure

- `src/lib/api.ts` — typed client + `ApiError`; `Job`/`IndexResponse`/`Capabilities` types.
- `src/lib/jobs.ts` — orderings, filter/sort, date/list helpers (ported from `app.js`).
- `src/hooks/useIndex.ts` — fetch + `refetch()` (called after every write).
- `src/components/UnlockProvider.tsx` — shared unlock state + modal dialog.
- `src/components/{StatBar,Sidebar,BrowseView,PipelineView,DetailPanel}.tsx` + `ui/`.
- `src/App.tsx` — Browse/Pipeline hash tabs, owner indicator, drawer wiring.

## Run

`docker compose --profile ui up` → frontend on `:8080` (Vite dev server, proxies `/api` →
`api:8000`), API on `:8000`. `Dockerfile.dev` = vite dev; `Dockerfile.prod` = node build →
nginx serve (for the deferred §10.9 deployment). `node_modules`/`dist` gitignored.
