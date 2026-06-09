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

### The first design fork (decide before writing the filter)

**The raw records have no structured `title` or `location` to filter on.** The
collectors (`collectors/greenhouse.py` etc.) store only `raw_html` (JD body) +
`source_url` + `company` and **discard the ATS `title` and `location.name`
fields** the APIs return. Options:

- **(A) Enhance collectors to capture title + location, then re-collect.** The
  cleanest signal. Greenhouse/Lever/Ashby all return title + location structured.
  No API cost (public APIs). Question: where do they go? `JDRecord` has no title
  field and schema is locked — likely prepend "`<title> — <location>`" into
  `raw_text` (deterministic, also helps the labeller), or carry a sidecar. Mind
  the content-hash id (`pipeline.dedupe`) if `raw_text` changes shape.
- **(B) Filter on `raw_html`/`raw_text` content only** — grep the body for
  London/UK/remote + role keywords. No re-collect, but weaker: a JD body doesn't
  reliably state its city, and the title isn't in the body.

Recommendation: **(A)** — re-collect with title + location preserved, then the
filter (and downstream labelling) has clean signal. Confirm with Michel first.

### Filter design (to iterate on)

- **Location screen:** keep London / UK / remote-EU / remote-global; drop clearly
  non-workable (US-onsite, APAC-onsite, relocation-required). Be permissive on
  ambiguous (let the scorer's location gate handle nuance later).
- **Role screen:** keep titles matching the target families (Solutions *, Pre-Sales,
  AI Delivery, Partner SA, Product-in-relevant-context, GTM-adjacent); drop pure
  SWE / data-eng / recruiting / finance / ops. Keep it generous — better to label
  a few extra than miss a fit.
- Output a filtered JSONL + a **report of survivors by company / inferred role /
  location**, and iterate the thresholds against that before any labelling spend.
- Then: clean → dedupe → **filter** → label (Batch, Tier 4) → validate → score.

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
