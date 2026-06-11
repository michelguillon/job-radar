# job_radar_RETROSPECTIVE.md — job-radar

> **This document captures what happened during the build.**
> **For the implemented system, see `job_radar_ARCHITECTURE.html`.**
> **For reusable lessons, see `job_radar_LEARNINGS.md`.**

**Build period:** 2026-06-07 to 2026-06-10 (Phases 1–5; Phase 6 in progress)
**Status:** Complete through Phase 5. Phase 6 retrospective to be added post-build.

---

## What I Thought I Was Building

A CLI data pipeline that collects job descriptions from public ATS APIs,
labels them with Claude, and produces a fine-tuning corpus.

The original scope was called "jd-refinery" — a data engineering project
whose output was a structured JSONL corpus. The schema seemed
straightforward: role type, seniority, required skills, domain, remote
policy. A few fields, a clear structure. The interesting problem was the
labelling pipeline — Batch API, cost tracking, eval set construction.

The implicit assumption: the corpus was the product.

---

## What I Actually Built

A personal job search intelligence system that I use daily. The corpus
is infrastructure for something useful, not the product itself.

What exists after Phases 1–5:

- A multi-source collection pipeline (Greenhouse, Lever, Ashby APIs)
  with incremental collection, SHA-256 deduplication, and a pre-label
  filter that cuts noise before spending on the Batch API
- A 17-field extraction schema validated on 10 real JDs before any
  automation ran — a schema that changed 10 times and is provably
  better for it
- A three-stage rule-based scorer (structural fit → blocking constraints
  → opportunity classification) with a fit_label taxonomy, conditional
  role matching for Product roles, and a search_mode that adapts to
  urgency without touching the scorer
- A calibration corpus of 23 records (10 positive anchors, 13
  calibration negatives) with pinned regression tests
- An append-only event log tracker (Model C) that survives re-scores
  because workflow state and scoring output are deliberately separate
- A daily digest with a since-cursor, a weekly cron pipeline, and a
  static read-only UI that surfaces scored roles for morning review
- A production scoring run: 53 records, capability blocker validated on
  real data, first false-positive class identified and fixed at source

---

## What Changed

### The product framing changed completely

"jd-refinery" became "job-radar" mid-build after recognising that a
corpus builder is not a useful daily tool. The pipeline code didn't
change. The architecture documentation was rewritten. The same Phase 1
build survived a complete product reframe — which was itself a
validation of the data-layer-first approach.

### The schema changed 10 times before automation ran

The original seed schema had 9 fields. After 10 manually-labelled JDs,
the schema had 17 extraction fields. Every change was triggered by a
real JD, not by upfront reasoning:

- `required_skills` → 4 fields (technologies / competencies ×
  required / nice-to-have)
- `delivery_motion` added as a first-class dimension (how value is
  delivered, orthogonal to role type)
- `leadership_geography` added for EMEA scope signal
- `application_decision` replaced `applied: bool` — fit score and
  application decision are orthogonal
- `culture_signals` added after several JDs revealed that verbatim
  cultural language is meaningful signal

### The scorer went through 5 substantive revisions before calibration held

The first scorer version had five equal-weight dimensions and produced
a score floor of 7–8 for every realistic JD. Four of five dimensions
didn't discriminate. The fix wasn't threshold tuning — it was
architectural: seniority and location became gates (penalise a miss,
contribute 0 on a hit) and role, domain, and technical depth became
the discriminating signal. Then: conditional Product role scoring,
language blocker regex fix, M&A blocking constraint, domain list
narrowing, location gate hardening against deceptive title/body
mismatches. Each fix came from calibration evidence, not assumption.

### VC boards turned out to be useless with BeautifulSoup

Every major VC portfolio board (Balderton, Atomico, Index Ventures) runs
on Consider, Getro, or a custom React SPA. BeautifulSoup gets nothing.
The decision was to mark all boards `requires_js`, build a skeleton that
logs skips cleanly, and defer VC board scraping to Phase 4. The "manually
inspect 2 boards before building" gate was the right call — it surfaced
the problem before any code was written.

### The extraction prompt is generated from the executable schema

The original approach was a hand-written prompt with a copy of the enum
vocabulary. The build discovered that three copies of the schema
(CORPUS_FINDINGS.md, models/record.py, and the extraction prompt) diverge
silently. The fix was to generate the closed-vocabulary section of the
extraction prompt directly from the models.record enums. Add a value to
the schema and the prompt updates itself.

### The tracker design was resolved before any code was written

The scorer regenerates every ApplicationRecord from scratch on each run.
Workflow state (applied, interviewing, shortlisted) must survive re-scores.
Three options were considered and one (Model C — append-only event log)
was chosen explicitly before implementation. The log-only fork meant
outcome and application_date are derived at read time, never persisted.
The result: a join architecture where live state = latest score +
projection from the log. This design decision took 30 minutes to resolve
and saved what would have been a significant bug in production.

---

## Biggest Wins

**1. Schema discipline before automation.** Validating the schema on 10
real JDs before writing any collector code was the highest-leverage
decision in the project. The schema that emerged was unforeseeable from
first principles. Every hour spent on manual labelling paid for itself
many times over in avoided rework.

**2. The capability blocker.** Splitting same-named roles by feasibility
— Databricks "Deployment Strategist" (hybrid → strong_fit) vs Mistral
"AI Deployment Strategist–UK" (hands-on → blocked_fit) — is the scorer's
most useful feature on real data. It's not a threshold; it's a structural
rule that reflects how Michel's profile actually works.

**3. Calibration from negatives.** Adding 13 deliberately negative JDs
exposed 5 scorer bugs (A–E) and one extraction quality bound (F). Not
one of the failures was fixed by moving a threshold. Each was a specific
rule. The calibration corpus approach — "a scorer is only as trustworthy
as the negatives that prove it discriminates" — is reusable across any
rule-based ranking system.

**4. Model C tracker.** The append-only event log with log-only derivation
was the right data model. It honors every convention (append-only, CLI-
writes, no in-place mutation) and gives a free audit trail. The design
has spare capacity: the next per-entity mutable attribute is a new event
kind plus one projected field, not a new table.

**5. Fixing extraction beat tuning the scorer.** Known Limitation F
(Enterprise Software catch-all, Product Marketing → Product) was fixed at
source in the extraction prompt. The scorer stayed locked. Domain:
"Enterprise Software" fell 27→10 in production records. One extraction
prompt fix did more for quality than any scorer rule change could.

---

## Biggest Mistakes

**1. The spec undersold the product.** "jd-refinery" described a corpus
builder. The system that was actually needed was a job search tool. The
corpus is infrastructure. This cost a respec mid-build, though it was
resolved before any code needed changing.

**2. The UI data contract was wrong on paper.** SPEC §9.4 described
`index.json` as "a flat array of validated records" (JDRecords). The
UI columns it asked for (`fit_label`, `fit_score`, `application_status`)
don't exist on a JDRecord. The real read model — the tracker's join —
had been built twice already. The spec prose was the bug, not the
consumer.

**3. VC boards were over-specced.** Eight VC boards listed in the spec,
selector config in YAML, BeautifulSoup scraping per board. Reality: every
board uses a React SPA. The spec should have said "verify manually before
speccing the scraper" — and it did say this, via the manual inspection
gate. The gate worked. But the earlier spec confidence was misplaced.

**4. The initial scorer was architecturally wrong.** Five equal-weight
0–2 dimensions with a summed score and a broad target list produces a
floor of 7–8 for every realistic candidate. This was predictable from the
design; it wasn't caught until the first calibration run. Sketch the
score distribution before implementing — if a scorer can't produce a
result below 6 for any realistic input, the architecture is wrong.

---

## Learning Shifts

### Before: the schema could be designed upfront

Fields were obvious: role type, seniority, required skills, domain.
Straightforward mapping from JD structure to data model.

### After: the schema that works is the one that survived contact with real data

10 JDs triggered 10 changes. The most significant was splitting
`required_skills` into 4 fields — technologies and competencies are
orthogonal dimensions a flat list conflates. `delivery_motion` wasn't
in the original design and turned out to be one of the most useful
dimensions for discriminating Michel's target roles.

---

### Before: scoring is a ranking problem — get the formula right

Five dimensions, equal weight, threshold tuning to taste.

### After: scoring is a discrimination problem — most dimensions don't discriminate

Four of five original dimensions were near-constant across all realistic
inputs. Seniority scored 2.0 on every record because the target band
covers most professional roles. The fix was architectural — not better
weights, but gates vs signals. Seniority became a gate (penalise a miss,
contribute 0 on a hit). Role, domain, and depth became the scale.

---

### Before: the corpus is the product

The corpus builder produces labelled JDs. That's useful. Ship it.

### After: the corpus is infrastructure for something useful

A corpus builder you don't use daily is a portfolio piece. A job search
tool you use every morning is a product. The same pipeline code serves
both framings. The difference is what you build on top of it.

---

### Before: calibration means testing the happy path

Validate the scorer on roles you'd apply to. Check it scores them right.

### After: calibration requires adversarial negatives

A scorer calibrated only on positive examples optimises for "doesn't
reject things Michel would apply to." It has no discrimination signal.
Adding 13 deliberately wrong JDs (junior roles, pure sales, hands-on
engineering, wrong geography) exposed 5 bugs that positive-only testing
would never have found.

---

### Before: a rule-based scorer can be threshold-tuned to produce the right labels

Move the strong_fit cutoff up or down based on what feels right.

### After: threshold tuning is the last lever, not the first

Every calibration miss came from a specific rule, not a wrong threshold.
Thresholds set from evidence (where do genuine positives and negatives
actually cluster?) held without adjustment on the first production run.
The lesson: walk each miss back to the rule that produced it before
reaching for the threshold.

---

### Before: workflow state lives in the scored record

ApplicationRecord carries application_status. Update it when status changes.

### After: a pure regenerable artifact cannot own mutable human state

The scorer regenerates every ApplicationRecord from scratch. Any state
written into a scored record dies on the next re-score. The separation
(immutable pipeline output + append-only event log + join on read)
is not a clever pattern — it's the only correct one when one component
is pure and regenerable and another carries human input.

---

### Before: fix quality problems in the scorer

High-scoring false positives → tighten scoring rules.

### After: fix quality problems at their source

Enterprise Software catch-all domain inflating scores → fix the
extraction prompt. Product Marketing → Product role mapping → fix the
extraction prompt. Scorer stays locked. Upstream fixes are always
cheaper and more durable than downstream compensations.

---

## Top 10 Learning Shifts (summary)

1. **Schema discovery > schema design.** Label 5–10 real examples before
   designing any extraction schema. The schema that works is the one
   that survived contact with real data.

2. **Gates vs signals.** Dimensions that every realistic input satisfies
   are gates, not scoring dimensions. Seniority, location, and role type
   within a broad target are table stakes — they penalise misses but
   don't reward hits.

3. **Calibrate from negatives.** A scorer is only as trustworthy as the
   negatives that prove it discriminates. Build the adversarial corpus
   before setting thresholds.

4. **Threshold tuning is the last lever.** Every calibration miss was a
   rule, not a threshold. Walk failures back to their root cause before
   reaching for the cutoff slider.

5. **Fix quality at source.** Scorer stays locked when extraction is
   wrong. Upstream fixes are cheaper and more durable than downstream
   compensations.

6. **Pure artifacts can't own mutable state.** When one system regenerates
   an artifact from scratch, human state that must survive across runs
   belongs in a separate append-only log, projected on read.

7. **The corpus is infrastructure.** Build what you'll use daily, not
   what produces a portfolio artifact. The pipeline serves the product;
   the pipeline is not the product.

8. **Resolve the design fork before writing code.** The tracker fork
   (Model A/B/C) took 30 minutes to resolve explicitly. The alternative
   was discovering the bug in production.

9. **Conditional role scoring is non-binary.** Product roles are only
   good fits in specific domain+signal contexts. A binary primary/
   secondary split misses the structure. Conditional primary with domain
   and signal matching captures the real constraint.

10. **The spec prose is the thing to fix.** When the read model (the
    tracker's join) was already built and correct, and the spec described
    a different data contract, the spec was the bug. Fix the document,
    not the code.

---

## If I Did It Again

**Start with the product framing, not the pipeline framing.** "What
will I use this for every morning?" is a better starting question than
"what data does this produce?" The data model that emerged from the
corpus-builder framing was correct for the job-search-tool framing too.
But the spec had to be rewritten mid-build.

**Sketch the score distribution before implementing the scorer.** If
you can't construct a realistic input that scores below 6 with your
proposed model, the model is wrong before you've written a line.

**Build the calibration corpus before tuning, not after.** The 13
negative JDs exposed bugs that took 2 hours to fix. Finding them after
threshold-tuning would have taken longer and the fixes would have been
worse.

**VC boards: inspect before speccing.** The manual inspection gate in
the spec was correct. The confident spec language about 8 boards and
per-board YAML selectors was not. Verify the data source before
speccing the integration.

**The tracker design fork is a template.** Any time a pure regenerable
artifact and human mutable state need to coexist, the answer is
Model C: append-only event log, join on read, derive don't persist.
Write this pattern down before the next project that needs it.


---

## Post-Phase 6 — Backlog sprint

After Phase 6 shipped, the "use it and accumulate data" plan was abandoned in favour of building the full backlog while everything was fresh. This turned out to be the right call — the schema and code needed designing now, not after 4 weeks of usage when the context would have been lost.

**What shipped in the backlog sprint:**

- `cli/analyse.py` — 4-report read-only corpus reporting (score-distribution, status, companies, gaps). A pure reducer over the canonical read join — no new data, no new files, just the existing corpus viewed differently.

- Rejection reasons — a second use of the annotations sink, not a second sink. `annotation_type: rejection_reason` + `REJECTION_REASON` vocabulary. Taught the lesson: before adding an endpoint/file/schema, ask whether it's the same shape as an existing append-only log with a different meaning.

- Company metadata v2 — `domain`, `fit_hypothesis`, `action`, `notes` per company in `company_seeds.yaml`. Built now with best-guess values rather than waiting for usage data; the values evolve, the schema doesn't.

- Company yield tracking — `--report yield` in `cli/analyse.py` + `GET /api/report/yield` endpoint + React sidebar download button. The yield report surfaces which companies produce useful roles vs noise, joining seeds metadata with scored corpus + workflow state.

- Company universe v1.1 → v2 — 62 → 81 companies verified across Greenhouse/Ashby/Lever. AdTech, retail media, and customer data sectors added. `find_ats_slugs.py` probe script built and iterated through three generations to fix broken Lever and Ashby probes.

**The unexpected lesson from the yield report first run:**

The join was by exact company name. First live run put ~22 of 53 scored jobs under `(unknown)` because "Mistral" in the corpus didn't match "Mistral AI" in the seeds. The instinct to add a fuzzy matcher was wrong — the (unknown) bucket is the diagnostic. Fix the source of truth (seed names aligned to corpus strings), leave genuinely unmonitored records visible. The alias map hides the drift it should expose.

**The cron was never actually runnable:**

Running the first production pipeline end-to-end exposed that `cron/collect_weekly.sh` had never completed a full run. Every stage had `--input required=True` so bare invocation errored. The wrapper was written and documented but never executed. The first real run is the test — treat any wrapper that hasn't been run end-to-end as documentation, not automation.

