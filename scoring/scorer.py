"""scoring/scorer.py — pure 3-stage rule-based scoring (job_radar_SPEC §6.2).

Consumes a ``JDRecord``'s **extraction** fields + a ``Profile`` and produces one
``ApplicationRecord``. The scorer never reads or writes JDRecord's legacy
annotation stub (Option A, ``docs/job_radar_PHASE2_PLAN.md``).

  Stage 1 — Structural fit  → ``fit_score`` (1–10)
            5 dimensions, each 0–2 (domain can score 0.5), summed and rounded.
  Stage 2 — Constraints     → ``blocking_constraints`` + ``requirement_gaps``
            blocking = generic scorer-owned regex (clearance / language /
            sponsorship); gaps = profile.requirement_gap_watchlist, detected by
            scorer-defined regex (profile says WHAT to watch, scorer says HOW).
  Stage 3 — Classification  → ``fit_label`` + ``fit_label_reason`` + ``priority_score``

Heuristics here are tunable; the rationale lives in scoring/CLAUDE.md.
``search_mode`` filtering (§6.3) is presentation — it lives in score.py, not here,
except for the documented broad-mode priority nudge.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from models.record import ApplicationRecord, JDRecord
from scoring.profile import Profile

# Seniority is an ordered ladder; "within one rank" of a target scores a partial.
SENIORITY_RANK = ("ic", "senior_ic", "lead", "manager", "director", "vp", "exec")
_RANK = {name: i for i, name in enumerate(SENIORITY_RANK)}

# company_stage values treated as early-stage for the priority urgency nudge.
# (PHASE2_PLAN wrote "startup", but that is a company_size_signal value — the
# COMPANY_STAGE equivalent is "seed".)
EARLY_STAGE = frozenset({"seed", "series_a", "series_b"})

# Location verbatim values that carry no usable city signal.
_UNCLEAR_LOCATION = frozenset({"", "not_stated", "unknown"})


# --- Stage 1: structural fit -----------------------------------------------


@dataclass
class Dimensions:
    """The five 0–2 structural sub-scores, kept for the fit_label_reason."""

    role: float
    seniority: float
    technical_depth: float
    domain: float
    location: float

    def raw(self) -> float:
        return self.role + self.seniority + self.technical_depth + self.domain + self.location


def _role_score(jd: JDRecord, profile: Profile) -> float:
    return 2.0 if set(jd.role_type) & profile.target_roles else 0.0


def _seniority_score(jd: JDRecord, profile: Profile) -> float:
    if jd.seniority in profile.target_seniority:
        return 2.0
    jd_rank = _RANK.get(jd.seniority)
    if jd_rank is None:
        return 0.0
    target_ranks = [_RANK[s] for s in profile.target_seniority if s in _RANK]
    if target_ranks and min(abs(jd_rank - t) for t in target_ranks) == 1:
        return 1.0
    return 0.0


def _technical_depth_score(jd: JDRecord, profile: Profile) -> float:
    if jd.technical_depth in profile.target_technical_depth:
        return 2.0
    if jd.technical_depth in profile.acceptable_technical_depth:
        return 1.0
    return 0.0


def _domain_score(jd: JDRecord, profile: Profile) -> float:
    domains = set(jd.domain)
    if domains & profile.domains_strong:
        return 2.0
    if domains & profile.domains_adjacent:
        return 1.0
    if domains & profile.domains_lower:
        return 0.5
    return 0.0


def _location_score(jd: JDRecord, profile: Profile) -> float:
    loc = jd.location.strip().lower()
    base = profile.location_base.strip().lower()
    if jd.remote_policy == "remote":
        return 2.0
    if base and base in loc:  # London (base) — any policy works, candidate is there
        return 2.0
    if jd.remote_policy == "onsite":  # non-London onsite, relocation:false
        return 0.0
    # hybrid or not_stated, and not the base city:
    if loc in _UNCLEAR_LOCATION:
        return 1.0  # city unclear — benefit of the doubt
    return 0.0  # a named non-London city with no remote option


def stage1_fit(jd: JDRecord, profile: Profile) -> tuple[int, Dimensions]:
    """Return ``(fit_score 1–10, Dimensions)``."""
    dims = Dimensions(
        role=_role_score(jd, profile),
        seniority=_seniority_score(jd, profile),
        technical_depth=_technical_depth_score(jd, profile),
        domain=_domain_score(jd, profile),
        location=_location_score(jd, profile),
    )
    fit = max(1, min(10, round(dims.raw())))
    return fit, dims


# --- Stage 2: blocking constraints + requirement gaps ----------------------

# Generic, scorer-owned hard stops (NOT in the profile). Kept conservative to
# avoid false positives (e.g. "French market" must not trip the language rule).
# Each entry: (human-readable constraint, compiled regex over the JD haystack).
_BLOCKING_RULES = [
    (
        "active security clearance required",
        re.compile(r"security clearance|(?:active|valid|current)\s+clearance"
                   r"|clearance\s+(?:is\s+)?required|\b(?:ts/sci|dv cleared|sc cleared)\b"),
    ),
    (
        "native/fluent non-English language required",
        re.compile(
            r"\b(?:native|fluent|mother[- ]tongue|bilingual)\b[^.]{0,40}\b"
            r"(?:german|french|spanish|italian|dutch|portuguese|mandarin|"
            r"cantonese|japanese|korean|arabic|hebrew|russian|polish|swedish)\b"
        ),
    ),
    (
        "work authorisation / no visa sponsorship",
        re.compile(
            r"no\s+(?:visa\s+)?sponsorship"
            r"|(?:do(?:es)?\s+not|cannot|can't|will\s+not|won't|unable\s+to)"
            r"\s+(?:offer\s+|provide\s+)?(?:visa\s+)?sponsor"
            r"|without\s+sponsorship"
            r"|must be (?:a )?(?:us|u\.s\.|eu)\s+citizen|citizenship\s+(?:is\s+)?required"
        ),
    ),
]

# Requirement-gap detection. The profile's requirement_gap_watchlist says WHAT to
# watch; these regexes say HOW to detect each phrase in a JD. Keyed by the EXACT
# watchlist phrase — if the profile rewords a phrase, its trigger simply stops
# firing (documented in scoring/CLAUDE.md). A gap is emitted only when the phrase
# is both in the active watchlist AND detected in the JD.
_GAP_TRIGGERS = {
    "M&A transaction experience": re.compile(
        r"\bm&a\b|mergers?\s+(?:and|&)\s+acquisitions?"
    ),
    "post-merger integration leadership": re.compile(
        r"post[- ]merger|merger integration"
    ),
    "deep Salesforce administration": re.compile(
        r"salesforce\s+(?:admin|administrat|certif)"
    ),
    "contact centre transformation expertise": re.compile(
        r"contact cent(?:er|re)|call cent(?:er|re)|\bccaas\b"
    ),
    "CRM and revenue operations expertise": re.compile(
        r"revenue operations|\brevops\b|crm administ"
    ),
    "hands-on production data science ownership": re.compile(
        r"\bdata scien(?:ce|tist)\b|machine learning engineer|\bml engineer\b"
    ),
    "specialist cloud architecture certification": re.compile(
        r"(?:aws|azure|gcp|google cloud)[^.]{0,30}certif"
        r"|certified[^.]{0,30}(?:architect|aws|azure|gcp)"
        r"|professional cloud architect"
    ),
    "formal management consulting background": re.compile(
        r"management consulting|\bmckinsey\b|\bbain\b|\bbcg\b|big[- ]?4|big[- ]?four"
    ),
}


def _haystack(jd: JDRecord) -> str:
    parts = [
        *jd.required_competencies,
        *jd.required_technologies,
        *jd.nice_to_have_competencies,
        *jd.nice_to_have_technologies,
        jd.raw_observations,
        jd.raw_text,
    ]
    return " ".join(parts).lower()


def stage2_constraints(jd: JDRecord, profile: Profile) -> tuple[list[str], list[str]]:
    """Return ``(requirement_gaps, blocking_constraints)``."""
    text = _haystack(jd)

    blocking = [label for label, pattern in _BLOCKING_RULES if pattern.search(text)]

    gaps = [
        phrase
        for phrase in profile.requirement_gap_watchlist
        if phrase in _GAP_TRIGGERS and _GAP_TRIGGERS[phrase].search(text)
    ]
    # No double-count: a gap already surfaced as a blocking constraint is dropped.
    gaps = [g for g in gaps if g not in blocking]
    return gaps, blocking


# --- Stage 3: classification + priority ------------------------------------


def stage3_label(fit_score: int, blocking: list[str]) -> str:
    """Map fit_score + blocker presence to a FIT_LABEL (job_radar_SPEC §6.2)."""
    has_block = bool(blocking)
    if has_block and fit_score >= 7:
        return "blocked_fit"
    if fit_score >= 8 and not has_block:
        return "strong_fit"
    if fit_score >= 6 and not has_block:
        return "good_fit"
    if fit_score >= 5:
        return "stretch"  # incl. 6–7 with a blocker
    if fit_score >= 3:
        return "interview_practice"
    return "income_bridge"  # <= 2


def priority_score(fit_score: int, jd: JDRecord, blocking: list[str], mode: str) -> int:
    """fit_score adjusted by urgency signals, clamped 1–10 (job_radar_SPEC §6.5)."""
    score = fit_score
    if jd.company_stage in EARLY_STAGE:
        score += 1
    if blocking:
        score -= 2
    if mode == "broad" and fit_score <= 4:
        score += 1  # surface low-fit roles when searching broadly
    return max(1, min(10, score))


# --- fit_label_reason ------------------------------------------------------

_ROLE_PHRASE = {2.0: "strong role match", 0.0: "role mismatch"}
_SENIORITY_PHRASE = {2.0: "on-target seniority", 1.0: "near-target seniority", 0.0: "seniority gap"}
_DEPTH_PHRASE = {2.0: "ideal technical depth", 1.0: "acceptable technical depth", 0.0: "technical-depth mismatch"}
_DOMAIN_PHRASE = {2.0: "strong domain", 1.0: "adjacent domain", 0.5: "peripheral domain", 0.0: "domain gap"}
_LOCATION_PHRASE = {2.0: "location works", 1.0: "location unclear", 0.0: "location blocker"}


def fit_label_reason(label: str, dims: Dimensions, gaps: list[str], blocking: list[str]) -> str:
    """One templated sentence summarising the dimensions + top blocker/gap."""
    summary = ", ".join(
        [
            _ROLE_PHRASE[dims.role],
            _SENIORITY_PHRASE[dims.seniority],
            _DEPTH_PHRASE[dims.technical_depth],
            _DOMAIN_PHRASE[dims.domain],
            _LOCATION_PHRASE[dims.location],
        ]
    )
    sentence = f"{label.replace('_', ' ').capitalize()}: {summary}."
    if blocking:
        sentence += f" Blocked by: {blocking[0]}."
    elif gaps:
        sentence += f" Gap: {gaps[0]}."
    return sentence


# --- Public entry point ----------------------------------------------------


def score(jd: JDRecord, profile: Profile, scored_at: str, mode: str | None = None) -> ApplicationRecord:
    """Score one JDRecord against the profile, returning an ApplicationRecord.

    ``mode`` defaults to the profile's ``search_mode``; pass a value to override
    (used by score.py ``--mode`` for the broad-mode priority nudge only).
    """
    active_mode = mode or profile.search_mode

    fit, dims = stage1_fit(jd, profile)
    gaps, blocking = stage2_constraints(jd, profile)
    label = stage3_label(fit, blocking)
    priority = priority_score(fit, jd, blocking, active_mode)

    return ApplicationRecord(
        job_id=jd.id,
        profile_version=profile.profile_version,
        scored_at=scored_at,
        fit_score=fit,
        fit_label=label,
        fit_label_reason=fit_label_reason(label, dims, gaps, blocking),
        requirement_gaps=gaps,
        blocking_constraints=blocking,
        priority_score=priority,
        application_status="new",
        notes="",
    )
