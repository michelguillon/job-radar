"""stats.py — corpus statistics + UI index export (job_radar_SPEC §5.3 Step 8, §9.4).

    python -m cli.stats --input "corpus/**/*.jsonl"            # print a JDRecord summary
    python -m cli.stats --input "corpus/validated/*.jsonl" --export-index

``--export-index`` writes ``corpus/index.json`` — the **read-only data contract for
the Phase 5 UI**. It is NOT a bare JDRecord array: the UI needs scoring
(``fit_label``/``priority_score``/``fit_label_reason``/gaps) and live workflow
status that a JDRecord does not carry. So the index is the same **join the tracker
performs** (CLAUDE.md deviation 23) — latest score per ``job_id`` ⨝ JDRecord
extraction ⨝ metadata sidecar ⨝ activity-log projection — denormalised one row per
scored job, wrapped with a small ``stats`` block (counts + score distribution +
cost-to-date) so the single mounted file is self-contained (the UI container only
mounts ``index.json``; it never reads ``stats.json`` or the corpus). See
CLAUDE.md deviation 27 + SPEC §9.4. Pre-built by this CLI, never written by the UI.
"""

from __future__ import annotations

import argparse
import glob
import json
import logging
from collections import Counter
from dataclasses import asdict

from cli.track import (
    LOG_PATH,
    META_GLOB,
    SCORED_GLOB,
    VALIDATED_GLOB,
    _default_state,
    _title_for,
    derive_location_workable,
    load_events,
    load_jdrecords,
    load_meta,
    load_scores,
    project,
)
from cli.db import (
    get_db,
    init_db,
    load_annotations_sqlite,
    load_cv_tailor_links_sqlite,
    load_events_sqlite,
)
from models.record import JDRECORD_SCHEMA_VERSION, SCHEMA_VERSION, JDRecord

INDEX_PATH = "corpus/index.json"
STATS_PATH = "corpus/stats.json"
# Field-level scoring flags (Phase 6). Canonical path lives here so the read model
# (this CLI) and the write path (api/) share one constant; api/settings imports it.
ANNOTATIONS_PATH = "corpus/annotations.jsonl"
# cv-tailor run links (cv-tailor integration Phase 1, job_radar_SPEC §11.3). Same pattern:
# canonical path here, shared by the read model (this CLI) and the write path (api/).
CV_TAILOR_LINKS_PATH = "corpus/cv_tailor_links.jsonl"


def load_records(input_glob: str) -> list[JDRecord]:
    records: list[JDRecord] = []
    for path in sorted(glob.glob(input_glob, recursive=True)):
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    records.append(JDRecord.from_jsonl(line))
    return records


def _counts(values) -> dict:
    """Counter as an insertion-friendly dict sorted by count desc."""
    return dict(Counter(values).most_common())


def summarize(records: list[JDRecord]) -> dict:
    """Return a summary dict over the corpus."""
    fit = [r.fit_score for r in records if r.fit_score is not None]
    return {
        "total": len(records),
        "by_tier": _counts(r.tier for r in records),
        "by_source_ats": _counts(r.source_ats for r in records),
        "by_role_type": _counts(rt for r in records for rt in (r.role_type or [])),
        "by_domain": _counts(d for r in records for d in (r.domain or [])),
        "by_application_decision": _counts(r.application_decision for r in records),
        "applied_count": sum(1 for r in records if r.applied),
        "fit_score": {
            "n": len(fit),
            "mean": round(sum(fit) / len(fit), 2) if fit else None,
            "min": min(fit) if fit else None,
            "max": max(fit) if fit else None,
        },
    }


def print_summary(summary: dict) -> None:
    print(f"Corpus: {summary['total']} records")

    def section(title, mapping):
        print(f"\n{title}:")
        for k, v in mapping.items():
            print(f"  {k}: {v}")

    section("By tier", summary["by_tier"])
    section("By source", summary["by_source_ats"])
    section("By role_type", summary["by_role_type"])
    section("By domain", summary["by_domain"])
    section("By application_decision", summary["by_application_decision"])
    fs = summary["fit_score"]
    print(f"\nApplied: {summary['applied_count']}")
    print(f"fit_score: n={fs['n']} mean={fs['mean']} min={fs['min']} max={fs['max']}")


# ---------------------------------------------------------------------------
# UI index — the join (score ⨝ JD ⨝ sidecar ⨝ workflow), denormalised
# ---------------------------------------------------------------------------

# Extraction fields lifted onto each index row (used by UI filters + detail),
# each with the empty value to use when no JDRecord joins the score.
_EXTRACTION_DEFAULTS = {
    "domain": [],
    "role_type": [],
    "seniority": "",
    "technical_depth": "",
    "remote_policy": "",
    "company_stage": "",
    "company_size_signal": "",
    "years_experience_required": "",
    "required_technologies": [],
    "required_competencies": [],
    "nice_to_have_technologies": [],
    "nice_to_have_competencies": [],
    "delivery_motion": [],
    "leadership_geography": [],
    "culture_signals": [],
    "raw_observations": "",
}


def _location_for(jd: JDRecord | None, meta: dict | None) -> str:
    """Display location: sidecar string (richer) first, JDRecord field as fallback."""
    if meta and meta.get("location_str"):
        return meta["location_str"]
    return jd.location if jd else ""


# Fields carried per annotation onto an index row (job_radar_SPEC §10.11 Feature 2).
_ANNOTATION_VIEW_FIELDS = (
    "ts", "annotation_type", "field", "observed", "expected", "reason",
    "scorer_label", "scorer_fit_score",
)


def load_annotations(path: str = ANNOTATIONS_PATH) -> dict[str, list[dict]]:
    """Group scoring flags from ``corpus/annotations.jsonl`` by ``job_id``.

    Append-only and tolerant (reuses ``cli.track.load_events``); each annotation is
    projected to the view fields the UI needs. Used by the index export (embed) and by
    the live ``GET /api/index`` overlay so a freshly submitted flag shows on reload.
    """
    by_job: dict[str, list[dict]] = {}
    for event in load_events(path):
        job_id = event.get("job_id")
        if not job_id:
            continue
        by_job.setdefault(job_id, []).append({f: event.get(f) for f in _ANNOTATION_VIEW_FIELDS})
    return by_job


def load_cv_tailor_links(path: str = CV_TAILOR_LINKS_PATH) -> dict[str, dict]:
    """Latest cv-tailor link per ``job_id`` from ``corpus/cv_tailor_links.jsonl``.

    Append-only and tolerant (reuses ``cli.track.load_events``); a job_id can recur (Phase 1
    re-records, Phase 3 callbacks) so the most recent ``ts`` wins (ISO strings compare
    lexically). Used by the index export (embed the ``cv_tailor`` section) and the live
    ``GET /api/index`` overlay so a freshly added link shows on reload (job_radar_SPEC §11.3).
    """
    latest: dict[str, dict] = {}
    for event in load_events(path):
        job_id = event.get("job_id")
        if not job_id:
            continue
        _migrate_cv_tailor_fields(event)
        prev = latest.get(job_id)
        if prev is None or str(event.get("ts", "")) >= str(prev.get("ts", "")):
            latest[job_id] = event
    return latest


def load_all_cv_tailor_links(path: str = CV_TAILOR_LINKS_PATH) -> list[dict]:
    """Every cv-tailor link record (NOT deduplicated), in file order, with the read-time
    field migration applied (deviation 43).

    ``load_cv_tailor_links`` keeps only the latest run per ``job_id`` (the read-model
    contract); the calibration report (``cli.analyse --report cv_tailor``) also needs the
    full history so it can surface multiple runs of the same role. Records without a
    ``job_id`` are skipped, same as the latest-per-job loader.
    """
    records: list[dict] = []
    for event in load_events(path):
        if not event.get("job_id"):
            continue
        _migrate_cv_tailor_fields(event)
        records.append(event)
    return records


def _migrate_cv_tailor_fields(record: dict) -> None:
    """Read-time field migration (deviation 43) — no file rewrite, no pipeline stage.

    Phase-1 records used ``cv_tailor_score`` and a speculative ``grounding_score``. The
    schema was cleaned up before Phase 3: ``cv_tailor_score`` → ``fit_score``, and
    ``grounding_score`` (no UI counterpart) dropped. Old lines on disk are normalised to the
    new names as they load; new lines already carry them. ``cv_quality_score`` simply absent
    on old records (correctly → null in the view)."""
    if "cv_tailor_score" in record and "fit_score" not in record:
        record["fit_score"] = record["cv_tailor_score"]
    record.pop("cv_tailor_score", None)
    record.pop("grounding_score", None)


def cv_tailor_view(link: dict | None) -> dict:
    """Project a cv-tailor link record to the ``cv_tailor`` section embedded on an index row.

    ``{has_output: false}`` when no link exists; otherwise the latest run's snapshot
    (job_radar_SPEC §11.3 read-model contract)."""
    if not link:
        return {"has_output": False}
    return {
        "has_output": True,
        "run_id": link.get("cv_tailor_run_id"),
        # fit_score + coverage_score are 0.0–1.0 (shown as %); cv_quality_score is 0.0–10.0
        # (shown as X.X/10). Old cv_tailor_score is migrated to fit_score on load (deviation 43).
        "fit_score": link.get("fit_score", link.get("cv_tailor_score")),
        "coverage_score": link.get("coverage_score"),
        "cv_quality_score": link.get("cv_quality_score"),
        "cvcm_enabled": link.get("cvcm_enabled"),
        "tailoring_mode": link.get("tailoring_mode"),
        "output_link": link.get("output_link"),
        "notes": link.get("notes"),
        "ts": link.get("ts"),
    }


def build_index_rows(scores, jds, metas, workflow, annotations=None, cv_tailor_links=None) -> list[dict]:
    """One denormalised row per scored ``job_id``: scoring + live workflow state +
    JDRecord extraction (filters + detail) + full JD text. Mirrors the tracker's
    join (cli.track.build_rows) but carries the extra extraction/detail the UI needs.

    Feature 1 (§10.11): exposes both the scorer's verdict (``scorer_*``) and any owner
    ``fit_override`` (``user_*``), plus the resolved ``display_*`` the UI sorts/filters on.
    The scorer's value is preserved — an override never mutates the ApplicationRecord.
    Feature 2 (§10.11): embeds existing annotations per job for visibility + dup checks.
    cv-tailor (§11.3): embeds the latest cv-tailor run link per job (``cv_tailor`` section).
    """
    annotations = annotations or {}
    cv_tailor_links = cv_tailor_links or {}
    rows: list[dict] = []
    for job_id, score in scores.items():
        jd = jds.get(job_id)
        meta = metas.get(jd.source_url) if jd else None
        state = workflow.get(job_id, _default_state())
        override = state.get("fit_override")
        display_fit = override or score.fit_label
        job_annotations = annotations.get(job_id, [])
        row = {
            "job_id": job_id,
            "company": jd.company if jd else "?",
            "title": _title_for(jd, meta, state.get("title_override")),
            # --- scoring (ApplicationRecord), with the display value the UI uses ---
            "fit_score": score.fit_score,
            "fit_label": display_fit,
            "fit_label_reason": score.fit_label_reason,
            "priority_score": score.priority_score,
            "requirement_gaps": score.requirement_gaps,
            "blocking_constraints": score.blocking_constraints,
            "scored_at": score.scored_at,
            "profile_version": score.profile_version,
            # --- fit override (Feature 1): scorer vs user, both preserved ---
            "scorer_fit_label": score.fit_label,
            "scorer_fit_score": score.fit_score,
            "scorer_priority_score": score.priority_score,
            "user_fit_label": override,
            "user_fit_reason": state.get("fit_override_reason"),
            "display_fit_label": display_fit,
            "display_priority_score": score.priority_score,
            "has_fit_override": override is not None,
            # --- live workflow state (activity-log projection) ---
            "application_status": state["status"],
            "outcome": state["outcome"],
            "application_date": state["application_date"],
            "notes": state["notes"],
            # --- scoring flags (Feature 2) ---
            "annotations": job_annotations,
            "annotation_count": len(job_annotations),
            "has_annotations": bool(job_annotations),
            # --- cv-tailor run link (§11.3) ---
            "cv_tailor": cv_tailor_view(cv_tailor_links.get(job_id)),
            # --- location ---
            "location": _location_for(jd, meta),
            "location_workable": derive_location_workable(meta),
            # --- provenance ---
            "source_url": jd.source_url if jd else "",
            "source_ats": jd.source_ats if jd else "",
            "tier": jd.tier if jd else None,
            "date_first_seen": jd.collected_at if jd else "",
            # --- full JD text (detail panel) ---
            "raw_text": jd.raw_text if jd else "",
        }
        for field, empty in _EXTRACTION_DEFAULTS.items():
            row[field] = getattr(jd, field) if jd else empty
        rows.append(row)
    return rows


# ---------------------------------------------------------------------------
# Interactive-state source selection (Phase 6.5 — SPEC_DB_MIGRATION §4 Steps 3/5).
# The three interactive sources (workflow projection, annotations, cv-tailor links)
# can come from JSONL or SQLite; pipeline artefacts (scores/jds/metas) are always JSONL.
# ---------------------------------------------------------------------------

def interactive_from_jsonl(activity_log: str, annotations: str, cv_tailor_links: str):
    """(workflow, annotations, cv_tailor_links) read from the JSONL files."""
    return (
        project(load_events(activity_log)),
        load_annotations(annotations),
        load_cv_tailor_links(cv_tailor_links),
    )


def interactive_from_sqlite(conn=None):
    """(workflow, annotations, cv_tailor_links) read from SQLite. Inits the DB so an
    empty/absent DB reports clean divergences rather than crashing on a missing table."""
    init_db()
    conn = conn or get_db()
    return (
        project(load_events_sqlite(conn)),
        load_annotations_sqlite(conn),
        load_cv_tailor_links_sqlite(conn),
    )


def build_rows_for_source(source: str, scores, jds, metas, *,
                          activity_log: str, annotations: str, cv_tailor_links: str) -> list[dict]:
    """Build index rows joining the always-JSONL pipeline artefacts with the interactive
    state read from ``source`` (``jsonl`` or ``sqlite``)."""
    if source == "sqlite":
        wf, ann, cvt = interactive_from_sqlite()
    else:
        wf, ann, cvt = interactive_from_jsonl(activity_log, annotations, cv_tailor_links)
    return build_index_rows(scores, jds, metas, wf, ann, cvt)


def compare_index_rows(rows_a: list[dict], rows_b: list[dict]) -> list[str]:
    """Compare two index-row lists (e.g. JSONL-derived vs SQLite-derived) by job_id.

    Returns a list of human-readable divergence descriptions (empty == identical). Reports
    job_ids present in only one side, and per-field value differences for shared job_ids.
    """
    by_a = {r["job_id"]: r for r in rows_a}
    by_b = {r["job_id"]: r for r in rows_b}
    diffs: list[str] = []
    for job_id in sorted(set(by_a) - set(by_b)):
        diffs.append(f"{job_id}: present in A only")
    for job_id in sorted(set(by_b) - set(by_a)):
        diffs.append(f"{job_id}: present in B only")
    for job_id in sorted(set(by_a) & set(by_b)):
        a, b = by_a[job_id], by_b[job_id]
        for key in sorted(set(a) | set(b)):
            if a.get(key) != b.get(key):
                diffs.append(f"{job_id}.{key}: A={a.get(key)!r} != B={b.get(key)!r}")
    return diffs


def load_cost_to_date(path: str = STATS_PATH) -> float:
    """Sum ``cost_usd`` across every run in ``corpus/stats.json`` (0.0 if absent)."""
    try:
        with open(path, encoding="utf-8") as fh:
            runs = json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError):
        return 0.0
    return round(sum(float(r.get("cost_usd", 0) or 0) for r in runs), 4)


def index_stats(rows: list[dict], *, cost_to_date: float = 0.0) -> dict:
    """Corpus-stats block embedded in index.json for the UI stats bar."""
    return {
        "total": len(rows),
        "by_fit_label": _counts(r["fit_label"] for r in rows),
        "by_application_status": _counts(r["application_status"] for r in rows),
        "fit_score_distribution": {
            str(s): c for s, c in sorted(Counter(r["fit_score"] for r in rows).items())
        },
        "cost_to_date_usd": cost_to_date,
    }


def build_index(rows: list[dict], stats: dict, *, generated_at: str | None = None) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "jdrecord_schema_version": JDRECORD_SCHEMA_VERSION,
        "generated_at": generated_at,
        "stats": stats,
        "records": rows,
    }


def export_index(
    rows: list[dict],
    stats: dict,
    *,
    path: str = INDEX_PATH,
    generated_at: str | None = None,
) -> str:
    """Write the joined, denormalised UI index (records + stats) to ``path``."""
    payload = build_index(rows, stats, generated_at=generated_at)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Corpus statistics and UI index export.")
    parser.add_argument("--input", default=VALIDATED_GLOB,
                        help=f"Glob for JSONL JDRecords to summarise (default: {VALIDATED_GLOB}; recursive ** supported)")
    parser.add_argument("--export-index", action="store_true", help="Also write corpus/index.json for the UI (joined score+JD+workflow view)")
    parser.add_argument("--scored", default=SCORED_GLOB, help=f"Glob for scored files used by --export-index (default: {SCORED_GLOB})")
    parser.add_argument("--validated", default=VALIDATED_GLOB, help=f"Glob for validated JDs used by --export-index (default: {VALIDATED_GLOB})")
    parser.add_argument("--meta", default=META_GLOB, help=f"Glob for metadata sidecars used by --export-index (default: {META_GLOB})")
    parser.add_argument("--activity-log", default=LOG_PATH, dest="activity_log", help=f"Activity log used by --export-index (default: {LOG_PATH})")
    parser.add_argument("--annotations", default=ANNOTATIONS_PATH, help=f"Scoring-flag log embedded by --export-index (default: {ANNOTATIONS_PATH})")
    parser.add_argument("--cv-tailor-links", default=CV_TAILOR_LINKS_PATH, dest="cv_tailor_links", help=f"cv-tailor run links embedded by --export-index (default: {CV_TAILOR_LINKS_PATH})")
    parser.add_argument("--stats-file", default=STATS_PATH, dest="stats_file", help=f"Cost ledger for cost-to-date (default: {STATS_PATH})")
    parser.add_argument(
        "--source", choices=("jsonl", "sqlite", "both"), default="jsonl",
        help="Where --export-index reads interactive state (workflow/annotations/cv-tailor): "
             "jsonl (default), sqlite, or both (compare the two, exit non-zero on any divergence). "
             "Pipeline artefacts (scores/JDs/metadata) are always JSONL.",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    records = load_records(args.input)
    print_summary(summarize(records))

    if args.export_index:
        scores = load_scores(args.scored)
        jds = load_jdrecords(args.validated)
        metas = load_meta(args.meta)
        paths = dict(activity_log=args.activity_log, annotations=args.annotations,
                     cv_tailor_links=args.cv_tailor_links)

        if args.source == "both":
            rows_jsonl = build_rows_for_source("jsonl", scores, jds, metas, **paths)
            rows_sqlite = build_rows_for_source("sqlite", scores, jds, metas, **paths)
            diffs = compare_index_rows(rows_jsonl, rows_sqlite)
            if diffs:
                print(f"\n❌ {len(diffs)} divergence(s) between JSONL and SQLite:")
                for d in diffs:
                    print(f"  - {d}")
                return 1
            print(f"\n✅ 0 divergences across {len(rows_jsonl)} jobs (JSONL vs SQLite)")
            rows = rows_jsonl  # both agree; export from the JSONL source (safe default)
        else:
            rows = build_rows_for_source(args.source, scores, jds, metas, **paths)

        stats = index_stats(rows, cost_to_date=load_cost_to_date(args.stats_file))
        path = export_index(rows, stats)
        print(f"\nIndex → {path} ({len(rows)} scored job(s), ${stats['cost_to_date_usd']:.2f} to date)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
