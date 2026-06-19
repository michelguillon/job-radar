"""Tests for cli/seeds.py — company_seeds import/export (SPEC_COMPANY_SEEDS_DB §4.3).

JR_DB_PATH is pointed at a per-test tmp DB by the autouse conftest fixture, so nothing
here touches the real corpus DB.
"""

from __future__ import annotations

import yaml

import cli.db as db
import cli.seeds as seeds


def _write_yaml(path, companies: list[dict]) -> str:
    path.write_text(yaml.dump(companies, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return str(path)


SAMPLE = [
    {"name": "Anthropic", "ats": "greenhouse", "slug": "anthropic",
     "domain": "frontier_ai", "fit_hypothesis": "high", "action": "keep", "notes": "watch SA roles"},
    {"name": "Cohere", "ats": "ashby", "slug": "cohere",
     "domain": "frontier_ai", "fit_hypothesis": "medium", "action": "keep", "notes": ""},
    {"name": "Jack & Jill", "ats": "manual", "slug": None,
     "domain": None, "fit_hypothesis": "watch_only", "action": "review_manually", "notes": "no public board"},
]


def test_seeds_import_inserts_all(tmp_path):
    path = _write_yaml(tmp_path / "seeds.yaml", SAMPLE)
    inserted, existed = seeds.import_seeds(path)
    assert (inserted, existed) == (3, 0)
    with db.get_db() as conn:
        assert len(db.list_company_seeds(conn)) == 3


def test_seeds_import_idempotent(tmp_path):
    path = _write_yaml(tmp_path / "seeds.yaml", SAMPLE)
    seeds.import_seeds(path)
    inserted, existed = seeds.import_seeds(path)  # second run
    assert (inserted, existed) == (0, 3)
    with db.get_db() as conn:
        assert len(db.list_company_seeds(conn)) == 3  # count unchanged


def test_seeds_import_idempotent_preserves_edits(tmp_path):
    """A re-import must not overwrite a row edited in the DB (INSERT OR IGNORE)."""
    path = _write_yaml(tmp_path / "seeds.yaml", SAMPLE)
    seeds.import_seeds(path)
    with db.get_db() as conn:
        db.update_company_seed(conn, "Anthropic", {"fit_hypothesis": "low"})
    seeds.import_seeds(path)  # re-import the original (high)
    with db.get_db() as conn:
        assert db.get_company_seed(conn, "Anthropic")["fit_hypothesis"] == "low"


def test_seeds_export_roundtrip(tmp_path):
    src = _write_yaml(tmp_path / "seeds.yaml", SAMPLE)
    seeds.import_seeds(src)

    out = tmp_path / "exported.yaml"
    count = seeds.export_seeds(str(out), today="2026-06-19")
    assert count == 3

    text = out.read_text(encoding="utf-8")
    assert text.startswith("# company_seeds.yaml")        # header comment block present
    assert "3 companies" in text

    exported = yaml.safe_load(text)                        # comments are ignored by the parser
    assert isinstance(exported, list)                      # bare top-level list, like the original
    by_name = {c["name"]: c for c in exported}
    assert set(by_name) == {"Anthropic", "Cohere", "Jack & Jill"}
    assert by_name["Anthropic"]["fit_hypothesis"] == "high"
    assert by_name["Jack & Jill"]["slug"] is None
    # Only the seven owner-facing columns are exported (no id/created_at/updated_at leak).
    assert set(by_name["Cohere"]) == set(db.COMPANY_SEED_COLUMNS)


def test_seeds_export_reimports_equivalently(tmp_path):
    """Export then import into a fresh DB yields the same company set (data round-trips)."""
    seeds.import_seeds(_write_yaml(tmp_path / "seeds.yaml", SAMPLE))
    out = str(tmp_path / "exported.yaml")
    seeds.export_seeds(out)

    with db.get_db() as conn:
        for row in db.list_company_seeds(conn):
            db.delete_company_seed(conn, row["name"])
    inserted, _ = seeds.import_seeds(out)
    assert inserted == 3
