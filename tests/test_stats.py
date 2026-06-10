"""Tests for stats.py — summary aggregation and the UI index export."""

import json

import cli.stats as stats
from tests.factories import make_record


def _rec(*, tier, role_type, domain, decision, fit, applied):
    r = make_record(raw_text="x", tier=tier)
    r.role_type = role_type
    r.domain = domain
    r.application_decision = decision
    r.fit_score = fit
    r.applied = applied
    return r


def _corpus():
    return [
        _rec(tier=1, role_type=["Solutions Engineering"], domain=["FinTech"], decision="applied", fit=7, applied=True),
        _rec(tier=2, role_type=["Pre-Sales", "Solutions Consulting"], domain=["SaaS"], decision="want_to_apply", fit=8, applied=False),
        _rec(tier=4, role_type=["GTM"], domain=["SaaS"], decision="pending", fit=None, applied=False),
    ]


def test_summarize_counts():
    s = stats.summarize(_corpus())
    assert s["total"] == 3
    assert s["by_tier"] == {1: 1, 2: 1, 4: 1}
    assert s["by_role_type"]["Pre-Sales"] == 1
    assert s["by_domain"]["SaaS"] == 2  # counted across two records
    assert s["by_application_decision"]["applied"] == 1
    assert s["applied_count"] == 1
    assert s["fit_score"] == {"n": 2, "mean": 7.5, "min": 7, "max": 8}


def test_export_index_is_flat_array(tmp_path):
    path = str(tmp_path / "index.json")
    stats.export_index(_corpus(), path=path)

    data = json.loads(open(path, encoding="utf-8").read())
    assert isinstance(data, list) and len(data) == 3
    row = data[0]
    # denormalised: extraction/annotation fields live at the top level, no nesting
    assert "extraction" not in row and "annotation" not in row
    assert row["seniority"] == "ic"
    assert row["application_decision"] == "applied"
    assert row["schema_version"]


def test_load_records_reads_glob(tmp_path):
    f = tmp_path / "a.jsonl"
    f.write_text("\n".join(r.to_jsonl() for r in _corpus()) + "\n", encoding="utf-8")
    loaded = stats.load_records(str(tmp_path / "*.jsonl"))
    assert len(loaded) == 3
