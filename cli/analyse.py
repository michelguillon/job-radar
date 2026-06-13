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
    python -m cli.analyse --report yield
    python -m cli.analyse --report cv_tailor       # Job Radar vs cv-tailor fit divergence
    python -m cli.analyse --report all             # all six, header-separated

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

from cli.collect import SEEDS_PATH, load_companies
from cli.stats import (
    ANNOTATIONS_PATH,
    CV_TAILOR_LINKS_PATH,
    STATS_PATH,
    load_all_cv_tailor_links_auto,
    load_annotations_auto,
    load_cost_to_date,
)
from cli.track import (
    LOG_PATH,
    META_GLOB,
    SCORED_GLOB,
    VALIDATED_GLOB,
    _default_state,
    _title_for,
    _truncate,
    load_activity_events,
    load_jdrecords,
    load_meta,
    load_scores,
    project,
)
from models.record import APPLICATION_STATUS

log = logging.getLogger("analyse")

REPORTS = ("score-distribution", "status", "companies", "gaps", "yield", "cv_tailor", "all")
DEFAULT_REPORT = "score-distribution"

# cv-tailor tailoring modes always rendered in the mode breakdown (even at 0 runs).
CVT_MODES = ("demo", "full")

# A scored role rated ≥ this then rejected is a scorer false positive (BACKLOG §5).
HIGH_SCORE_THRESHOLD = 7
# A shortlist rate below this on a high-volume company flags it as noise (BACKLOG §9).
NOISE_SHORTLIST_RATE = 10

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


def rejection_report(annotations: dict[str, list[dict]], by_job: dict[str, str]) -> dict:
    """Aggregate ``rejection_reason`` annotations: total recorded, distinct rejected
    roles, reason frequency, and per-company counts + reason breakdown.

    ``annotations`` is the load_annotations projection (job_id → list of annotation
    dicts); only ``annotation_type == "rejection_reason"`` entries are counted."""
    reasons = Counter()
    roles: set[str] = set()
    company_counts = Counter()
    company_reasons: dict[str, Counter] = {}
    for job_id, anns in annotations.items():
        for a in anns:
            if a.get("annotation_type") != "rejection_reason":
                continue
            reason = a.get("reason")
            reasons[reason] += 1
            roles.add(job_id)
            company = by_job.get(job_id, "(unknown)")
            company_counts[company] += 1
            company_reasons.setdefault(company, Counter())[reason] += 1
    return {
        "total": sum(reasons.values()),
        "role_count": len(roles),
        "reasons": reasons,
        "company_counts": company_counts,
        "company_reasons": company_reasons,
    }


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
# Pure: company yield (BACKLOG_YIELD_TRACKING §§5–9)
# ---------------------------------------------------------------------------
#
# Joins the company seeds (name + v2 metadata) against the scored corpus + the
# workflow projection + the validated JDs + rejection annotations, producing one
# row per company plus domain/ATS rollups. Everything is derived at report time —
# no new corpus file is written. Cost is an *estimate*: jobs_scored × COST_PER_JOB,
# where COST_PER_JOB = total labelling cost / total jobs labelled (corpus/stats.json).

_YIELD_COUNT_KEYS = (
    "jobs_collected", "jobs_scored", "reviewed", "shortlisted",
    "applied", "rejected", "archived", "high_score_rejected",
)


def _zero_yield_metrics() -> dict:
    return {k: 0 for k in _YIELD_COUNT_KEYS}


def company_yield_metrics(scores, by_job, jds, workflow) -> dict[str, dict]:
    """Raw per-company corpus counts, keyed by company name.

    ``jobs_collected`` counts validated JDs (everything pulled into the corpus);
    the rest count the *scored* roles and their latest workflow lane.
    ``high_score_rejected`` = a role the scorer rated ``>= HIGH_SCORE_THRESHOLD``
    that ended up ``rejected`` (the scorer-false-positive proxy)."""
    collected = Counter(jd.company for jd in jds.values())
    rows: dict[str, dict] = {}

    def row(company: str) -> dict:
        r = rows.get(company)
        if r is None:
            r = _zero_yield_metrics()
            r["jobs_collected"] = collected.get(company, 0)
            rows[company] = r
        return r

    for job_id, score in scores.items():
        r = row(by_job[job_id])
        r["jobs_scored"] += 1
        status = _status_for(job_id, workflow)
        if status in REVIEWED_STATUSES:
            r["reviewed"] += 1
        if status == "shortlisted":
            r["shortlisted"] += 1
        elif status == "applied":
            r["applied"] += 1
        elif status == "rejected":
            r["rejected"] += 1
            if score.fit_score >= HIGH_SCORE_THRESHOLD:
                r["high_score_rejected"] += 1
        elif status == "archived":
            r["archived"] += 1
    # Companies that were collected but have nothing scored still get a (zero) row.
    for company in collected:
        row(company)
    return rows


def _derive_yield_rates(r: dict, cost_per_job: float | None) -> None:
    """Fold derived rates + estimated cost into a company row, in place.

    Rates are suppressed (``None`` → rendered ``—``) below COMPANY_MIN_RATE_JOBS
    scored jobs — a rate on a tiny sample is noise, not signal (BACKLOG §6)."""
    jobs, reviewed = r["jobs_scored"], r["reviewed"]
    est_cost = jobs * cost_per_job if cost_per_job else None
    r["estimated_cost_usd"] = est_cost
    if jobs < COMPANY_MIN_RATE_JOBS:
        r["shortlist_rate"] = r["apply_rate"] = r["rejection_rate"] = r["false_positive_rate"] = None
    else:
        base = max(reviewed, 1)
        r["shortlist_rate"] = _pct(r["shortlisted"], base)
        r["apply_rate"] = _pct(r["applied"], base)
        r["rejection_rate"] = _pct(r["rejected"], base)
        r["false_positive_rate"] = _pct(r["high_score_rejected"], base)
    r["cost_per_shortlist"] = (est_cost / r["shortlisted"]) if (est_cost and r["shortlisted"]) else None
    r["cost_per_application"] = (est_cost / r["applied"]) if (est_cost and r["applied"]) else None


def _yield_rollup(rows: list[dict], key: str) -> list[dict]:
    """Aggregate the per-company rows by ``key`` (``domain`` or ``ats``)."""
    groups: dict[str, dict] = {}
    for r in rows:
        g = groups.setdefault(r[key] or "(unknown)", {
            "key": r[key] or "(unknown)", "companies": 0, "jobs_scored": 0,
            "reviewed": 0, "shortlisted": 0, "applied": 0, "high_score_rejected": 0,
            "estimated_cost_usd": 0.0,
        })
        g["companies"] += 1
        for k in ("jobs_scored", "reviewed", "shortlisted", "applied", "high_score_rejected"):
            g[k] += r[k]
        g["estimated_cost_usd"] += r["estimated_cost_usd"] or 0.0
    for g in groups.values():
        g["shortlist_rate"] = _pct(g["shortlisted"], max(g["reviewed"], 1)) if g["jobs_scored"] else 0
    return sorted(groups.values(), key=lambda g: (-g["jobs_scored"], g["key"]))


def build_yield_report(seeds, scores, jds, workflow, annotations, *, cost_per_job: float | None) -> dict:
    """Pure join: company seeds ⨝ scored corpus ⨝ workflow ⨝ validated JDs.

    Returns ``{cost_per_job, companies: [row...], domain_rollup, ats_rollup}`` —
    one row per company (union of the seed list and any company that appears in
    the corpus), sorted by scored-job volume. The caller renders it."""
    by_job = companies_by_job(scores, jds)
    metrics = company_yield_metrics(scores, by_job, jds, workflow)
    seed_by_name = {s["name"]: s for s in seeds}
    names = set(seed_by_name) | set(metrics)

    rows: list[dict] = []
    for name in names:
        seed = seed_by_name.get(name, {})
        row = {
            "company": name,
            "domain": seed.get("domain") or "(unknown)",
            "ats": seed.get("ats") or "(unknown)",
            "slug": seed.get("slug"),
            "fit_hypothesis": seed.get("fit_hypothesis") or "",
            "action": seed.get("action") or "keep",
            "notes": seed.get("notes") or "",
            "in_seeds": name in seed_by_name,
            **(metrics.get(name) or _zero_yield_metrics()),
        }
        _derive_yield_rates(row, cost_per_job)
        rows.append(row)
    rows.sort(key=lambda r: (-r["jobs_scored"], r["company"].lower()))

    return {
        "cost_per_job": cost_per_job,
        "companies": rows,
        "domain_rollup": _yield_rollup(rows, "domain"),
        "ats_rollup": _yield_rollup(rows, "ats"),
    }


# ---------------------------------------------------------------------------
# Pure: cv-tailor calibration (job_radar_SPEC §11.1 + §11.3)
# ---------------------------------------------------------------------------
#
# Joins the cv-tailor run links against the scored corpus to compare the two
# systems' fit verdicts. Job Radar's fit_score is 1–10; cv-tailor's fit_score is
# 0.0–1.0. Both are normalised to 0–100 and the delta (CVT − JR) shows divergence —
# negative = cv-tailor scored lower (expected, especially in demo mode). A run whose
# job_id is not in the scored corpus is surfaced (not dropped) as diagnostic data.


def _cvt_pct(value: float | None) -> int | None:
    """A 0.0–1.0 cv-tailor score → 0–100 integer percent (None-safe)."""
    return round(value * 100) if value is not None else None


def _cvt_row(job_id: str, link: dict, score, jd, meta, state) -> dict:
    """One latest-per-job comparison row (Job Radar vs cv-tailor)."""
    in_corpus = score is not None
    cvt_fit_pct = _cvt_pct(link.get("fit_score"))
    jr_fit = score.fit_score if in_corpus else None
    delta = (cvt_fit_pct - jr_fit * 10) if (cvt_fit_pct is not None and jr_fit is not None) else None
    return {
        "job_id": job_id,
        "in_corpus": in_corpus,
        "company": jd.company if jd else None,
        "title": _title_for(jd, meta, state.get("title_override")) if jd else None,
        "jr_fit_score": jr_fit,
        "jr_label": score.fit_label if in_corpus else None,
        "cvt_fit_pct": cvt_fit_pct,
        "coverage_pct": _cvt_pct(link.get("coverage_score")),
        "cv_quality_score": link.get("cv_quality_score"),
        "mode": link.get("tailoring_mode") or "(unknown)",
        "run_id": link.get("cv_tailor_run_id"),
        "ts": link.get("ts"),
        "delta": delta,
    }


def build_cv_tailor_report(all_links, scores, jds, metas, workflow) -> dict:
    """Pure join: cv-tailor run links ⨝ scored corpus ⨝ validated JDs.

    ``all_links`` is the full (non-deduplicated) list from
    ``cli.stats.load_all_cv_tailor_links``. Returns the latest-per-job comparison
    ``rows`` (sorted by Job Radar fit_score desc, with out-of-corpus runs last), the
    ``divergence`` summary, the per-``mode`` breakdown, and the ``multiple_runs`` per
    role. The caller renders it; nothing here writes a corpus file."""
    latest: dict[str, dict] = {}
    runs_by_job: dict[str, list[dict]] = {}
    for link in all_links:
        jid = link["job_id"]
        runs_by_job.setdefault(jid, []).append(link)
        prev = latest.get(jid)
        if prev is None or str(link.get("ts", "")) >= str(prev.get("ts", "")):
            latest[jid] = link

    rows: list[dict] = []
    for jid, link in latest.items():
        score = scores.get(jid)
        jd = jds.get(jid)
        meta = metas.get(jd.source_url) if jd else None
        state = workflow.get(jid, _default_state())
        rows.append(_cvt_row(jid, link, score, jd, meta, state))
    # In-corpus rows first, by JR fit desc; out-of-corpus rows last, by job_id.
    rows.sort(key=lambda r: (
        0 if r["in_corpus"] else 1,
        -(r["jr_fit_score"] or 0),
        (r["company"] or r["job_id"]).lower(),
    ))

    # Divergence summary over rows that have both verdicts (delta computable).
    scored = [r for r in rows if r["delta"] is not None]
    divergence = None
    if scored:
        divergence = {
            "mean": round(sum(r["delta"] for r in scored) / len(scored)),
            "most_aligned": min(scored, key=lambda r: abs(r["delta"])),
            "most_divergent": max(scored, key=lambda r: abs(r["delta"])),
        }

    # Per-mode breakdown (latest-per-job rows grouped by tailoring_mode).
    extra_modes = sorted({r["mode"] for r in rows} - set(CVT_MODES) - {"(unknown)"})
    mode_order = list(CVT_MODES) + extra_modes + (["(unknown)"] if any(r["mode"] == "(unknown)" for r in rows) else [])
    mode_breakdown = []
    for mode in mode_order:
        group = [r for r in rows if r["mode"] == mode]
        fits = [r["cvt_fit_pct"] for r in group if r["cvt_fit_pct"] is not None]
        covs = [r["coverage_pct"] for r in group if r["coverage_pct"] is not None]
        mode_breakdown.append({
            "mode": mode,
            "runs": len(group),
            "cvt_fit_mean": round(sum(fits) / len(fits)) if fits else None,
            "coverage_mean": round(sum(covs) / len(covs)) if covs else None,
        })

    # Roles with more than one run (full history), oldest→latest, latest flagged.
    multiple_runs = []
    for jid, runs in runs_by_job.items():
        if len(runs) < 2:
            continue
        ordered = sorted(runs, key=lambda r: str(r.get("ts", "")))
        latest_ts = ordered[-1].get("ts")
        jd = jds.get(jid)
        meta = metas.get(jd.source_url) if jd else None
        state = workflow.get(jid, _default_state())
        multiple_runs.append({
            "job_id": jid,
            "company": jd.company if jd else None,
            "title": _title_for(jd, meta, state.get("title_override")) if jd else None,
            "runs": [{
                "run_id": r.get("cv_tailor_run_id"),
                "ts": r.get("ts"),
                "cvt_fit_pct": _cvt_pct(r.get("fit_score")),
                "coverage_pct": _cvt_pct(r.get("coverage_score")),
                "cv_quality_score": r.get("cv_quality_score"),
                "is_latest": r.get("ts") == latest_ts,
            } for r in ordered],
        })
    multiple_runs.sort(key=lambda m: (m["company"] or m["job_id"]).lower())

    return {
        "rows": rows,
        "role_count": len(latest),
        "total_runs": len(all_links),
        "divergence": divergence,
        "mode_breakdown": mode_breakdown,
        "multiple_runs": multiple_runs,
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


def format_gaps(scores, *, today: str, annotations=None, by_job=None) -> str:
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

    # Rejection reasons (BACKLOG §2) — only when at least one is recorded (no zero-noise).
    rej = rejection_report(annotations or {}, by_job or {})
    if rej["total"]:
        lines += ["", f"REJECTION REASONS — {rej['total']} recorded across {rej['role_count']} rejected roles", ""]
        rwidth = max(len(str(r)) for r, _ in rej["reasons"].most_common())
        for reason, count in rej["reasons"].most_common():
            lines.append(f"  {str(reason):<{rwidth}}  {count:>3}   ({_pct(count, rej['total']):>2}%)")
        lines += ["", "Most-rejected companies:"]
        ranked = rej["company_counts"].most_common(10)
        cwidth = max(len(c) for c, _ in ranked)
        for company, count in ranked:
            breakdown = ", ".join(f"{r} ×{n}" for r, n in rej["company_reasons"][company].most_common())
            lines.append(f"  {company:<{cwidth}}  {count}  ({breakdown})")
    return "\n".join(lines)


def _rate(v: int | None) -> str:
    """A percent or ``—`` when suppressed/None (small-sample guard)."""
    return f"{v}%" if v is not None else "—"


def _money(v: float | None) -> str:
    return f"${v:.2f}" if v is not None else "—"


def format_yield(data: dict, *, today: str) -> str:
    """Render the company yield report (BACKLOG_YIELD_TRACKING §9)."""
    rows = data["companies"]
    cost_per_job = data["cost_per_job"]
    live = [r for r in rows if r["jobs_scored"] > 0]
    seeded = [r for r in rows if r["in_seeds"]]
    total_scored = sum(r["jobs_scored"] for r in rows)
    total_cost = sum((r["estimated_cost_usd"] or 0.0) for r in rows)
    cpj = f"${cost_per_job:.3f}/job" if cost_per_job else "n/a"

    lines = [
        f"COMPANY YIELD REPORT — {today}",
        f"Corpus: {total_scored} scored jobs | {len(live)} companies with live roles | "
        f"{len(seeded)} seeded | est. cost ${total_cost:.2f} | COST_PER_JOB {cpj}",
        f"(estimated cost = jobs_scored × COST_PER_JOB; rates suppressed below "
        f"{COMPANY_MIN_RATE_JOBS} scored jobs)",
        "",
        f"{'Company':<24} {'Fit':<6} {'Domain':<22} {'Jobs':>4} {'Rev':>4} {'Short%':>6} {'Cost/SL':>8}",
        "─" * 80,
    ]
    for r in live:
        lines.append(
            f"{_truncate(r['company'], 24):<24} {r['fit_hypothesis']:<6} "
            f"{_truncate(r['domain'], 22):<22} {r['jobs_scored']:>4} {r['reviewed']:>4} "
            f"{_rate(r['shortlist_rate']):>6} {_money(r['cost_per_shortlist']):>8}"
        )

    # ━━ Best performers (shortlist_rate desc, min reviewed) ━━
    ranked = sorted(
        (r for r in live if r["reviewed"] >= COMPANY_MIN_REVIEWED and r["shortlist_rate"] is not None),
        key=lambda r: -r["shortlist_rate"],
    )
    lines += ["", f"━━ Best performers (shortlist rate, min {COMPANY_MIN_REVIEWED} reviewed) ━━"]
    if not ranked:
        lines.append("  (no company has enough reviewed roles yet)")
    else:
        for r in ranked[:10]:
            lines.append(
                f"  {_truncate(r['company'], 24):<24} {r['shortlisted']}/{r['reviewed']} reviewed  "
                f"({_rate(r['shortlist_rate'])})  cost/shortlist {_money(r['cost_per_shortlist'])}"
            )

    # ━━ High-volume noise (jobs desc, shortlist_rate < threshold) ━━
    noise = sorted(
        (r for r in live if r["shortlist_rate"] is not None and r["shortlist_rate"] < NOISE_SHORTLIST_RATE),
        key=lambda r: -r["jobs_scored"],
    )
    lines += ["", f"━━ High-volume noise (≥{COMPANY_MIN_RATE_JOBS} scored, shortlist rate < {NOISE_SHORTLIST_RATE}%) ━━"]
    if not noise:
        lines.append("  (none)")
    else:
        for r in noise[:10]:
            lines.append(
                f"  {_truncate(r['company'], 24):<24} {r['jobs_scored']:>3} scored  "
                f"shortlist {_rate(r['shortlist_rate'])}  fp {_rate(r['false_positive_rate'])}"
            )

    # ━━ High false-positive rate (scorer said good, you rejected) ━━
    fp = sorted(
        (r for r in live if r["false_positive_rate"] is not None and r["false_positive_rate"] > 0),
        key=lambda r: -r["false_positive_rate"],
    )
    lines += ["", "━━ High false-positive rate (scored ≥7 then rejected) ━━"]
    if not fp:
        lines.append("  (none)")
    else:
        for r in fp[:10]:
            note = f"  — {_truncate(r['notes'], 40)}" if r["notes"] else ""
            lines.append(
                f"  {_truncate(r['company'], 24):<24} {r['high_score_rejected']}/{r['reviewed']} reviewed  "
                f"fp {_rate(r['false_positive_rate'])}{note}"
            )

    # ━━ No live jobs (in seeds, zero validated records) ━━
    dark = sorted((r for r in seeded if r["jobs_collected"] == 0), key=lambda r: r["company"].lower())
    lines += ["", "━━ No live jobs (seeded, zero validated records) ━━"]
    if not dark:
        lines.append("  (none)")
    else:
        for r in dark:
            tag = "  (manual watch — apply directly)" if r["ats"] == "manual" else ""
            lines.append(f"  {_truncate(r['company'], 28):<28} [{r['ats']}]{tag}")

    # ━━ Actions flagged (action != keep) ━━
    flagged = sorted(
        (r for r in seeded if r["action"] != "keep"),
        key=lambda r: (r["action"], r["company"].lower()),
    )
    lines += ["", "━━ Actions flagged (action ≠ keep) ━━"]
    if not flagged:
        lines.append("  (none)")
    else:
        awidth = max(len(r["action"]) for r in flagged)
        for r in flagged:
            note = f"  — {_truncate(r['notes'], 56)}" if r["notes"] else ""
            lines.append(f"  {_truncate(r['company'], 24):<24} {r['action']:<{awidth}}{note}")

    # ━━ Domain rollup ━━ / ━━ ATS rollup ━━
    for title, rollup in (("Domain rollup", data["domain_rollup"]), ("ATS rollup", data["ats_rollup"])):
        lines += ["", f"━━ {title} ━━",
                  f"  {'Category':<26} {'Cos':>3} {'Jobs':>4} {'Short%':>6} {'Est. cost':>9}"]
        for g in rollup:
            short = f"{g['shortlist_rate']}%" if g["jobs_scored"] else "—"
            lines.append(
                f"  {_truncate(g['key'], 26):<26} {g['companies']:>3} {g['jobs_scored']:>4} "
                f"{short:>6} {_money(g['estimated_cost_usd']):>9}"
            )
    return "\n".join(lines)


def _qual(value: float | None) -> str:
    """A cv-tailor quality score (0.0–10.0) as X.X, or ``—`` when absent."""
    return f"{value:.1f}" if value is not None else "—"


def _cvt_pct_str(value: int | None) -> str:
    return f"{value}%" if value is not None else "—"


def _short_id(job_id: str, width: int = 18) -> str:
    """A truncated job_id for out-of-corpus diagnostic rows (keeps the sha prefix)."""
    return job_id if len(job_id) <= width else job_id[:width] + "..."


def format_cv_tailor(data: dict, *, today: str) -> str:
    """Render the cv-tailor calibration report (job_radar_SPEC §11.1 + §11.3)."""
    rows = data["rows"]
    if not rows:
        return f"CV-TAILOR CALIBRATION REPORT — {today}\n\nNo cv-tailor runs recorded yet."

    modes_present = {r["mode"] for r in rows}
    mode_summary = f"all {next(iter(modes_present))} mode" if len(modes_present) == 1 else "mixed modes"
    lines = [
        f"CV-TAILOR CALIBRATION REPORT — {today}",
        f"{data['role_count']} roles with cv-tailor runs | {mode_summary}",
        "",
        "━━ By Job Radar fit score (desc) " + "━" * 44,
        "",
        f"{'Company':<22} {'Title':<40} {'JR':>2}  {'JR label':<18} "
        f"{'CVT':>4}  {'Cov':>4}  {'Qual':>4}  {'Mode':<6} {'Δ':>4}",
        "─" * 116,
    ]
    in_corpus = [r for r in rows if r["in_corpus"]]
    out_corpus = [r for r in rows if not r["in_corpus"]]
    for r in in_corpus:
        delta = f"{r['delta']:+d}" if r["delta"] is not None else "—"
        lines.append(
            f"{_truncate(r['company'] or '?', 22):<22} {_truncate(r['title'] or '?', 40):<40} "
            f"{r['jr_fit_score']:>2}  {(r['jr_label'] or ''):<18} "
            f"{_cvt_pct_str(r['cvt_fit_pct']):>4}  {_cvt_pct_str(r['coverage_pct']):>4}  "
            f"{_qual(r['cv_quality_score']):>4}  {_truncate(r['mode'], 6):<6} {delta:>4}"
        )
    if out_corpus:
        lines += ["", "Runs not in the scored corpus (diagnostic — role not collected/scored):"]
        for r in out_corpus:
            lines.append(
                f"  {_short_id(r['job_id']):<22} (not in corpus)   "
                f"CVT: {_cvt_pct_str(r['cvt_fit_pct'])}  cov: {_cvt_pct_str(r['coverage_pct'])}  "
                f"qual: {_qual(r['cv_quality_score'])}"
            )

    # ━━ Divergence summary ━━
    lines += ["", "━━ Divergence summary " + "━" * 55, "",
              "Δ = CVT fit% − (JR fit_score × 10)  [negative = cv-tailor lower than Job Radar]", ""]
    div = data["divergence"]
    if not div:
        lines.append("  (no role has both a Job Radar score and a cv-tailor run yet)")
    else:
        def _label(r: dict) -> str:
            return f"{r['company'] or _short_id(r['job_id'])} {_truncate(r['title'] or '', 40)}".strip()
        sign = "cv-tailor consistently lower" if div["mean"] < 0 else "cv-tailor consistently higher"
        lines += [
            f"Mean divergence:   {div['mean']:+d}  ({sign})",
            f"Most aligned:      {_label(div['most_aligned'])}  (Δ {div['most_aligned']['delta']:+d})",
            f"Most divergent:    {_label(div['most_divergent'])}  (Δ {div['most_divergent']['delta']:+d})",
        ]

    # ━━ By mode ━━
    lines += ["", "━━ By mode " + "━" * 66, ""]
    for m in data["mode_breakdown"]:
        fit = _cvt_pct_str(m["cvt_fit_mean"])
        cov = _cvt_pct_str(m["coverage_mean"])
        lines.append(f"  {m['mode']:<6} {m['runs']:>3} runs   CVT fit mean: {fit:>4}   Coverage mean: {cov:>4}")

    # ━━ Multiple runs ━━
    lines += ["", "━━ Multiple runs (same role, different runs) " + "━" * 32, ""]
    if not data["multiple_runs"]:
        lines.append("  (no role has more than one run)")
    else:
        for m in data["multiple_runs"]:
            label = f"{m['company'] or ''} {m['title'] or ''}".strip() or _short_id(m["job_id"])
            lines.append(f"  {label}: {len(m['runs'])} runs")
            for run in m["runs"]:
                flag = "  ← latest" if run["is_latest"] else ""
                lines.append(
                    f"    {run['run_id'] or '(no run_id)'}  fit: {_cvt_pct_str(run['cvt_fit_pct'])}  "
                    f"cov: {_cvt_pct_str(run['coverage_pct'])}  qual: {_qual(run['cv_quality_score'])}{flag}"
                )

    # ━━ Notes ━━
    lines += ["", "━━ Notes " + "━" * 68, "",
              "All cv-tailor demo-mode fit% and coverage% run systematically lower than full",
              "mode (typically 2–3× after refinement iterations). Run full mode on high-priority",
              "roles before drawing conclusions from a large negative Δ."]
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


def load_yield_seeds(seeds_path: str = SEEDS_PATH) -> list[dict]:
    """Company seeds for the yield report, or ``[]`` if the file is absent.

    The seeds are informational here (company metadata for the join) — a missing
    file degrades to a corpus-only yield report rather than erroring."""
    try:
        return load_companies(seeds_path)
    except FileNotFoundError:
        return []


def build_reports(report: str, scores, jds, metas, workflow, *, today: str, now: datetime,
                  cost: float | None, cost_per_job: float | None, annotations=None, seeds=None,
                  cv_tailor_links=None) -> list[str]:
    """Return the requested report(s) as a list of rendered blocks."""
    by_job = companies_by_job(scores, jds)
    blocks: dict[str, str] = {
        "score-distribution": lambda: format_score_distribution(scores, by_job, today=today, cost=cost, cost_per_job=cost_per_job),
        "status": lambda: format_status(scores, jds, metas, workflow, today=today, now=now),
        "companies": lambda: format_companies(scores, by_job, workflow, today=today),
        "gaps": lambda: format_gaps(scores, today=today, annotations=annotations, by_job=by_job),
        "yield": lambda: format_yield(
            build_yield_report(seeds or [], scores, jds, workflow, annotations or {}, cost_per_job=cost_per_job),
            today=today,
        ),
        "cv_tailor": lambda: format_cv_tailor(
            build_cv_tailor_report(cv_tailor_links or [], scores, jds, metas, workflow),
            today=today,
        ),
    }
    order = (["score-distribution", "status", "companies", "gaps", "yield", "cv_tailor"]
             if report == "all" else [report])
    return [blocks[name]() for name in order]


def cmd_analyse(argv: list[str], *, now=_now, out=print) -> int:
    parser = argparse.ArgumentParser(prog="analyse.py", description="Read-only corpus reports.")
    parser.add_argument("--report", choices=REPORTS, default=DEFAULT_REPORT,
                        help=f"Which report to print (default: {DEFAULT_REPORT})")
    parser.add_argument("--scored", default=SCORED_GLOB, help=f"Glob for scored files (default: {SCORED_GLOB})")
    parser.add_argument("--validated", default=VALIDATED_GLOB, help=f"Glob for validated JDs (default: {VALIDATED_GLOB})")
    parser.add_argument("--meta", default=META_GLOB, help=f"Glob for metadata sidecars (default: {META_GLOB})")
    parser.add_argument("--log", default=LOG_PATH, help=f"Activity log path (default: {LOG_PATH})")
    parser.add_argument("--annotations", default=ANNOTATIONS_PATH, help=f"Annotations log (default: {ANNOTATIONS_PATH})")
    parser.add_argument("--stats-file", default=STATS_PATH, dest="stats_file", help=f"Cost ledger (default: {STATS_PATH})")
    parser.add_argument("--seeds", default=SEEDS_PATH, help=f"Company seeds for the yield report (default: {SEEDS_PATH})")
    parser.add_argument("--cv-tailor-links", default=CV_TAILOR_LINKS_PATH, dest="cv_tailor_links",
                        help=f"cv-tailor run links for the cv_tailor report (default: {CV_TAILOR_LINKS_PATH})")
    args = parser.parse_args(argv)

    scores = load_scores(args.scored)
    jds = load_jdrecords(args.validated)
    metas = load_meta(args.meta)
    workflow = project(load_activity_events(args.log))
    annotations = load_annotations_auto(args.annotations)
    seeds = load_yield_seeds(args.seeds)
    cv_tailor_links = load_all_cv_tailor_links_auto(args.cv_tailor_links)

    if not scores:
        out("(no scored jobs found — run the pipeline first)")
        return 0

    cost, jobs = load_cost_and_jobs(args.stats_file)
    cost_per_job = (cost / jobs) if (cost is not None and jobs) else None

    now_dt = now()
    today = now_dt.strftime("%Y-%m-%d")
    blocks = build_reports(args.report, scores, jds, metas, workflow,
                           today=today, now=now_dt, cost=cost, cost_per_job=cost_per_job,
                           annotations=annotations, seeds=seeds, cv_tailor_links=cv_tailor_links)
    out(("\n\n" + "=" * 72 + "\n\n").join(blocks))
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    return cmd_analyse(argv)


if __name__ == "__main__":
    raise SystemExit(main())
