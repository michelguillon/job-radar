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

---

## Phase state

| Phase | Status |
|---|---|
| 1 — Corpus Engine | Steps 0–3 complete (58 tests). Steps 4–9 pending. |
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
| 4 — Lever + Ashby | ⏳ next | Register in collect.COLLECTORS; reuse collectors/base.py |
| 5 — VC boards | ❌ pending | Inspect 2 boards manually before building |
| 6 — Tier 2 tooling | ❌ pending | |
| 7 — Batch API labelling | ❌ pending | |
| 8 — Validation + stats | ❌ pending | stats.py needs --export-index for Phase 5 |
| 9 — Export | ❌ pending | |

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
- [ ] Inspect 2 VC board pages, populate selectors in vc_boards.yaml
      before Step 5

---

## Learnings captured during build

*(Add new entries as the build progresses)*

### 2026-06-09 — Schema v1.1 typo in Step 1 spec text
Step 1 of the spec said `SCHEMA_VERSION = "1.1"` but CORPUS_FINDINGS
and the locked schema both said 1.2. Used 1.2. Lesson: the dataclass
in `models/record.py` is the executable source of truth — when in
doubt, check it against CORPUS_FINDINGS §1.1, not the step text.

### 2026-06-09 — Greenhouse `content` is HTML-entity-escaped
The `?content=true` field comes back entity-escaped (`&lt;p&gt;`).
BeautifulSoup would treat that as literal text, not tags, so the
collector runs `html.unescape()` before storing `raw_html`. Otherwise
`clean()` would never strip the tags.

### 2026-06-09 — Backfill reuses the dedupe pipeline for free verification
`scripts/backfill_manual_hashes.py` assigns ids by running the real
`dedupe(records, set())` rather than hashing by hand. This guarantees
the manual ids match what the live pipeline would produce, and the
`dropped == 0` check doubles as the "no two records share a hash"
verification. Lesson: assign corpus ids through the pipeline, never
by a parallel hand-rolled hash.

### 2026-06-09 — SHA-256 backfill blocked by placeholder raw_text
All 10 manual records had `raw_text: "stored separately"` when Step 2
was built. Running `record_hash()` on this placeholder would have
collapsed 9 records as duplicates. Backfill deferred until
`JD_SOURCE_TEXTS.md` was in place. Lesson: the dedup pipeline must
run on real content, not placeholders. Populate raw_text before
running dedup.

---

## CLAUDE.md hierarchy

Keep this file lean. Add area-specific conventions to nested files:

- `collectors/CLAUDE.md` — API client patterns, rate limiting, error handling
- `pipeline/CLAUDE.md` — batch API patterns, cost tracking
- `scoring/CLAUDE.md` — scoring logic, profile schema (Phase 2+)
- `ui/CLAUDE.md` — UI conventions, index.json contract (Phase 5+)
