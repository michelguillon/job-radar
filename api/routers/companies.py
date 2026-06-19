"""api/routers/companies.py — company universe management (SPEC_COMPANY_SEEDS_DB §4, deviation 55).

CRUD over the ``company_seeds`` SQLite table — the ONE mutable interactive-state table (company
metadata is reference data, not an event log, so ``PATCH`` updates in place; every other write
endpoint stays append-only — see api/CLAUDE.md). Reads are public; writes are owner-gated
per-route (``Depends(require_unlocked)``, deviation 42). Plus ``POST /probe-ats`` (server-side
ATS auto-discovery) and ``GET /export`` (download the universe as YAML, reusing the
``cli.seeds`` exporter).

The table is created on demand via ``cli.db.init_db`` (idempotent). The production DB already
exists post-Phase-6.5, and a fresh install runs ``python -m cli.seeds import`` at deploy time,
so this never silently flips the interactive-state read source.
"""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from api import ats_probe
from api.events import emit_index_updated
from api.security import require_unlocked
from api.settings import Settings, get_settings
from cli.db import (
    delete_company_seed,
    get_company_seed,
    get_db,
    init_db,
    insert_company_seed,
    list_company_seeds,
    update_company_seed,
)
from cli.seeds import dump_seeds_yaml
from cli.track import load_jdrecords

router = APIRouter(prefix="/api/companies", tags=["companies"])


class CompanyCreate(BaseModel):
    name: str
    ats: str
    slug: str | None = None
    domain: str | None = None
    fit_hypothesis: str | None = None
    action: str | None = "keep"
    notes: str | None = ""


class CompanyPatch(BaseModel):
    ats: str | None = None
    slug: str | None = None
    domain: str | None = None
    fit_hypothesis: str | None = None
    action: str | None = None
    notes: str | None = None


class ProbeRequest(BaseModel):
    name: str


def _conn() -> sqlite3.Connection:
    """Open a DB connection, ensuring the schema exists (idempotent CREATE TABLE IF NOT EXISTS)."""
    init_db()
    return get_db()


def _has_corpus_records(name: str, validated_glob: str) -> bool:
    """True if any collected/scored JD belongs to ``name``. Company lives on the JDRecord
    (the ApplicationRecord has none), so this checks the validated corpus — the same exact-name
    key the yield report joins on. Used to refuse a hard DELETE of a company with history."""
    jds = load_jdrecords(validated_glob)
    return any(jd.company == name for jd in jds.values())


@router.get("")
def list_companies() -> list[dict]:
    """All companies ordered by name (public — drives the management UI)."""
    conn = _conn()
    try:
        return list_company_seeds(conn)
    finally:
        conn.close()


@router.get("/export", dependencies=[Depends(require_unlocked)], response_class=PlainTextResponse)
def export_companies() -> PlainTextResponse:
    """Download the full universe as ``company_seeds.yaml`` (same format as the CLI export —
    reuses ``cli.seeds.dump_seeds_yaml``). Owner-only."""
    from datetime import datetime, timezone

    conn = _conn()
    try:
        rows = list_company_seeds(conn)
    finally:
        conn.close()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    text = dump_seeds_yaml(rows, today=today)
    return PlainTextResponse(
        text,
        media_type="text/yaml",
        headers={"Content-Disposition": f'attachment; filename="company_seeds_{today}.yaml"'},
    )


@router.post("/probe-ats", dependencies=[Depends(require_unlocked)])
def probe_ats(body: ProbeRequest) -> dict:
    """Probe Greenhouse/Ashby/Lever for a company name; return the first match or
    ``{"found": false}``. Never raises (api/ats_probe swallows all errors). Owner-only."""
    if not body.name.strip():
        raise HTTPException(status_code=422, detail="name is required")
    return ats_probe.probe_ats(body.name.strip())


@router.post("", dependencies=[Depends(require_unlocked)])
def create_company(body: CompanyCreate) -> dict:
    """Add a new company. 422 if name/ats empty; 409 if the name already exists."""
    if not body.name.strip() or not body.ats.strip():
        raise HTTPException(status_code=422, detail="name and ats are required")
    rec = {
        "name": body.name.strip(),
        "ats": body.ats.strip(),
        "slug": body.slug,
        "domain": body.domain,
        "fit_hypothesis": body.fit_hypothesis,
        "action": body.action or "keep",
        "notes": body.notes or "",
    }
    conn = _conn()
    try:
        try:
            with conn:
                insert_company_seed(conn, rec)
        except sqlite3.IntegrityError:
            raise HTTPException(status_code=409, detail=f"company already exists: {rec['name']}")
        created = get_company_seed(conn, rec["name"])
    finally:
        conn.close()
    emit_index_updated()
    return created


@router.patch("/{name}", dependencies=[Depends(require_unlocked)])
def patch_company(name: str, body: CompanyPatch) -> dict:
    """Update any subset of {ats, slug, domain, fit_hypothesis, action, notes}; bumps
    updated_at. 404 if not found. (PATCH-in-place is unique to this reference table — every
    other write endpoint is append-only; deviation 55.)"""
    fields = body.model_dump(exclude_unset=True)
    conn = _conn()
    try:
        with conn:
            matched = update_company_seed(conn, name, fields)
        if not matched:
            raise HTTPException(status_code=404, detail=f"company not found: {name}")
        updated = get_company_seed(conn, name)
    finally:
        conn.close()
    emit_index_updated()
    return updated


@router.delete("/{name}", dependencies=[Depends(require_unlocked)], status_code=204)
def delete_company(name: str, settings: Settings = Depends(get_settings)) -> None:
    """Hard-delete a company added by mistake. 404 if not found; 409 if it has corpus records
    (use ``action: remove`` instead, which keeps the row and stops collection)."""
    conn = _conn()
    try:
        if get_company_seed(conn, name) is None:
            raise HTTPException(status_code=404, detail=f"company not found: {name}")
        if _has_corpus_records(name, settings.validated_glob):
            raise HTTPException(
                status_code=409,
                detail="Company has corpus records — use action: remove instead",
            )
        with conn:
            delete_company_seed(conn, name)
    finally:
        conn.close()
    emit_index_updated()
