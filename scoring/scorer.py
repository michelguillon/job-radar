"""scoring/scorer.py — pure 3-stage rule-based scoring (job_radar_SPEC §6.2).

Consumes a ``JDRecord``'s **extraction** fields + a ``Profile`` and produces one
``ApplicationRecord``. The scorer never reads or writes JDRecord's legacy
annotation stub (Option A, ``docs/job_radar_PHASE2_PLAN.md``).

  Stage 1 — Structural fit  → ``fit_score`` (1–10)
            Signal vs gates (see "Stage 1 model" below).
  Stage 2 — Constraints     → ``blocking_constraints`` + ``requirement_gaps``
            blocking = generic scorer-owned regex (clearance / language /
            sponsorship); gaps = profile.requirement_gap_watchlist, detected by
            scorer-defined regex (profile says WHAT to watch, scorer says HOW).
  Stage 3 — Classification  → ``fit_label`` + ``fit_label_reason`` + ``priority_score``

Stage 1 model (Option A+B — gates vs signal, decided 2026-06-09):
  The earlier flat "5 equal 0–2 dims summed" model gave no resolution on a
  curated corpus — seniority and location saturated at max for every realistic
  JD, so 4 of 5 dimensions did almost no discriminating work. Now:

  * **Signal** (sets the 0–10 scale): role, domain, technical_depth.
    These are what differentiate fit. Weighted role ×2, domain ×2 (primary
    discriminators) and technical_depth ×1 (secondary, coarser) → max 10.
  * **Gates** (penalties only): seniority, location. A *hit* contributes 0; a
    *miss* subtracts. Table-stakes dimensions can only pull a score down, never
    inflate it. No partial credit (the old "within one rank" seniority tier is
    gone — a gate is binary, with one graded "unclear" tier for location).

  fit_score = round_half_up(signal − seniority_penalty − location_penalty),
  clamped to 1–10.

Heuristics here are tunable; the rationale lives in scoring/CLAUDE.md. The penalty
magnitudes and fit_label thresholds are **provisional** — they are being
calibrated against a corpus that deliberately includes negative JDs (§6).
``search_mode`` filtering (§6.3) is presentation — it lives in score.py.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

from models.record import ApplicationRecord, JDRecord
from scoring.profile import Profile

# --- Weights and penalties (provisional — calibrated against negatives, §6) ---

ROLE_WEIGHT = 2.0    # primary discriminator   (sub-score 0/2  → 0..4)
DOMAIN_WEIGHT = 2.0  # primary discriminator   (sub-score 0..2 → 0..4)
DEPTH_WEIGHT = 1.0   # secondary discriminator (sub-score 0..2 → 0..2)
#                                                       signal max = 10

SENIORITY_MISS_PENALTY = 3.0   # seniority not in target band
LOCATION_UNCLEAR_PENALTY = 1.0  # hybrid/unspecified policy, city unknown
LOCATION_FAIL_PENALTY = 3.0    # cannot work there (non-base onsite, relocation:false)

# Capability-blocker rule (Stage 2 overrides a misleadingly high Stage 1).
# A hands-on role that mandates a cluster of specialist technologies the candidate
# cannot execute on is not feasible, however well the enums line up (the Databricks
# calibration case: SA + AI Platform structural match, but required Spark/SQL/
# Databricks/multi-cloud hands-on depth). Threshold calibrated against the manual
# corpus — Databricks has 6 unmet required techs vs JP Morgan 2 / Mistral 1; >=3
# isolates the genuine blocker. PROVISIONAL — re-tune as negative JDs are added.
UNMET_REQUIRED_THRESHOLD = 3

# A negative_signal matched as a core requirement caps fit_score here (B). A role
# whose *nature* is something the candidate is steering away from can't be a strong
# fit however the enums line up (e.g. a pure quota-carrying sales role).
NEGATIVE_SIGNAL_CEILING = 5

# company_stage values treated as early-stage for the priority urgency nudge.
# (PHASE2_PLAN wrote "startup", but that is a company_size_signal value — the
# COMPANY_STAGE equivalent is "seed".)
EARLY_STAGE = frozenset({"seed", "series_a", "series_b"})

# Location verbatim values that carry no usable city signal.
_UNCLEAR_LOCATION = frozenset({"", "not_stated", "unknown"})

# Filler tokens allowed in an *onsite* location alongside the base city. Anything
# else left over (another city/region name) means the stated location is not a
# clean base-city onsite, so the gate fails regardless of a base-city substring
# (E2 — the Appian case: title "London", body "McLean, Virginia, 4-5 days/week").
_ONSITE_LOCATION_FILLER = frozenset(
    {
        "england", "scotland", "wales", "uk", "u", "k", "united", "kingdom", "gb",
        "great", "britain", "greater", "central", "city", "centre", "center", "area",
        "metro", "region", "district", "hq", "headquarters", "office", "offices",
        "based", "location", "site", "onsite", "on", "hybrid", "remote", "days",
        "day", "week", "per", "the", "at", "our", "in", "and", "or",
    }
)


def _round_half_up(value: float) -> int:
    """Round halves up (6.5 → 7), unlike Python's round() banker's rounding."""
    return math.floor(value + 0.5)


# --- Stage 1: structural fit (signal − gate penalties) ---------------------


@dataclass
class Breakdown:
    """Per-record scoring detail, kept for fit_label_reason and review."""

    # Signal sub-scores (0–2 before weighting).
    role: float
    domain: float
    technical_depth: float
    # Gate outcomes + the penalty each contributed.
    seniority_gate: str   # "pass" | "miss"
    location_gate: str    # "pass" | "unclear" | "fail"
    seniority_penalty: float
    location_penalty: float

    @property
    def signal(self) -> float:
        return (
            self.role * ROLE_WEIGHT
            + self.domain * DOMAIN_WEIGHT
            + self.technical_depth * DEPTH_WEIGHT
        )

    @property
    def fit_raw(self) -> float:
        return self.signal - self.seniority_penalty - self.location_penalty


def _conditional_qualifies(jd: JDRecord, cond) -> bool:
    """A conditional_primary role (e.g. Product) behaves as primary when the JD is
    in a relevant domain, or pairs a strong signal with a weak signal."""
    if set(jd.domain) & cond.domains:
        return True
    text = " ".join([jd.raw_text, *jd.required_competencies, *jd.required_technologies]).lower()
    strong = any(sig.lower() in text for sig in cond.strong_signals)
    weak = any(sig.lower() in text for sig in cond.weak_signals)
    return strong and weak


def _role_score(jd: JDRecord, profile: Profile) -> float:
    """Three-tier role match (deviates from SPEC §6.5's flat lookup):
    primary 2.0 → conditional_primary (2.0 if it qualifies, else 1.0) → secondary
    1.0 → no match 0.0."""
    jd_roles = set(jd.role_type)
    if jd_roles & profile.target_roles:  # primary
        return 2.0
    for role_name, cond in profile.conditional_primary.items():
        if role_name in jd_roles:
            return 2.0 if _conditional_qualifies(jd, cond) else 1.0
    if jd_roles & profile.secondary_roles:
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


def _depth_score(jd: JDRecord, profile: Profile) -> float:
    if jd.technical_depth in profile.target_technical_depth:
        return 2.0
    if jd.technical_depth in profile.acceptable_technical_depth:
        return 0.5  # acceptable, but a clear step below target (Option B)
    return 0.0


def _seniority_gate(jd: JDRecord, profile: Profile) -> tuple[str, float]:
    """Binary gate — in the target band or not (no within-one-rank credit)."""
    if jd.seniority in profile.target_seniority:
        return "pass", 0.0
    return "miss", SENIORITY_MISS_PENALTY


def _onsite_is_clean_base(loc: str, base: str) -> bool:
    """True if an onsite location is the base city with only filler around it.

    A base-city substring is not enough: "London (…McLean, Virginia…)" names a
    different real work city, so removing the base leaves non-filler tokens → not
    clean → the onsite gate fails (E2)."""
    if not base or base not in loc:
        return False
    residual = re.findall(r"[a-z]+", loc.replace(base, " "))
    return all(tok in _ONSITE_LOCATION_FILLER for tok in residual)


def _location_gate(jd: JDRecord, profile: Profile) -> tuple[str, float]:
    """Gate with one graded 'unclear' tier. Base-city onsite/hybrid passes — the
    candidate already lives there; relocation:false is encoded by NOT excusing a
    named non-base city. Onsite is strict (E2): it must be a clean base city, so a
    deceptive base-city substring can't rescue a different stated work location."""
    loc = jd.location.strip().lower()
    base = profile.location_base.strip().lower()
    if jd.remote_policy == "remote":
        return "pass", 0.0
    if jd.remote_policy == "onsite":
        if _onsite_is_clean_base(loc, base):
            return "pass", 0.0
        return "fail", LOCATION_FAIL_PENALTY  # non-base (or ambiguous) onsite
    # hybrid or not_stated:
    if base and base in loc:  # base city, hybrid/unspecified policy
        return "pass", 0.0
    if loc in _UNCLEAR_LOCATION:
        return "unclear", LOCATION_UNCLEAR_PENALTY
    return "fail", LOCATION_FAIL_PENALTY  # a named non-base city, no remote option


def stage1_fit(jd: JDRecord, profile: Profile) -> tuple[int, Breakdown]:
    """Return ``(fit_score 1–10, Breakdown)``."""
    seniority_gate, seniority_penalty = _seniority_gate(jd, profile)
    location_gate, location_penalty = _location_gate(jd, profile)
    bd = Breakdown(
        role=_role_score(jd, profile),
        domain=_domain_score(jd, profile),
        technical_depth=_depth_score(jd, profile),
        seniority_gate=seniority_gate,
        location_gate=location_gate,
        seniority_penalty=seniority_penalty,
        location_penalty=location_penalty,
    )
    fit = max(1, min(10, _round_half_up(bd.fit_raw)))
    return fit, bd


# --- Stage 2: blocking constraints + requirement gaps ----------------------

# Generic, scorer-owned hard stops (NOT in the profile). Kept conservative to
# avoid false positives. Each entry: (constraint, regex over the JD haystack).
# The language rule is handled separately (_language_blocker) because it needs a
# "plus / advantage" exclusion the others don't.
_BLOCKING_RULES = [
    (
        "active security clearance required",
        re.compile(r"security clearance|(?:active|valid|current)\s+clearance"
                   r"|clearance\s+(?:is\s+)?required|\b(?:ts/sci|dv cleared|sc cleared)\b"),
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

# A — native/fluent non-English language. Conservative on two axes: the qualifier
# must be adjacent to a named language (so "French market" is ignored), AND the
# requirement must not be framed as optional ("…is a plus/advantage/desirable"),
# which is what wrongly blocked the Grey Matter AdTech anchor.
_LANGUAGE_RE = re.compile(
    r"\b(?:native|fluent|mother[- ]tongue|bilingual)\b[^.]{0,40}?\b"
    r"(?:german|french|spanish|italian|dutch|portuguese|mandarin|"
    r"cantonese|japanese|korean|arabic|hebrew|russian|polish|swedish)\b"
)
_OPTIONAL_FRAMING_RE = re.compile(
    r"\b(?:a |an )?(?:plus|advantage|advantageous|desirable|desired|bonus|"
    r"preferred|preferable|asset|beneficial|welcome|nice[- ]to[- ]have|"
    r"would be (?:a |an )?(?:plus|asset|advantage))\b"
)

# C — M&A / post-merger integration. Promoted from a soft requirement_gap to a
# blocker when it is a CORE requirement (job title or a required competency, not
# nice-to-have) — the Director, M&A Integrations calibration case.
_MA_RE = re.compile(
    r"\bm&a\b|mergers?\s+(?:and|&)\s+acquisitions?|post[- ]merger|merger integration"
)

# B — negative_signals. The profile names role NATURES to steer away from; these
# regexes detect each in a JD's core content. Keyed by the EXACT profile phrase
# (reword in the profile → trigger stops firing). A hit caps fit at
# NEGATIVE_SIGNAL_CEILING. Only phrases with a trigger here can fire.
_NEGATIVE_SIGNAL_TRIGGERS = {
    "pure quota-carrying sales role": re.compile(
        r"quota[- ]?(?:carrying|crushing)|own(?:ing)?\s+(?:individual\s+)?quotas?"
        r"|individual\s+quotas?|carry(?:ing)?\s+a\s+quota"
    ),
    "narrow implementation consultant role": re.compile(r"implementation consultant"),
    "role centred primarily on CRM administration": re.compile(
        r"crm administ|salesforce administ"
    ),
}

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


def _is_proficient(tech: str, proficient: frozenset[str]) -> bool:
    """A required technology is 'met' if it overlaps a candidate proficient skill
    by substring (either direction), lowercased. Deliberately simple and
    reproducible; revisit if it mis-matches as the corpus grows."""
    t = tech.strip().lower()
    if not t:
        return True  # empty/garbage requirement is not a gap
    return any(t in skill or skill in t for skill in proficient)


def unmet_required_technologies(jd: JDRecord, profile: Profile) -> list[str]:
    """Required technologies the candidate has no proficient skill for."""
    return [t for t in jd.required_technologies if not _is_proficient(t, profile.proficient_technologies)]


def capability_blocker(jd: JDRecord, profile: Profile) -> str | None:
    """A hands-on specialist requirement the candidate fundamentally lacks.

    Fires only when the candidate is not a hands-on specialist (target depth
    excludes ``hands_on``), the JD demands ``hands_on`` execution, and >= the
    threshold of required technologies are unmet. Returns a human-readable
    blocking string, or None.
    """
    if "hands_on" in profile.target_technical_depth:
        return None  # a hands-on candidate is not blocked by a specialist stack
    if jd.technical_depth != "hands_on":
        return None  # leadership/hybrid roles: the candidate leads, not executes
    unmet = unmet_required_technologies(jd, profile)
    if len(unmet) < UNMET_REQUIRED_THRESHOLD:
        return None
    shown = ", ".join(unmet[:3])
    extra = f", +{len(unmet) - 3} more" if len(unmet) > 3 else ""
    return f"hands-on specialist requirements exceed profile ({shown}{extra})"


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


def _job_title(jd: JDRecord) -> str:
    """The JD's title — first non-empty line of raw_text — lowercased."""
    for line in jd.raw_text.splitlines():
        if line.strip():
            return line.strip().lower()
    return ""


def _core_text(jd: JDRecord) -> str:
    """Title + required (not nice-to-have) content — for 'core requirement' tests."""
    return " ".join([_job_title(jd), *jd.required_competencies, *jd.required_technologies]).lower()


def _language_blocker(text: str) -> bool:
    """True if a native/fluent non-English language is required (A). A match framed
    as optional ('…is a plus/advantage/desirable') within ~50 chars does not count."""
    for m in _LANGUAGE_RE.finditer(text):
        window = text[m.start():m.end() + 50]
        if not _OPTIONAL_FRAMING_RE.search(window):
            return True
    return False


def ma_blocker(jd: JDRecord) -> str | None:
    """C — M&A / post-merger integration required as a core requirement (job title
    or a required competency, not nice-to-have)."""
    if _MA_RE.search(_job_title(jd)) or any(_MA_RE.search(c.lower()) for c in jd.required_competencies):
        return "M&A / post-merger integration experience required"
    return None


def negative_signal_hits(jd: JDRecord, profile: Profile) -> list[str]:
    """B — profile negative_signals detected as a core requirement of the JD."""
    core = _core_text(jd) + " " + jd.raw_text.lower()
    return [
        sig
        for sig in profile.negative_signals
        if sig in _NEGATIVE_SIGNAL_TRIGGERS and _NEGATIVE_SIGNAL_TRIGGERS[sig].search(core)
    ]


# M&A gaps that are subsumed once M&A is promoted to a blocker (no double-count).
_MA_GAPS = ("M&A transaction experience", "post-merger integration leadership")


def stage2_constraints(jd: JDRecord, profile: Profile) -> tuple[list[str], list[str]]:
    """Return ``(requirement_gaps, blocking_constraints)``.

    blocking_constraints = generic scorer-owned hard stops (clearance, language,
    sponsorship) + the hands-on capability blocker + the M&A core-requirement
    blocker. These are how Stage 2 overrides a misleadingly high Stage 1.
    """
    text = _haystack(jd)

    blocking = [label for label, pattern in _BLOCKING_RULES if pattern.search(text)]
    if _language_blocker(text):
        blocking.append("native/fluent non-English language required")
    cap = capability_blocker(jd, profile)
    if cap:
        blocking.append(cap)
    ma = ma_blocker(jd)
    if ma:
        blocking.append(ma)

    gaps = [
        phrase
        for phrase in profile.requirement_gap_watchlist
        if phrase in _GAP_TRIGGERS and _GAP_TRIGGERS[phrase].search(text)
    ]
    # No double-count: drop gaps already surfaced as blockers, and the soft M&A
    # gaps once M&A has been promoted to a blocker.
    gaps = [g for g in gaps if g not in blocking]
    if ma:
        gaps = [g for g in gaps if g not in _MA_GAPS]
    return gaps, blocking


# --- Stage 3: classification + priority ------------------------------------


def stage3_label(fit_score: int, blocking: list[str]) -> str:
    """Map fit_score + blocker presence to a FIT_LABEL (job_radar_SPEC §6.2).

    Thresholds are PROVISIONAL pending calibration against negative JDs (§6).
    """
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

_ROLE_PHRASE = {2.0: "strong role match", 1.0: "secondary role match", 0.0: "role mismatch"}
_DOMAIN_PHRASE = {2.0: "strong domain", 1.0: "adjacent domain", 0.5: "peripheral domain", 0.0: "domain gap"}
_DEPTH_PHRASE = {2.0: "ideal technical depth", 0.5: "acceptable technical depth", 0.0: "technical-depth mismatch"}
_GATE_NOTE = {
    ("seniority", "miss"): "seniority off-target",
    ("location", "unclear"): "location unclear",
    ("location", "fail"): "location blocker",
}


def fit_label_reason(label: str, bd: Breakdown, gaps: list[str], blocking: list[str]) -> str:
    """One templated sentence: the three signal dimensions, then any failed gate,
    then the top blocker/gap."""
    summary = ", ".join(
        [
            _ROLE_PHRASE[bd.role],
            _DOMAIN_PHRASE[bd.domain],
            _DEPTH_PHRASE[bd.technical_depth],
        ]
    )
    gate_notes = [
        note
        for key, note in _GATE_NOTE.items()
        if (key[0] == "seniority" and bd.seniority_gate == key[1])
        or (key[0] == "location" and bd.location_gate == key[1])
    ]
    if gate_notes:
        summary += " (" + "; ".join(gate_notes) + ")"

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

    fit, bd = stage1_fit(jd, profile)

    # B — a negative_signal matched as a core requirement caps the fit_score:
    # the role's nature is something the candidate is steering away from.
    neg = negative_signal_hits(jd, profile)
    if neg:
        fit = min(fit, NEGATIVE_SIGNAL_CEILING)

    gaps, blocking = stage2_constraints(jd, profile)
    label = stage3_label(fit, blocking)
    priority = priority_score(fit, jd, blocking, active_mode)

    reason = fit_label_reason(label, bd, gaps, blocking)
    if neg:
        reason += f" Capped by negative signal: {neg[0]}."

    return ApplicationRecord(
        job_id=jd.id,
        profile_version=profile.profile_version,
        scored_at=scored_at,
        fit_score=fit,
        fit_label=label,
        fit_label_reason=reason,
        requirement_gaps=gaps,
        blocking_constraints=blocking,
        priority_score=priority,
        application_status="new",
        notes="",
    )
