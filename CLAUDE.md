# CLAUDE.md — job-radar

## Project

**job-radar** — personal job search intelligence system.
Identifies, assesses, prioritises, and tracks job opportunities.

Formerly: jd-refinery (renamed 2026-06-09 during respec).

---

## Sources of truth

| Source | Purpose |
|---|---|
| `docs/job_radar_SPEC.md` | Architecture, implementation steps, phase scoping |
| `docs/CORPUS_FINDINGS.md` | Schema v1.2 definition, labelling rules, JD records |
| `models/record.py` | Executable schema — must stay in sync with CORPUS_FINDINGS §1.1 |

If CORPUS_FINDINGS §1.1 and `models/record.py` diverge, fix both and
bump `SCHEMA_VERSION`.

---

## Build conventions

- **Docker only** — `docker compose run --rm job-radar python ...`
- **Tests always** — pytest, placed in `tests/`. Run after every step.
- **Schema locked at v1.2** — no changes without explicit instruction
- **Batch API only** for labelling — never synchronous extraction
- **BeautifulSoup only** for scraping — no Playwright, no Selenium
- **JSONL only** — no database, no ORM, no migrations
- **Append-only records** — never migrate in place; bump schema version
- **Extraction vs annotation boundary is strict** — Claude never
  populates annotation fields; human never populates extraction fields
- **CLI writes, UI reads** — all state changes through CLI scripts only
- **Decisions & learnings** — record architecture decisions and reusable
  lessons in `docs/job_radar_LEARNINGS.md`, appended after each step/phase
  (append-only; never rewrite existing entries)

---

## Phase state

| Phase | Status |
|---|---|
| 1 — Corpus Engine | Steps 0–8 complete (90 tests). Step 9 pending. |
| 2 — Scoring Engine | Not started |
| 3 — Job Tracker | Not started |
| 4 — Discovery Layer | Not started |
| 5 — UI | Not started |
| 6 — Fine-Tuned Analyser | Deferred (Project 5) |

---

## Step state (Phase 1)

| Step | Status | Notes |
|---|---|---|
| 0 — Scaffold | ✅ complete | Docker, dirs, seeds, 10 manual records |
| 1 — JDRecord model | ✅ complete | v1.2, validate(), round-trip tests |
| 2 — Clean + dedupe | ✅ complete | clean(), record_hash(). SHA-256 backfill run in Step 3. |
| 3 — Greenhouse | ✅ complete | collectors/base.py + greenhouse.py + collect.py. Backfill done — 10 unique hashes, 0 pending. |
| 4 — Lever + Ashby | ✅ complete | lever.py + ashby.py registered. Live: Mistral 170, Perplexity 71. |
| 5 — VC boards | ✅ complete | All boards JS-rendered (requires_js) — skeleton skips all; scraping deferred to Phase 4 |
| 6 — Tier 2 tooling | ✅ complete | tier2_review.py — a/e/s loop, resumable via corpus/tier2_progress.json. Extraction is a placeholder (Step 7 replaces). |
| 7 — Batch API labelling | ✅ complete | pipeline/label.py + label.py. Live verified: 5/5 labelled, $0.055, cost→stats.json. opus-4-8, prompt from locked enums. |
| 8 — Validation + stats | ✅ complete | validate.py → corpus/validated/{validated,failures}_*.jsonl; stats.py summary + --export-index → corpus/index.json (flat, UI contract). |
| 9 — Export | ⏳ next | export.py — prompt/completion JSONL; eval/train/full sets; exclude validation failures + wrong schema_version; Tier 4 out of eval |

---

## Known deviations from spec (captured from build)

1. `SCHEMA_VERSION = "1.2"` (spec Step 1 text said 1.1 — typo, 1.2 is correct)
2. Records stored as compact single-line JSONL (not pretty-printed)
3. `.gitignore` uses `corpus/**/*` + negations (not bare `corpus/`) to
   track directory skeleton while ignoring data
4. Added: `models/__init__.py`, root `conftest.py`, `tests/factories.py`,
   `.gitattributes`, this `CLAUDE.md`
5. `docker-compose.yml` marks `env_file` as `required: false`
6. SHA-256 backfill on 10 manual records run in Step 3 (was deferred
   from Step 2 — raw_text was placeholder then)
7. Added `collectors/base.py` (shared `fetch_json` retry/backoff +
   `build_raw_record`) so Lever/Ashby are URL + field mapping only
8. Added `scripts/` package for one-off corpus maintenance
   (`backfill_manual_hashes.py`)
9. `docker-compose.yml` service renamed `jd-refinery` → `job-radar`
   (completing the rename so the documented run command works)

---

## Schema summary (v1.2)

Three layers — never mixed:

```
JDRecord          extraction    Claude populates    objective
JobPosting        product       system populates    operational (Phase 2+)
ApplicationRecord annotation    Michel populates    subjective  (Phase 2+)
```

For Phase 1, annotation fields live temporarily in `JDRecord`.
They migrate to `ApplicationRecord` in Phase 2.

---

## Pending tasks

- [x] SHA-256 backfill — done in Step 3 (10 unique hashes, 0 pending)
- [x] Verify Greenhouse slugs — Anthropic (377 jobs) and Figma (167)
      confirmed live
- [ ] Verify remaining Lever/Ashby slugs before Step 4 live runs
- [x] Inspect VC board pages — done (Step 5 gate). All JS-rendered SPAs;
      scraping deferred to Phase 4 (see Learning 10)

---

## Decisions & learnings

Architecture decisions and reusable learnings live in
`docs/job_radar_LEARNINGS.md` (Cross-Cutting Decisions + Learning Entries),
appended after each step or phase. This file stays lean — conventions and
current state, not a learning log.

---

## CLAUDE.md hierarchy

Keep this file lean. Add area-specific conventions to nested files:

- `collectors/CLAUDE.md` — API client patterns, rate limiting, error handling
- `pipeline/CLAUDE.md` — batch API patterns, cost tracking
- `scoring/CLAUDE.md` — scoring logic, profile schema (Phase 2+)
- `ui/CLAUDE.md` — UI conventions, index.json contract (Phase 5+)
