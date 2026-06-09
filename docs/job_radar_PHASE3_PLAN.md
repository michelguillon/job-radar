# job_radar_PHASE3_PLAN.md — Job Tracker / real-corpus build plan

**Status:** Phase 1 ✅ and Phase 2 ✅ (scorer **v1** locked, commit `ad88e60`).
Phase 3 started: collection verified end-to-end against the seeds.
This is the authoritative handoff for Phase 3. Read with `CLAUDE.md` and
`docs/job_radar_SPEC.md §5, §6`.

> **Goal from here is user value — surfacing real opportunities — not optimising
> the scorer in isolation.** We are building a real corpus, not a test set.

---

## Where we are

- **Scorer v1 locked.** Gates-vs-signal model, 3-tier role (primary /
  conditional_primary Product / secondary), capability + M&A blockers,
  negative-signal ceiling. `fit_label` thresholds set from evidence and held
  against the 23-record corpus. Do **not** change the scorer in Phase 3 until the
  structured score review (below) says the evidence demands it.
- **Calibration regression set:** `corpus/calibration/` (13 JDs, gitignored data,
  reproducible from `docs/jobs_calibration_corpus.txt` via
  `scripts/build_calibration_raw.py`). Re-run `python -m scripts.report_calibration
  --full` after ANY scorer change. Excluded from all exports.
- **First real collection done:** `corpus/raw/raw_20260609.jsonl` — **2,510 raw
  records** (gitignored). Distribution:
  - Greenhouse 2,230 — Databricks 778 · Stripe 498 · Anthropic 377 · Adyen 212 ·
    The Trade Desk 197 · Figma 168
  - Lever 168 — Mistral 168
  - Ashby 112 — Perplexity 71 · Modal 31 · Anyscale 10
  - VC boards 0 (all JS-rendered, deferred to Phase 4)

---

## Phase 3 objectives (in order)

1. **Stable collection + scoring at scale** — target **500+ validated** relevant
   jobs (not 2,510 raw).
2. **Weekly extraction-quality review** — ~10 jobs/week; track role / domain /
   seniority distribution; watch for **`Enterprise Software` and `Product`
   over-tagging** (the deferred Known Limitation F).
3. **Structured score review after 100+ real scored jobs** — *before any further
   scorer changes.*

**Option D (career-pattern scoring) is DEFERRED.** Do not implement until
production data shows role + domain + depth + blockers cannot explain observed
errors.

---

## Immediate task — the pre-label filter (start here, iterate)

2,510 raw → a few hundred genuinely-relevant, **before** the paid Batch labelling.
Labelling all 2,510 ≈ **$40** (measured: ~$0.016/record on the 13-JD run) to
extract mostly-irrelevant global engineering roles. A cheap, code-only screen on
the raw records (location ≈ UK/London/remote-EU; role-title vs target families)
must cut the set first. CLI writes; JSONL only; no scoring in this step.

### The first design fork — RESOLVED (2026-06-09): sidecar metadata

**The raw records had no structured `title` or `location` to filter on.** The
collectors stored only `raw_html` + `source_url` + `company` and discarded the
ATS `title` and `location` fields. Chosen approach: **(A) enhance the collectors
and re-collect — via a metadata SIDECAR, not by overloading `raw_text`.**

Michel's decision: `raw_text` stays **employer-provided JD text only**; no
synthetic title/location header is injected. Collectors now return `CollectedJob`
(record + meta) and `collect.py` writes `corpus/raw/meta_{date}.jsonl` alongside
`raw_{date}.jsonl`. Sidecar fields (keyed by `source_url`, stable pre-dedupe):
`title`, `location_str` (all listed locations joined), `workplace_type`,
`is_remote`, `country`, `raw_location_payload`. The metadata feeds the filter now
and is passed to the extraction prompt as **separate context** at labelling time.
Identity is unaffected — `pipeline.dedupe` hashes `clean(raw_html)`, which the
sidecar never touches.

### Filter design — BUILT (`pipeline/prefilter.py` + `prefilter.py`)

- **Location screen:** keep UK / London / UK-remote / Europe-remote / EMEA-remote /
  multi-location-incl-UK / bare-Remote / not-stated (ambiguous kept); drop clear
  non-UK onsite and remote tied to a non-European country (incl. **US state names**
  — "Remote – California" — which have no country field on Greenhouse).
- **Role screen (generous):** STRONG_KEEP target families (Solutions
  *eng/arch/consult*, Pre-Sales, Sales Engineer, **Applied AI Architect**, Forward
  Deployed, Field Engineering, **Deployment Strategist**, Partner SA, AI Delivery)
  → drop pure sales (AE/AM/SDR/BDR) → drop recruiting/HR → keep Product, Customer
  (Success/Experience), GTM/Partner (incl. **Partner Success/Programs**) → else
  drop off-target. Strong-keep precedes the sales drop so "Technical Account
  Manager" survives.
- **Near-dedupe:** after screening, `collapse_near_duplicates` merges
  `(company, language-stripped title)` groups to one UK-preferred representative —
  the same role posted to N locations / language variants that exact-body dedupe
  misses.
- Output: `corpus/filtered/filtered_{date}.jsonl` (survivors, JDRecords only) +
  a stdout report (raw / dupes / screen pass / collapsed / survivors; drop reasons;
  kept by company / role bucket / location bucket).
- Pipeline: re-collect (+meta) → clean → dedupe → **filter** → label (Batch, Tier 4,
  meta passed as prompt context) → validate → score.

**First live cut (2026-06-09):** 2,507 raw → 116 exact dupes → 2,391 unique →
screened → near-deduped → survivors written to `corpus/filtered/`. Three recall
bugs found by inspecting survivors/drops and fixed before locking the cut (Applied
AI Architect family; `architectu**re**`/`field engineer**ing**` boundary; US-state
remote). Re-run after seed-list expansion to widen coverage.

### Seed-list maintenance (parallel, low priority)

7 of 16 seeds 404'd (stale slugs): Greenhouse **Snowflake, Confluent, HashiCorp,
Criteo**; Lever **Hugging Face, Cohere, Scale AI**. Criteo (AdTech — a *strong*
domain) is worth recovering (likely moved ATS). Find current slugs and re-collect
to widen coverage after the filter approach is proven.

---

## Conventions (unchanged — see CLAUDE.md)

Docker only; Batch API only for labelling (never synchronous); BeautifulSoup only;
JSONL only, append-only, never migrate in place; CLI writes / UI reads; tests in
`tests/` after every step; commit+push per step with the Co-Authored-By trailer;
keep the nearest `CLAUDE.md` current.
