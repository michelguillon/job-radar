"""Text cleaning — strip HTML, strip boilerplate, normalise whitespace/case.

Pipeline order (docs/SPEC_JD_REFINERY.md §3.7, Step 2):

    clean() = strip_html -> strip_boilerplate -> normalise

``normalise`` is the canonical form fed to the deduplication hash, so any change
here changes record ids. The boilerplate list starts with three common
equal-opportunity / accommodation footer patterns and grows from Tier 1/2
observations.
"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup

# Sentence-level boilerplate patterns. Each removes the matching sentence
# (text up to and including the terminating period), case-insensitively.
# Seeded with three common EEO / accommodation footers.
BOILERPLATE_PATTERNS: list[str] = [
    r"(?is)[^.]*\bis an equal opportunity employer\b[^.]*\.",
    r"(?is)[^.]*\bcommitted to (?:building |creating )?a diverse and inclusive\b[^.]*\.",
    r"(?is)[^.]*\breasonable accommodation[s]?\b[^.]*\.",
]

_WHITESPACE_RE = re.compile(r"\s+")


def strip_html(text: str) -> str:
    """Return plain text with HTML tags removed and entities decoded."""
    if not text:
        return ""
    return BeautifulSoup(text, "html.parser").get_text(separator=" ")


def strip_boilerplate(text: str) -> str:
    """Remove known boilerplate footer sentences (EEO statements etc.)."""
    for pattern in BOILERPLATE_PATTERNS:
        text = re.sub(pattern, " ", text)
    return text


def normalise(text: str) -> str:
    """Collapse all whitespace to single spaces, strip ends, lowercase."""
    return _WHITESPACE_RE.sub(" ", text).strip().lower()


def clean(raw_html: str) -> str:
    """Full cleaning pipeline: strip HTML, strip boilerplate, normalise."""
    return normalise(strip_boilerplate(strip_html(raw_html)))


def clean_readable(raw_html: str) -> str:
    """Human-readable clean: strip HTML + boilerplate, keep line breaks and case.

    Unlike ``clean`` (which lowercases and collapses everything to one line for
    the dedup hash), this preserves paragraph structure and original casing — the
    form stored in a labelled record's ``raw_text`` so the labeller reads a normal
    JD and the scorer's first-line heuristics behave. Collapses intra-line runs of
    spaces/tabs and drops blank lines.
    """
    text = strip_boilerplate(strip_html(raw_html))
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in text.splitlines()]
    return "\n".join(ln for ln in lines if ln)
