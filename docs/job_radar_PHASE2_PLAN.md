# job_radar_PHASE2_PLAN.md — Scoring Engine build plan & locked decisions

**Status:** Phase 1 complete (Steps 0–9, 95 tests, all on `origin/main`).
Phase 2 started: `candidate_profile.yaml` created, reviewed, and finalised
(enum-clean). **Scorer not yet built** — this doc is the handoff to build it.

This is the authoritative plan for the Phase 2 scorer. Read it with
`docs/job_radar_SPEC.md §6` (the spec) — where this doc and the spec differ,
the differences are deliberate and noted below.

---

## LOCKED DECISION — output model (Option A)

Decided by Michel, 2026-06-09:

- **Add an `ApplicationRecord` dataclass now** as the scorer's output model.
  Scoring output is personal assessment / workflow state, NOT JD extraction —
  it belongs in its own record.
- **Do NOT migrate annotation fields out of `JDRecord` in this step.** `JDRecord`
  remains the validated extraction artifact; its Phase 1 annotation fields are
  now **legacy/stub** — the scorer must NOT read or write them.
- **Do NOT introduce `JobPosting` yet.** Full three-layer split
  (`JDRecord` / `JobPosting` / `ApplicationRecord`) is a separate, explicit
  cleanup step AFTER scoring is proven.
- **Bump `SCHEMA_VERSION` → `"1.3"`** — the project schema now includes a new
  record type and new scorer output fields. Update `models/record.py` and
  `docs/CORPUS_FINDINGS.md §1.1` together (CLAUDE.md tie-break rule).
- **Rule going forward:** from Phase 2 on, new scoring/annotation output is
  written ONLY to `ApplicationRecord`. The annotation fields on `JDRecord` are
  not used by the scorer. Temporary duplication is acceptable under this rule.

### ApplicationRecord output fields (exact)

```python
job_id: str               # links to JDRecord.id
profile_version: str      # candidate_profile.yaml profile_version used
scored_at: str            # ISO datetime the score was produced (staleness vs profile updates)
fit_score: int            # 1–10 (Stage 1)
fit_label: str            # Stage 3 taxonomy (enum below)
fit_label_reason: str     # one sentence, shown in UI
requirement_gaps: list[str]
blocking_constraints: list[str]
priority_score: int       # 1–10 (fit + urgency adjustments)
application_status: str   # lifecycle enum; scorer always emits "new"
notes: str                # free-form, "" from scorer
```

New enums to add to `models/record.py`:
- `FIT_LABEL = {strong_fit, good_fit, stretch, blocked_fit, interview_practice, income_bridge}`
- `APPLICATION_STATUS = {new, review, shortlisted, applied, interviewing, offer, rejected, archived}` (Phase 3 lifecycle; scorer emits `new`)

Add `validate_application_record()` (mirror of `validate()`): enum checks on
`fit_label`/`application_status`, ranges on `fit_score`/`priority_score` (1–10),
list-of-str on gaps/constraints, `schema_version == "1.3"`.

---

## Files to build

| File | Purpose |
|---|---|
| `models/record.py` | Add `ApplicationRecord` dataclass + `to_jsonl`/`from_jsonl`/`to_dict`/`from_dict`, `FIT_LABEL`, `APPLICATION_STATUS`, `validate_application_record()`. Bump `SCHEMA_VERSION = "1.3"`. |
| `scoring/__init__.py` | package marker |
| `scoring/profile.py` | load + **validate** `candidate_profile.yaml` against schema enums |
| `scoring/scorer.py` | pure 3-stage scoring → ApplicationRecord (or a ScoreResult merged into one) |
| `score.py` | CLI: `--input`, `--min-fit`, `--mode` → `corpus/scored/scored_{ts}.jsonl` |
| `scoring/CLAUDE.md` | nested conventions (scoring logic, profile contract) — per hierarchy |
| `corpus/scored/.gitkeep` | output dir skeleton (already created in prep) |
| `tests/test_profile.py`, `tests/test_scorer.py`, `tests/test_score.py` | tests |

Run via Docker only: `docker compose run --rm job-radar python -m pytest -q`.

---

## candidate_profile.yaml structure (IMPORTANT — richer than spec §6.4)

The finalised profile is structurally richer than the spec §6.4 example. The
loader/scorer must read THIS structure (tie-break: the artifact wins). All
enum-bound values are valid against `models/record.py` (verified).

Enum-bound (used for Stage-1 matching):
- `candidate.target_roles.primary` — list of `ROLE_TYPE`
- `candidate.target_seniority` — list of `SENIORITY`
- `candidate.target_delivery_motion` — list of `DELIVERY_MOTION` (narrative only; not a Stage-1 dim)
- `candidate.target_technical_depth` — list of `TECHNICAL_DEPTH` (full match)
- `candidate.acceptable_technical_depth` — list of `TECHNICAL_DEPTH` (partial match)
- `candidate.location.base` (str), `candidate.location.acceptable_remote_policy` (list of `REMOTE_POLICY`), `candidate.location.relocation` (bool)
- `candidate.domains.strong` / `.adjacent` / `.lower_priority` — lists of `DOMAIN`

Free-text (used for Stage-2 gaps / signals, fuzzy/substring — NOT enum-bound):
- `candidate.career_patterns`, `candidate.skills.{technologies,competencies}.{strong,developing,familiar}`,
  `candidate.experience_anchors`, `candidate.requirement_gap_watchlist`,
  `candidate.positive_signals`, `candidate.negative_signals`

`profile_version` + `last_updated` are required top-level fields.

---

## Scorer design (proposed heuristics — tunable, document choices in scoring/CLAUDE.md)

Consumes `JDRecord` **extraction fields** + profile. Never reads JDRecord
annotation stub.

### Stage 1 — Structural fit → `fit_score` (1–10)
5 dimensions, each 0–2, summed (raw 0–10), clamped/rounded to 1–10.

| Dim | 2 | 1 | 0 |
|---|---|---|---|
| role_match | JD `role_type` ∩ `target_roles.primary` | — | no intersection |
| seniority_match | JD `seniority` ∈ `target_seniority` | within one rank of target set | otherwise |
| technical_depth_match | JD `technical_depth` ∈ `target_technical_depth` | ∈ `acceptable_technical_depth` | otherwise |
| domain_match | JD `domain` ∩ `domains.strong` | ∩ `adjacent` (use **0.5** for `lower_priority`) | no match |
| location_match | remote; or London (base) any policy | hybrid + city unclear/not_stated | onsite/hybrid non-London (relocation:false) |

Seniority rank order: `ic < senior_ic < lead < manager < director < vp < exec`.
`fit_score = max(1, min(10, round(raw)))`.

### Stage 2 — `blocking_constraints` + `requirement_gaps`
Scan a haystack = lowercased JD `required_competencies` + `required_technologies`
+ `nice_to_have_*` + `raw_observations` + `raw_text`.
- **blocking_constraints** — generic, scorer-owned regex rules (NOT in profile):
  security clearance; native/fluent non-English language requirement;
  citizenship / no-sponsorship. Keep conservative (avoid false positives like
  "French market").
- **requirement_gaps** — driven by `profile.requirement_gap_watchlist`. Define a
  detection trigger (regex) per watchlist phrase in the scorer (the profile says
  WHAT to watch; the scorer defines HOW to detect). Exclude any gap already
  captured as a blocking_constraint (no double-count).

### Stage 3 — `fit_label` + `fit_label_reason` + `priority_score`
```
has_block = bool(blocking_constraints)
if has_block and fit_score >= 7:  blocked_fit
elif fit_score >= 8 and not has_block:  strong_fit
elif fit_score >= 6 and not has_block:  good_fit
elif fit_score >= 5:  stretch          # incl. 6–7 with a blocker
elif fit_score >= 3:  interview_practice
else:                 income_bridge     # <= 2
```
`fit_label_reason`: one templated sentence from the dimension results + top
blocker/gap.
`priority_score`: start from `fit_score`; `+1` if `company_stage` early-stage
(`startup`/`series_a`/`series_b`); `-2` if any blocking_constraint; in `broad`
mode `+1` to low-fit (≤4) so they surface; clamp 1–10.

`search_mode` filtering (§6.3) lives in `score.py` presentation / `--mode`, not
in the score itself. Filter table per spec §6.3.

---

## score.py CLI
```bash
python score.py --input "corpus/validated/validated_*.jsonl"
python score.py --input "corpus/validated/validated_*.jsonl" --min-fit 6
python score.py --input "corpus/validated/validated_*.jsonl" --mode active
```
- Default `--input`: `corpus/validated/validated_*.jsonl` (spec §6.8's
  `corpus/labelled/validated_*` path is STALE — Step 8 writes to
  `corpus/validated/`).
- `--mode` overrides profile `search_mode` for the run.
- Output: `corpus/scored/scored_{ts}.jsonl`, one ApplicationRecord per JDRecord,
  `application_status: "new"`. Do NOT mutate validated JDRecord files.
- Print: count scored, fit_label distribution, count shown vs filtered at the
  active mode.

---

## Verification (Phase 2 scorer step)
- Profile loads + validates; invalid enum value → clear error.
- Scorer runs on the 10 manual records; produces a plausible fit_label spread.
- ApplicationRecord round-trips (`to_jsonl`/`from_jsonl`) and
  `validate_application_record()` passes.
- `--min-fit` and `--mode` filter as expected; Tier/`search_mode` filter matches §6.3.
- Full suite green in Docker.

---

## Conventions (unchanged)
Docker-only; tests every step; commit+push per step (Co-Authored-By trailer in
CLAUDE.md/commit rule); append a Cross-Cutting Decision / Learning to
`docs/job_radar_LEARNINGS.md`; keep root `CLAUDE.md` lean and update the Phase 2
row + step table as you go. Repo: github.com/michelguillon/job-radar (push via
plain git).
