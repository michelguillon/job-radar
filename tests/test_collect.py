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

    def fake_fetch(slug, name, *, collected_at=None, updated_after=None):
        seen.append((slug, name))
        return [_record(name)]

    records = collect.collect(SEEDS, registry={"greenhouse": fake_fetch})
    # lever company skipped (no collector registered)
    assert seen == [("anthropic", "Anthropic"), ("figma", "Figma")]
    assert len(records) == 2


def test_collect_passes_per_source_cursor():
    seen = {}

    def fake_fetch(slug, name, *, collected_at=None, updated_after=None):
        seen[name] = updated_after
        return [_record(name)]

    collect.collect(
        SEEDS,
        registry={"greenhouse": fake_fetch, "lever": fake_fetch},
        updated_after_by_source={"greenhouse": "2026-06-10T00:00:00+00:00"},  # lever absent → None
    )
    assert seen["Anthropic"] == "2026-06-10T00:00:00+00:00"
    assert seen["Mistral"] is None  # non-incremental source gets no cursor


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
        collect, "COLLECTORS",
        {"greenhouse": lambda slug, name, *, collected_at=None, updated_after=None: [_record(name)]},
    )
    monkeypatch.setattr(collect, "CURSOR_DIR", str(tmp_path))
    wrote = []
    monkeypatch.setattr(collect, "write_records", lambda *a, **k: wrote.append(True))

    rc = collect.main(["--source", "greenhouse", "--dry-run"])
    assert rc == 0
    assert wrote == []  # dry-run never writes
    assert "[dry-run] 2 records" in capsys.readouterr().out
    # dry-run never advances the cursor
    assert collect.read_cursor("greenhouse", str(tmp_path)) is None


# --- cursor persistence ---


def test_read_cursor_absent_returns_none(tmp_path):
    assert collect.read_cursor("greenhouse", str(tmp_path)) is None


def test_write_then_read_cursor_round_trips(tmp_path):
    collect.write_cursor("greenhouse", "2026-06-10T07:00:00+00:00", str(tmp_path))
    assert collect.read_cursor("greenhouse", str(tmp_path)) == "2026-06-10T07:00:00+00:00"
    # stored as a dotfile named per source
    assert (tmp_path / ".last_collected_greenhouse").exists()


# --- main: cursor advance rules ---


def _patch_main(monkeypatch, tmp_path, *, seeds=SEEDS):
    """Wire main()'s IO to tmp_path: in-memory collectors, no-op writers, tmp cursors."""
    monkeypatch.setattr(collect, "load_companies", lambda *a, **k: seeds)
    monkeypatch.setattr(collect, "CURSOR_DIR", str(tmp_path))
    monkeypatch.setattr(collect, "write_records", lambda *a, **k: "raw.jsonl")
    monkeypatch.setattr(collect, "write_meta", lambda *a, **k: "meta.jsonl")
    seen = {}

    def fake(slug, name, *, collected_at=None, updated_after=None):
        seen[name] = updated_after
        return [_record(name)]

    monkeypatch.setattr(collect, "COLLECTORS", {"greenhouse": fake, "lever": fake})
    return seen


def test_main_advances_cursor_on_full_source_run(monkeypatch, tmp_path):
    _patch_main(monkeypatch, tmp_path)
    assert collect.main(["--source", "greenhouse"]) == 0
    cursor = collect.read_cursor("greenhouse", str(tmp_path))
    assert cursor is not None and cursor.endswith("+00:00")  # ISO UTC run-start written


def test_main_company_run_does_not_advance_cursor(monkeypatch, tmp_path):
    _patch_main(monkeypatch, tmp_path)
    collect.main(["--source", "greenhouse", "--company", "anthropic"])
    assert collect.read_cursor("greenhouse", str(tmp_path)) is None  # subset run never advances


def test_main_full_flag_ignores_existing_cursor(monkeypatch, tmp_path):
    seen = _patch_main(monkeypatch, tmp_path)
    collect.write_cursor("greenhouse", "2026-01-01T00:00:00+00:00", str(tmp_path))
    collect.main(["--source", "greenhouse", "--full"])
    assert seen["Anthropic"] is None  # --full passes no cursor to the collector


def test_main_incremental_run_reads_existing_cursor(monkeypatch, tmp_path):
    seen = _patch_main(monkeypatch, tmp_path)
    collect.write_cursor("greenhouse", "2026-06-01T00:00:00+00:00", str(tmp_path))
    collect.main(["--source", "greenhouse"])
    assert seen["Anthropic"] == "2026-06-01T00:00:00+00:00"  # cursor fed to the collector
