# scoring/ — conventions (Phase 2 Scoring Engine)

Rule-based scorer. Consumes a `JDRecord`'s **extraction** fields + a `Profile`
and emits one `ApplicationRecord` per JD. See `docs/job_radar_PHASE2_PLAN.md`
(authoritative) and `docs/job_radar_SPEC.md §6`.

## Hard rules

- **Scorer reads JDRecord *extraction* only.** Never read or write JDRecord's
  legacy annotation stub (`fit_score`, `applied`, `blocking_constraints`, …).
  Scoring output goes to `ApplicationRecord` exclusively (Option A).
- **Pure functions.** `scorer.py` does no IO — load/glob/write live in `score.py`.
  `score(jd, profile, scored_at, mode=None)` is deterministic given its inputs;
  `scored_at` is injected (never `datetime.now()` inside the scorer) so tests and
  re-runs are reproducible.
- **CLI writes, never mutates.** `score.py` writes `corpus/scored/scored_{ts}.jsonl`
  and never touches the validated JDRecord inputs.
- **Profile enums are schema enums.** Every enum-bound profile field is validated
  against `models/record.py` (`ROLE_TYPE`, `SENIORITY`, `DOMAIN`,
  `TECHNICAL_DEPTH`, `REMOTE_POLICY`, `DELIVERY_MOTION`) at load time. An off-enum
  profile is a loud `ProfileError`, not a silent miss.

## Schema version split (v1.3, Option A)

`SCHEMA_VERSION = "1.3"` is the project version and tags `ApplicationRecord`.
`JDRECORD_SCHEMA_VERSION = "1.2"` stays frozen — the existing JD corpus is **not
migrated** (CLAUDE.md: append-only). A v1.2 line is a JDRecord; a v1.3 line is an
ApplicationRecord. Don't collapse the two constants.

## Scoring model — gates vs signal (Option A+B, 2026-06-09)

The original flat model (5 equal 0–2 dims, summed) gave **no resolution** on a
curated corpus: seniority and location saturated at max for every realistic JD,
so 4 of 5 dimensions did almost no discriminating work and ~everything became
`strong_fit`. The redesign splits dimensions into **signal** (sets the scale) and
**gates** (penalties only). See `docs/job_radar_SPEC.md §6.5` and the calibration
principle in §6.

**Stage 1 — structural fit → `fit_score` 1–10.**

*Signal* (the three discriminating dimensions, weighted to max 10):
- `role` ×2 — binary: 2 if `role_type ∩ target_roles`, else 0 (max 4).
- `domain` ×2 — 2 strong, 1 adjacent, **0.5 lower_priority**, 0 none (max 4).
- `technical_depth` ×1 — 2 if in `target_technical_depth`, **0.5 if in
  `acceptable_technical_depth`**, 0 else (max 2). Secondary/coarser, so ×1.

*Gates* (table stakes — a hit contributes **0**, a miss subtracts; never inflate):
- `seniority` — **binary**, no partial credit: in `target_seniority` → pass (0);
  else → −`SENIORITY_MISS_PENALTY` (3). (The old "within one rank" tier is gone.)
- `location` — pass (0) if remote OR base-city (any policy); `unclear` (−1) if
  hybrid/`not_stated` with no city; `fail` (−3) if a named non-base city or
  non-base onsite. Base-city onsite still passes — the candidate lives there;
  `relocation: false` is encoded by penalising named non-base cities.

`fit_score = clamp(1..10, round_half_up(signal − seniority_penalty − location_penalty))`.
`round_half_up` (6.5 → 7), not Python's banker's `round`.

**Stage 2 — `blocking_constraints` + `requirement_gaps`** over a lowercased
haystack (`required_*` + `nice_to_have_*` + `raw_observations` + `raw_text`).
- `blocking_constraints` = generic **scorer-owned** regex (clearance, native/
  fluent non-English language, visa/citizenship — conservative; the language rule
  needs a native/fluent qualifier adjacent to a named language so "French market"
  doesn't trip) **plus the capability blocker** (below).
- **Capability blocker — Stage 2 overrides a misleadingly high Stage 1.** A
  hands-on role that mandates a specialist stack the candidate can't execute is
  not feasible however well the enums line up (the Databricks calibration case:
  SA + AI Platform match, but required Spark/SQL/Databricks/multi-cloud hands-on).
  Fires only when: `hands_on ∉ target_technical_depth` (candidate isn't a hands-on
  specialist) **and** JD `technical_depth == "hands_on"` **and** `≥
  UNMET_REQUIRED_THRESHOLD` (3) of `required_technologies` are unmet by the
  candidate's `proficient_technologies` (skills strong+developing; *familiar*
  excluded — it doesn't clear a hands-on bar). It is emitted as a
  `blocking_constraint`, so Stage 3's existing label logic demotes the role. The
  depth gate is what spares hybrid/leadership roles with unmet stacks (Writer,
  Fin) — the candidate would lead, not execute.
- `requirement_gaps` (soft): the profile's `requirement_gap_watchlist` says
  **WHAT** to watch; `_GAP_TRIGGERS` says **HOW**. Keyed by exact phrase — reword
  in the profile and the trigger stops firing (update both together). A gap also
  surfaced as a blocking constraint is dropped (no double-count).

**Stage 3 — `fit_label` + `fit_label_reason` + `priority_score`.**
- Label ladder (order matters): blocked_fit (blocker & fit≥7) → strong_fit
  (≥8, no blocker) → good_fit (≥6, no blocker) → stretch (≥5, incl. 6–7 with a
  blocker) → interview_practice (≥3) → income_bridge (≤2).
- `priority_score` = `fit_score`, `+1` if `company_stage` in `{seed, series_a,
  series_b}` (PHASE2_PLAN wrote "startup", but that is a `company_size_signal`
  value — `seed` is the `company_stage` equivalent), `-2` if any blocker, `+1` to
  low-fit (≤4) in `broad` mode, clamped 1–10.
- `fit_label_reason` is one templated sentence — the three signal phrases, any
  failed gate in parentheses, then the top blocker (else top gap).

## Provisional, evidence-calibrated values

Penalty magnitudes (`*_PENALTY`), the `UNMET_REQUIRED_THRESHOLD`, and the
Stage-3 `fit_label` thresholds are **provisional**. They are tuned against a
corpus that deliberately includes **negative JDs** (roles that *should* score low
or block) — discrimination is validated against examples, not assumed. The
`UNMET_REQUIRED_THRESHOLD = 3` currently isolates Databricks (6 unmet) from
JP Morgan (2) / Mistral (1). `fit_label` thresholds are NOT finalised until the
negative-calibration corpus is in place. When you change a value, update the
table above and the affected `tests/test_scorer.py` case in the same edit.

## search_mode is presentation, not scoring

The scorer is constant. `search_mode` (`selective`/`active`/`broad`) only changes
which labels are *shown* — that filter lives in `score.py` (`is_shown`, `_HIDDEN`,
`_SEPARATE`, the §6.3 table), plus the one documented broad-mode priority nudge.
`--mode` overrides the profile's mode for a run; `--min-fit` is a presentation
filter on top. The scored file always contains **every** record — filtering never
drops rows from the durable artifact.
