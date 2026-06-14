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
- **Batch API only** for *bulk* labelling — never synchronous extraction. **One sanctioned
  exception:** manual-ingest scores a single pasted JD synchronously (`pipeline.label.extract_one`,
  Haiku 4.5) — deviation 44. Reuses the batch prompt/parser; do not generalise to bulk paths.
- **BeautifulSoup only** for scraping — no Playwright, no Selenium
- **JSONL for pipeline artefacts; SQLite for interactive state** (Phase 6.5,
  deviation 49 + `docs/SPEC_DB_MIGRATION.md`). Pipeline output (`raw`/`filtered`/`labelled`/
  `validated`/`scored`/`calibration`/`stats.json`/`watchlist`) stays JSONL — append-once,
  regenerable, the fine-tuning ground truth; no ORM. The three **interactive** sinks
  (`activity_log`, `annotations`, `cv_tailor_links`) moved to `corpus/job_radar.db`
  (stdlib `sqlite3`, WAL on every connection, **INSERT-only — never UPDATE/DELETE**). Their
  JSONL files are kept as read-only audit archives.
- **Append-only everywhere** — JSONL appends or SQLite INSERTs; never migrate a record in
  place, bump schema version instead.
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
  `CORPUS_FINDINGS.md`, `job_radar_ARCHITECTURE.*`, `RETROSPECTIVE`). The canonical
  `README.md` lives at the **repo root** (the stale `docs/job_radar_README.md` stub
  was removed 2026-06-11 — don't recreate a second README under `docs/`). Before
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
| 6 — Interactive UI | ✅ complete — thin FastAPI `api/` (security/settings/main + index/auth/workflow/annotations routers) over `cli.track` + `models.record`; stdlib-HMAC `jr_write` cookie, fail-closed (`JR_WRITE_KEY`/`COOKIE_SECURE`); `GET /api/index` re-projects the live activity log; `ANNOTATION_TYPE` + `validate_annotation_event` (constants only, no schema bump); `corpus/annotations.jsonl` sink. **React/Vite `frontend/`** (cv-tailor stack: `UnlockProvider`, typed `lib/api`, `useIndex`, Browse/Pipeline/Detail + owner write controls + flag form) replaces the retired Phase 5 `ui/`. `api` + `frontend` compose services (`--profile ui` → :8080/:8000). **362 tests + browser-verified.** **Deployed** behind Caddy + Cloudflare at job-radar.michel-portfolio.co.uk (`docker-compose.prod.yml`, SPEC §10.9). **§10.11 workflow enhancements built**: manual fit override + annotation visibility/dedup (event-log append + read-model join, no scorer/schema change; deviation 37). Conventions: `api/CLAUDE.md`, `frontend/CLAUDE.md` (deviations 28–37). **Manual JD entry via UI built** (SPEC §11.1): `POST /api/manual-ingest` + `frontend/.../AddRoleModal.tsx` — synchronous single-JD extract→score→append→reindex, `ats="manual"` (deviation 44). |
| 6.5 — Persistence Hardening | 🔶 **Steps 1–5 shipped; Step 6 deferred** — interactive state (`activity_log`/`annotations`/`cv_tailor_links`) moved JSONL → SQLite (`corpus/job_radar.db`, WAL, INSERT-only). `cli/db.py` + `cli/db_migrate.py`; dual-write all write endpoints; reads auto-detect (`use_sqlite()`); `--export-index --source {jsonl\|sqlite\|both}` (default sqlite); `cron/backup_db.sh`. 506 tests, `--source both` = 0 divergences on the 53-job corpus. **Step 6 (remove JSONL writes) waits on a 1-week prod dual-write soak.** Deviation 49 + `docs/SPEC_DB_MIGRATION.md`. |
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

40. *(→ SPEC §11.1 + BACKLOG_YIELD_TRACKING)* Company metadata + yield tracking. `company_seeds.yaml`
    is now the **v2 format**: a bare top-level list (no `companies:` wrapper) with optional
    `domain`/`fit_hypothesis`/`action`/`notes` per entry. `load_companies` accepts **both** shapes
    (`data["companies"] if isinstance(data, dict) else data`). New report `cli.analyse --report yield`
    (+ `GET /api/report/yield` read-only download + React sidebar button) joins seeds ⨝ scored ⨝
    workflow ⨝ validated ⨝ annotations. Notable points: (a) the join is **by exact company name**,
    so seed `name` values are kept aligned to the corpus strings (seed renamed "Mistral AI" →
    "Mistral"); only one-off **manual/calibration** records (JP Morgan Chase, AI Consultancy, Fin
    (Intercom), Outreach, Zendesk — never in the monitored ATS universe) fall under domain
    `(unknown)`. (b) `action` is **advisory in v1** —
    `pause` logs but still collects; `manual`/`slug: null` entries are logged+skipped, never an error.
    (c) `COST_PER_JOB` is derived at report time from `stats.json`; `cost_per_job=None` (missing stats)
    degrades gracefully. (d) Volume metric is `jobs_scored` (cost = `jobs_scored × COST_PER_JOB`);
    rates suppressed below 5 scored jobs. (e) Settings gained `seeds_path`/`stats_path`
    (`JR_SEEDS_PATH`/`JR_STATS_PATH`), defaulted so existing `Settings(...)` construction keeps working.
    (f) Seed file is **81 companies** (greenhouse 49 / ashby 27 / lever 4 / manual 1) — the v2 header's
    "73" was inaccurate. Perplexity is **kept** (carried from v1, has scored roles); Jack & Jill is the
    `manual` watch entry.

41. *(→ SPEC §11.3 Phase 1)* cv-tailor integration Phase 1 — manual cv-tailor metrics.
    New append-only sink `corpus/cv_tailor_links.jsonl` (`CV_TAILOR_LINK_VERSION = 1` +
    `validate_cv_tailor_link`; constants only, **no schema bump** — same pattern as OUTCOME /
    ANNOTATION_TYPE). **Never** mutates JDRecord/ApplicationRecord/any cv-tailor output —
    a side snapshot keyed by `job_id`. Notable points: (a) The `cv_tailor` index section is
    embedded at **both** export (`cli.stats.build_index_rows`, via `load_cv_tailor_links` +
    `cv_tailor_view`) **and** the live `GET /api/index` overlay (so a freshly recorded link
    shows on reload without a re-export) — identical treatment to annotations (deviation 37);
    `{has_output: false}` when no link exists. (b) `api/routers/cv_tailor.py` gates **per-route**
    (`POST /api/cv-tailor-results` carries `Depends(require_unlocked)`) rather than at the router
    level, because `GET /api/jobs/{job_id}` in the same router is **public** (read-only JD detail
    incl. `raw_text`, already visible in the UI; built now for the Phase 2 handoff). *(POST auth
    extended to cookie-OR-Bearer + fields renamed in deviation 43.)* (c) UI scores
    are 0–100 in the form, divided by 100 to the 0.0–1.0 floats the API stores; displayed as %.
    (d) `CvTailorSection` is rendered inside `WriteControls` (above the scoring-flags panel) **and**
    standalone when `!configured` (read-only-deploy fallback) so the snapshot is visible even where
    write controls are hidden; Add/Edit affordances gate on `unlocked`. (e) New settings field
    `cv_tailor_links_path` (`JR_CV_TAILOR_LINKS_PATH`), defaulted to the `cli.stats` constant.

42. *(Phase 6 — security refactor)* Per-route gating replaces router-level
    gating for all write endpoints. `require_unlocked` is now declared on
    each individual POST route, not at the APIRouter constructor. This
    makes the security decision explicit at the point of definition and
    prevents accidental gating of intentionally-public GET endpoints.
    Introduced by the cv_tailor.py pattern (deviation 41) and applied
    consistently across workflow.py and annotations.py. No behaviour
    change — same endpoints protected, same endpoints public. Convention:
    `api/CLAUDE.md` "Endpoint security — per-route gating rule".

43. *(→ SPEC §11.3 + INTEGRATION_SPEC §6)* cv-tailor schema cleanup + Phase 3 Bearer-token
    auth (before automating the callback). **Schema:** the three metrics now mirror the
    cv-tailor UI — `fit_score` + `coverage_score` are 0.0–1.0 (shown as %), `cv_quality_score`
    is the raw **0.0–10.0** rubric score (shown as X.X/10, **not** normalised — different range
    in `validate_cv_tailor_link`). `cv_tailor_score` → renamed `fit_score`; `grounding_score`
    (no UI counterpart) **removed**. Still constants-only, no `SCHEMA_VERSION` bump.
    **Read-time migration (not a file rewrite):** `cli.stats._migrate_cv_tailor_fields` maps
    old `cv_tailor_score` → `fit_score` and drops `grounding_score` as records load, so the
    existing append-only file is never rewritten and old lines surface under the new names.
    **Phase 3 auth:** `POST /api/cv-tailor-results` now accepts the owner capability cookie
    **OR** a `CV_TAILOR_SERVICE_KEY` Bearer token (`api.security.has_valid_service_token`,
    constant-time) — an inline dual-auth check that **supersedes** the per-route
    `require_unlocked` on this one endpoint (deviation 41(b)); both fail closed. New settings
    field `cv_tailor_service_key` (`CV_TAILOR_SERVICE_KEY`, separate from `JR_WRITE_KEY`,
    unset = Bearer path closed); added to `.env.example`. `GET /api/jobs/{job_id}` unchanged.

44. *(→ SPEC §11.1)* **Manual JD entry via UI.** `POST /api/manual-ingest`
    (`api/routers/manual_ingest.py`, owner-gated per-route) scores ONE pasted JD synchronously
    and appends it to the corpus. Notable points: (a) **The one sanctioned violation of "Batch
    API only — never synchronous extraction":** `pipeline.label.extract_one` is a single
    `messages.create` (**Haiku 4.5**, standard non-batch pricing — its own `SYNC_COST_PER_MTOK`,
    NOT the Opus batch table) that *reuses* the batch `build_system_prompt`/`build_user_content`/
    `parse_extraction`, so the extraction shape is identical. (b) Dedup hashes the **normalised**
    text — `record_hash(normalise(raw_text))` — so a manual entry and its auto-collected twin share
    one `job_id` (409 on re-submit, *before* any extraction cost). (c) A manual entry is
    `source_ats="manual"` **and** `tier=4` (Claude-extracted) — orthogonal to the human Tier-1/2
    `corpus/manual/` drop folder, which still works. (d) Writes `validated_manual_{ts}` /
    `scored_manual_{ts}` / `meta_manual_{ts}` files next to their read globs (so `load_*` pick them
    up), appends a `manual_ingest` cost entry to `stats.json`, and rebuilds `index.json` via the same
    `cli.stats` join. An optional `notes` becomes a workflow `note` event (never silently dropped).
    (e) Owner-supplied `title`/`location` ride to the extraction via the `[ATS METADATA]` block; an
    empty `source_url` is synthesised to `manual:{job_id}` to keep the sidecar key unique. (f) New
    settings field `profile_path` (`JR_PROFILE_PATH`, default `candidate_profile.yaml`). (g) Frontend
    `AddRoleModal.tsx` in the sidebar — owner-only (renders `null` unless `unlocked`), shows a
    10–20s "extracting and scoring" state, never closes mid-flight. `SCHEMA_VERSION` unchanged.

45. *(→ SPEC §11.1 + §11.3)* **CV-Tailor calibration report.** `cli.analyse --report cv_tailor`
    (sixth report) compares Job Radar's fit verdict against cv-tailor's per role, joining
    `corpus/cv_tailor_links.jsonl` ⨝ scored ⨝ validated. Strictly read-only, same pure-functions
    shape as the other reports. Notable points: (a) **Two loaders for one sink, by design:** the
    new `cli.stats.load_all_cv_tailor_links` returns **all** runs (list, un-deduplicated) so the
    multiple-runs section can show run history — distinct from `load_cv_tailor_links` (latest per
    `job_id`, the read-model contract); same `_migrate_cv_tailor_fields` + skip-no-job_id. (b) The
    calibration signal is `Δ = CVT_fit% − (JR_fit_score × 10)` (both normalised to 0–100; JR is
    1–10, CVT is 0.0–1.0); negative = cv-tailor lower. Most-aligned/divergent rank by `|Δ|`. (c)
    Runs whose `job_id` is **not** in the scored corpus are surfaced as a "(not in corpus)"
    diagnostic block, never dropped. (d) Per-mode breakdown counts **latest-per-role** rows (so
    header role-count and breakdown run-count agree); `demo`/`full` always render. (e)
    `GET /api/report/cv_tailor` (read-only, no auth) returns the *same* report via the same pure
    functions (mirrors `/api/report/yield`); "CV-Tailor calibration" download button in the React
    sidebar. No schema bump, no new sink.

46. *(→ SPEC §16 + `docs/SPEC_LANGFUSE_INSTRUMENTATION.md` §3)* **Langfuse pipeline tracing
    (Phase B).** `cli/telemetry.py` is the ONE module importing the langfuse SDK (lazily, inside
    functions — so `import cli.telemetry` works with langfuse uninstalled). Opt-in by
    `LANGFUSE_PUBLIC_KEY`: unset → every recorder is a clean no-op (the default; `conftest.py`
    pops the key so the suite runs untraced, escape hatch `JR_TRACE_TESTS=1`). Notable points:
    (a) **Post-hoc spans** — the Batch API is async, so the two recorders build their trace tree
    AFTER results arrive, let the root span CLOSE, then `flush()` (the CLI exits with no periodic
    exporter — flush-before-close loses the trace; `langfuse_LEARNINGS.md` §7/§8). (b) **Three**
    targets: `record_extraction_batch` (`cli/label.py`, after `merge_results`), `record_scoring_run`
    (`cli/score.py`), and `record_manual_ingest` (`api/routers/manual_ingest.py` — the synchronous
    UI paste-and-score is a SEPARATE code path from the batch CLIs, so it needs its own trace; one
    POST = one `manual_ingest` trace with the Haiku extraction generation + scoring breakdown).
    **Gotcha that caused "debug trace shows but my real ingest doesn't":** instrumenting only the
    CLIs leaves the manual-ingest endpoint untraced — it never calls `cli.label`/`cli.score`. Rows
    assembled by **pure** builders (`build_trace_rows`/`build_scoring_rows`); the scoring breakdown
    is re-derived with `stage1_fit` (read-only — scorer untouched). (c) No
    business-logic/prompt/schema change (`SCHEMA_VERSION` unchanged); observability never raises
    into the pipeline (every recorder guards + swallows). (d) `python -m cli.telemetry debug-trace`
    is the zero-cost path probe (`auth_check` lives here, NEVER in `init_langfuse` — a sync probe
    would hang). (e) **Deployment:** Job Radar's OWN project keys (not cv-tailor's),
    `LANGFUSE_BASE_URL` = INTERNAL container URL (no Cloudflare hairpin), no quotes; `job-radar-api`
    joins the external `tracing` network (server-side `.env` + compose, see `.env.example`). The
    CLI-runner `job-radar` service (cron: `cli.label`/`cli.score`) reaches Langfuse via a SEPARATE
    server-only overlay **`docker-compose.tracing.yml`** (`cron/collect_weekly.sh` runs the stages
    through it; opt out with `JR_COMPOSE_FILES="-f docker-compose.yml"` on a host without the
    `tracing` network). Kept separate from `docker-compose.prod.yml` — it carries only the network,
    not the api/frontend/caddy prod wiring. `cli.digest` (daily) is not traced.
    (f) **Each root span MUST set `propagate_attributes(trace_name=…)`** (mirroring cv-tailor's
    `run_trace`) — that is what stamps the `langfuse.trace.name` span attribute the **worker
    requires** to promote a trace from MinIO into ClickHouse. Without it the spans upload but the
    trace silently never appears in the UI (diagnosed by diffing MinIO payloads vs cv-tailor). All
    three entry points set it: `extraction_batch`, `scoring_run`, and the `debug-trace` probe.

47. *(→ SPEC §11.1 + deviation 44)* **Manual ingest uses SOFT validation, not the pipeline's
    hard enum gate.** `POST /api/manual-ingest` is a deliberate owner decision to add a specific
    role, so the closed-vocabulary gate must not block it. `models.record.soft_validate` runs the
    SAME checks as `validate` and **returns `(hard_errors, warnings)`** — it *classifies*
    `validate()`'s findings, never re-implements them. A finding ending `"not in allowed values"`
    (an enum vocabulary gap — right type, off-vocabulary value, e.g. `role_type:
    ["Customer Success"]`) is a **warning** (logged + returned in the 200 body as `warnings`,
    surfaced amber by `AddRoleModal`, record stored as-is). Everything else (a wrong *type* —
    `domain` a string not a list — or a missing field) is a **hard error**: the endpoint **422s**
    on `hard_errors` because a malformed type silently corrupts every downstream stage. Notable
    points: (a) `validate` is **unchanged** and still the hard gate for the automated pipeline
    (batch label, `cli.validate`, prefilter output) — `ROLE_TYPE` is **not** expanded. (b) Manual
    ingest **never runs the prefilter** (it imports no `prefilter`; **pinned** by
    `test_manual_ingest_bypasses_prefilter` + `test_manual_ingest_imports_no_prefilter`) — a
    deliberate add is not screened on role-bucket/location. (c) The scorer already tolerates an
    off-vocabulary `role_type` (set-intersection → role dimension scores 0, never raises) — no
    scorer change. (d) `soft_validate` is a thin, intentionally-named seam over `validate` so the
    bypass is explicit at the call site; no schema bump (`SCHEMA_VERSION` unchanged). (e) Known
    limit: `_check_enum` is membership-only, so a *list* passed to a scalar enum field is bucketed
    as a warning, not a hard error — rare model output, scorer-tolerant.

48. *(→ SPEC §11.1)* **SSE live updates — in-process bus, no Redis.** `GET /api/events`
    (`api/routers/events.py`, **public**, `text/event-stream`) emits an `index_updated` frame after
    every write so the UI re-fetches `GET /api/index` instead of going stale. The bus
    (`api/events.py`) is an **in-process** `set` of per-connection `asyncio.Queue`s — single-process
    FastAPI app, so no Redis/external pub-sub (deferred to the §11.4 PostgreSQL/multi-process step;
    only that module changes, the `GET /api/events` *contract* is stable). **Sync-endpoint gotcha:**
    write endpoints are `def` (threadpool), so they can't touch an `asyncio.Queue` directly —
    `emit_index_updated` hops onto the event loop captured at startup (`bind_loop` in the FastAPI
    `lifespan` handler) via `call_soon_threadsafe`; no loop bound / no subscribers → clean
    no-op, so a write is never coupled to the bus. Emitted after **every** write that changes the
    read model: `POST /api/status`, `/api/note`, `/api/title`, `/api/manual-ingest`,
    `/api/cv-tailor-results`, `/api/fit-override`, `/api/outcome`, `/api/annotations`. (`note`/
    `title` were added after the first build — notes show in the detail panel, title overrides in
    Browse — so they emit too.) Frontend
    (`useIndex`) pairs the SSE `EventSource` with a `visibilitychange` re-fetch (the latter covers
    "came back from cv-tailor" with zero backend). A 30s keepalive comment keeps proxies from
    cutting an idle stream. No schema/scorer change.

49. *(→ SPEC_DB_MIGRATION + SPEC §11.4)* **Phase 6.5 — interactive state moved JSONL → SQLite.**
    The three interactive sinks (`activity_log`, `annotations`, `cv_tailor_links`) now live in
    `corpus/job_radar.db` (stdlib `sqlite3`, gitignored); pipeline artefacts stay JSONL forever
    (boundary in SPEC_DB_MIGRATION §1). **Steps 1–5 shipped; Step 6 (remove JSONL writes) is
    deferred pending a 1-week production dual-write soak.** Key points: (a) **Append-only kept as
    discipline** — INSERT-only, never UPDATE/DELETE; `project()` is unchanged (a fold over a flat
    event list). (b) `cli/db.py` is the single home for schema (`init_db`, WAL + FKs on every
    `get_db`), the JSONL↔SQL row mapping (`insert_*`/`_enc`/`_dec`/`_bool_to_int`), the SQLite read
    paths (`load_events_sqlite` etc.), and the dual-write helpers (`write_*`). (c) **Two DDL
    corrections to the spec** (LEARNINGS Step 1): `schema_version.version` is PK so `INSERT OR
    IGNORE` is idempotent; the annotations dedup is a UNIQUE **expression** index over
    `IFNULL(field,'')` (a plain UNIQUE wouldn't dedupe the `field=NULL` rejection_reasons —
    deviation 39). (d) **Dual-write** (`api/routers/{workflow,annotations,cv_tailor,manual_ingest}`):
    every write hits both stores; the annotations **409 now comes from the SQLite UNIQUE index**
    (IntegrityError), not a JSONL scan. (e) **Reads auto-detect** via `cli.db.use_sqlite()`
    (`DB exists?`): the API overlay + reports + the CLIs (`track list`/`analyse`/`digest`) call
    *separate* `_auto` loaders (`load_activity_events`, `load_*_auto`) — the bare `load_*` stay PURE
    JSONL as the `cli.stats --export-index --source both` comparison baseline (default `--source`
    flipped to `sqlite`). (f) **Existence-as-switch footgun:** the API lifespan deliberately does
    NOT create the DB; an empty DB made before backfill would hide all interactive state. **Deploy
    ordering:** run `python -m cli.db_migrate` (backfill) before serving writes. (g) Tests are
    hermetic via an autouse `conftest._isolate_db` (per-test `JR_DB_PATH`). (h) Backup:
    `cron/backup_db.sh` (daily `.backup` + 7-day prune). `SCHEMA_VERSION` unchanged.


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
