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

## Scoring model (the three stages)

**Stage 1 — structural fit → `fit_score` 1–10.** Five dimensions, each 0–2
(domain can be 0.5), summed and `max(1, min(10, round(raw)))`.
- `role`: binary — 2 if `role_type ∩ target_roles`, else 0.
- `seniority`: 2 if in `target_seniority`; 1 if within one rank on the
  `ic<senior_ic<lead<manager<director<vp<exec` ladder; else 0.
- `technical_depth`: 2 if in `target_technical_depth`; 1 if in
  `acceptable_technical_depth`; else 0.
- `domain`: 2 strong, 1 adjacent, **0.5 lower_priority**, 0 none (best match wins).
- `location`: 2 if remote OR JD location contains the profile base city (London,
  any policy); 0 if onsite non-base; for hybrid/`not_stated`, 1 if the city is
  unclear/`not_stated`, else 0. Base-city onsite still scores 2 — the candidate
  already lives there. `relocation: false` is encoded by *not* rewarding named
  non-base cities.

**Stage 2 — `blocking_constraints` + `requirement_gaps`** over a lowercased
haystack (`required_*` + `nice_to_have_*` + `raw_observations` + `raw_text`).
- `blocking_constraints`: generic, **scorer-owned** regex (NOT in the profile) —
  security clearance, native/fluent non-English language, visa/citizenship.
  Deliberately conservative: the language rule requires a native/fluent qualifier
  adjacent to a named language so "French market" does not trip it.
- `requirement_gaps`: the profile's `requirement_gap_watchlist` says **WHAT** to
  watch; `_GAP_TRIGGERS` in the scorer defines **HOW** to detect each phrase.
  Triggers are keyed by the exact watchlist phrase — reword a phrase in the
  profile and its trigger stops firing (intentional; update both together). A gap
  already surfaced as a blocking constraint is dropped (no double-count).

**Stage 3 — `fit_label` + `fit_label_reason` + `priority_score`.**
- Label ladder (order matters): blocked_fit (blocker & fit≥7) → strong_fit
  (≥8, no blocker) → good_fit (≥6, no blocker) → stretch (≥5, incl. 6–7 with a
  blocker) → interview_practice (≥3) → income_bridge (≤2).
- `priority_score` = `fit_score`, `+1` if `company_stage` in `{seed, series_a,
  series_b}` (PHASE2_PLAN wrote "startup", but that is a `company_size_signal`
  value — `seed` is the `company_stage` equivalent), `-2` if any blocker, `+1` to
  low-fit (≤4) in `broad` mode, clamped 1–10.
- `fit_label_reason` is one templated sentence from the dimension phrases plus the
  top blocker (else top gap).

## search_mode is presentation, not scoring

The scorer is constant. `search_mode` (`selective`/`active`/`broad`) only changes
which labels are *shown* — that filter lives in `score.py` (`is_shown`, `_HIDDEN`,
`_SEPARATE`, the §6.3 table), plus the one documented broad-mode priority nudge.
`--mode` overrides the profile's mode for a run; `--min-fit` is a presentation
filter on top. The scored file always contains **every** record — filtering never
drops rows from the durable artifact.

## Tuning

Heuristics (rank ladder, domain 0.5, location rules, regex sets, label
thresholds) are intended to be tuned against real scored output. When you change
one, update the table above and the affected test in `tests/test_scorer.py` in the
same edit — the tests encode the current contract.
