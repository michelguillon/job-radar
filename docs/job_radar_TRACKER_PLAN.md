# job_radar_TRACKER_PLAN.md — Phase 3 Job Tracker (`track.py`) build plan

**Authoritative handoff for building the Job Tracker.** Read this with `CLAUDE.md`,
`docs/job_radar_SPEC.md §7`, and `docs/job_radar_LEARNINGS.md`.

> **Goal:** turn "a scored feed" into "a job search you're actually running" —
> a CLI to move opportunities through an application lifecycle and record outcomes,
> *without* the human's workflow state being wiped when the corpus is re-scored.

---

## Read first, in this order

1. `docs/job_radar_SPEC.md §7` — the Job Tracker spec (status lifecycle, `track.py`
   commands, `activity_log.jsonl`, outcome tracking). **This is what we're building.**
2. `CLAUDE.md` — conventions, phase/state tables, deviations (1–22). Note the
   **Definition of done** block: SPEC + LEARNINGS + nearest CLAUDE.md updated in the
   *same* change as code+tests, every task. Not optional.
3. `models/record.py` — `ApplicationRecord` (the scored record the tracker manages)
   + its `_APPLICATION_FIELDS`, `APPLICATION_STATUS` enum, `validate_application_record`.
4. `score.py` + `scoring/scorer.py` + `scoring/CLAUDE.md` — how `ApplicationRecord`s
   are produced. **Critical:** the scorer is **pure and regenerates every record from
   scratch** (`application_status` always emitted as `"new"`, `notes` as `""`). This
   is the heart of the design problem below.
5. `docs/job_radar_LEARNINGS.md` — esp. Learning 14 (one dataclass, two serialisation
   shapes), the "CLI writes; UI reads" cross-cutting decision, Learnings 20–22
   (production scoring, extraction fix). Carry these forward.
6. The existing CLIs as patterns: `validate.py`, `stats.py`, `tier2_review.py`
   (injectable IO + resumable), `prefilter.py`.

---

## Where we are (end of the previous conversation)

Phase 1 ✅ and Phase 2 ✅ (scorer **v1 locked**). Phase 3 corpus pipeline is built
and exercised end-to-end on real data:

- **Collection + sidecar:** collectors emit `CollectedJob` (record + metadata
  sidecar `corpus/raw/meta_{date}.jsonl`); `raw_text` stays employer text only.
- **Pre-label filter:** `prefilter.py` (location + role screens, near-dedupe) →
  `corpus/filtered/`. **GTM/partner observation watchlist** diverts that class to
  `corpus/watchlist/` (no scoring; gathering evidence before GTM becomes a target_role).
- **Labelling:** `label.py --meta` passes the sidecar as an `[ATS METADATA]` prompt
  block; `clean_readable` populates `raw_text`. Extraction prompt tightened to fix
  Known Limitation F (Product-Marketing→GTM, no Enterprise-Software default).
- **First production run, promoted:** 44 records labelled + scored (tightened prompt)
  live in `corpus/{labelled,validated,scored}/`. fit_label spread: strong_fit 16 ·
  stretch 4 · blocked_fit 9 · good_fit 2 · interview_practice 11 · income_bridge 2.
  First-run (pre-fix) archived at `corpus/_recal/prod_firstrun/`. Calibration baseline
  locked at `corpus/calibration/validated_*.jsonl`.

Every `ApplicationRecord` currently has `application_status="new"` — nothing
transitions it. **`track.py` does not exist.** That is this build.

---

## The task

1. **Spec `track.py` first → share for review BEFORE building.** The central design
   problem (below) has real forks; resolve them with Michel before code.
2. Then build: `track.py` + tests (Docker), per-step commits with the Co-Authored-By
   trailer, SPEC §7 + LEARNINGS + CLAUDE.md updated in the same change. Push via plain git.

---

## The central design problem — workflow state must survive a re-score

`score.py` **regenerates** every `ApplicationRecord` from scratch on each run (pure,
deterministic scorer; writes a fresh `corpus/scored/scored_{ts}.jsonl`). So if the
tracker writes `application_status="applied"` (or notes, application_date, outcome)
*into* a scored record, the next collection→label→score cycle produces a new record
with `status="new"` and **wipes the human's workflow state.**

SPEC §7.4 as written says track.py "Updates ApplicationRecord in `corpus/scored/`"
*and* "Appends to `corpus/activity_log.jsonl`" — which is in tension with the pure,
regenerable scorer. **Resolving this is the spec's main job.** Options:

- **(A) Separate workflow store.** Keep `ApplicationRecord` pure (score only; status
  always `"new"`). Workflow state lives in its own artifact keyed by `job_id`
  (`corpus/tracker/…`). The UI/tracker *joins* score + workflow by `job_id`. Cleanest
  separation; the scorer never owns mutable human state.
- **(B) Merge on re-score.** `score.py` carries forward `application_status` / `notes`
  / `application_date` by `job_id` from the previous scored file when regenerating.
  One record holds score + workflow, but it couples the pure scorer to mutable state.
- **(C, recommended) Append-only event log as source of truth.**
  `corpus/activity_log.jsonl` is an append-only event stream
  (`{ts, job_id, event, value, notes}`). A job's *live* state = its score (regenerable
  from `scored_*.jsonl`) **+** the latest workflow projection from the log by `job_id`.
  `track.py` only ever *appends* events (never mutates a scored file); re-scoring is
  safe because the log is independent of the scorer and re-projected on read. This
  honours every convention (append-only, CLI-writes, scorer-pure, JSONL) and gives a
  free audit trail. **Recommend (C); confirm with Michel.**

**Stable join key:** `job_id` is the JD content hash. If a JD's text changes it gets
a *new* hash → new `job_id` → workflow won't carry to the new version (it's a
different posting revision). Flag this as accepted behaviour, not a bug.

---

## SPEC §7 requirements to implement

- **Status lifecycle (§7.2):** `new → review → shortlisted → applied → interviewing →
  offer / rejected → archived` (enum `APPLICATION_STATUS`, already in `models/record.py`).
  Decide which transitions are legal vs free-form.
- **`track.py` CLI (§7.4):**
  ```
  track.py --job-id sha256:abc --status applied
  track.py --job-id sha256:abc --status interviewing --notes "First round booked"
  track.py --job-id sha256:abc --outcome rejected_post_screen
  track.py list --status shortlisted
  track.py list --min-fit 7 --location-workable yes
  ```
  `list` joins the live state (score + workflow) and prints a review table (title from
  the sidecar by `source_url`; fit_score/label/priority from the score).
- **`corpus/activity_log.jsonl` (§7.4):** append-only audit trail, never edited.
- **Outcome tracking (§7.3):** `outcome` + `outcome_notes` (enum: `rejected_pre_screen`
  | `rejected_post_screen` | `rejected_interview` | `rejected_final` | `offer_declined`
  | `offer_accepted` | `withdrew`). Spec whether these live on `ApplicationRecord`
  (schema bump) or only in the log/workflow store. **Note:** the actual
  predict-vs-outcome calibration analysis is **deferred until 20+ completed
  applications** — build the capture, not the analysis.

---

## Design questions to resolve in the spec (the forks)

1. **State model: A / B / C** (above). Recommend C.
2. **Schema:** does `ApplicationRecord` gain `outcome`/`outcome_notes`/`application_date`
   (→ bump `SCHEMA_VERSION`, append-only per CLAUDE.md), or do those live only in the
   workflow store / log? (If C, prefer log/store and keep `ApplicationRecord` pure.)
3. **Transition rules:** enforce the lifecycle order, or allow any status set with a
   warning? (`tier2_review.py` is a precedent for a simple, forgiving CLI.)
4. **`list` view contract:** what columns, what default sort (priority? fit?), and how
   it composes with the existing §6.3 `search_mode` presentation filters in `score.py`.
5. **Reproducibility:** inject the clock (no `datetime.now()` inside logic) and IO, as
   `scorer.py` / `tier2_review.py` do, so tests are deterministic.

---

## Conventions (unchanged — see CLAUDE.md)

Docker only (`docker compose run --rm job-radar python …`); JSONL only, **append-only,
never migrate in place**; **CLI writes / UI reads**; tests in `tests/` after every
step; **commit + push per step** with the `Co-Authored-By: Claude Opus 4.8 (1M
context)` trailer; **keep SPEC + LEARNINGS + nearest CLAUDE.md current in the same
change** (definition of done). Push via plain git (user owns the GitHub repo).

**Do not touch the scorer** (locked until the 100+-scored-job structured review) and
**do not add GTM to `target_roles`** (watchlist is gathering that evidence). The
tracker reads scores; it does not change scoring.

---

## Parallel / later (not this build)

Corpus to 500+ validated; widen seeds (recover the 7 stale 404 slugs incl.
Criteo/AdTech); weekly extraction-quality review; structured scorer review at 100+
scored jobs; watchlist review at ~50–100 observations.
