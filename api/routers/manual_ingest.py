"""api/routers/manual_ingest.py — manual JD entry via the UI (job_radar_SPEC §11.1).

A growing number of high-value roles come from companies *outside* the monitored ATS
universe (Workday portals, custom career pages, referrals, LinkedIn). ``corpus/manual/`` is
the CLI escape hatch; this endpoint is the browser-accessible equivalent — same output, same
pipeline, same detail-panel experience.

``POST /api/manual-ingest`` (owner-gated) runs ONE pasted JD through the live pipeline
**synchronously** (~10–20s): ``build_manual_record`` → single-call Claude extraction
(``pipeline.label.extract_one``, Haiku 4.5 — the *one* sanctioned non-batch extraction, see
CLAUDE.md deviation 44) → ``soft_validate`` (advisory, never blocks — deviation 47) → ``score``
→ append validated + scored + meta sidecar files (``*_manual_{ts}.jsonl``, ``ats="manual"``) →
cost to ``stats.json`` → rebuild ``index.json``. It NEVER runs the prefilter screen (a
deliberate owner add is not a candidate to reject on role-bucket/location), and never touches
the automated collection pipeline, the scorer, or the schema.

Deduplication is the same SHA-256 the pipeline uses: ``record_hash(normalise(raw_text))`` (NOT
the raw text — the automated pipeline normalises before hashing, so normalising here keeps a
manually-entered JD and its auto-collected twin on the same ``job_id``). A re-submission is a
409 no-op before any extraction cost is spent.
"""

from __future__ import annotations

import json
import logging
import os

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.events import emit_index_updated
from api.security import require_unlocked
from api.settings import Settings, get_settings
from cli import telemetry
from cli.db import write_activity_event
from cli.label import append_stats
from cli.score import build_scoring_rows
from cli.stats import (
    build_index_rows,
    export_index,
    index_stats,
    load_annotations_auto,
    load_cost_to_date,
    load_cv_tailor_links_auto,
)
from cli.track import (
    _clock,
    build_event,
    load_activity_events,
    load_jdrecords,
    load_meta,
    load_scores,
    project,
)
from collectors.base import build_meta
from models.record import (
    _ANNOTATION_FIELDS,
    _EXTRACTION_FIELDS,
    JDRecord,
    soft_validate,
)
from pipeline.clean import normalise
from pipeline.dedupe import record_hash
from pipeline.label import ANNOTATION_DEFAULTS, SYNC_MODEL, build_user_content, estimate_sync_cost, extract_one
from scoring.profile import load_profile
from scoring.scorer import score

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["manual-ingest"])

# Claude-extracted, so the Tier-4 (automated-labelled) tier — distinct from the human-structured
# Tier-1/2 records in corpus/manual/. ``source_ats="manual"`` marks the browser entry point.
MANUAL_TIER = 4
MIN_JD_CHARS = 200  # below this is almost certainly not a full JD


class ManualIngestRequest(BaseModel):
    company: str
    title: str
    raw_text: str
    source_url: str = ""
    notes: str = ""


def build_manual_record(*, company: str, title: str, raw_text: str, source_url: str, collected_at: str) -> JDRecord:
    """A Tier-4 ``manual`` JDRecord with identity/raw set and every extraction/annotation field
    ``None`` (extraction fills them next). ``id`` is the content hash the pipeline would assign."""
    return JDRecord(
        id=record_hash(normalise(raw_text)),
        source_url=source_url,
        source_ats="manual",
        company=company,
        collected_at=collected_at,
        tier=MANUAL_TIER,
        raw_html=None,
        raw_text=raw_text,
        **{f: None for f in (*_EXTRACTION_FIELDS, *_ANNOTATION_FIELDS)},
    )


def _out_path(read_glob: str, prefix: str, ts: str) -> str:
    """A writable ``{prefix}_manual_{ts}.jsonl`` next to the read glob, matching its pattern.

    e.g. ``corpus/scored/scored_*.jsonl`` → ``corpus/scored/scored_manual_{ts}.jsonl`` (so the
    next ``load_scores(scored_glob)`` picks it up). Tests point the globs at ``tmp_path``."""
    directory = os.path.dirname(read_glob) or "."
    os.makedirs(directory, exist_ok=True)
    return os.path.join(directory, f"{prefix}_manual_{ts}.jsonl")


def _rebuild_index(settings: Settings) -> None:
    """Re-run the same join ``cli.stats --export-index`` does, so the new role shows on reload."""
    scores = load_scores(settings.scored_glob)
    jds = load_jdrecords(settings.validated_glob)
    metas = load_meta(settings.meta_glob)
    workflow = project(load_activity_events(settings.log_path))
    annotations = load_annotations_auto(settings.annotations_path)
    cv_links = load_cv_tailor_links_auto(settings.cv_tailor_links_path)
    rows = build_index_rows(scores, jds, metas, workflow, annotations, cv_links)
    stats = index_stats(rows, cost_to_date=load_cost_to_date(settings.stats_path))
    export_index(rows, stats, path=settings.index_path, generated_at=_clock())


@router.post("/manual-ingest", dependencies=[Depends(require_unlocked)])
def manual_ingest(body: ManualIngestRequest, settings: Settings = Depends(get_settings)) -> dict:
    """Owner-gated synchronous ingest of one pasted JD. See module docstring for the pipeline.

    200 → ``{job_id, company, title, fit_label, fit_score, priority_score, warnings}``; 409
    duplicate; 422 too-short / unparseable / incomplete extraction; 500 unexpected pipeline
    error. ``warnings`` carries advisory soft-validation findings (e.g. an off-vocabulary
    ``role_type``) — the role is stored regardless (deviation 47); ``[]`` when clean."""
    text = body.raw_text.strip()
    if not text:
        raise HTTPException(status_code=422, detail="JD text is required")
    if len(text) < MIN_JD_CHARS:
        raise HTTPException(status_code=422, detail="JD text too short — paste the full job description")
    if not body.company.strip() or not body.title.strip():
        raise HTTPException(status_code=422, detail="company and title are required")

    job_id = record_hash(normalise(body.raw_text))
    if job_id in load_scores(settings.scored_glob):
        raise HTTPException(status_code=409, detail={"job_id": job_id, "message": "This JD is already in the corpus"})

    # Synthesise a unique source_url when none is given, so the metadata sidecar (keyed by
    # source_url → carries the owner-supplied title/location to the join) can't collide across
    # manual entries with empty URLs.
    source_url = body.source_url.strip() or f"manual:{job_id}"
    record = build_manual_record(
        company=body.company.strip(), title=body.title.strip(),
        raw_text=body.raw_text, source_url=source_url, collected_at=_clock(),
    )
    meta = build_meta(
        source_url=source_url, source_ats="manual", company=body.company.strip(),
        title=body.title.strip(), location_str="",
    )

    # --- single-JD Claude extraction (synchronous; the one sanctioned non-batch path) ---
    try:
        extraction, usage = extract_one(record, meta=meta)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail=f"extraction failed — model returned no parseable JSON ({exc})")
    except Exception:  # transport / timeout / API error
        log.exception("manual ingest: extraction call failed for %s", job_id)
        raise HTTPException(status_code=500, detail="extraction failed — please try again")

    try:
        for field in _EXTRACTION_FIELDS:
            setattr(record, field, extraction[field])
    except (KeyError, TypeError) as exc:
        raise HTTPException(status_code=422, detail=f"extraction incomplete — missing field {exc}")
    record.tier = MANUAL_TIER
    # Seed neutral annotation defaults so the record is schema-valid (Claude never sets these).
    for field, default in ANNOTATION_DEFAULTS.items():
        if getattr(record, field) is None:
            setattr(record, field, default)

    # Soft validation — the owner deliberately chose to add this role, so the closed-vocabulary
    # *enum* gate must not block it (deviation 47). soft_validate splits validate()'s findings:
    # structural type errors (e.g. domain not a list) STILL hard-fail (422) — they silently
    # corrupt downstream stages — while enum vocabulary gaps are advisory warnings: the record is
    # stored as-is and the warnings ride back in the 200 response for the UI to surface in amber.
    hard_errors, warnings = soft_validate(record)
    if hard_errors:
        log.warning("manual ingest: %d structural error(s) for %s: %s", len(hard_errors), job_id, hard_errors)
        raise HTTPException(status_code=422, detail=f"extraction produced a structurally invalid record: {hard_errors}")
    if warnings:
        log.info("manual ingest: %d soft-validation warning(s) for %s: %s", len(warnings), job_id, warnings)

    # --- score (locked scorer, same as the pipeline) ---
    try:
        profile = load_profile(settings.profile_path)
        scored_at = _clock()
        app_record = score(record, profile, scored_at)
    except Exception:
        log.exception("manual ingest: scoring failed for %s", job_id)
        raise HTTPException(status_code=500, detail="scoring failed — please try again")

    # --- append corpus files (validated JD + scored ApplicationRecord + meta sidecar) ---
    ts = scored_at.replace("-", "").replace(":", "")
    with open(_out_path(settings.validated_glob, "validated", ts), "w", encoding="utf-8") as fh:
        fh.write(record.to_jsonl() + "\n")
    with open(_out_path(settings.scored_glob, "scored", ts), "w", encoding="utf-8") as fh:
        fh.write(app_record.to_jsonl() + "\n")
    with open(_out_path(settings.meta_glob, "meta", ts), "w", encoding="utf-8") as fh:
        fh.write(json.dumps(meta, ensure_ascii=False) + "\n")

    # Persist any owner note as a workflow note event (otherwise it would be silently dropped).
    # Phase 6.5 Step 6: SQLite is the sole write destination for interactive state (this is a
    # separate activity_log write path from the workflow router, frozen alongside it after the
    # clean 5-day production soak — so the JSONL audit archive stays consistent across writers).
    if body.notes.strip():
        note_event = build_event(job_id, event="note", value=None, notes=body.notes.strip(), ts=_clock())
        # JSONL archived at corpus/activity_log.jsonl (read-only audit trail)
        write_activity_event(note_event)

    # --- cost tracking (same ledger as batch runs) + index rebuild ---
    append_stats({"run": ts, "step": "manual_ingest", "job_id": job_id, "records": 1, **estimate_sync_cost(usage)},
                 path=settings.stats_path)
    _rebuild_index(settings)
    emit_index_updated()  # notify any open SSE connection so the new role appears live

    # Observability (opt-in, no-op without LANGFUSE_PUBLIC_KEY): one `manual_ingest` trace —
    # the Haiku extraction generation + the scoring breakdown. Runs AFTER the corpus is persisted
    # and is fully guarded, so a tracing hiccup can never fail an ingest the user already completed.
    if telemetry.is_enabled():
        try:
            dimensions = build_scoring_rows([record], [app_record], profile)[0]["dimensions"]
            telemetry.record_manual_ingest(job_id, {
                "company": body.company.strip(),
                "model": SYNC_MODEL,
                "prompt": build_user_content(record, meta),
                "completion": extraction,
                "input_tokens": usage.get("input", 0),
                "output_tokens": usage.get("output", 0),
                "validated": not warnings,
                "fit_label": app_record.fit_label,
                "fit_score": app_record.fit_score,
                "priority_score": app_record.priority_score,
                "dimensions": dimensions,
            }, metadata={"scored_at": scored_at})
        except Exception:
            log.warning("manual ingest: telemetry trace failed (non-fatal) for %s", job_id, exc_info=True)

    return {
        "job_id": job_id,
        "company": body.company.strip(),
        "title": body.title.strip(),
        "fit_label": app_record.fit_label,
        "fit_score": app_record.fit_score,
        "priority_score": app_record.priority_score,
        "warnings": warnings,
    }
