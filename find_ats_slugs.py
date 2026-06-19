#!/usr/bin/env python3
"""
find_ats_slugs.py — probe unknown ATS companies in company_seeds_v3.yaml

For each company with ats: unknown, tries Greenhouse, Ashby, and Lever
to find which ATS they use and what their slug is.

Usage (run from job-radar repo root inside Docker):
  docker compose run --rm job-radar python find_ats_slugs.py

Or locally if httpx is available:
  pip install httpx pyyaml && python find_ats_slugs.py

Output:
  - Prints results to stdout
  - Writes find_ats_slugs_results.yaml with suggested updates
"""

import time
import re
import httpx
import yaml
from pathlib import Path

SEEDS_FILE = Path("company_seeds.yaml")
OUTPUT_FILE = Path("find_ats_slugs_results.yaml")
DELAY = 0.4  # seconds between requests

# ── Slug candidates ────────────────────────────────────────────────────────────

def slug_candidates(name: str) -> list:
    base = name.lower()
    base = re.sub(r"['\u2019]", "", base)
    base = re.sub(r"[^a-z0-9 ]", " ", base)
    base = base.strip()
    words = base.split()

    candidates = []
    candidates.append("".join(words))
    candidates.append("-".join(words))
    if len(words) > 1:
        candidates.append("".join(words[:2]))
    candidates.append(words[0])
    if len(words) > 1:
        candidates.append("".join(w[0] for w in words))

    for suffix in (" ai", " labs", " technologies", " systems",
                   " platform", " analytics", " solutions", " inc",
                   " ltd", " bank", " x"):
        if base.endswith(suffix):
            trimmed = base[:-len(suffix)].strip().replace(" ", "")
            if trimmed:
                candidates.append(trimmed)

    return list(dict.fromkeys(c for c in candidates if c))


# ── ATS probes ─────────────────────────────────────────────────────────────────

def probe_greenhouse(slug: str, client: httpx.Client) -> bool:
    try:
        r = client.get(
            f"https://api.greenhouse.io/v1/boards/{slug}/jobs",
            timeout=8)
        return r.status_code == 200
    except Exception:
        return False


def probe_ashby(slug: str, client: httpx.Client) -> bool:
    try:
        r = client.post(
            f"https://api.ashbyhq.com/posting-api/job-board/{slug}",
            json={"includeCompensation": False},
            timeout=8)
        return r.status_code == 200
    except Exception:
        return False


def probe_lever(slug: str, client: httpx.Client) -> bool:
    try:
        r = client.get(
            f"https://api.lever.co/v0/postings/{slug}?mode=json&limit=1",
            timeout=8)
        if r.status_code != 200:
            return False
        data = r.json()
        return isinstance(data, list)
    except Exception:
        return False


PROBES = [
    ("greenhouse", probe_greenhouse),
    ("ashby",      probe_ashby),
    ("lever",      probe_lever),
]


# ── Main ───────────────────────────────────────────────────────────────────────

def find_ats(name: str, client: httpx.Client):
    for ats_name, probe_fn in PROBES:
        for slug in slug_candidates(name):
            if probe_fn(slug, client):
                return ats_name, slug
            time.sleep(DELAY)
    return None


def main():
    seeds = yaml.safe_load(SEEDS_FILE.read_text())
    unknowns = [s for s in seeds if s.get("ats") == "unknown"]
    print(f"Probing {len(unknowns)} unknown ATS companies...\n")

    found = []
    not_found = []

    with httpx.Client(
        headers={"User-Agent": "job-radar-ats-probe/1.0"},
        follow_redirects=True,
    ) as client:
        for company in unknowns:
            name = company["name"]
            print(f"  {name:<40}", end="", flush=True)
            result = find_ats(name, client)
            if result:
                ats, slug = result
                print(f"FOUND  {ats:<12} slug={slug}")
                found.append({"name": name, "ats": ats, "slug": slug})
            else:
                print("not found — investigate_ats")
                not_found.append({"name": name})

    print(f"\n{'─'*60}")
    print(f"Found:     {len(found)}")
    print(f"Not found: {len(not_found)}")

    results = {
        "found": found,
        "not_found": [{"name": c["name"], "action": "investigate_ats"}
                      for c in not_found],
    }
    OUTPUT_FILE.write_text(
        yaml.dump(results, default_flow_style=False, allow_unicode=True))
    print(f"\nResults written to {OUTPUT_FILE}")
    print("Apply found results manually to company_seeds.yaml")


if __name__ == "__main__":
    main()
