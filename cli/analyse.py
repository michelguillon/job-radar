"""analyse.py — read-only corpus reporting (Phase 4+, job_radar_SPEC §11.1).

Prints structured reports over the existing corpus files. It is **strictly
read-only**: it never writes a corpus file, never calls a pipeline stage, and
never touches the Anthropic API. Same shape as cli.track / cli.digest — pure
aggregation functions over plain data (so tests stay deterministic), with a thin
``main()`` doing the IO (glob loads, the clock) and dispatch.

    python -m cli.analyse                          # default: score-distribution
    python -m cli.analyse --report score-distribution
    python -m cli.analyse --report status
    python -m cli.analyse --report companies
    python -m cli.analyse --report gaps
    python -m cli.analyse --report all             # all four, header-separated

Reuses the tracker's loaders + join (cli.track.load_scores / load_jdrecords /
load_meta / load_events / project) — it does not reimplement the score ⨝ JD ⨝
activity-log join. This is the foundation for the company yield-tracking backlog
(docs/BACKLOG_YIELD_TRACKING.md); v1 reports only what is derivable from the
current data (no company metadata yet).
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import Counter
from datetime import datetime, timezone

from cli.stats import STATS_PATH, load_cost_to_date
from cli.track import (
    LOG_PATH,
    META_GLOB,
    SCORED_GLOB,
    VALIDATED_GLOB,
    _default_state,
    _title_for,
    _truncate,
    load_events,
    load_jdrecords,
    load_meta,
    load_scores,
    project,
)
from models.record import APPLICATION_STATUS

log = logging.getLogger("analyse")

REPORTS = ("score-distribution", "status", "companies", "gaps", "all")
DEFAULT_REPORT = "score-distribution"

# Canonical fit-label order (mirrors models/record.py FIT_LABEL + the UI ordering)
# so empty buckets still render in a sensible, stable order.
FIT_LABEL_ORDER = [
    "strong_fit", "good_fit", "stretch", "blocked_fit", "interview_practice", "income_bridge",
]
# Funnel order for the pipeline section (mirrors the UI STATUS_ORDER).
STATUS_ORDER = [
    "new", "review", "shortlisted", "applied", "interviewing", "offer", "rejected", "archived",
]
# "Reviewed" = progressed past the untriaged backlog and not parked as done.
REVIEWED_STATUSES = APPLICATION_STATUS - {"new", "archived"}

STALE_DAYS = 21          # an applied role with no movement past this is likely dead
COMPANY_MIN_RATE_JOBS = 5  # below this many scored jobs, suppress per-company rates
COMPANY_MIN_REVIEWED = 5   # min reviewed before a shortlist-rate ranks


# ---------------------------------------------------------------------------
# Pure: small helpers
# ---------------------------------------------------------------------------

def _pct(n: int, total: int) -> int:
    """Integer percent, 0 when the denominator is 0 (never divide by zero)."""
    return round(100 * n / total) if total else 0


def _bar(count: int, max_count: int, width: int = 12) -> str:
    """A proportional block bar (empty when there is nothing to scale against)."""
    if max_count <= 0 or count <= 0:
        return ""
    return "█" * max(1, round(width * count / max_count))


def companies_by_job(scores: dict, jds: dict) -> dict[str, str]:
    """job_id → company (from the joined JDRecord), '(unknown)' when no JD joins."""
    return {jid: (jds[jid].company if jid in jds else "(unknown)") for jid in scores}


def _status_for(job_id: str, workflow: dict) -> str:
    return workflow.get(job_id, _default_state())["status"]


# ---------------------------------------------------------------------------
# Pure: aggregation
# ---------------------------------------------------------------------------

def fit_label_counts(scores: dict) -> dict[str, int]:
    """fit_label → count, in canonical order (every label present, even at 0)."""
    raw = Counter(s.fit_label for s in scores.values())
    return {label: raw.get(label, 0) for label in FIT_LABEL_ORDER}


def fit_score_counts(scores: dict) -> dict[int, int]:
    """fit_score (1–10) → count, every bucket present even at 0."""
    raw = Counter(s.fit_score for s in scores.values())
    return {score: raw.get(score, 0) for score in range(1, 11)}


def company_label_counts(scores: dict, by_job: dict[str, str], label: str) -> Counter:
    """Counter of company → number of scored jobs at ``label``."""
    return Counter(by_job[jid] for jid, s in scores.items() if s.fit_label == label)


def status_counts(scores: dict, workflow: dict) -> dict[str, int]:
    """application_status → count across the scored jobs (every status present)."""
    raw = Counter(_status_for(jid, workflow) for jid in scores)
    return {status: raw.get(status, 0) for status in STATUS_ORDER}


def review_rates(counts: dict[str, int]) -> dict:
    """Reviewed / shortlist / apply rates from the pipeline counts.

    reviewed = everything that left the 'new' backlog and is not 'archived'.
    shortlist/apply rates are computed against that reviewed base (lane counts —
    a job currently in a later lane is not double-counted in an earlier one).
    """
    total = sum(counts.values())
    reviewed = sum(c for s, c in counts.items() if s in REVIEWED_STATUSES)
    shortlisted = counts.get("shortlisted", 0)
    applied = counts.get("applied", 0)
    return {
        "total": total,
        "reviewed": reviewed,
        "shortlisted": shortlisted,
        "applied": applied,
        "review_rate": _pct(reviewed, total),
        "shortlist_rate": _pct(shortlisted, reviewed),
        "apply_rate": _pct(applied, reviewed),
    }


def stale_applications(scores, jds, metas, workflow, *, now: datetime, threshold: int = STALE_DAYS) -> list[dict]:
    """Applied roles whose earliest 'applied' date is > ``threshold`` days ago."""
    out: list[dict] = []
    for job_id in scores:
        state = workflow.get(job_id, _default_state())
        if state["status"] != "applied" or not state["application_date"]:
            continue
        try:
            applied = datetime.fromisoformat(state["application_date"]).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        days = (now - applied).days
        if days <= threshold:
            continue
        jd = jds.get(job_id)
        meta = metas.get(jd.source_url) if jd else None
        out.append({
            "company": jd.company if jd else "(unknown)",
            "title": _title_for(jd, meta, state.get("title_override")),
            "application_date": state["application_date"],
            "days": days,
        })
    return sorted(out, key=lambda r: -r["days"])


def company_report(scores: dict, by_job: dict[str, str], workflow: dict) -> list[dict]:
    """One row per company: jobs / strong / blocked / reviewed / shortlisted counts,
    sorted by job count desc then name. Rates are derived by the caller (suppressed
    below COMPANY_MIN_RATE_JOBS)."""
    rows: dict[str, dict] = {}
    for job_id, score in scores.items():
        company = by_job[job_id]
        row = rows.setdefault(company, {
            "company": company, "jobs": 0, "strong": 0, "blocked": 0, "reviewed": 0, "shortlisted": 0,
        })
        row["jobs"] += 1
        if score.fit_label == "strong_fit":
            row["strong"] += 1
        elif score.fit_label == "blocked_fit":
            row["blocked"] += 1
        status = _status_for(job_id, workflow)
        if status in REVIEWED_STATUSES:
            row["reviewed"] += 1
        if status == "shortlisted":
            row["shortlisted"] += 1
    return sorted(rows.values(), key=lambda r: (-r["jobs"], r["company"].lower()))


def gaps_report(scores: dict) -> dict:
    """Blocking-constraint + requirement-gap frequency, scoped per the report."""
    blocked = [s for s in scores.values() if s.fit_label == "blocked_fit"]
    strong = [s for s in scores.values() if s.fit_label == "strong_fit"]
    return {
        "blocked_role_count": len(blocked),
        "blocking_constraints": Counter(c for s in blocked for c in (s.blocking_constraints or [])),
        "requirement_gaps": Counter(g for s in scores.values() for g in (s.requirement_gaps or [])),
        "strong_role_count": len(strong),
        "strong_fit_gaps": Counter(g for s in strong for g in (s.requirement_gaps or [])),
    }


# ---------------------------------------------------------------------------
# Pure: presentation
# ---------------------------------------------------------------------------

def _counter_block(counter: Counter, *, top: int, indent: str = "  ") -> list[str]:
    """Render a Counter's ``top`` most-common as 'label  count' lines."""
    items = counter.most_common(top)
    if not items:
        return [f"{indent}(none)"]
    width = max(len(str(k)) for k, _ in items)
    return [f"{indent}{str(k):<{width}}  {v}" for k, v in items]


def format_score_distribution(scores, by_job, *, today: str, cost: float | None, cost_per_job: float | None) -> str:
    n_companies = len(set(by_job.values()))
    cost_str = ""
    if cost is not None:
        per = f" (${cost_per_job:.2f}/job avg)" if cost_per_job else ""
        cost_str = f" | est. cost ${cost:.2f}{per}"
    lines = [
        f"SCORE DISTRIBUTION REPORT — {today}",
        f"Corpus: {len(scores)} scored jobs | {n_companies} companies{cost_str}",
        "",
        "fit_label distribution:",
    ]
    labels = fit_label_counts(scores)
    width = max(len(k) for k in labels)
    for label, count in labels.items():
        lines.append(f"  {label:<{width}}  {count:>3}  ({_pct(count, len(scores)):>2}%)")

    lines += ["", "fit_score distribution (1–10):"]
    sc = fit_score_counts(scores)
    max_sc = max(sc.values()) if sc else 0
    for score in range(10, 0, -1):
        count = sc[score]
        lines.append(f"  {score:>2} {_bar(count, max_sc):<12}  {count}")

    lines += ["", "Top 10 companies by strong_fit count:"]
    lines += _counter_block(company_label_counts(scores, by_job, "strong_fit"), top=10)
    lines += ["", "Top 10 companies by blocked_fit count:"]
    lines += _counter_block(company_label_counts(scores, by_job, "blocked_fit"), top=10)
    return "\n".join(lines)


def format_status(scores, jds, metas, workflow, *, today: str, now: datetime) -> str:
    counts = status_counts(scores, workflow)
    rates = review_rates(counts)
    lines = [f"APPLICATION STATUS REPORT — {today}", "", "Pipeline:"]
    width = max(len(s) for s in STATUS_ORDER)
    for status in STATUS_ORDER:
        lines.append(f"  {status:<{width}}  {counts[status]:>3}")

    lines += [
        "",
        f"Review rate:    {rates['reviewed']} / {rates['total']}  ({rates['review_rate']}%)",
        f"Shortlist rate: {rates['shortlisted']} / {rates['reviewed']}  ({rates['shortlist_rate']}%)  of reviewed",
        f"Apply rate:     {rates['applied']} / {rates['reviewed']}  ({rates['apply_rate']}%)  of reviewed",
        "",
        f"Stale applications (>{STALE_DAYS} days since applied):",
    ]
    stale = stale_applications(scores, jds, metas, workflow, now=now)
    if not stale:
        lines.append("  (none)")
    else:
        cwidth = max(len(r["company"]) for r in stale)
        for r in stale:
            lines.append(
                f"  {r['company']:<{cwidth}}  {_truncate(r['title'], 44):<44}  "
                f"applied {r['application_date']}  ({r['days']} days)"
            )
    return "\n".join(lines)


def format_companies(scores, by_job, workflow, *, today: str) -> str:
    rows = company_report(scores, by_job, workflow)
    lines = [
        f"COMPANY REPORT — {today}",
        f"(all {len(rows)} companies with scored jobs; rates suppressed below "
        f"{COMPANY_MIN_RATE_JOBS} scored jobs)",
        "",
        f"{'Company':<24} {'Jobs':>4}  {'Strong':>6}  {'Blocked':>7}  {'Reviewed':>8}  {'Shortlisted':>11}",
        "─" * 70,
    ]
    for r in rows:
        lines.append(
            f"{_truncate(r['company'], 24):<24} {r['jobs']:>4}  {r['strong']:>6}  "
            f"{r['blocked']:>7}  {r['reviewed']:>8}  {r['shortlisted']:>11}"
        )

    # Top by shortlist rate (only meaningful with enough reviewed roles).
    ranked = sorted(
        ((r, _pct(r["shortlisted"], r["reviewed"])) for r in rows if r["reviewed"] >= COMPANY_MIN_REVIEWED),
        key=lambda t: -t[1],
    )
    lines += ["", f"Top by shortlist rate (min {COMPANY_MIN_REVIEWED} reviewed):"]
    if not ranked:
        lines.append("  (no company has enough reviewed roles yet)")
    else:
        cwidth = max(len(r["company"]) for r, _ in ranked)
        for r, rate in ranked[:10]:
            lines.append(f"  {r['company']:<{cwidth}}  {r['shortlisted']} / {r['reviewed']}  ({rate}%)")

    # Companies with a real sample but nothing shortlisted — candidates to drop.
    zero = [r for r in rows if r["jobs"] >= COMPANY_MIN_RATE_JOBS and r["shortlisted"] == 0]
    lines += ["", f"Zero shortlists despite {COMPANY_MIN_RATE_JOBS}+ scored:"]
    if not zero:
        lines.append("  (none)")
    else:
        cwidth = max(len(r["company"]) for r in zero)
        for r in sorted(zero, key=lambda r: -r["jobs"]):
            lines.append(f"  {r['company']:<{cwidth}}  ({r['jobs']} scored, 0 shortlisted)")
    return "\n".join(lines)


def format_gaps(scores, *, today: str) -> str:
    g = gaps_report(scores)
    lines = [
        f"REQUIREMENT GAPS & BLOCKERS — {today}",
        "",
        f"Top blocking constraints (across {g['blocked_role_count']} blocked_fit roles):",
    ]
    lines += _counter_block(g["blocking_constraints"], top=10)
    lines += ["", "Top requirement gaps (across all scored roles):"]
    lines += _counter_block(g["requirement_gaps"], top=10)
    lines += ["", f"Gaps appearing in strong_fit roles ({g['strong_role_count']} roles — worth addressing):"]
    lines += _counter_block(g["strong_fit_gaps"], top=10)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# IO + report dispatch
# ---------------------------------------------------------------------------

def _now() -> datetime:
    return datetime.now(timezone.utc)


def load_cost_and_jobs(stats_path: str = STATS_PATH) -> tuple[float | None, int]:
    """(cost_to_date_usd, total_jobs_labelled) from corpus/stats.json.

    Cost reuses cli.stats.load_cost_to_date; jobs sum the ``labelled`` of every
    label run. Returns ``(None, 0)`` if stats.json is missing — the cost line is
    then skipped gracefully (it is informational, never load-bearing)."""
    try:
        with open(stats_path, encoding="utf-8") as fh:
            runs = json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError):
        return None, 0
    cost = load_cost_to_date(stats_path)
    jobs = sum(int(r.get("labelled", 0) or 0) for r in runs if r.get("step") == "label")
    return cost, jobs


def build_reports(report: str, scores, jds, metas, workflow, *, today: str, now: datetime,
                  cost: float | None, cost_per_job: float | None) -> list[str]:
    """Return the requested report(s) as a list of rendered blocks."""
    by_job = companies_by_job(scores, jds)
    blocks: dict[str, str] = {
        "score-distribution": lambda: format_score_distribution(scores, by_job, today=today, cost=cost, cost_per_job=cost_per_job),
        "status": lambda: format_status(scores, jds, metas, workflow, today=today, now=now),
        "companies": lambda: format_companies(scores, by_job, workflow, today=today),
        "gaps": lambda: format_gaps(scores, today=today),
    }
    order = ["score-distribution", "status", "companies", "gaps"] if report == "all" else [report]
    return [blocks[name]() for name in order]


def cmd_analyse(argv: list[str], *, now=_now, out=print) -> int:
    parser = argparse.ArgumentParser(prog="analyse.py", description="Read-only corpus reports.")
    parser.add_argument("--report", choices=REPORTS, default=DEFAULT_REPORT,
                        help=f"Which report to print (default: {DEFAULT_REPORT})")
    parser.add_argument("--scored", default=SCORED_GLOB, help=f"Glob for scored files (default: {SCORED_GLOB})")
    parser.add_argument("--validated", default=VALIDATED_GLOB, help=f"Glob for validated JDs (default: {VALIDATED_GLOB})")
    parser.add_argument("--meta", default=META_GLOB, help=f"Glob for metadata sidecars (default: {META_GLOB})")
    parser.add_argument("--log", default=LOG_PATH, help=f"Activity log path (default: {LOG_PATH})")
    parser.add_argument("--stats-file", default=STATS_PATH, dest="stats_file", help=f"Cost ledger (default: {STATS_PATH})")
    args = parser.parse_args(argv)

    scores = load_scores(args.scored)
    jds = load_jdrecords(args.validated)
    metas = load_meta(args.meta)
    workflow = project(load_events(args.log))

    if not scores:
        out("(no scored jobs found — run the pipeline first)")
        return 0

    cost, jobs = load_cost_and_jobs(args.stats_file)
    cost_per_job = (cost / jobs) if (cost is not None and jobs) else None

    now_dt = now()
    today = now_dt.strftime("%Y-%m-%d")
    blocks = build_reports(args.report, scores, jds, metas, workflow,
                           today=today, now=now_dt, cost=cost, cost_per_job=cost_per_job)
    out(("\n\n" + "=" * 72 + "\n\n").join(blocks))
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    return cmd_analyse(argv)


if __name__ == "__main__":
    raise SystemExit(main())
