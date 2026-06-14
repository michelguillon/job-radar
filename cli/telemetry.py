"""cli/telemetry.py — Langfuse observability (opt-in, no-op when unconfigured).

The ONE module that imports the langfuse SDK in Job Radar (the analogue of
cv-tailor's ``tailor/telemetry.py``). The pipeline CLIs trace *through* the
recorder functions here, so when ``LANGFUSE_PUBLIC_KEY`` is absent every call is
a clean no-op and the langfuse import surface stays in one place
(SPEC_LANGFUSE_INSTRUMENTATION §3).

Two facts drive the design (carried over from the cv-tailor build, verified live
against the same self-hosted Langfuse v4 server):

1. **Lazy SDK import.** ``from langfuse import …`` happens INSIDE functions, never
   at module top, so ``import cli.telemetry`` works with langfuse uninstalled
   (local dev / the test suite when the key is unset). The langfuse dependency is
   only touched on the enabled path.

2. **Post-hoc, not real-time (the Job-Radar difference).** cv-tailor traces a
   live pipeline with decorators + nested context managers on one thread. Job
   Radar uses the Claude **Batch API** — results arrive asynchronously, so spans
   are created *after* the batch ends, from already-collected data. The CLI
   process then exits immediately: there is no periodic background exporter to
   fall back on, so each recorder builds its tree, lets the root span CLOSE, and
   ``flush()``es AFTER the close (the flush-timing bug that bit cv-tailor —
   flushing before the root closes loses the trace).

3. **Deterministic trace id.** ``Langfuse.create_trace_id(seed=batch_id|run_id)``
   gives a stable trace id the root span claims via ``trace_context``, so the
   ``batch_id → trace_id`` log line (WARNING — uvicorn/Docker drop INFO) lets you
   jump from a pipeline run straight to its trace.

Observability must NEVER break the pipeline: every recorder guards on
``is_enabled()`` and swallows its own errors; ``init_langfuse`` never calls
``auth_check()`` (a sync, no-timeout network probe that can hang startup).
"""

from __future__ import annotations

import logging
import os

log = logging.getLogger("cli.telemetry")

__all__ = [
    "is_enabled", "init_langfuse", "debug_trace",
    "record_extraction_batch", "record_scoring_run", "record_manual_ingest",
    "record_role_scoring_decision", "on_cv_tailor_result", "flush",
]

# Set once the global Langfuse singleton is live, so init_langfuse() is a true
# no-op on repeat calls (debug-trace + each recorder all call it defensively).
_INITIALIZED = False


def is_enabled() -> bool:
    """True iff Langfuse credentials are configured. The single tracing on/off gate."""
    return bool(os.getenv("LANGFUSE_PUBLIC_KEY"))


def _resolved_host() -> str:
    """The host the SDK will use — LANGFUSE_BASE_URL → LANGFUSE_HOST → cloud default."""
    return os.getenv("LANGFUSE_BASE_URL") or os.getenv("LANGFUSE_HOST") or "https://cloud.langfuse.com"


def init_langfuse() -> None:
    """Initialise the Langfuse global singleton once. No-op (and import-safe) when
    unconfigured; a failed init disables tracing, never crashes the caller.

    NEVER calls ``auth_check()`` — that is a synchronous, no-timeout network probe
    that can hang a startup sequence. Construct only; the probe lives in
    ``debug_trace`` (on-demand, can't wedge a pipeline run)."""
    if not is_enabled():
        return
    global _INITIALIZED
    if _INITIALIZED:
        return
    try:
        from langfuse import Langfuse
        Langfuse()                                     # construct the singleton + OTel exporter
        _INITIALIZED = True
        log.info("Langfuse init OK: host=%s (auth_check deferred to debug-trace)", _resolved_host())
    except Exception:                                  # observability must not break the caller
        log.exception("Langfuse init failed; tracing disabled")


def _strmeta(fields: dict | None) -> dict | None:
    """Stringify metadata values (langfuse observation metadata is ``dict[str, str]``); drop None."""
    if not fields:
        return None
    return {k: str(v) for k, v in fields.items() if v is not None} or None


def _norm10(value: float) -> float:
    """Normalise a 0–10 score onto 0–1 (Langfuse scores are most useful on one scale)."""
    return value / 10


def _divergence(jr_fit_0_10: float, ct_fit_0_1: float) -> float:
    """|Job Radar fit (normalised 0–1) − cv-tailor fit (0–1)| — the cross-system delta."""
    return abs(_norm10(jr_fit_0_10) - ct_fit_0_1)


def flush() -> None:
    """Flush pending observations (best-effort, no-op safe)."""
    if not is_enabled():
        return
    try:
        from langfuse import get_client
        get_client().flush()
    except Exception:
        log.debug("langfuse flush failed", exc_info=True)


# --------------------------------------------------------------------------- #
# Post-hoc recorders — built after Batch API results / a scoring run arrive    #
# --------------------------------------------------------------------------- #

def record_extraction_batch(batch_id: str, rows: list[dict], metadata: dict | None = None) -> str | None:
    """Create one ``extraction_batch`` trace from a completed Batch API run.

    ``rows`` is one dict per JD result, with keys::

        job_id, company, model, prompt, completion,
        input_tokens, output_tokens, validated (bool)

    Trace shape (SPEC §3.2): a root ``extraction_batch`` span → one ``jd_extraction``
    span per JD → a ``claude_extraction`` generation (model + token usage) → a
    ``validation_passed`` numeric score on the JD span. The root span CLOSES before
    ``flush()`` (the CLI is about to exit — no background exporter). Best-effort:
    any failure logs a WARNING and returns None, never raising into the pipeline.
    """
    if not is_enabled():
        return None
    metadata = metadata or {}
    try:
        from langfuse import Langfuse, get_client, propagate_attributes
        init_langfuse()
        lf = get_client()
        tid = Langfuse.create_trace_id(seed=batch_id)
        # propagate_attributes(trace_name=…) is what stamps `langfuse.trace.name` onto the spans —
        # the attribute the Langfuse worker REQUIRES to ingest a trace into ClickHouse (without it
        # the spans land in MinIO but never surface in the UI). Mirrors tailor/telemetry.run_trace:
        # open the root span, then wrap the body in propagate_attributes so every child carries it.
        with lf.start_as_current_observation(
            as_type="span", name="extraction_batch",
            trace_context={"trace_id": tid}, input=metadata,
        ), propagate_attributes(trace_name="extraction_batch", metadata=_strmeta({
            "batch_id": batch_id,
            "date": metadata.get("date"),
            "jd_count": len(rows),
        })):
            for row in rows:
                with lf.start_as_current_observation(
                    as_type="span", name="jd_extraction",
                    input={"job_id": row.get("job_id"), "company": row.get("company")},
                ) as jd_span:
                    with lf.start_as_current_observation(
                        as_type="generation", name="claude_extraction",
                        model=row.get("model"), input=row.get("prompt"),
                    ) as gen:
                        gen.update(
                            output=row.get("completion"),
                            usage_details={
                                "input": int(row.get("input_tokens") or 0),
                                "output": int(row.get("output_tokens") or 0),
                            },
                        )
                    _score(lf, tid, jd_span, "validation_passed",
                           1.0 if row.get("validated") else 0.0)
        # Root span is now CLOSED — safe to flush (no periodic exporter; CLI exits next).
        lf.flush()
        log.warning("Langfuse batch trace created: batch_id=%s trace_id=%s", batch_id, tid)
        return tid
    except Exception as exc:                            # never let observability raise into the pipeline
        log.warning("Langfuse batch trace failed (non-fatal): %s", exc)
        return None


def record_scoring_run(run_id: str, rows: list[dict], metadata: dict | None = None) -> str | None:
    """Create one ``scoring_run`` trace from a completed scoring run.

    ``rows`` is one dict per scored JD, with keys::

        job_id, company, fit_label, fit_score,
        dimensions: [ {dimension, score, rationale}, … ]

    Trace shape (SPEC §3.2): a root ``scoring_run`` span → one ``jd_scoring`` span
    per JD (metadata: job_id/company/fit_label/fit_score) → one ``dimension_score``
    span per scoring dimension (metadata: dimension/score/rationale). The scorer is
    rule-based (no LLM call), so there are no generations here. Flush follows the
    root close, as above. Best-effort — failures log a WARNING, never raise.
    """
    if not is_enabled():
        return None
    metadata = metadata or {}
    try:
        from langfuse import Langfuse, get_client, propagate_attributes
        init_langfuse()
        lf = get_client()
        tid = Langfuse.create_trace_id(seed=run_id)
        # trace_name=… stamps `langfuse.trace.name`, which the worker needs to ingest the trace
        # (see record_extraction_batch). Mirrors tailor/telemetry.run_trace.
        with lf.start_as_current_observation(
            as_type="span", name="scoring_run",
            trace_context={"trace_id": tid}, input=metadata,
        ), propagate_attributes(trace_name="scoring_run", metadata=_strmeta({
            "run_date": metadata.get("run_date"),
            "jd_count": len(rows),
        })):
            for row in rows:
                with lf.start_as_current_observation(
                    as_type="span", name="jd_scoring",
                    input={"job_id": row.get("job_id"), "company": row.get("company")},
                ) as jd_span:
                    jd_span.update(metadata=_strmeta({
                        "job_id": row.get("job_id"),
                        "company": row.get("company"),
                        "fit_label": row.get("fit_label"),
                        "fit_score": row.get("fit_score"),
                    }))
                    for dim in row.get("dimensions", []):
                        with lf.start_as_current_observation(
                            as_type="span", name="dimension_score",
                            metadata=_strmeta({
                                "dimension": dim.get("dimension"),
                                "score": dim.get("score"),
                                "rationale": dim.get("rationale"),
                            }),
                        ):
                            pass                       # leaf span — metadata only
        lf.flush()
        log.warning("Langfuse scoring trace created: run_id=%s trace_id=%s", run_id, tid)
        return tid
    except Exception as exc:
        log.warning("Langfuse scoring trace failed (non-fatal): %s", exc)
        return None


def record_manual_ingest(job_id: str, row: dict, metadata: dict | None = None) -> str | None:
    """Create one ``manual_ingest`` trace for a synchronous UI paste-and-score.

    Distinct from the two CLI-driven recorders above: the manual-ingest path
    (`POST /api/manual-ingest`) runs INSIDE the long-lived FastAPI process, not a batch
    CLI — one Haiku extraction + one scorer pass per request. So one POST = one trace.

    ``row`` keys::

        company, model, prompt, completion, input_tokens, output_tokens, validated (bool),
        fit_label, fit_score, priority_score, dimensions: [{dimension, score, rationale}, …]

    Trace shape: root ``manual_ingest`` span → a ``claude_extraction`` generation (Haiku,
    token usage) → a ``jd_scoring`` span (fit metadata) → one ``dimension_score`` span per
    dimension → a ``validation_passed`` score on the trace. ``propagate_attributes(trace_name)``
    stamps ``langfuse.trace.name`` (worker ingestion requirement). Best-effort — never raises.
    """
    if not is_enabled():
        return None
    metadata = metadata or {}
    try:
        from langfuse import Langfuse, get_client, propagate_attributes
        init_langfuse()
        lf = get_client()
        tid = Langfuse.create_trace_id(seed=f"manual_{job_id}")
        with lf.start_as_current_observation(
            as_type="span", name="manual_ingest",
            trace_context={"trace_id": tid},
            input={"job_id": job_id, "company": row.get("company")},
        ), propagate_attributes(trace_name="manual_ingest", metadata=_strmeta({
            "job_id": job_id,
            "company": row.get("company"),
            "source": "manual_ingest",
            "scored_at": metadata.get("scored_at"),
        })):
            with lf.start_as_current_observation(
                as_type="generation", name="claude_extraction",
                model=row.get("model"), input=row.get("prompt"),
            ) as gen:
                gen.update(
                    output=row.get("completion"),
                    usage_details={
                        "input": int(row.get("input_tokens") or 0),
                        "output": int(row.get("output_tokens") or 0),
                    },
                )
            with lf.start_as_current_observation(
                as_type="span", name="jd_scoring",
                metadata=_strmeta({
                    "fit_label": row.get("fit_label"),
                    "fit_score": row.get("fit_score"),
                    "priority_score": row.get("priority_score"),
                }),
            ):
                for dim in row.get("dimensions", []):
                    with lf.start_as_current_observation(
                        as_type="span", name="dimension_score",
                        metadata=_strmeta({
                            "dimension": dim.get("dimension"),
                            "score": dim.get("score"),
                            "rationale": dim.get("rationale"),
                        }),
                    ):
                        pass                           # leaf span — metadata only
            # Trace-level score (the root span is still open, so trace_id resolves).
            try:
                lf.create_score(name="validation_passed",
                                value=1.0 if row.get("validated") else 0.0,
                                trace_id=tid, data_type="NUMERIC")
            except Exception:
                log.debug("langfuse manual-ingest score failed", exc_info=True)
        lf.flush()
        log.warning("Langfuse manual-ingest trace created: job_id=%s trace_id=%s", job_id, tid)
        return tid
    except Exception as exc:
        log.warning("Langfuse manual-ingest trace failed (non-fatal): %s", exc)
        return None


# --------------------------------------------------------------------------- #
# Phase C — per-role scoring decision (one independent trace per scored role)   #
# --------------------------------------------------------------------------- #

def record_role_scoring_decision(
    job_id: str,
    company: str,
    role_title: str,
    scored_at: str,
    # Stage 1 outputs (signal sub-scores + the weighted composite).
    role_score: float,
    domain_score: float,
    depth_score: float,
    stage1_composite: float,
    # Stage 2 outputs (gates + constraints).
    seniority_gate: str,          # "pass" | "miss"/"fail"
    location_gate: str,           # "pass" | "unclear" | "fail"
    blocking_constraints: list,
    requirement_gaps: list,
    # Stage 3 outputs (classification).
    fit_label: str,
    fit_score: float,             # 0–10 (raw scorer output, not normalised)
    priority_score: float,        # 0–10 (raw scorer output)
    # "Stage 1 call" details. NB: Job Radar's scorer is RULE-BASED — there is no
    # LLM call at scoring time (the LLM ran earlier, during extraction, and is
    # traced by record_extraction_batch / record_manual_ingest). These fields carry
    # the deterministic-scorer inputs/outputs so the spec's stage1 generation shape
    # is preserved; the wiring (cli/score.py) passes model="rule_based_scorer",
    # zero tokens, the JD text as the prompt, and the structured scores as the output.
    stage1_model: str,
    stage1_input_tokens: int,
    stage1_output_tokens: int,
    stage1_prompt: str,
    stage1_response: str,
) -> str | None:
    """Create one independent ``role_scoring_decision`` trace for a single scored role.

    The trace is the permanent record of *why Job Radar assigned this fit label*. It
    exists whether or not cv-tailor ever runs; ``on_cv_tailor_result`` enriches the
    SAME trace later (same deterministic ``job_id`` seed). Trace shape (SPEC §3.2):
    root ``role_scoring_decision`` span → ``stage1_structural_fit`` span (with a
    ``claude_stage1`` generation) → ``stage2_blocking_constraints`` span →
    ``stage3_fit_label`` span; every dimension/gate attached as a NUMERIC trace score
    (queryable + chartable, unlike metadata). ``propagate_attributes(trace_name=…)``
    stamps ``langfuse.trace.name`` (worker ingestion requirement, §12). Flush follows
    the root close. Best-effort — any failure logs a WARNING and returns None, never
    raising into the scoring pipeline.
    """
    if not is_enabled():
        return None
    try:
        import json

        from langfuse import Langfuse, get_client, propagate_attributes
        init_langfuse()
        lf = get_client()
        tid = Langfuse.create_trace_id(seed=job_id)
        blocking_json = json.dumps(blocking_constraints or [])
        gaps_json = json.dumps(requirement_gaps or [])
        with lf.start_as_current_observation(
            as_type="span", name="role_scoring_decision",
            trace_context={"trace_id": tid},
            input={"job_id": job_id, "company": company, "role_title": role_title},
        ), propagate_attributes(trace_name="role_scoring_decision", metadata=_strmeta({
            "job_id": job_id,
            "company": company,
            "role_title": role_title,
            "scored_at": scored_at,
            "fit_label": fit_label,
            "blocking_constraints": blocking_json,
            "requirement_gaps": gaps_json,
        })):
            with lf.start_as_current_observation(
                as_type="span", name="stage1_structural_fit",
                metadata=_strmeta({
                    "role_score": role_score,
                    "domain_score": domain_score,
                    "depth_score": depth_score,
                    "composite": stage1_composite,
                }),
            ):
                with lf.start_as_current_observation(
                    as_type="generation", name="claude_stage1",
                    model=stage1_model, input=stage1_prompt,
                ) as gen:
                    gen.update(
                        output=stage1_response,
                        usage_details={
                            "input": int(stage1_input_tokens or 0),
                            "output": int(stage1_output_tokens or 0),
                        },
                    )
            with lf.start_as_current_observation(
                as_type="span", name="stage2_blocking_constraints",
                metadata=_strmeta({
                    "seniority_gate": seniority_gate,
                    "location_gate": location_gate,
                    "blocking_constraints": blocking_json,
                    "requirement_gaps": gaps_json,
                }),
            ):
                pass                                   # leaf span — metadata only
            with lf.start_as_current_observation(
                as_type="span", name="stage3_fit_label",
                metadata=_strmeta({
                    "fit_label": fit_label,
                    "fit_score": str(fit_score),
                    "priority_score": str(priority_score),
                }),
            ):
                pass                                   # leaf span — metadata only
            # Dimension + gate scores as NUMERIC trace scores (chartable, not just metadata).
            trace_scores = {
                "fit_score": _norm10(fit_score),               # 0–10 → 0–1
                "priority_score": _norm10(priority_score),     # 0–10 → 0–1
                "role_score": role_score,                      # raw sub-score (0–2)
                "domain_score": domain_score,                  # raw sub-score (0–2)
                "depth_score": depth_score,                    # raw sub-score (0–2)
                "seniority_gate": 1.0 if seniority_gate == "pass" else 0.0,
                "location_gate": 1.0 if location_gate == "pass" else (
                    0.5 if location_gate == "unclear" else 0.0),
            }
            for sname, svalue in trace_scores.items():
                try:
                    lf.create_score(name=sname, value=svalue, trace_id=tid, data_type="NUMERIC")
                except Exception:
                    log.debug("langfuse role-scoring score %s failed", sname, exc_info=True)
        lf.flush()
        log.warning("Langfuse role-scoring trace created: job_id=%s trace_id=%s", job_id, tid)
        return tid
    except Exception as exc:
        log.warning("Langfuse role-scoring trace failed (non-fatal): %s", exc)
        return None


def on_cv_tailor_result(
    job_id: str,
    fit_score: float | None,           # cv-tailor fit_score (0.0–1.0)
    coverage_score: float | None,      # cv-tailor coverage_score (0.0–1.0)
    cv_quality_score: float | None,    # cv-tailor cv_quality_score (0.0–10.0)
    job_radar_fit_score: float | None = None,  # JR fit passed to cv-tailor (0–10)
) -> None:
    """Enrich the existing ``role_scoring_decision`` trace with cv-tailor's verdict.

    Uses the SAME deterministic trace id (``seed=job_id``) the scoring trace claimed,
    so both systems' scores land on one trace — no join required (SPEC §3.3). Attaches
    cv-tailor's fit/coverage/quality as NUMERIC scores and, when the JR fit it was given
    is known, the ``fit_score_divergence`` delta. None-valued metrics are skipped (a
    cv-tailor run may report only some). Best-effort — never raises into the API handler.
    """
    if not is_enabled():
        return
    try:
        from langfuse import Langfuse, get_client
        init_langfuse()
        lf = get_client()
        tid = Langfuse.create_trace_id(seed=job_id)

        if fit_score is not None:
            lf.create_score(trace_id=tid, name="cv_tailor_fit_score",
                            value=fit_score, data_type="NUMERIC")
        if coverage_score is not None:
            lf.create_score(trace_id=tid, name="cv_tailor_coverage_score",
                            value=coverage_score, data_type="NUMERIC")
        if cv_quality_score is not None:
            lf.create_score(trace_id=tid, name="cv_tailor_quality_score",
                            value=_norm10(cv_quality_score),  # 0–10 → 0–1
                            data_type="NUMERIC")
        if job_radar_fit_score is not None and fit_score is not None:
            lf.create_score(trace_id=tid, name="fit_score_divergence",
                            value=_divergence(job_radar_fit_score, fit_score),
                            data_type="NUMERIC")
        lf.flush()
        log.warning("Langfuse cv_tailor enrichment: job_id=%s trace_id=%s", job_id, tid)
    except Exception as exc:
        log.warning("Langfuse cv_tailor enrichment failed (non-fatal): %s", exc)


def _score(lf, trace_id: str, observation, name: str, value: float) -> None:
    """Attach a numeric score to an observation; best-effort (a score failure must
    not abort the surrounding trace)."""
    try:
        lf.create_score(
            name=name, value=value, trace_id=trace_id,
            observation_id=observation.id, data_type="NUMERIC",
        )
    except Exception:
        log.debug("langfuse score %s failed", name, exc_info=True)


# --------------------------------------------------------------------------- #
# Zero-cost path probe (SPEC §11) — exercises init → trace → score → flush     #
# --------------------------------------------------------------------------- #

def debug_trace(name: str = "debug_trace") -> dict:
    """Create one minimal trace + score with NO LLM call and flush it — exercises
    the whole export path (init → trace → score → flush → server) at zero cost, to
    verify the infrastructure before spending any tokens. Returns a verdict dict
    ``{enabled, host, trace_id, auth_check, error}``; ``trace_id`` is None when
    disabled or failed. Run from inside the container:

        python -m cli.telemetry debug-trace
    """
    info: dict = {"enabled": is_enabled(), "host": _resolved_host(),
                  "trace_id": None, "auth_check": None, "error": None}
    if not is_enabled():
        return info
    try:
        import time
        from langfuse import Langfuse, get_client, propagate_attributes
        init_langfuse()                                # ensure the singleton exists (idempotent)
        lf = get_client()
        # The decisive probe: does the SDK reach the host AND do the keys authenticate?
        try:
            info["auth_check"] = bool(lf.auth_check())
        except Exception as exc:
            info["auth_check"] = False
            info["error"] = f"auth_check: {type(exc).__name__}: {exc}"
        seed = f"{name}_{int(time.time() * 1000)}"     # unique per call → a fresh trace each hit
        tid = Langfuse.create_trace_id(seed=seed)
        info["trace_id"] = tid
        # propagate_attributes(trace_name=…) stamps `langfuse.trace.name` — the attribute the worker
        # needs to ingest the trace into ClickHouse (without it the probe span lands in MinIO but the
        # trace never appears in the UI). Mirrors the real recorders + tailor/telemetry.run_trace.
        with lf.start_as_current_observation(as_type="span", name=name,
                                             trace_context={"trace_id": tid}), \
                propagate_attributes(trace_name=name):
            pass                                       # empty root span — no children, no LLM call
        lf.create_score(name="debug_score", value=1.0, trace_id=tid, data_type="NUMERIC")
        lf.flush()
        log.info("Langfuse debug trace created name=%s trace_id=%s host=%s auth_check=%s",
                 name, tid, _resolved_host(), info["auth_check"])
    except Exception as exc:
        info["error"] = f"{type(exc).__name__}: {exc}"
        log.exception("Langfuse debug_trace failed")
    return info


if __name__ == "__main__":
    import json
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "debug-trace":
        init_langfuse()
        print(json.dumps(debug_trace(), indent=2))
    else:
        print("Usage: python -m cli.telemetry debug-trace")
