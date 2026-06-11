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

**Tie-break rule:** When spec prose and `models/record.py` disagree,
trust the executable artifact and fix the prose. The dataclass is the
thing tests actually run against.

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
- **Stage CLIs live in `cli/` — create new ones there, never in the repo root.**
  A pipeline-stage / operational CLI (e.g. a future `digest.py`) goes in `cli/`
  as `cli/<stage>.py` with a `main()` + `if __name__ == "__main__"` guard, and is
  run as **`python -m cli.<stage>`** (e.g. `python -m cli.score`,
  `python -m cli.track list`) — NOT `python score.py` (a script run by path puts
  `cli/` on `sys.path` and can't import the repo-root packages; `-m` from the root
  can). One-off / throwaway corpus tools go in `scripts/`
  (`python -m scripts.<name>`). Root holds only `conftest.py`.
- **Git workflow — commit directly to `main`; no branches, no PRs.** Solo
  developer: make the change on `main`, show it for human review, then commit +
  push to `main` directly once approved. Do **not** create feature branches or
  open pull requests (this overrides the harness default of "branch first on the
  default branch"). Commit/push only when the user asks; commit messages still
  end with the `Co-Authored-By` trailer.
- **Temporary build docs (feature PLANs, handoffs, prompts) are NOT repo content.**
  Write them under a gitignored **`tmp/`** directory, never in `docs/`. `docs/` holds
  only durable source-of-truth (`job_radar_SPEC.md`, `job_radar_LEARNINGS.md`,
  `CORPUS_FINDINGS.md`, `job_radar_ARCHITECTURE.*`, `RETROSPECTIVE`, `README`). Before
  discarding a plan, **migrate any durable decision/deferral into SPEC / LEARNINGS / the
  nearest `CLAUDE.md`** — never let the plan become the only home for a decision (the
  anti-pattern that once left retired phase plans cited as "authoritative" in code + source
  docs; those decisions now live in SPEC §6.9/§7.4/§11.2). Prompt scratch follows the same rule
  (`docs/*PROMPT*` is gitignored as a transitional measure).
- **Definition of done (EVERY task)** — a change is not complete until the
  docs are current. This is not optional and not an afterthought:
  1. **`docs/job_radar_SPEC.md`** — if anything about the architecture,
     pipeline, schema, or phase scope changed, update the SPEC in the **same**
     change. The SPEC must always describe the system as it actually is.
  2. **`docs/job_radar_LEARNINGS.md`** — append a learning entry for every
     decision, finding, reversal, or surprise (append-only; never rewrite
     existing entries). Capture the *why*, not just the *what*.
  3. The nearest **`CLAUDE.md`** — update conventions/state in the same change.
  Treat SPEC + LEARNINGS as part of the commit, alongside code and tests —
  never a "later" task.

---

## Phase state

| Phase | Status |
|---|---|
| 1 — Corpus Engine | ✅ complete — Steps 0–9, 95 tests. Pipeline end-to-end. |
| 2 — Scoring Engine | ✅ **complete (scorer v1)** — `scoring/{profile,scorer}.py` + `score.py`, 179 tests. Option A (`ApplicationRecord` v1.3 → `corpus/scored/`) + gates-vs-signal model + 3-tier role (primary/conditional/secondary) + capability/M&A blockers + negative-signal ceiling. Thresholds **set from evidence** (held against the 23-record corpus: 10 manual + 13 calibration). Calibration regression set: `corpus/calibration/`. Known limit F (extraction generosity) deferred. Conventions: `scoring/CLAUDE.md`. |
| 3 — Job Tracker | ✅ complete — `track.py` (model C, append-only event log), 263 tests. Extraction quality fixed (deviation 21). Real corpus build underway. Scorer locked. |
| 4 — Discovery Layer | ✅ complete + **operational** — incremental collection (deviation 24) + `cli/digest.py` (deviation 26) + **working** weekly cron (`cron/`, fixed deviation 36) + cross-corpus dedupe (deviation 19). **102-company universe** seeded (SPEC §11.1); first real server run: 5,498 collected → 65 new survivors → 117 scored, $3.18 to date. |
| 5 — Static UI | ✅ complete — `ui/{index.html,app.js,style.css}` static SPA (no framework/build/CDN), reads the joined `corpus/index.json`, served by nginx behind the `ui` Docker profile (`docker compose --profile ui up` → :8080). Browse + Pipeline + detail drawer + filters + stats bar. `index.json` contract changed to a join (deviation 27). 318 tests. |
| 6 — Interactive UI | ✅ complete — thin FastAPI `api/` (security/settings/main + index/auth/workflow/annotations routers) over `cli.track` + `models.record`; stdlib-HMAC `jr_write` cookie, fail-closed (`JR_WRITE_KEY`/`COOKIE_SECURE`); `GET /api/index` re-projects the live activity log; `ANNOTATION_TYPE` + `validate_annotation_event` (constants only, no schema bump); `corpus/annotations.jsonl` sink. **React/Vite `frontend/`** (cv-tailor stack: `UnlockProvider`, typed `lib/api`, `useIndex`, Browse/Pipeline/Detail + owner write controls + flag form) replaces the retired Phase 5 `ui/`. `api` + `frontend` compose services (`--profile ui` → :8080/:8000). **362 tests + browser-verified.** **Deployed** behind Caddy + Cloudflare at job-radar.michel-portfolio.co.uk (`docker-compose.prod.yml`, SPEC §10.9). **§10.11 workflow enhancements built**: manual fit override + annotation visibility/dedup (event-log append + read-model join, no scorer/schema change; deviation 37). Conventions: `api/CLAUDE.md`, `frontend/CLAUDE.md` (deviations 28–37). |
| 7 — Fine-Tuned Analyser | Deferred (Project 5) |

---

## Step state (Phase 1)

| Step | Status | Notes |
|---|---|---|
| 0 — Scaffold | ✅ complete | Docker, dirs, seeds, 10 manual records |
| 1 — JDRecord model | ✅ complete | v1.2, validate(), round-trip tests |
| 2 — Clean + dedupe | ✅ complete | clean(), record_hash(). SHA-256 backfill run in Step 3. |
| 3 — Greenhouse | ✅ complete | collectors/base.py + greenhouse.py + collect.py. Backfill done — 10 unique hashes, 0 pending. html.unescape() required on response body. |
| 4 — Lever + Ashby | ✅ complete | lever.py + ashby.py registered. Lever returns bare array + split description fields. Live: Mistral 170, Perplexity 71. |
| 5 — VC boards | ✅ complete | All boards JS-rendered (requires_js) — skeleton skips all; scraping deferred to Phase 4 |
| 6 — Tier 2 tooling | ✅ complete | tier2_review.py — a/e/s loop, resumable via corpus/tier2_progress.json. IO + extract injectable for tests. |
| 7 — Batch API labelling | ✅ complete | pipeline/label.py + label.py. Live verified: 5/5 labelled, $0.055, cost→stats.json. Prompt generated from executable schema enums. |
| 8 — Validation + stats | ✅ complete | validate.py → corpus/validated/{validated,failures}_*.jsonl; stats.py summary + --export-index → corpus/index.json (flat, UI contract). |
| 9 — Export | ✅ complete | export.py — prompt/completion JSONL; eval(1-3)/train(all-validated)/full(superset) sets. |

---

## Known deviations from spec (active guards and gotchas)

Deleted: 1–9, 12 (build logistics / scaffold decisions — done, irreversible, no ongoing value).
Reduced to spec pointer: 13–16, 22–23, 25, 27, 33–35, 37 (fully covered in SPEC — see pointer).
Kept in full: everything below — active operational guards Claude Code must know.

---

10. **Greenhouse HTML entity-escaping.** `?content=true` returns HTML entity-escaped
    content — `html.unescape()` must run on the response body before storing `raw_html`.
    Forgetting this breaks extraction silently (escaped entities in the text).

11. **Lever returns a bare JSON array**, not `{"jobs":[...]}`. Split description fields.
    The collector handles this; don't assume Greenhouse's response shape.

13. *(→ SPEC §5.7)* Prompt closed-vocabulary section generated from `models.record` enums —
    not hand-listed. Prompt caching active on the system prefix.

14. *(→ SPEC §6.9 + schema summary)* Schema versioned **per record type**:
    `SCHEMA_VERSION="1.3"` (ApplicationRecord) + `JDRECORD_SCHEMA_VERSION="1.2"` (frozen).
    Don't collapse these two constants.

15. *(→ SPEC §6.9)* Three-tier role model (primary / conditional_primary / secondary)
    deviates from SPEC §6.5's flat lookup. Profile has `conditional_primary` + `secondary`
    under `target_roles`.

16. *(→ superseded by 21)* Known Limitation F (extraction generosity) — fixed in
    production via extraction prompt (deviation 21). Scorer untouched.

17. **Calibration corpus excluded from exports.** `corpus/calibration/` (13 negative/
    conditional JDs) is a **permanent scorer regression set** — `export.py` skips any
    `calibration` path. Re-run `python -m scripts.report_calibration --full` whenever
    the scorer changes and re-validate the spread before locking a change.

18. **CollectedJob + metadata sidecar.** Collectors return `CollectedJob` (record +
    metadata), not a bare `JDRecord`. ATS title + location go to a parallel sidecar
    `corpus/raw/meta_{date}.jsonl` (keyed by `source_url`) — **never injected into
    `raw_text`**, which stays employer JD text only.

19. **Pre-label filter is the only dedup in the running pipeline.** `cli/dedupe.py` is
    an empty stub. `pipeline/prefilter.py` runs before any Batch spend and seeds its
    `seen` set from `load_processed_hashes()` (every already-labelled or scored job_id)
    so a `--full`/new-environment re-collect can't re-pay to label seen jobs.
    `--include-processed` opts out. `collapse_near_duplicates` merges survivors sharing
    `(company, language-stripped title)` — same role, many locations — keeping the
    best-located representative (UK first).

20. **`clean_readable` is required before labelling.** Collected survivors have
    `raw_text=""` (only `raw_html`). `pipeline.clean.clean_readable` populates
    `raw_text` — HTML stripped, **line breaks + case kept** (the hash-form `clean()`
    lowercases to one line, breaking the scorer's first-line title heuristic).
    `cli.label.load_records` does this automatically on empty `raw_text`; no separate
    prep stage needed. Sidecar title/location go to the prompt as a separate
    `[ATS METADATA]` block — never merged into `raw_text`.

21. **Known Limitation F — fixed in extraction prompt, scorer untouched.**
    `build_system_prompt` disambiguates: Product Marketing → `GTM` (not `Product`);
    post-sales/CS is not `AI Delivery`; no `Enterprise Software` default (`domain: []`
    when nothing applies). Scorer stays locked until the 100+-job review.

22. *(→ SPEC §5.10)* GTM/partner observation watchlist — `prefilter.py` diverts
    GTM/partner roles to `corpus/watchlist/` (never labelled, scored, or costed).
    `GTM` deliberately stays out of `target_roles` until the watchlist justifies it.

23. *(→ SPEC §7.4)* Job Tracker model C + Log-only — fully described in SPEC §7.4.
    Key invariant: `track.py` **only appends**, never mutates a scored file.

24. **Incremental collection is client-side, not server-side.** ATS board APIs expose
    no `updated_after` param (Greenhouse's `updated_after` is Harvest API only; Lever/
    Ashby boards take none — verified). `collect.py` fetches the full list and filters
    client-side via `passes_cursor`. Cost saved is downstream Batch spend, not the GET.
    Cursor = **start** timestamp of last successful run. Lever has no timestamp →
    always full-fetch. Details: `collectors/CLAUDE.md`; mechanics: SPEC §8.2.

25. *(→ build conventions above)* Stage CLIs live in `cli/` and run as
    `python -m cli.<stage>` — never `python cli/<stage>.py` (path-based import breaks
    repo-root package imports).

26. **`cli/digest.py` is a view over tracker state, not a pipeline stage.** It reuses
    `cli.track` loaders + `project`. Since-cursor `corpus/.digest_last_run` = **start**
    timestamp (same reasoning as collect cursor). A full manual re-score restamps
    `scored_at` and would resurface the whole corpus in the next digest — incremental
    collection keeps the cron digest bounded to genuinely-new postings.

27. *(→ SPEC §9.4)* `corpus/index.json` is a join (ApplicationRecord ⨝ JDRecord ⨝
    sidecar ⨝ activity-log projection), not a flat JDRecord array. Superseded by the
    live overlay in deviation 29.

28. **Capability cookie is stdlib HMAC, not `itsdangerous`** (supersedes SPEC §10.8
    step 8). Cookie `jr_write` (HttpOnly, SameSite=lax, Secure via `COOKIE_SECURE`,
    path `/api`). Fail-closed: no `JR_WRITE_KEY` → all writes 403. `itsdangerous` is
    **not** a dependency.

29. **`GET /api/index` overlays the live activity log + annotations over `index.json`.**
    `api/routers/index.py` serves the pre-built join **and** re-projects
    `project(load_events())` + refreshes embedded annotations (deviation 37 extended
    this). Both live without a re-export. *(Revision: annotations now affect the read
    model — deviation 37 supersedes the original "annotations don't affect" note.)*

30. **`api` compose service reuses the `job-radar` image** — runs `uvicorn api.main:app`
    rather than a separate `Dockerfile.api`. Only the M2 frontend gets its own
    Dockerfiles. Thin-layer rule lives in `api/CLAUDE.md`.

31. **Frontend image-tag-collision gotcha.** A manual `docker build -t job-radar-frontend`
    collides with the compose-assigned image name → `docker compose up` silently reuses
    the stale image. Always `docker compose --profile ui up -d --build frontend`.

32. **Outcome recording + application staleness** (SPEC §10.10 item 4). `POST
    /api/outcome {job_id, outcome, notes?}`. Rejection stage auto-derives from workflow
    status (`applied→post_screen`, `interviewing→interview`, `offer→final`). Applied
    date surfaced with age + stale flag past `STALE_DAYS` (21). No schema/scorer change.

33. *(→ SPEC §10.10 items 1–3)* Detail modal, pipeline lane order, button styling fixes.

34. *(→ SPEC §10.10 item 5)* `rejected` as first-class default-hidden state;
    `effectiveStatus()` derives display status from outcome at read time.

35. *(→ SPEC §10.10 item 6 + `frontend/CLAUDE.md`)* Tailwind + shadcn rearchitecture;
    global CSS deleted. Don't reintroduce global semantic class names — they collide
    with Tailwind utilities silently.

36. **Cron pipeline defaults + UTC midnight caveat.** Stages previously had
    `--input required=True` — every bare cron line errored. Now have sensible UTC-date
    defaults. `cli/dedupe.py` is an empty stub (prefilter deduplicates). **Don't
    schedule cron near 00:00 UTC** — date-keyed stages would split across two timestamps.

37. *(→ SPEC §10.10 item 7 + §10.11)* Manual fit override + annotation visibility.
    Key invariant: `fit_override` reason lives in event `notes`, folded separately from
    workflow notes so they never clobber each other. `GET /api/index` overlay now
    re-resolves live fit override **and** refreshes embedded annotations (revises
    deviation 29).

38. *(→ SPEC §11.1)* `cli/analyse.py` — read-only corpus reports (score-distribution /
    status / companies / gaps; `--report all`). **Strictly read-only** (no corpus write,
    no pipeline stage, no API). Reuses the tracker loaders + `project` join, not a
    reimplementation. Diverged from the build prompt's companies-report example header
    ("minimum 3 scored jobs to appear"): per the prompt's own implementation notes + DoD
    it shows **all** companies and suppresses *rates* below 5 scored jobs (the shortlist-rate
    ranking needs ≥5 reviewed) — no "min jobs to appear" filter.

39. *(→ SPEC §11.1 + BACKLOG §2)* Rejection reasons reuse the annotations sink — a
    `rejection_reason` `ANNOTATION_TYPE` + `REJECTION_REASON` vocab (constants only, no schema
    bump), recording *why a role wasn't pursued despite its score*. Same `POST /api/annotations`
    + `annotations.jsonl` (no new endpoint/file). Notable points: (a) `annotation_type ==
    "rejection_reason"` is the **only** type whose `reason` the API validates (against
    `REJECTION_REASON`); all others keep free-text `reason`. (b) A rejection_reason carries
    `field: null` — `validate_annotation_event` was relaxed to allow `field` ∈ {str, None}
    (a wrong *type* still fails), and `AnnotationRequest.field` is now `str | None`. (c) The UI
    control **omits a free-text notes field** (the layout mock showed one, but the annotation
    record + POST body carry no notes destination — the structured `reason` is the payload).
    (d) `cli.analyse --report gaps` shows the rejection section only when ≥1 is recorded.


## Schema summary

Two record types live in `models/record.py`, versioned **per type** (Option A):

```
JDRecord          extraction   Claude populates   objective    v1.2 (frozen)
ApplicationRecord assessment   scorer populates   subjective   v1.3 (built)
JobPosting        product      system populates   operational  (deferred)
```

- `SCHEMA_VERSION = "1.3"` (project / `ApplicationRecord`);
  `JDRECORD_SCHEMA_VERSION = "1.2"` (JDRecord envelope, **not migrated**).
- `JDRecord`'s Phase-1 annotation fields are now **legacy stubs** — the scorer
  never reads or writes them. New scoring output lives only in `ApplicationRecord`
  (`corpus/scored/`). `JobPosting` and the full annotation migration are a later,
  explicit step.

---

## Export set definitions

```
eval    Tier 1+2+3 human-reviewed only — held-out eval set, never training
train   All tiers validated — fine-tuning input
full    Everything including failures — inspection only, never training
```

`train` ≈ `full` currently (few Tier 4 records, low failure rate).
The separation exists by design for when scale makes it matter.

---

## CLAUDE.md hierarchy

Keep this file lean. Add area-specific conventions to nested files:

- `collectors/CLAUDE.md` — API client patterns, encoding gotchas, **incremental
  capability matrix** (exists)
- `pipeline/CLAUDE.md` — batch API patterns, cost tracking, label-merge defaults
- `scoring/CLAUDE.md` — scoring logic, profile schema (Phase 2+)
- `ui/CLAUDE.md` — Phase 5 static-UI conventions, index.json join contract (exists)
- `api/CLAUDE.md` — Phase 6 thin-backend invariants: import `cli.track`/`models.record`,
  never the scorer; gate every write with `require_unlocked`; fail-closed; live overlay
  on `GET /api/index`; env (`JR_WRITE_KEY`/`COOKIE_SECURE`) (exists)
- `frontend/CLAUDE.md` — Phase 6 M2 React conventions (added with M2)
