# SPEC_LANGFUSE_INSTRUMENTATION.md
## Langfuse Instrumentation — cv-tailor + Job Radar

**Status:** Phase A (cv-tailor) ✅ verified live 2026-06-12 · Phase B (Job Radar) ✅ verified live 2026-06-13 · Phase C (per-role scoring traces) ✅ built 2026-06-14 (live verification pending on server)
**Prerequisite:** `SPEC_LANGFUSE_DEPLOYMENT.md` complete and healthy ✅
**Build order:** cv-tailor first ✅, Job Radar second ✅
**SDK version:** langfuse v4 — confirmed `langfuse==4.7.1` in both built images (`requirements.txt`: `langfuse>=4.0.0`)

> **Note:** This spec was originally written against SDK v2. All code blocks
> have been rewritten for SDK v4. The v4 SDK is OTel-based — the API is
> context manager and decorator driven, not object-chaining. The trace
> structure (section 2.2) is unchanged — only the Python code to produce it.

---

## 1. Instrumentation philosophy

**Every scoring decision is a first-class event.**

The core insight: a Job Radar trace should exist independently of whether
cv-tailor was ever run. Every scored role gets a trace — that trace is the
permanent record of "why did Job Radar say this?" The cv-tailor callback
enriches it later if and when it arrives. The divergence between the two
systems' verdicts on the same role is the evidence base for Phase 4.

This means two distinct trace points per role:

1. **At scoring time** (`cli/score.py`) — one trace per scored role, capturing
   the full scoring decision: all stages, all dimension scores, fit label,
   priority score, blocking constraints, requirement gaps. This is the
   independent Job Radar verdict, recorded whether or not cv-tailor ever runs.

2. **At cv-tailor callback receipt** — the existing Job Radar trace for that
   role is enriched with cv-tailor's scores. The divergence delta is computed
   and stored. Same trace, same role, both systems' verdicts visible together.

**What this is not:** a log of batch API calls. The batch is an implementation
detail. What matters is the scoring decision on each role, traceable back to
the individual stage outputs that produced it.

Add granularity only where gaps appear after a few weeks of data.
Over-instrumenting at the start adds maintenance cost before you know
what's useful.

**SDK v4 pattern:** `@observe()` decorator for cv-tailor. Manual post-hoc
observations for Job Radar (Batch API — results arrive async, traced after
the fact).

---

## 2. cv-tailor instrumentation

### 2.1 Project

One Langfuse project: `cv-tailor`. API keys from deployment setup.

### 2.2 Trace structure

Each cv-tailor run = one Langfuse trace. This is unchanged from the
original spec — only the code to produce it changes.

```
Trace: cv_tailor_run
  name = "cv_tailor_run"
  metadata = {
    run_id: "...",              ← stored in propagate_attributes, enables cross-system lookup
    mode: "demo" | "full",
    job_id: "sha256:..." | null,
    company: "Elastic" | null,
    job_radar_fit_label: "strong_fit" | null,
    job_radar_fit_score: 10 | null
  }

  Span: phase0_jd_analysis
    Generation: mistral_extraction
      model: "mistral-small" | "mistral-large"
      input: <JD text>
      output: <JDAnalysis JSON>
      usage: {input_tokens, output_tokens}

  Span: phase1_fit_assessment
    Generation: claude_fit_assessment
      model: "claude-sonnet-4-6" | "claude-haiku-4-5"
      input: <fit assessment prompt>
      output: <FitAssessment JSON>
      usage: {input_tokens, output_tokens}
    metadata = {
      outcome: "strong_fit" | "good_fit" | "partial" | "poor_fit",
      overall_fit_score: 0.72,
      cvcm_enabled: true
    }

  Span: phase2_cv_selection
    metadata = {
      candidates_evaluated: 3,
      selected_cv: "cv_director_2026.docx"
    }

  Span: phase3_refinement
    metadata = {iterations_run: 2, converged: true}

    Span: iteration_1
      Generation: claude_orchestrator
        model: "claude-sonnet-4-6"
        input: <orchestration prompt>
        output: <refinement decisions>
      Generation: haiku_section_rewrite  (0..N per iteration)
        model: "claude-haiku-4-5"
        input: <section + instructions>
        output: <rewritten section>
      metadata = {
        keyword_coverage: 0.35,
        critique_score: 7.2,
        sections_converged: 3,
        sections_active: 2
      }

    Span: iteration_2
      ... same structure ...

  Span: phase4_grounding
    Generation: claude_grounding_check
      model: "claude-haiku-4-5"
      input: <grounding prompt>
      output: <grounding result>
    metadata = {
      fabrication_flags: 0,
      grounded_coverage: 0.81
    }

  Span: phase5_cover_letter    (if generated)
    Generation: claude_cover_letter
      ...

  Span: phase6_final_assembly
    metadata = {
      output_format: "docx",
      sections_in_final: 8
    }

  Score: fit_score          = 0.56   (Phase 3 callback value)
  Score: coverage_score     = 0.35   (Phase 3 callback value)
  Score: cv_quality_score   = 8.1    (Phase 3 callback value)
  Score: job_radar_fit_score = 10    (from job_radar_source, if present)
```

### 2.3 SDK integration

Install:
```bash
pip install langfuse
```

Add to `requirements.txt`:
```
langfuse>=4.0.0
```

Create `tailor/telemetry.py` — initialises the client once and exposes
a helper to check if tracing is enabled. In SDK v4, `get_client()`
returns the global singleton; if no `LANGFUSE_PUBLIC_KEY` is set the
client is still returned but tracing is silently disabled.

```python
# tailor/telemetry.py
import os
from langfuse import get_client, Langfuse

def init_langfuse() -> None:
    """Initialise Langfuse client if credentials are present.
    Call once at app startup (e.g. in main or runner init).
    No-op if LANGFUSE_PUBLIC_KEY is absent — tracing disabled cleanly.
    """
    if os.getenv("LANGFUSE_PUBLIC_KEY"):
        Langfuse()  # initialises the global singleton

def is_enabled() -> bool:
    """Returns True if Langfuse credentials are configured."""
    return bool(os.getenv("LANGFUSE_PUBLIC_KEY"))
```

**Tracing is opt-in by config.** No `LANGFUSE_PUBLIC_KEY` in `.env` →
all `@observe()` decorators and context managers are no-ops. Tests run
without tracing. Production has it enabled. No mocking required.

### 2.4 Trace creation

In SDK v4, there is no explicit `lf.trace()` call. Instead, the root
`@observe()` decorated function *is* the trace. Trace-level metadata
is set via `propagate_attributes()`.

In `api/runner.py`:

```python
from langfuse import observe, propagate_attributes, get_client
from tailor.telemetry import is_enabled

@observe(name="cv_tailor_run")
def launch_run(run_id: str, job_radar_source: dict | None = None, mode: str = "demo", ...):
    # Set trace-level metadata — propagates to all child spans
    if is_enabled():
        with propagate_attributes(
            trace_name="cv_tailor_run",
            metadata={
                "run_id": run_id,
                "mode": mode,
                "job_id": job_radar_source.get("job_id") if job_radar_source else None,
                "company": job_radar_source.get("company") if job_radar_source else None,
                "job_radar_fit_label": job_radar_source.get("fit_label") if job_radar_source else None,
                "job_radar_fit_score": str(job_radar_source.get("fit_score")) if job_radar_source else None,
            }
        ):
            return run_pipeline(run_id, job_radar_source, mode, ...)
    else:
        return run_pipeline(run_id, job_radar_source, mode, ...)
```

> **v4 note on metadata values:** `propagate_attributes` requires
> `metadata` to be `dict[str, str]` — all values must be strings.
> Cast non-strings explicitly (e.g. `str(fit_score)`).

### 2.5 Phase spans

Each phase function gets an `@observe()` decorator. Because cv-tailor
phases are already separate functions, this is a one-line change per
phase. Child spans nest automatically via OTel context propagation.

```python
from langfuse import observe, get_client

@observe(name="phase0_jd_analysis", as_type="span")
def run_phase0(jd_text: str, ...):
    # instrument the Mistral call as a generation inside this span
    lf = get_client()
    with lf.start_as_current_observation(
        as_type="generation",
        name="mistral_extraction",
        model="mistral-small",
        input={"jd_text": jd_text},
    ) as gen:
        result = call_mistral(jd_text)
        gen.update(
            output=result,
            usage_details={"input_tokens": result.usage.input, "output_tokens": result.usage.output}
        )
    return result

@observe(name="phase1_fit_assessment", as_type="span")
def run_phase1(jd_analysis, cv_text, ...):
    lf = get_client()
    with lf.start_as_current_observation(
        as_type="generation",
        name="claude_fit_assessment",
        model="claude-sonnet-4-6",
        input={"jd_analysis": jd_analysis, "cv": cv_text},
    ) as gen:
        result = call_claude_fit(jd_analysis, cv_text)
        gen.update(
            output=result.assessment,
            usage_details={"input_tokens": result.usage.input, "output_tokens": result.usage.output}
        )
        # Update the parent span (phase1) with outcome metadata
        lf.update_current_observation(metadata={
            "outcome": result.assessment.fit_label,
            "overall_fit_score": str(result.assessment.overall_score),
        })
    return result

@observe(name="phase3_refinement", as_type="span")
def run_phase3(cv_draft, jd_analysis, ...):
    lf = get_client()
    for i, iteration in enumerate(run_iterations(...)):
        with lf.start_as_current_observation(
            as_type="span",
            name=f"iteration_{i+1}",
        ) as iter_span:
            # orchestrator call
            with lf.start_as_current_observation(
                as_type="generation",
                name="claude_orchestrator",
                model="claude-sonnet-4-6",
                input=iteration.orchestrator_prompt,
            ) as gen:
                decisions = call_orchestrator(iteration)
                gen.update(output=decisions)

            # section rewrites (0..N)
            for section in iteration.sections_to_rewrite:
                with lf.start_as_current_observation(
                    as_type="generation",
                    name="haiku_section_rewrite",
                    model="claude-haiku-4-5",
                    input={"section": section.name, "instructions": section.instructions},
                ) as gen:
                    rewritten = call_haiku_rewrite(section)
                    gen.update(output=rewritten)

            iter_span.update(metadata={
                "keyword_coverage": str(iteration.keyword_coverage),
                "critique_score": str(iteration.critique_score),
            })
```

### 2.6 Score attachment

In SDK v4, scores are attached via the API client, not the trace object.
Do this after the run completes in `api/runner.py`:

```python
from langfuse import get_client
from tailor.telemetry import is_enabled

def attach_scores(run_id: str, metrics: dict, job_radar_source: dict | None = None):
    if not is_enabled():
        return
    lf = get_client()
    scores = []
    if metrics.get("fit_score") is not None:
        scores.append({"name": "fit_score", "value": metrics["fit_score"]})
    if metrics.get("coverage_score") is not None:
        scores.append({"name": "coverage_score", "value": metrics["coverage_score"]})
    if metrics.get("cv_quality_score") is not None:
        scores.append({"name": "cv_quality_score", "value": metrics["cv_quality_score"]})
    if job_radar_source and job_radar_source.get("fit_score") is not None:
        scores.append({
            "name": "job_radar_fit_score",
            "value": job_radar_source["fit_score"] / 10  # normalise to 0–1
        })
    for score in scores:
        lf.api.scores.create(
            trace_id=run_id,
            name=score["name"],
            value=score["value"],
            data_type="NUMERIC",
        )
```

> **Why `lf.api.scores.create()`?** In v4, scores are attached via
> the REST API client rather than on a trace object, since there's no
> persistent trace object to call `.score()` on after the decorated
> function returns. The `run_id` ties the score back to the correct trace.

### 2.7 HITL decisions

Log HITL inputs as events on the current observation:

```python
from langfuse import get_client
from tailor.telemetry import is_enabled

def log_hitl_input(phase: str, hitl_text: str, interpretation: str):
    if not is_enabled():
        return
    lf = get_client()
    lf.create_event(
        name="hitl_input",
        metadata={
            "phase": phase,
            "input": hitl_text,
            "interpretation": interpretation,
        }
    )
```

### 2.8 What NOT to trace in cv-tailor

- Internal string manipulation, template rendering
- File I/O (reading/writing docx, json)
- The SSE event stream itself
- Individual token counts within a rewrite (aggregate at generation level)

---

## 3. Job Radar instrumentation (Phase B ✅ + Phase C ✅ built)

Phase B (batch infrastructure) is built and verified live 2026-06-13.
Phase C (per-role scoring traces — this section) is **built 2026-06-14**
(`record_role_scoring_decision()` + `on_cv_tailor_result()` in `cli/telemetry.py`,
wired in `cli/score.py` and `api/routers/cv_tailor.py`; deviation 50). Live
verification (steps 5–7 below) runs on the M720q server with the job-radar keys.

### 3.1 Project

One Langfuse project: `job-radar`. Separate from cv-tailor.
Never share keys with cv-tailor — auth_check returns true regardless, traces
land in wrong project. Each app uses its own project's key pair.

---

### 3.2 Trace point 1 — Per-role scoring decision (Phase C ✅ built)

**One trace per scored role. Exists independently of cv-tailor.**

This is the core instrumentation. Every time `cli/score.py` scores a JD,
a trace is created that permanently records why Job Radar assigned that
fit label. The cv-tailor callback may or may not ever arrive — the scoring
trace is complete and valuable on its own.

> **Build note (the scorer has no LLM call).** Job Radar's scorer
> (`scoring/scorer.py`) is **purely rule-based** — deterministic regex + enum
> lookups over the *already-extracted* JDRecord. There is **no LLM call at scoring
> time**; the LLM ran earlier during *extraction* (traced by `extraction_batch` /
> `manual_ingest`). The `claude_stage1` generation is therefore preserved for the
> trace shape but populated honestly from `cli/score.py`: `model="rule_based_scorer"`,
> zero tokens, the JD text as the prompt, the structured sub-scores as the output.
> Dimension scores attach **raw** (`role`/`domain`/`depth` 0–2); `fit_score` and
> `priority_score` are **normalised** 0–10→0–1. Gate scores: seniority `pass→1.0`
> else `0.0` (the breakdown's `"miss"` maps to 0.0); location `pass→1.0` /
> `unclear→0.5` / `fail→0.0`.

```
Trace: role_scoring_decision
  name = "role_scoring_decision"
  trace_id = deterministic from job_id (Langfuse.create_trace_id(seed=job_id))
  metadata = {
    job_id: "sha256:...",           ← permanent cross-system lookup key
    company: "Elastic",
    role_title: "Staff Engineer",
    scored_at: "2026-06-13T...",
    fit_label: "strong_fit" | "good_fit" | "partial_fit" | "poor_fit",
    priority_score: 8.2,
    fit_score: 0.72,
    blocking_constraints: [],       ← list of any hard blockers
    requirement_gaps: []            ← list of unmet requirements
  }

  Span: stage1_structural_fit
    metadata = {
      role_score: 0.85,
      domain_score: 0.70,
      depth_score: 0.80,
      composite: 0.78
    }
    Generation: claude_stage1        ← the LLM call that produced these scores
      model: "claude-opus-4-8" (or haiku)
      input: <JD + scoring prompt>
      output: <structured scores JSON>
      usage: {input_tokens, output_tokens}

  Span: stage2_blocking_constraints
    metadata = {
      seniority_gate: "pass" | "fail",
      location_gate: "pass" | "fail",
      blocking_constraints: [],
      requirement_gaps: []
    }

  Span: stage3_fit_label
    metadata = {
      fit_label: "strong_fit",
      priority_score: 8.2,
      rationale: "..."
    }

  Score: fit_score = 0.72            (numeric, 0–1)
  Score: priority_score = 8.2        (numeric, 0–10)
  Score: role_score = 0.85
  Score: domain_score = 0.70
  Score: depth_score = 0.80
  Score: seniority_gate = 1 | 0      (1 = pass)
  Score: location_gate = 1 | 0
```

**Key design decisions:**

- **Deterministic trace ID from job_id.** `Langfuse.create_trace_id(seed=job_id)`
  means the trace for a role is always findable by job_id. The cv-tailor callback
  uses the same seed to locate and enrich the trace without storing a Langfuse ID.

- **All dimension scores as Langfuse scores, not just metadata.** Scores are
  queryable and chartable in the UI. Metadata is searchable but not plottable.
  Dimension scores go in both places — metadata for the span context, Langfuse
  scores for the dashboard view.

- **Blocking constraints and requirement gaps as metadata arrays.** These are
  the "why not" signals — surfacing them on the trace makes it possible to see
  patterns across roles (e.g. seniority gate blocking 40% of strong-looking roles).

---

### 3.3 Trace point 2 — cv-tailor callback enrichment (Phase C ✅ built)

**Enriches the existing role_scoring_decision trace when cv-tailor results arrive.**

> **Built as `on_cv_tailor_result()`** (`cli/telemetry.py`), called from
> `POST /api/cv-tailor-results` (`api/routers/cv_tailor.py`) AFTER the snapshot is
> persisted — best-effort, never fails the callback. `job_radar_fit_score` is read
> from the stored `ApplicationRecord` (`load_scores(...)[job_id].fit_score`, 0–10).
> All four cv-tailor metrics are optional, so each score is attached only when
> non-None; `fit_score_divergence` needs both the JR fit and the cv-tailor fit.

When cv-tailor completes a run for a Job Radar role, it calls back to Job Radar
(or Job Radar polls). At that point, the existing `role_scoring_decision` trace
is enriched:

```python
# In the cv-tailor callback handler (Job Radar side)
def on_cv_tailor_result(job_id: str, cv_tailor_scores: dict):
    if not is_enabled():
        return
    lf = get_client()
    tid = Langfuse.create_trace_id(seed=job_id)  # same seed → same trace

    # Attach cv-tailor scores to the existing trace
    lf.create_score(trace_id=tid, name="cv_tailor_fit_score",
                    value=cv_tailor_scores["fit_score"], data_type="NUMERIC")
    lf.create_score(trace_id=tid, name="cv_tailor_coverage_score",
                    value=cv_tailor_scores["coverage_score"], data_type="NUMERIC")
    lf.create_score(trace_id=tid, name="cv_tailor_quality_score",
                    value=cv_tailor_scores["cv_quality_score"], data_type="NUMERIC")

    # Compute and store divergence delta
    jr_fit = cv_tailor_scores.get("job_radar_fit_score", 0) / 10  # normalise to 0–1
    ct_fit = cv_tailor_scores["fit_score"]
    divergence = abs(jr_fit - ct_fit)
    lf.create_score(trace_id=tid, name="fit_score_divergence",
                    value=divergence, data_type="NUMERIC")
    lf.flush()
```

The result: a single trace per role that shows both systems' verdicts side by side,
plus the divergence delta. No join required — all data is on the same trace.

**What the closed-loop trace enables:**
- "Why did Job Radar rate this role strong_fit but cv-tailor scored it 0.4?"
  → open the trace, compare stage outputs against cv-tailor phase outputs
- Dashboard: sort roles by fit_score_divergence descending → highest disagreement first
- Research question: is divergence systematic by company, domain, or seniority level?

---

### 3.4 Existing Phase B traces (already built)

Phase B (built 2026-06-13) instruments the batch infrastructure:

| Target | Where | Trace name | Status |
|---|---|---|---|
| `extraction_batch` | `cli/label.py` | `extraction_batch` | ✅ live |
| `scoring_run` | `cli/score.py` | `scoring_run` | ✅ live — batch-level only |
| `manual_ingest` | `api/routers/manual_ingest.py` | `manual_ingest` | ✅ live |
| `role_scoring_decision` | `cli/score.py` (per role) | `role_scoring_decision` | ✅ built (Phase C) |
| cv-tailor enrichment | `api/routers/cv_tailor.py` | (enriches `role_scoring_decision`) | ✅ built (Phase C) |

Phase C adds the per-role scoring decision trace *alongside* the scoring run.
The `scoring_run` batch trace continues to exist as the container; each
`role_scoring_decision` trace is a parallel, independent record per role
(its own deterministic trace id, seeded from `job_id`).

---

### 3.5 Phase C build order

1. ✅ Add `record_role_scoring_decision()` to `cli/telemetry.py`
2. ✅ Wire it into `cli/score.py` — call after each role is scored
   (`build_role_decision_kwargs`, after the `scoring_run` batch trace)
3. ✅ Add `on_cv_tailor_result()` enrichment to the cv-tailor callback handler
   (`api/routers/cv_tailor.py`)
4. ✅ Add `fit_score_divergence` computation (`telemetry._divergence`, pure + tested)
5. ⏳ Run debug probe: `python -m cli.telemetry debug-trace` confirms connectivity
   (on the server — locally reports `enabled: false`)
6. ⏳ Score one role, verify `role_scoring_decision` trace appears in UI with all
   dimension scores attached
7. ⏳ Trigger a cv-tailor run for that role, verify the same trace is enriched
   with cv-tailor scores and divergence delta

Steps 1–4 done 2026-06-14; steps 5–7 are live verification on the M720q server
(needs the job-radar Langfuse keys).

### 3.6 Phase C Definition of Done

1. ✅ Every scored role produces a `role_scoring_decision` trace with:
   - All three stage spans (stage1, stage2, stage3)
   - A stage1 generation with token counts (rule-based scorer → `rule_based_scorer`,
     0 tokens, JD text as prompt, structured sub-scores as output — see §3.2 build note)
   - All dimension scores as Langfuse scores (fit, priority, role, domain, depth,
     seniority_gate, location_gate)
   - blocking_constraints and requirement_gaps in metadata
2. ✅ cv-tailor callback enriches the trace with cv_tailor_fit_score,
   cv_tailor_coverage_score, cv_tailor_quality_score, fit_score_divergence
3. ⏳ Traces queryable by job_id in the Langfuse UI (live verification, server)
4. ⏳ Dashboard sortable by fit_score_divergence — highest disagreement first (server)
5. ✅ All existing tests pass unchanged (512 pass: 506 baseline + 6 new, no key set)

### 3.7 Cross-system linkage

`job_id` is the permanent cross-system key. It is stored in:
- Job Radar: `corpus/jobs.jsonl` and the trace metadata
- cv-tailor: passed as `job_radar_source.job_id` and stored in trace metadata
- Langfuse: both traces carry it, findable by metadata search

The deterministic trace ID `Langfuse.create_trace_id(seed=job_id)` means
neither system needs to store a Langfuse trace ID — it can always be
recomputed from the job_id.

---

---

## 4. Tests

### cv-tailor
- `@observe()` decorators are no-ops when `LANGFUSE_PUBLIC_KEY` is absent
- No test env changes needed — tracing silently disabled
- Run existing test suite; must pass unchanged
- Add one smoke test: set `LANGFUSE_PUBLIC_KEY` to a test project key,
  run one pipeline, confirm trace appears in Langfuse UI

### Job Radar
- Same pattern: no `LANGFUSE_PUBLIC_KEY` → no tracing
- Existing 440 tests must pass unchanged

---

## 5. Build order

### Phase A — cv-tailor (build first)
1. `pip install langfuse`, add `langfuse>=4.0.0` to `requirements.txt`
2. Create `tailor/telemetry.py`
3. Call `init_langfuse()` at app startup
4. Add `@observe(name="cv_tailor_run")` to `launch_run()` in `runner.py`
5. Add `propagate_attributes()` block with trace metadata
6. Instrument Phase 0 — `@observe` + generation context manager
7. Instrument Phase 1 — `@observe` + generation + metadata update
8. Instrument Phase 3 — `@observe` + iteration spans + generation per rewrite
9. Instrument Phase 4 — `@observe` + generation + metadata
10. Attach scores via `lf.api.scores.create()` after run completes
11. Deploy, run one real cv-tailor job, verify trace in Langfuse UI
12. Instrument remaining phases (2, 5, 6) — lower priority

### Phase B — Job Radar (after cv-tailor confirmed)
1. `pip install langfuse`, add to `requirements.txt`
2. Create `cli/telemetry.py` (same pattern as cv-tailor)
3. Instrument extraction batch (post-batch context managers)
4. Instrument scoring run (spans, no generations)
5. Deploy, run one extraction, verify traces

---

## 6. Definition of Done — cv-tailor (Phase A)

1. A completed cv-tailor run produces a trace in Langfuse with:
   - `run_id` in trace metadata — enables cross-system lookup
   - Phase spans for Phase 0, 1, 3, 4
   - LLM generations with token counts
   - `fit_score`, `coverage_score`, `cv_quality_score` as trace scores
   - `job_radar_fit_score` attached when run came from Job Radar
2. Tracing disabled cleanly when `LANGFUSE_PUBLIC_KEY` is absent
3. All existing cv-tailor tests pass unchanged

## 7. Definition of Done — Job Radar (Phase B) ✅ shipped 2026-06-13

1. ✅ Completed extraction batch produces trace with child spans per JD (`extraction_batch`)
2. ✅ Scoring run produces trace with dimension breakdown per JD (`scoring_run`)
3. ✅ **Manual ingest produces a `manual_ingest` trace** (extraction generation + scoring
   breakdown) — the separate API path, instrumented after it was found untraced
4. ✅ Every trace sets `langfuse.trace.name` via `propagate_attributes` — without it the
   worker drops the trace (does not reach ClickHouse / the UI)
5. ✅ All existing Job Radar tests pass with no `LANGFUSE_PUBLIC_KEY` (468; was 440 at spec time)
6. ✅ Traces queryable alongside cv-tailor traces in the Langfuse UI

**Forward work (post-close): refine *what* we trace.** The plumbing is done and verified;
the next iteration tunes granularity from real usage — e.g. capturing cost/latency on the
batch generations, trimming low-value metadata, and deciding whether dimension-level spans
earn their keep. Add granularity only where gaps appear (see §1) — don't pre-instrument.

---

## 8. What this enables

Once both systems are instrumented and 20+ linked runs exist:

**In the Langfuse UI:**
- Filter cv-tailor traces by `metadata.job_id` — see every run for a
  specific Job Radar role
- Compare `job_radar_fit_score` vs `fit_score` on the same trace
- See which Phase 3 iterations took longest and cost most
- See HITL decisions and how Haiku interpreted them

**Via direct DB query (PostgreSQL + ClickHouse):**
- Join traces by `job_id` to answer the §7 research questions
- Compute average divergence between Job Radar and cv-tailor fit scores
  by company, domain, or role type
- Identify systematic extraction failures (low `validation_passed` rate
  for specific companies)

This is the raw material for the Phase 4 redesign — multi-agent scoring
orchestration grounded in evidence rather than assumption.

---

## 12. Critical operational finding — `langfuse.trace.name` required by worker

Discovered during Job Radar Phase B. The Langfuse v3 worker uses
`langfuse.trace.name` as a routing signal to process OTel spans from MinIO
into ClickHouse. Spans without this attribute sit in MinIO indefinitely —
no error is logged anywhere.

**How it gets set:**
- `start_as_current_observation(name="your_name")` → sets it automatically ✅
- `lf.trace(name="...")` low-level API → does NOT set it ✗

Always use `start_as_current_observation` with an explicit name on the root
observation. Never use `lf.trace()` as the root span.

**Diagnostic — read the raw MinIO payload:**

```bash
docker exec langfuse-langfuse-minio-1 sh -c \
  "mc alias set local http://localhost:9000 \$MINIO_ROOT_USER \$MINIO_ROOT_PASSWORD \
   && mc cat local/langfuse/otel/<project_id>/<path>.json" 2>/dev/null
```

Look for `{"key":"langfuse.trace.name",...}` in the span attributes.
If absent — spans will not be processed into ClickHouse.

**Updated triage order (supersedes §11.3 step 2):**

1. Debug probe → `enabled` → `auth_check` → `trace_id`
2. Confirm `trace_id` in UI in the **right project**
3. Read raw MinIO JSON → confirm `langfuse.trace.name` present
4. Only now run one real job (token-spending step)
5. If debug traces land but real runs don't → flush/scope bug (§10.6)

---

## 13. Audit every pipeline entry point

During Job Radar Phase B, the manual job addition path was not instrumented
in the initial build — only the automated batch path was. Always check every
route that produces traceable work, not just the primary path. In Job Radar:
both `cli/label.py` (batch) and the manual addition path are instrumented.
