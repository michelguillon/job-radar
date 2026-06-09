"""Tests for the pre-label filter — pure screens (pipeline.prefilter) and the
prefilter.py CLI run()/IO."""

import prefilter
from collectors.base import build_meta, build_raw_record
from pipeline.prefilter import (
    collapse_near_duplicates,
    screen,
    screen_location,
    screen_role,
    watchlist_signal,
)


def _meta(title="Solutions Engineer", location_str="London, UK", **kw):
    return build_meta(
        source_url=kw.pop("source_url", "https://x/1"),
        source_ats=kw.pop("source_ats", "greenhouse"),
        company=kw.pop("company", "Acme"),
        title=title,
        location_str=location_str,
        **kw,
    )


# --- role screen -------------------------------------------------------------


def test_role_keeps_solutions_families():
    for t in ["Solutions Engineer", "Pre-Sales Architect", "Sales Engineer",
              "Customer Engineer", "Forward Deployed Engineer", "AI Delivery Lead"]:
        keep, _ = screen_role(t)
        assert keep, t


def test_role_drops_pure_sales():
    for t in ["Account Executive", "Enterprise Account Executive", "Account Manager",
              "Sales Development Representative", "SDR", "BDR", "Sales Manager"]:
        keep, bucket = screen_role(t)
        assert not keep and bucket == "sales", t


def test_role_keeps_architecture_and_field_engineering_suffixes():
    # word-boundary suffix bug: these must match despite -ure / -ing
    assert screen_role("Manager of Solutions Architecture")[0]
    assert screen_role("Director, Field Engineering")[0]


def test_role_keeps_applied_ai_architect_family():
    for t in ["Applied AI Architect", "Applied AI Architect, Industries",
              "AI Architect", "Manager of Applied AI Architecture"]:
        assert screen_role(t)[0], t


def test_role_drops_recruiting_even_with_gtm_keyword():
    # "gtm"/"product" appear inside a skills list — still a recruiting role
    keep, bucket = screen_role("Talent Acquisition (Engineering/Product/GTM/Science)")
    assert not keep and bucket == "recruiting"


def test_role_keeps_technical_account_manager_over_sales_drop():
    # "account manager" is a sales drop, but TAM is a target customer role and
    # the strong-keep check runs first.
    keep, bucket = screen_role("Technical Account Manager")
    assert keep and bucket == "solutions"


def test_role_keeps_product_and_customer():
    assert screen_role("Senior Product Manager")[0]
    assert screen_role("Director, Product")[0]
    assert screen_role("Customer Success Manager")[0]


def test_role_keeps_deployment_strategist_and_partner_success():
    for t in ["Deployment Strategist", "AI Deployment Strategist - UK",
              "Head of Partner Success", "Head of Partner Programs"]:
        assert screen_role(t)[0], t


def test_role_drops_off_target():
    for t in ["Software Engineer", "Staff Data Engineer", "ML Research Scientist",
              "Finance Analyst", "Brand Designer"]:
        keep, bucket = screen_role(t)
        assert not keep and bucket == "off_target", t


# --- location screen ---------------------------------------------------------


def test_location_keeps_uk():
    assert screen_location(_meta(location_str="London, UK")) == (True, "uk")
    assert screen_location(_meta(location_str="Manchester")) == (True, "uk")
    assert screen_location(_meta(location_str="Anywhere", country="GB")) == (True, "uk")


def test_location_keeps_multi_including_uk():
    assert screen_location(_meta(location_str="San Francisco | London"))[0]


def test_location_drops_non_uk_onsite():
    assert screen_location(_meta(location_str="San Francisco, CA")) == (False, "non_uk_onsite")
    assert screen_location(_meta(location_str="Paris", country="FR")) == (False, "non_uk_onsite")


def test_location_remote_rules():
    # bare remote → ambiguous keep
    assert screen_location(_meta(location_str="Remote", workplace_type="remote")) == (True, "remote_ambiguous")
    # remote tied to a non-European country → drop
    assert screen_location(_meta(location_str="Remote - US", workplace_type="remote")) == (False, "remote_non_uk")
    assert screen_location(_meta(location_str="Remote", workplace_type="remote", country="US")) == (False, "remote_non_uk")
    # remote in Europe → keep
    assert screen_location(_meta(location_str="Remote - Europe", workplace_type="remote")) == (True, "europe_remote")
    assert screen_location(_meta(location_str="Remote", workplace_type="remote", country="FR")) == (True, "europe_remote")
    # US-state remote (no country field, common on Greenhouse) → drop
    assert screen_location(_meta(location_str="Remote - California; Remote - Oregon")) == (False, "remote_non_uk")
    assert screen_location(_meta(location_str="Remote - Ohio")) == (False, "remote_non_uk")
    # multi-location with London still wins (UK checked first)
    assert screen_location(_meta(location_str="London | Remote - California"))[0]


def test_location_remote_flag_from_is_remote():
    # Ashby Tokyo/Hybrid/isRemote True/Japan → remote + non-European → drop
    m = _meta(location_str="Tokyo", workplace_type="hybrid", is_remote=True, country="Japan")
    assert screen_location(m) == (False, "remote_non_uk")


def test_location_not_stated_keeps():
    assert screen_location(_meta(location_str="")) == (True, "not_stated")


# --- combined screen ---------------------------------------------------------


def test_screen_requires_both_role_and_location():
    # good role, bad location → location drop
    r = screen(_meta(title="Solutions Engineer", location_str="San Francisco, CA"))
    assert not r.keep and r.drop_reason == "location:non_uk_onsite"
    # bad role, good location → role drop (role attributed first)
    r = screen(_meta(title="Account Executive", location_str="London"))
    assert not r.keep and r.drop_reason == "role:sales"
    # both good → keep
    r = screen(_meta(title="Solutions Engineer", location_str="London"))
    assert r.keep and r.drop_reason == ""


# --- near-duplicate collapse -------------------------------------------------


def _entry(rec, company, title, loc_bucket):
    return {"record": rec, "company": company, "title": title, "loc_bucket": loc_bucket}


def test_collapse_merges_language_variants():
    entries = [
        _entry("a", "Stripe", "Customer Success Manager", "uk"),
        _entry("b", "Stripe", "Customer Success Manager (French speaking)", "uk"),
        _entry("c", "Stripe", "Customer Success Manager (German speaking)", "uk"),
    ]
    kept, collapsed = collapse_near_duplicates(entries)
    assert len(kept) == 1 and collapsed == 2


def test_collapse_prefers_uk_representative():
    entries = [
        _entry("de", "Databricks", "AI Engineer - FDE (Forward Deployed Engineer)", "europe_remote"),
        _entry("uk", "Databricks", "AI Engineer - FDE (Forward Deployed Engineer)", "uk"),
        _entry("es", "Databricks", "AI Engineer - FDE (Forward Deployed Engineer)", "europe_remote"),
    ]
    kept, collapsed = collapse_near_duplicates(entries)
    assert collapsed == 2 and len(kept) == 1 and kept[0]["record"] == "uk"


def test_collapse_keeps_distinct_specialisations():
    # same base title, different (non-language) specialisation → NOT merged
    entries = [
        _entry("1", "Databricks", "Senior Solutions Architect (Enterprise Accounts)", "uk"),
        _entry("2", "Databricks", "Senior Solutions Architect (Utilities/Energy)", "uk"),
    ]
    kept, collapsed = collapse_near_duplicates(entries)
    assert len(kept) == 2 and collapsed == 0


# --- GTM/partner observation watchlist ---------------------------------------


def test_watchlist_signal_matches_gtm_partner_class():
    for t in ["GTM Leader", "Head of Go-To-Market", "Head of Partner Enablement",
              "Director, Partner Programs", "Partner Success Lead",
              "Director Strategic Partnerships", "VP Ecosystem", "Sr. Alliance Director",
              "Chief of Staff, Global Partnerships", "Director, Customer Success",
              "Head of Customer Experience"]:
        assert watchlist_signal(t), t


def test_watchlist_signal_excludes_core_targets_and_plain_csm():
    for t in ["Solutions Architect", "Product Manager, Payments", "Pre-Sales Engineer",
              "Customer Success Manager", "Partner Manager SI", "Technical Account Manager"]:
        assert not watchlist_signal(t), t


def test_run_diverts_workable_watchlist_from_survivors():
    records = [
        _rec("https://x/1", html="<p>a</p>"),  # GTM Leader, London -> watchlist
        _rec("https://x/2", html="<p>b</p>"),  # Solutions Architect, London -> survivor
        _rec("https://x/3", html="<p>c</p>"),  # GTM Leader, San Francisco -> location drop (not watchlist)
    ]
    meta_index = {
        "https://x/1": _meta(title="GTM Leader, EMEA", location_str="London", source_url="https://x/1"),
        "https://x/2": _meta(title="Solutions Architect", location_str="London", source_url="https://x/2"),
        "https://x/3": _meta(title="GTM Leader", location_str="San Francisco", source_url="https://x/3"),
    }
    survivors, report = prefilter.run(records, meta_index)

    assert [r.source_url for r in survivors] == ["https://x/2"]      # watchlist diverted, US dropped
    wl = report["watchlist"]
    assert [w["source_url"] for w in wl] == ["https://x/1"]          # only the workable GTM role
    assert report["drop_reasons"]["location:non_uk_onsite"] == 1     # the US GTM role is a normal location drop


def test_run_watchlist_excludes_product_and_recruiting_false_positives():
    records = [
        _rec("https://x/1", html="<p>a</p>"),  # Product Manager, Ecosystem Risk -> stays (product)
        _rec("https://x/2", html="<p>b</p>"),  # Talent Acquisition (GTM) -> dropped (recruiting), not watchlist
        _rec("https://x/3", html="<p>c</p>"),  # Chief of Staff, Partnerships -> watchlist (gtm_partner)
    ]
    meta_index = {
        "https://x/1": _meta(title="Product Manager, Ecosystem Risk", location_str="London", source_url="https://x/1"),
        "https://x/2": _meta(title="Talent Acquisition (Engineering/Product/GTM/Science)", location_str="London", source_url="https://x/2"),
        "https://x/3": _meta(title="Chief of Staff, Global Partnerships", location_str="London", source_url="https://x/3"),
    }
    survivors, report = prefilter.run(records, meta_index)

    assert "https://x/1" in {r.source_url for r in survivors}        # product role stays in scoring
    assert [w["source_url"] for w in report["watchlist"]] == ["https://x/3"]  # only the GTM/partner role
    assert report["drop_reasons"]["role:recruiting"] == 1            # talent acquisition dropped, not observed


# --- CLI run() + IO ----------------------------------------------------------


def _rec(source_url, company="Acme", html="<p>unique body</p>"):
    return build_raw_record(
        source_url=source_url, source_ats="greenhouse", company=company,
        collected_at="2026-06-09", raw_html=html,
    )


def test_run_screens_dedupes_and_reports():
    records = [
        _rec("https://x/1", html="<p>job one</p>"),   # keep (London SE)
        _rec("https://x/2", html="<p>job two</p>"),   # drop role (AE)
        _rec("https://x/3", html="<p>job three</p>"),  # drop location (SF SE)
        _rec("https://x/4", html="<p>job one</p>"),   # exact dup of #1 body → deduped
    ]
    meta_index = {
        "https://x/1": _meta(title="Solutions Engineer", location_str="London", source_url="https://x/1"),
        "https://x/2": _meta(title="Account Executive", location_str="London", source_url="https://x/2"),
        "https://x/3": _meta(title="Solutions Engineer", location_str="San Francisco", source_url="https://x/3"),
        "https://x/4": _meta(title="Solutions Engineer", location_str="London", source_url="https://x/4"),
    }
    survivors, report = prefilter.run(records, meta_index)

    assert report["raw_count"] == 4
    assert report["dropped_dupes"] == 1          # #4 is an exact body dup of #1
    assert report["deduped_count"] == 3
    assert report["kept_count"] == 1             # only #1 survives both screens
    assert [r.source_url for r in survivors] == ["https://x/1"]
    assert report["drop_reasons"]["role:sales"] == 1
    assert report["drop_reasons"]["location:non_uk_onsite"] == 1
    assert report["by_company"]["Acme"] == 1


def test_run_flags_missing_metadata():
    records = [_rec("https://x/1")]
    survivors, report = prefilter.run(records, {})  # no meta for the record
    assert survivors == []
    assert report["no_meta"] == 1
    assert report["drop_reasons"]["no_meta"] == 1


def test_write_survivors_round_trips(tmp_path):
    from models.record import JDRecord

    out = tmp_path / "filtered" / "filtered_20260609.jsonl"
    rec = _rec("https://x/1")
    rec.id = "sha256:abc"
    prefilter.write_survivors([rec], str(out))
    lines = out.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert JDRecord.from_jsonl(lines[0]).source_url == "https://x/1"
