"""Tests for the collect.py CLI: selection, routing, writing, and dry-run."""

import collect
from collectors.base import CollectedJob, build_meta, build_raw_record


SEEDS = [
    {"name": "Anthropic", "ats": "greenhouse", "slug": "anthropic"},
    {"name": "Figma", "ats": "greenhouse", "slug": "figma"},
    {"name": "Mistral", "ats": "lever", "slug": "mistral"},
]


def _record(company="Acme"):
    return CollectedJob(
        record=build_raw_record(
            source_url="https://x/1",
            source_ats="greenhouse",
            company=company,
            collected_at="2026-06-09",
            raw_html="<p>x</p>",
        ),
        meta=build_meta(
            source_url="https://x/1",
            source_ats="greenhouse",
            company=company,
            title="Solutions Engineer",
            location_str="London, UK",
        ),
    )


# --- select ---


def test_select_filters_by_source():
    out = collect.select(SEEDS, "greenhouse", None)
    assert [c["name"] for c in out] == ["Anthropic", "Figma"]


def test_select_all_returns_everything():
    assert len(collect.select(SEEDS, "all", None)) == 3


def test_select_by_company_slug():
    out = collect.select(SEEDS, "greenhouse", "anthropic")
    assert [c["name"] for c in out] == ["Anthropic"]


def test_select_by_company_name_case_insensitive():
    out = collect.select(SEEDS, "all", "mistral")
    assert [c["name"] for c in out] == ["Mistral"]


# --- collect / routing ---


def test_collect_routes_to_registered_collector():
    seen = []

    def fake_fetch(slug, name, *, collected_at=None):
        seen.append((slug, name))
        return [_record(name)]

    records = collect.collect(SEEDS, registry={"greenhouse": fake_fetch})
    # lever company skipped (no collector registered)
    assert seen == [("anthropic", "Anthropic"), ("figma", "Figma")]
    assert len(records) == 2


def test_collect_skips_unregistered_ats():
    records = collect.collect(
        [{"name": "Mistral", "ats": "lever", "slug": "mistral"}],
        registry={"greenhouse": lambda *a, **k: [_record()]},
    )
    assert records == []


# --- write / dry-run ---


def test_write_records_appends_jsonl(tmp_path):
    from models.record import JDRecord

    out_dir = tmp_path / "raw"
    path = collect.write_records([_record("A"), _record("B")], out_dir=str(out_dir), date_str="20260609")
    assert path.endswith("raw_20260609.jsonl")

    lines = (out_dir / "raw_20260609.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert JDRecord.from_jsonl(lines[0]).company == "A"

    # second call appends rather than overwrites
    collect.write_records([_record("C")], out_dir=str(out_dir), date_str="20260609")
    lines = (out_dir / "raw_20260609.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3


def test_write_meta_writes_sidecar(tmp_path):
    import json

    out_dir = tmp_path / "raw"
    path = collect.write_meta([_record("A"), _record("B")], out_dir=str(out_dir), date_str="20260609")
    assert path.endswith("meta_20260609.jsonl")

    lines = (out_dir / "meta_20260609.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    meta = json.loads(lines[0])
    assert meta["title"] == "Solutions Engineer"
    assert meta["location_str"] == "London, UK"
    assert meta["source_url"] == "https://x/1"


def test_main_dry_run_writes_nothing(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(collect, "load_companies", lambda *a, **k: SEEDS)
    monkeypatch.setattr(
        collect, "COLLECTORS", {"greenhouse": lambda slug, name, *, collected_at=None: [_record(name)]}
    )
    wrote = []
    monkeypatch.setattr(collect, "write_records", lambda *a, **k: wrote.append(True))

    rc = collect.main(["--source", "greenhouse", "--dry-run"])
    assert rc == 0
    assert wrote == []  # dry-run never writes
    assert "[dry-run] 2 records" in capsys.readouterr().out
