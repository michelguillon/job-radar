"""seeds.py — import/export the company universe between SQLite and YAML
(SPEC_COMPANY_SEEDS_DB §4.3, deviation 55).

    python -m cli.seeds import company_seeds.yaml   # YAML -> SQLite (idempotent backfill)
    python -m cli.seeds export company_seeds.yaml   # SQLite -> YAML (backup / fresh-install seed)

The ``company_seeds`` table is the source of truth after the one-shot import; the YAML file
becomes an export/backup artefact (regenerable from the DB at any time). Import is idempotent
(``INSERT OR IGNORE`` — existing rows are left untouched on a re-run). Export produces a file
structurally identical to the original ``company_seeds.yaml`` (a bare top-level list with the
documented header comment block) so it can re-seed a fresh install.

The YAML-building (``dump_seeds_yaml``) lives here so the CLI export and the API
``GET /api/companies/export`` share one implementation.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone

import yaml

from cli.collect import SEEDS_PATH, load_companies
from cli.db import (
    COMPANY_SEED_COLUMNS,
    get_db,
    import_company_seed,
    init_db,
    list_company_seeds,
)

# Header comment block prepended to an exported YAML (yaml.dump can't emit comments). Mirrors
# the original company_seeds.yaml so a round-tripped file documents its own provenance.
_HEADER_TEMPLATE = """\
# company_seeds.yaml — Job Radar Company Universe
# Exported: {date} | {count} companies
# Source of truth: corpus/job_radar.db (company_seeds table)
# This file is an export — edit companies via the Job Radar UI or
# PATCH /api/companies/{{name}}
#
# domain vocabulary:
#   frontier_ai | ai_application_platform | ai_data_platform | ai_infrastructure
#   developer_tooling | fintech_infrastructure | fintech_platform
#   adtech_martech | identity_security | enterprise_software
#   semiconductor_ai_compute | strategic_ai_delivery | retail_media_data
#   customer_data_martech | mlops_observability | enterprise_crm_platform
#
# fit_hypothesis: high | medium | low | watch_only
# action: keep | promote | downgrade | pause | remove | investigate_ats | review_manually
# ats: greenhouse | ashby | lever | manual | unknown
"""


def _seed_for_export(row: dict) -> dict:
    """Project a DB row down to the seven owner-facing columns, in a stable order, so the
    exported YAML matches the original schema (drops id/created_at/updated_at)."""
    return {col: row.get(col) for col in COMPANY_SEED_COLUMNS}


def dump_seeds_yaml(rows: list[dict], *, today: str | None = None) -> str:
    """Render company rows to the YAML export text (header comment + bare top-level list).

    Shared by ``cli.seeds export`` and the API export download so the two never drift.
    """
    today = today or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    header = _HEADER_TEMPLATE.format(date=today, count=len(rows))
    body = yaml.dump(
        [_seed_for_export(r) for r in rows],
        sort_keys=False, default_flow_style=False, allow_unicode=True, width=88,
    )
    return header + "\n" + body


def import_seeds(path: str = SEEDS_PATH) -> tuple[int, int]:
    """Import every company from ``path`` into SQLite (idempotent). Returns
    ``(inserted, already_existed)``."""
    init_db()
    companies = load_companies(path)
    inserted = 0
    with get_db() as conn:
        for company in companies:
            if import_company_seed(conn, company):
                inserted += 1
    return inserted, len(companies) - inserted


def export_seeds(path: str = SEEDS_PATH, *, today: str | None = None) -> int:
    """Export all companies from SQLite to ``path`` as YAML. Returns the company count."""
    init_db()
    with get_db() as conn:
        rows = list_company_seeds(conn)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(dump_seeds_yaml(rows, today=today))
    return len(rows)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) < 1 or argv[0] not in ("import", "export"):
        print("usage: python -m cli.seeds {import|export} [path]")
        return 2
    subcommand = argv[0]
    path = argv[1] if len(argv) > 1 else SEEDS_PATH

    if subcommand == "import":
        inserted, existed = import_seeds(path)
        print(f"Imported {inserted} companies ({existed} already existed)")
    else:
        count = export_seeds(path)
        print(f"Exported {count} companies to {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
