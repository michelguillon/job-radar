"""scoring/profile.py — load + validate candidate_profile.yaml.

The profile is a MANAGED, VERSIONED asset (job_radar_SPEC §6.4). Its enum-bound
fields must use exact values from the schema enums in ``models/record.py`` —
this loader validates that up front so the scorer never silently drifts from a
profile that names a role/domain/seniority the schema doesn't know.

The finalised profile is structurally richer than the spec §6.4 example
(``docs/job_radar_PHASE2_PLAN.md`` — the artifact wins on tie-break). This loader
reads THAT structure and exposes only what the scorer consumes as a flat
``Profile`` object:

  enum-bound (Stage-1 structural matching):
    target_roles (primary), conditional_primary (domains enum-bound; signal
    lists free-text), secondary_roles, target_seniority, target_technical_depth,
    acceptable_technical_depth, acceptable_remote_policy,
    domains_strong / domains_adjacent / domains_lower, search_mode
  free-text (Stage-2 gaps/signals — fuzzy, NOT enum-bound):
    requirement_gap_watchlist, positive_signals, negative_signals
  scalar:
    profile_version, location_base, relocation

``target_delivery_motion`` is validated against the enum but is narrative only —
not a Stage-1 dimension (PHASE2_PLAN).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import yaml

from models.record import (
    DELIVERY_MOTION,
    DOMAIN,
    REMOTE_POLICY,
    ROLE_TYPE,
    SENIORITY,
    TECHNICAL_DEPTH,
)

DEFAULT_PROFILE_PATH = "candidate_profile.yaml"

# search_mode is profile-level vocabulary (job_radar_SPEC §6.3), not a schema enum.
SEARCH_MODES = frozenset({"selective", "active", "broad"})


class ProfileError(ValueError):
    """Raised when candidate_profile.yaml is structurally invalid or off-enum."""


@dataclass
class ConditionalRole:
    """A role that is a *primary* target only in the right context (e.g. Product).

    Qualifies as primary when the JD is in one of ``domains``, OR pairs a
    ``strong_signals`` hit with a ``weak_signals`` hit; otherwise it falls back to
    secondary. ``domains`` is enum-bound (DOMAIN); the signal lists are free-text.
    """

    domains: frozenset[str]
    strong_signals: list[str] = field(default_factory=list)
    weak_signals: list[str] = field(default_factory=list)


@dataclass
class Profile:
    """The candidate definition the scorer matches every JDRecord against."""

    profile_version: str
    search_mode: str

    target_roles: frozenset[str]            # primary roles (universally on-target)
    target_seniority: frozenset[str]
    target_delivery_motion: frozenset[str]
    target_technical_depth: frozenset[str]
    acceptable_technical_depth: frozenset[str]

    location_base: str
    acceptable_remote_policy: frozenset[str]
    relocation: bool

    domains_strong: frozenset[str]
    domains_adjacent: frozenset[str]
    domains_lower: frozenset[str]

    # Technologies the candidate can execute on (skills.technologies strong +
    # developing, lowercased). "familiar" is deliberately excluded — it does not
    # clear a hands-on specialist bar. Used by the scorer's capability-blocker rule.
    proficient_technologies: frozenset[str] = field(default_factory=frozenset)

    # Three-tier role targeting (see ConditionalRole). primary lives in
    # target_roles above; these two complete it. Optional — a profile may omit them.
    conditional_primary: dict[str, ConditionalRole] = field(default_factory=dict)
    secondary_roles: frozenset[str] = field(default_factory=frozenset)

    requirement_gap_watchlist: list[str] = field(default_factory=list)
    positive_signals: list[str] = field(default_factory=list)
    negative_signals: list[str] = field(default_factory=list)


# --- Enum validation -------------------------------------------------------

# (yaml path, enum) for every enum-bound list field, relative to ``candidate``.
_ENUM_LIST_FIELDS = (
    ("target_roles.primary", ROLE_TYPE),
    ("target_seniority", SENIORITY),
    ("target_delivery_motion", DELIVERY_MOTION),
    ("target_technical_depth", TECHNICAL_DEPTH),
    ("acceptable_technical_depth", TECHNICAL_DEPTH),
    ("location.acceptable_remote_policy", REMOTE_POLICY),
    ("domains.strong", DOMAIN),
    ("domains.adjacent", DOMAIN),
    ("domains.lower_priority", DOMAIN),
)


def _dig(data: dict, dotted: str):
    """Walk a dotted path; return None if any segment is missing."""
    node = data
    for key in dotted.split("."):
        if not isinstance(node, dict) or key not in node:
            return None
        node = node[key]
    return node


def validate_profile(data: dict) -> list[str]:
    """Return a list of error strings; empty list means the profile is valid."""
    errors: list[str] = []

    for top in ("profile_version", "last_updated"):
        if not isinstance(data.get(top), str) or not data[top]:
            errors.append(f"{top}: required top-level string")

    candidate = data.get("candidate")
    if not isinstance(candidate, dict):
        errors.append("candidate: required mapping")
        return errors  # nothing else is checkable without it

    mode = candidate.get("search_mode")
    if mode not in SEARCH_MODES:
        errors.append(f"candidate.search_mode: {mode!r} not in {sorted(SEARCH_MODES)}")

    for dotted, allowed in _ENUM_LIST_FIELDS:
        value = _dig(candidate, dotted)
        if value is None:
            errors.append(f"candidate.{dotted}: required list")
            continue
        if not isinstance(value, list):
            errors.append(f"candidate.{dotted}: must be a list")
            continue
        bad = [v for v in value if v not in allowed]
        if bad:
            errors.append(f"candidate.{dotted}: {bad!r} not in allowed values")

    _validate_role_tiers(candidate, errors)
    return errors


def _validate_role_tiers(candidate: dict, errors: list[str]) -> None:
    """Validate the optional secondary + conditional_primary role tiers."""
    secondary = _dig(candidate, "target_roles.secondary")
    if secondary is not None:
        if not isinstance(secondary, list):
            errors.append("candidate.target_roles.secondary: must be a list")
        else:
            bad = [v for v in secondary if v not in ROLE_TYPE]
            if bad:
                errors.append(f"candidate.target_roles.secondary: {bad!r} not in allowed values")

    cond = _dig(candidate, "target_roles.conditional_primary")
    if cond is None:
        return
    if not isinstance(cond, dict):
        errors.append("candidate.target_roles.conditional_primary: must be a mapping")
        return
    for role_name, spec in cond.items():
        if role_name not in ROLE_TYPE:
            errors.append(f"candidate.target_roles.conditional_primary: {role_name!r} not in allowed values")
        domains = spec.get("domains") if isinstance(spec, dict) else None
        if domains is None:
            errors.append(f"candidate.target_roles.conditional_primary.{role_name}.domains: required list")
            continue
        if not isinstance(domains, list):
            errors.append(f"candidate.target_roles.conditional_primary.{role_name}.domains: must be a list")
            continue
        bad = [d for d in domains if d not in DOMAIN]
        if bad:
            errors.append(f"candidate.target_roles.conditional_primary.{role_name}.domains: {bad!r} not in allowed values")


# --- Loading ---------------------------------------------------------------


def _frozen(candidate: dict, dotted: str) -> frozenset[str]:
    value = _dig(candidate, dotted)
    return frozenset(value) if isinstance(value, list) else frozenset()


def _list(candidate: dict, key: str) -> list[str]:
    value = candidate.get(key)
    return list(value) if isinstance(value, list) else []


def _conditional_roles(candidate: dict) -> dict[str, ConditionalRole]:
    raw = _dig(candidate, "target_roles.conditional_primary")
    if not isinstance(raw, dict):
        return {}
    out: dict[str, ConditionalRole] = {}
    for role_name, spec in raw.items():
        spec = spec or {}
        out[role_name] = ConditionalRole(
            domains=frozenset(spec.get("domains") or []),
            strong_signals=list(spec.get("strong_signals") or []),
            weak_signals=list(spec.get("weak_signals") or []),
        )
    return out


def from_dict(data: dict) -> Profile:
    """Build a validated ``Profile`` from a parsed YAML mapping.

    Raises ``ProfileError`` (with every problem listed) if validation fails.
    """
    errors = validate_profile(data)
    if errors:
        raise ProfileError("invalid candidate profile:\n  - " + "\n  - ".join(errors))

    c = data["candidate"]
    loc = c.get("location", {})
    techs = (c.get("skills") or {}).get("technologies") or {}
    proficient = [
        t.lower()
        for tier in ("strong", "developing")
        for t in (techs.get(tier) or [])
        if isinstance(t, str)
    ]
    return Profile(
        profile_version=data["profile_version"],
        search_mode=c["search_mode"],
        target_roles=_frozen(c, "target_roles.primary"),
        target_seniority=_frozen(c, "target_seniority"),
        target_delivery_motion=_frozen(c, "target_delivery_motion"),
        target_technical_depth=_frozen(c, "target_technical_depth"),
        acceptable_technical_depth=_frozen(c, "acceptable_technical_depth"),
        location_base=loc.get("base", "") if isinstance(loc, dict) else "",
        acceptable_remote_policy=_frozen(c, "location.acceptable_remote_policy"),
        relocation=bool(loc.get("relocation", False)) if isinstance(loc, dict) else False,
        domains_strong=_frozen(c, "domains.strong"),
        domains_adjacent=_frozen(c, "domains.adjacent"),
        domains_lower=_frozen(c, "domains.lower_priority"),
        proficient_technologies=frozenset(proficient),
        conditional_primary=_conditional_roles(c),
        secondary_roles=_frozen(c, "target_roles.secondary"),
        requirement_gap_watchlist=_list(c, "requirement_gap_watchlist"),
        positive_signals=_list(c, "positive_signals"),
        negative_signals=_list(c, "negative_signals"),
    )


def load_profile(path: str = DEFAULT_PROFILE_PATH) -> Profile:
    """Load, validate, and return the candidate profile from a YAML file."""
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        raise ProfileError(f"{path}: top-level YAML must be a mapping")
    return from_dict(data)
