"""Tests for scripts.build_score_subset.select — the pure selection logic."""

from collectors.base import build_raw_record
from scripts.build_score_subset import select


def _rec(url, company):
    return build_raw_record(
        source_url=url, source_ats="greenhouse", company=company,
        collected_at="2026-06-09", raw_html="<p>body</p>",
    )


def _meta(url, company, title, location="London"):
    return {"source_url": url, "company": company, "title": title, "location_str": location}


def test_keeps_all_non_databricks_and_caps_databricks_buckets():
    records, metas = [], {}

    def add(url, company, title, loc="London"):
        records.append(_rec(url, company))
        metas[url] = _meta(url, company, title, loc)

    # 4 non-Databricks (all kept)
    add("n1", "Stripe", "Solutions Architect")
    add("n2", "Mistral", "Partner Solution Architect")
    add("n3", "Anthropic", "Applied AI Architect")
    add("n4", "Figma", "Solutions Consultant")
    # Databricks across all 5 buckets + extras that must be dropped
    add("d1", "Databricks", "AI Engineer - FDE", "Remote - Germany")
    add("d1uk", "Databricks", "AI Engineer - FDE", "United Kingdom")  # UK-preferred over d1
    add("d2", "Databricks", "Deployment Strategist", "London, United Kingdom")
    add("d3", "Databricks", "Delivery Solutions Architect", "London, United Kingdom")
    add("d4", "Databricks", "Senior Solutions Architect (Energy)", "London, United Kingdom")
    add("d5", "Databricks", "Sr. Alliance Director", "London, United Kingdom")
    add("d6", "Databricks", "Staff Solutions Architect", "London")  # no bucket → dropped

    selected, _ = select(records, metas, databricks_n=5, csm_max=2)
    urls = {r.source_url for r in selected}

    # all non-Databricks kept
    assert {"n1", "n2", "n3", "n4"} <= urls
    # exactly 5 Databricks, one per bucket, UK FDE preferred, extras dropped
    dbx = [r for r in selected if r.company == "Databricks"]
    assert len(dbx) == 5
    assert "d1uk" in urls and "d1" not in urls  # UK-preferred representative
    assert "d6" not in urls  # matched no bucket


def test_caps_customer_success_manager_at_two():
    records, metas = [], {}

    def add(url, company, title, loc="London"):
        records.append(_rec(url, company))
        metas[url] = _meta(url, company, title, loc)

    add("c1", "Stripe", "Customer Success Manager", "London")
    add("c2", "Anthropic", "Customer Success Manager", "London, UK")
    add("c3", "Stripe", "Customer Success Manager", "Remote - US")
    add("keep", "Stripe", "Solutions Architect", "London")

    selected, _ = select(records, metas, csm_max=2)
    csm = [r for r in selected if "customer success manager" in metas[r.source_url]["title"].lower()]
    assert len(csm) == 2
    # the US-located CSM is the one dropped (UK preferred)
    assert "c3" not in {r.source_url for r in selected}
    assert "keep" in {r.source_url for r in selected}
