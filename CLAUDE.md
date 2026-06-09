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
| 3 — Job Tracker | 🔄 in progress — building a **real** corpus (target 500+ validated). Collection now captures a **metadata sidecar** (`corpus/raw/meta_{date}.jsonl`: title + structured location, keyed by `source_url`) — `raw_text` stays employer JD text only. **Pre-label filter** (`pipeline/prefilter.py` + `prefilter.py`): deterministic location + role screen over the sidecar, cuts raw → survivors *before* paid labelling (`corpus/filtered/`). Next: label survivors (pass meta into the prompt as separate context), then weekly extraction-quality review (watch Enterprise Software / Product over-tagging) and a structured score review after 100+ real scored jobs. Option D (career-pattern scoring) **deferred** until prod data shows role+domain+depth+blockers can't explain errors. |
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
| 3 — Greenhouse | ✅ complete | collectors/base.py + greenhouse.py + collect.py. Backfill done — 10 unique hashes, 0 pending. html.unescape() required on response body. |
| 4 — Lever + Ashby | ✅ complete | lever.py + ashby.py registered. Lever returns bare array + split description fields. Live: Mistral 170, Perplexity 71. |
| 5 — VC boards | ✅ complete | All boards JS-rendered (requires_js) — skeleton skips all; scraping deferred to Phase 4 |
| 6 — Tier 2 tooling | ✅ complete | tier2_review.py — a/e/s loop, resumable via corpus/tier2_progress.json. IO + extract injectable for tests. |
| 7 — Batch API labelling | ✅ complete | pipeline/label.py + label.py. Live verified: 5/5 labelled, $0.055, cost→stats.json. Prompt generated from executable schema enums. |
| 8 — Validation + stats | ✅ complete | validate.py → corpus/validated/{validated,failures}_*.jsonl; stats.py summary + --export-index → corpus/index.json (flat, UI contract). |
| 9 — Export | ✅ complete | export.py — prompt/completion JSONL; eval(1-3)/train(all-validated)/full(superset) sets. |

---

## Known deviations from spec (captured from build)

1. `SCHEMA_VERSION = "1.2"` (spec Step 1 text said 1.1 — typo, 1.2 is correct)
2. Records stored as compact single-line JSONL (not pretty-printed)
3. `.gitignore` uses `corpus/**/*` + negations to track skeleton, ignore data
4. Added: `models/__init__.py`, root `conftest.py`, `tests/factories.py`,
   `.gitattributes`, this `CLAUDE.md`, `collectors/base.py`, `scripts/`
5. `docker-compose.yml` marks `env_file` as `required: false`
6. SHA-256 backfill on 10 manual records run in Step 3 (deferred from Step 2)
7. `collectors/base.py` added — shared `fetch_json` retry/backoff +
   `build_raw_record`; each collector is URL + field mapping only
8. `scripts/` package for one-off corpus maintenance
9. `docker-compose.yml` service renamed `jd-refinery` → `job-radar`
10. Greenhouse `?content=true` returns HTML entity-escaped content —
    `html.unescape()` run on response body before storing `raw_html`
11. Lever returns bare JSON array + split description fields (not `{"jobs":[...]}`)
12. `pipeline/merge_results` seeds neutral annotation defaults after labelling
    so whole-record validation passes before human annotates
13. Prompt closed-vocabulary section generated from `models.record` enums —
    not hand-listed; prompt caching active on system prefix
14. (Phase 2) Schema versioned **per record type**: `SCHEMA_VERSION="1.3"`
    (ApplicationRecord) + `JDRECORD_SCHEMA_VERSION="1.2"` (frozen). The three
    sites that hard-coded `SCHEMA_VERSION` for a JDRecord envelope (`factories`,
    `test_record`, `stats.export_index`) were repointed at `JDRECORD_SCHEMA_VERSION`.
15. (Phase 2 scorer) The `role` dimension is **no longer a flat `target_roles`
    lookup** (deviates from SPEC §6.5). It is three-tier — primary (2.0) /
    `conditional_primary` (Product: 2.0 if a relevant domain or strong+weak signal,
    else 1.0) / secondary (1.0) / no match (0). Profile gained
    `conditional_primary` + `secondary` under `target_roles`.
16. (Phase 2 scorer, **known limitation — F, deferred**) Tier-4 automated
    extraction is generous on `role_type` mapping and defaults to `Enterprise
    Software` as a catch-all `domain`. Because `Enterprise Software` is a *strong*
    domain, this inflates some off-target roles; scorer gates/blockers partially
    recover. Full fix = extraction-prompt/corpus maintenance, deferred to a later
    phase.
17. **Calibration corpus** lives in `corpus/calibration/` (13 deliberately
    negative / conditional JDs) and is **excluded from train/eval/fine-tune
    exports** (`export.py` skips any `calibration` path). It is a **permanent
    scorer regression set** — re-run `python -m scripts.report_calibration --full`
    whenever the scorer changes, and re-validate the spread before locking a change.
18. (Phase 3) **Collectors now return `CollectedJob` (record + metadata)**, not a
    bare `JDRecord`. The ATS APIs expose `title` + structured location that the
    schema-locked `JDRecord` has no field for; rather than overload `raw_text`
    (which stays **employer JD text only**), `collect.py` writes a parallel
    **metadata sidecar** `corpus/raw/meta_{date}.jsonl` (`base.META_FIELDS`,
    keyed by `source_url`). Used by the pre-label filter now and passed to the
    extraction prompt as separate context later — never injected into `raw_text`.
19. (Phase 3) **Pre-label filter** = `pipeline/prefilter.py` (pure location + role
    screens, generous by design) + `prefilter.py` CLI (clean+dedupe → screen →
    **near-dedupe** → `corpus/filtered/filtered_{date}.jsonl` + survivor-distribution
    report). Runs **before** any Batch labelling spend. Screens read the sidecar
    only (no model, no scoring). `collapse_near_duplicates` merges survivors that
    share `(company, language-stripped title)` — the same role posted to many
    locations / language variants that exact-body dedupe can't catch — keeping the
    single best-located representative (UK first); specialisation parentheticals
    are preserved so distinct roles aren't merged. The survivors file is JDRecords
    only; the sidecar remains the join source for the later labelling step.

---

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

- `collectors/CLAUDE.md` — API client patterns, rate limiting, encoding gotchas
- `pipeline/CLAUDE.md` — batch API patterns, cost tracking, label-merge defaults
- `scoring/CLAUDE.md` — scoring logic, profile schema (Phase 2+)
- `ui/CLAUDE.md` — UI conventions, index.json contract (Phase 5+)
