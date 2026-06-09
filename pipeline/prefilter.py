"""Pre-label filter — deterministic location + role screen over metadata.

The 2,500+ raw postings are global and mostly off-target (SWE, data-eng,
research, recruiting at large AI/infra companies). Labelling them all via the
Batch API costs ~$40 to extract mostly-irrelevant roles. This module cuts the
set to a few hundred genuinely-relevant postings *before* any labelling spend,
using only the structured metadata sidecar (title + location) — no model calls,
no scoring.

Pure logic only (no IO): ``prefilter.py`` (the CLI) does the loading/writing.
Both screens are intentionally **generous** — it is cheaper to label a few extra
than to miss a fit, and the scorer's gates handle nuance later.

Screens (a posting is kept only if it passes *both*):

- **Location** — keep UK / London / UK-remote / Europe-remote / EMEA-remote /
  multi-location including the UK; keep bare "Remote" / not-stated (ambiguous);
  drop clear non-UK onsite and remote roles tied to a non-European country.
- **Role** — keep titles in the target families (solutions / pre-sales /
  customer engineering / product / GTM / partner); drop pure sales titles
  (Account Executive, Account Manager, SDR/BDR, …) and everything off-target.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# --- Location vocabulary -----------------------------------------------------

UK_COUNTRIES = {"GB", "UK", "GBR", "UNITED KINGDOM"}

# European countries (2-letter + common full names) — a *remote* role tied to
# one of these is kept. The set only ever upgrades a keep; an omission falls
# through to the generous "remote_ambiguous" keep, never to a drop.
EUROPE_COUNTRIES = {
    "AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE", "GR",
    "HU", "IE", "IT", "LV", "LT", "LU", "MT", "NL", "PL", "PT", "RO", "SK",
    "SI", "ES", "SE", "NO", "IS", "LI", "CH",
    "FRANCE", "GERMANY", "IRELAND", "NETHERLANDS", "SPAIN", "ITALY", "PORTUGAL",
    "BELGIUM", "SWEDEN", "DENMARK", "FINLAND", "NORWAY", "POLAND", "AUSTRIA",
    "SWITZERLAND", "GREECE", "CZECHIA", "CZECH REPUBLIC", "ROMANIA", "HUNGARY",
    "LUXEMBOURG", "EUROPE",
}

# A *remote* role tied to one of these countries is dropped (non-European).
NON_EUROPE_COUNTRIES = {
    "US", "USA", "UNITED STATES", "CA", "CAN", "CANADA", "JP", "JPN", "JAPAN",
    "IN", "IND", "INDIA", "SG", "SGP", "SINGAPORE", "AU", "AUS", "AUSTRALIA",
    "NZ", "NEW ZEALAND", "BR", "BRA", "BRAZIL", "MX", "MEX", "MEXICO", "AE",
    "UNITED ARAB EMIRATES", "CN", "CHN", "CHINA", "HK", "HONG KONG", "KR",
    "KOR", "SOUTH KOREA", "IL", "ISRAEL", "ZA",
}

_UK_LOC = re.compile(
    r"\b(?:u\.?k\.?|united kingdom|england|scotland|wales|northern ireland|"
    r"london|manchester|edinburgh|cambridge|oxford|bristol|leeds|birmingham|"
    r"glasgow|reading|cardiff|belfast)\b"
)
_EUROPE_LOC = re.compile(r"\b(?:europe|european|emea|eu)\b")
# US state names — a "Remote - California" posting has no country field (common
# on Greenhouse), so the state name is the only signal that a "remote" role is
# US-bound and not workable from London.
_US_STATES = (
    r"alabama|alaska|arizona|arkansas|california|colorado|connecticut|delaware|"
    r"florida|georgia|hawaii|idaho|illinois|indiana|iowa|kansas|kentucky|"
    r"louisiana|maine|maryland|massachusetts|michigan|minnesota|mississippi|"
    r"missouri|montana|nebraska|nevada|new hampshire|new jersey|new mexico|"
    r"north carolina|north dakota|ohio|oklahoma|oregon|pennsylvania|"
    r"rhode island|south carolina|south dakota|tennessee|texas|utah|vermont|"
    r"virginia|washington|west virginia|wisconsin|wyoming|d\.c\."
)
_NON_UK_REMOTE = re.compile(
    r"\b(?:us|u\.s\.?|usa|united states|americas|north america|latam|apac|asia|"
    r"india|canada|singapore|tokyo|japan|sydney|australia|anz|bangalore|dubai|"
    r"uae|new york|san francisco|sf bay|" + _US_STATES + r")\b"
)

# --- Role vocabulary ---------------------------------------------------------
# STRONG_KEEP is checked before SALES_DROP so "Technical Account Manager" (a
# target customer role) is kept even though "account manager" is a sales drop.

_STRONG_KEEP = re.compile(
    # ``architect(?:ure)?`` / ``engineer(?:ing)?`` so "Solutions Architecture"
    # and "Field Engineering" match (the bare form misses the -ure/-ing suffix).
    # ``(?:applied )?ai architect(?:ure)?`` keeps Anthropic's Applied AI
    # Architect family (AI Delivery / Solutions Architecture — profile primary).
    r"\b(?:solutions? (?:engineer|architect(?:ure)?|consultant|consulting)|"
    r"sales engineer|pre[- ]?sales|presales|technical account manager|"
    r"customer engineer|forward[- ]deployed|field engineer(?:ing)?|value engineer|"
    r"(?:applied )?ai architect(?:ure)?|deployment strategist|"
    r"implementation (?:architect|consultant|engineer|specialist)|"
    r"solutions? lead|ai delivery|partner (?:solutions?|architect|engineer)|"
    r"delivery (?:lead|manager|architect))\b"
)
_SALES_DROP = re.compile(
    r"\b(?:account executive|account manager|sales representative|sales rep|"
    r"sales development|business development|sdr|bdr|inside sales|"
    r"channel sales|sales manager|enterprise sales|territory)\b"
)
# Recruiting / HR — explicitly off-target, dropped before the product/GTM keeps
# so a skills-list title like "Talent Acquisition (…GTM/Product…)" can't sneak in.
_RECRUITING_DROP = re.compile(
    r"\b(?:talent acquisition|recruit(?:er|ing|ment)?|sourcer|"
    r"people partner|hr business partner)\b"
)
_PRODUCT_KEEP = re.compile(
    r"\b(?:product manager|product management|product lead|product owner|"
    r"head of product|director,? product|product director|principal product|"
    r"group product|vp,? product|chief product|senior product|staff product|"
    r"product strategy)\b"
)
_CUSTOMER_KEEP = re.compile(
    r"\b(?:customer success|customer experience|professional services|"
    r"customer solutions|adoption)\b"
)
_GTM_PARTNER_KEEP = re.compile(
    r"\b(?:go[- ]to[- ]market|gtm|partner manager|partnerships?|alliances?|"
    r"partner (?:enablement|success|programs?|experience)|business value)\b"
)


@dataclass(frozen=True)
class ScreenResult:
    """Outcome of screening one posting's metadata."""

    keep: bool
    role_keep: bool
    role_bucket: str
    loc_keep: bool
    loc_bucket: str
    drop_reason: str  # "" when kept; else "role:<bucket>" / "location:<bucket>"


def screen_location(meta: dict) -> tuple[bool, str]:
    """Return ``(keep, bucket)`` for the location screen."""
    loc = (meta.get("location_str") or "").lower()
    country = (meta.get("country") or "").strip().upper()
    workplace_type = (meta.get("workplace_type") or "not_stated").lower()
    remote = bool(meta.get("is_remote")) or workplace_type == "remote" or "remote" in loc

    # 1. Anything in the UK → keep (covers multi-location including the UK).
    if country in UK_COUNTRIES or _UK_LOC.search(loc):
        return True, "uk"

    # 2. Remote roles.
    if remote:
        if _EUROPE_LOC.search(loc) or country in EUROPE_COUNTRIES:
            return True, "europe_remote"
        if country in NON_EUROPE_COUNTRIES or _NON_UK_REMOTE.search(loc):
            return False, "remote_non_uk"
        return True, "remote_ambiguous"  # bare "Remote" / global — keep for now

    # 3. Onsite/hybrid with a concrete non-UK location → drop.
    if loc or country:
        return False, "non_uk_onsite"

    # 4. Nothing stated → keep (ambiguous).
    return True, "not_stated"


def screen_role(title: str) -> tuple[bool, str]:
    """Return ``(keep, bucket)`` for the role-title screen."""
    t = (title or "").lower()
    if _STRONG_KEEP.search(t):
        return True, "solutions"
    if _SALES_DROP.search(t):
        return False, "sales"
    if _RECRUITING_DROP.search(t):
        return False, "recruiting"
    if _PRODUCT_KEEP.search(t):
        return True, "product"
    if _CUSTOMER_KEEP.search(t):
        return True, "customer"
    if _GTM_PARTNER_KEEP.search(t):
        return True, "gtm_partner"
    return False, "off_target"


# --- Near-duplicate collapse ------------------------------------------------
# Exact-body dedupe (pipeline.dedupe) can't catch the same role posted to many
# locations or language variants — their bodies differ. After screening, collapse
# survivors that share a company and a normalised title, keeping the single
# best-located representative (UK first). Language qualifiers like "(French
# speaking)" are stripped from the key so the Stripe CSM language variants merge;
# specialisation parentheticals ("(Enterprise Accounts)") are NOT stripped, so two
# genuinely distinct Senior Solutions Architect roles stay separate.

_LANG_QUALIFIER = re.compile(r"\s*\([a-z]+(?:[\s/&-][a-z]+)*\s+speaking\)\s*", re.I)
_LOC_RANK = {"uk": 0, "europe_remote": 1, "remote_ambiguous": 2, "not_stated": 3}


def dedupe_key(company: str, title: str) -> tuple[str, str]:
    """Near-dup key: company + title with language qualifiers removed, normalised."""
    t = _LANG_QUALIFIER.sub(" ", title or "")
    t = re.sub(r"\s+", " ", t).strip().lower()
    return ((company or "").strip().lower(), t)


def collapse_near_duplicates(entries: list[dict]) -> tuple[list[dict], int]:
    """Collapse same-role survivors to one best-located representative.

    Each entry is a dict with at least ``company``, ``title`` and ``loc_bucket``.
    Preserves first-seen order of the kept representatives. Returns
    ``(kept_entries, collapsed_count)``.
    """
    best: dict[tuple[str, str], dict] = {}
    order: list[tuple[str, str]] = []
    for e in entries:
        key = dedupe_key(e["company"], e["title"])
        if key not in best:
            best[key] = e
            order.append(key)
        elif _LOC_RANK.get(e["loc_bucket"], 9) < _LOC_RANK.get(best[key]["loc_bucket"], 9):
            best[key] = e
    kept = [best[k] for k in order]
    return kept, len(entries) - len(kept)


def screen(meta: dict) -> ScreenResult:
    """Screen one posting. Kept only if both role and location pass.

    The single ``drop_reason`` attributes to role first, then location (a
    posting failing both is reported as a role drop); the CLI also tabulates the
    independent role-fail and location-fail counts.
    """
    role_keep, role_bucket = screen_role(meta.get("title", ""))
    loc_keep, loc_bucket = screen_location(meta)
    keep = role_keep and loc_keep
    if keep:
        drop_reason = ""
    elif not role_keep:
        drop_reason = f"role:{role_bucket}"
    else:
        drop_reason = f"location:{loc_bucket}"
    return ScreenResult(keep, role_keep, role_bucket, loc_keep, loc_bucket, drop_reason)


# --- GTM / partner observation watchlist (NO scoring impact) -----------------
# These adjacent roles currently score poorly because GTM is not a profile
# target_role. Before any profile/scorer change, gather real evidence: a
# location-workable posting whose title matches a watchlist signal is DIVERTED
# from the labelling/scoring stream (no Batch cost, no ApplicationRecord) and
# logged for a later career-strategy review (job_radar_SPEC §5.10). Observation
# only — this never affects survivors that go to labelling.

_WATCHLIST_CORE = re.compile(
    r"\b(?:gtm|go[- ]to[- ]market|partner enablement|partner programs?|"
    r"partner success|strategic partnerships?|ecosystem|alliances?|"
    r"chief of staff)\b",
    re.I,
)
_CS_CX = re.compile(r"customer (?:success|experience)", re.I)
_LEADERSHIP = re.compile(r"\b(?:director|head|vp|chief|lead|leader|leadership)\b", re.I)


def watchlist_signal(title: str) -> bool:
    """True if a title belongs to the GTM/partner observation watchlist.

    Customer Success/Experience matches only at *leadership* level (Director /
    Head / VP / Lead) — a plain "Customer Success Manager" stays in the scoring
    stream (it is a different, already-tested question).
    """
    t = title or ""
    if _WATCHLIST_CORE.search(t):
        return True
    return bool(_CS_CX.search(t) and _LEADERSHIP.search(t))
