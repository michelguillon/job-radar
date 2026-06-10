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
from models.record import JDRECORD_SCHEMA_VERSION, SCHEMA_VERSION, JDRecord

INDEX_PATH = "corpus/index.json"
STATS_PATH = "corpus/stats.json"


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


def build_index_rows(scores, jds, metas, workflow) -> list[dict]:
    """One denormalised row per scored ``job_id``: scoring + live workflow state +
    JDRecord extraction (filters + detail) + full JD text. Mirrors the tracker's
    join (cli.track.build_rows) but carries the extra extraction/detail the UI needs.
    """
    rows: list[dict] = []
    for job_id, score in scores.items():
        jd = jds.get(job_id)
        meta = metas.get(jd.source_url) if jd else None
        state = workflow.get(job_id, _default_state())
        row = {
            "job_id": job_id,
            "company": jd.company if jd else "?",
            "title": _title_for(jd, meta, state.get("title_override")),
            # --- scoring (ApplicationRecord) ---
            "fit_score": score.fit_score,
            "fit_label": score.fit_label,
            "fit_label_reason": score.fit_label_reason,
            "priority_score": score.priority_score,
            "requirement_gaps": score.requirement_gaps,
            "blocking_constraints": score.blocking_constraints,
            "scored_at": score.scored_at,
            "profile_version": score.profile_version,
            # --- live workflow state (activity-log projection) ---
            "application_status": state["status"],
            "outcome": state["outcome"],
            "application_date": state["application_date"],
            "notes": state["notes"],
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
    parser.add_argument("--input", required=True, help="Glob for JSONL JDRecords (recursive ** supported)")
    parser.add_argument("--export-index", action="store_true", help="Also write corpus/index.json for the UI (joined score+JD+workflow view)")
    parser.add_argument("--scored", default=SCORED_GLOB, help=f"Glob for scored files used by --export-index (default: {SCORED_GLOB})")
    parser.add_argument("--validated", default=VALIDATED_GLOB, help=f"Glob for validated JDs used by --export-index (default: {VALIDATED_GLOB})")
    parser.add_argument("--meta", default=META_GLOB, help=f"Glob for metadata sidecars used by --export-index (default: {META_GLOB})")
    parser.add_argument("--activity-log", default=LOG_PATH, dest="activity_log", help=f"Activity log used by --export-index (default: {LOG_PATH})")
    parser.add_argument("--stats-file", default=STATS_PATH, dest="stats_file", help=f"Cost ledger for cost-to-date (default: {STATS_PATH})")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    records = load_records(args.input)
    print_summary(summarize(records))

    if args.export_index:
        scores = load_scores(args.scored)
        jds = load_jdrecords(args.validated)
        metas = load_meta(args.meta)
        workflow = project(load_events(args.activity_log))
        rows = build_index_rows(scores, jds, metas, workflow)
        stats = index_stats(rows, cost_to_date=load_cost_to_date(args.stats_file))
        path = export_index(rows, stats)
        print(f"\nIndex → {path} ({len(rows)} scored job(s), ${stats['cost_to_date_usd']:.2f} to date)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
