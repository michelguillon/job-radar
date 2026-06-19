# SPEC_COMPANY_SEEDS_DB.md
## Company Seeds — SQLite Migration + Management UI

**Status:** ✅ **Built (2026-06-19)** — deviation 55. All four steps shipped: `company_seeds`
SQLite table + `cli/seeds.py` import/export (109 companies migrated), `cli/collect.py` reads
SQLite (YAML fallback), `api/routers/companies.py` (+ `api/ats_probe.py`), and the owner-only
`Companies` frontend tab. 551 tests pass; `tsc -b` clean.
**Last updated:** 2026-06-19
**Depends on:** Phase 6.5 complete ✅

> **Built notes / divergences from this spec** (authoritative — the spec prose below is the
> original design):
> - The corpus-records check on `DELETE` uses `load_jdrecords` (validated corpus, the
>   exact-name yield join key) — there is no `corpus` SQLite table as the build sketch's SQL
>   implied; company lives on the JDRecord, not the ApplicationRecord.
> - `GET /api/companies/export` and `POST /api/companies/probe-ats` are **owner-gated** (the
>   build prompt scoped them owner; reads of the list are public).
> - The **yield report still reads `company_seeds.yaml`** (`cli.analyse`/`load_companies`
>   unchanged) — §8's "yield reads from DB" is deferred; regenerate the YAML via export when
>   yield must reflect DB edits.
> - The probe endpoints are aligned with the **live collector URLs**
>   (`boards-api.greenhouse.io`, etc.), not the slightly different ones in `find_ats_slugs.py`.
> - No `schema_version` bump (internal DB version stays 1; new table is additive).

---

## 1. Why

`company_seeds.yaml` is currently read at collection time and yield
report time. It's manually edited in a text editor and committed to git.
As the universe grows (109 companies, more to come) and fit_hypothesis
values need updating based on evidence, YAML is the wrong tool:

- No UI to edit — requires SSH + vim or local checkout
- No history of changes (beyond git log)
- Not queryable alongside yield data
- Adding a company requires the script + manual YAML edit + commit

Moving to SQLite makes it a first-class part of the product — editable
from the browser, queryable for yield analysis, consistent with the rest
of the interactive state store.

---

## 2. Data model

### 2.1 `company_seeds` table

```sql
CREATE TABLE company_seeds (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL UNIQUE,
    ats             TEXT NOT NULL,           -- greenhouse|ashby|lever|manual|unknown
    slug            TEXT,                    -- null for manual/unknown
    domain          TEXT,
    fit_hypothesis  TEXT,                    -- high|medium|low|watch_only
    action          TEXT DEFAULT 'keep',     -- keep|promote|downgrade|pause|remove|investigate_ats
    notes           TEXT DEFAULT '',
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now'))
);

CREATE INDEX idx_company_seeds_ats    ON company_seeds (ats);
CREATE INDEX idx_company_seeds_action ON company_seeds (action);
```

Unlike `activity_log` and `annotations`, this table **allows UPDATE**
— company metadata is reference data, not an event log. The append-only
principle does not apply here.

### 2.2 Migration from YAML

One-shot backfill (idempotent — safe to re-run):

```bash
python -m cli.db_migrate --seeds company_seeds.yaml
```

Reads `company_seeds.yaml`, inserts all companies via `INSERT OR IGNORE`
(existing rows untouched on re-run). After first successful run, the YAML
file becomes a backup/export artefact — the DB is the source of truth.

The collector (`cli/collect.py`) currently reads `company_seeds.yaml`.
Update it to read from SQLite after migration.

---

## 3. Scope

### Five use cases

**1. View** — see all companies in a table with their ATS, domain,
fit_hypothesis, action, notes. Sortable by name, domain, fit_hypothesis.

**2. Edit** — change fit_hypothesis, action, notes inline per company.
Owner-gated. No page navigation — inline edit in the table row.

**3. Add** — add a new company with name, ATS, slug, domain,
fit_hypothesis, action, notes. Includes ATS auto-discovery.

**4. Pause / remove** — mark a company's action as `pause` or `remove`
without deleting the DB record. Keeps history, stops collection.

**5. ATS auto-discovery** — when adding a company, probe Greenhouse,
Ashby, and Lever automatically and pre-fill ATS + slug if found.

**6. Export to YAML** — export the full company universe from SQLite
back to `company_seeds.yaml`. Useful for backup, fresh install seeding,
inspection, and git history. Available both as a CLI command and a
download button in the UI.

Yield stats are **excluded from v1** — the yield report remains a
separate CLI/download. The company management UI is purely about
maintaining the universe, not analysing it.

---

## 4. Backend

### 4.1 `api/routers/companies.py` (new router)

All write endpoints are owner-gated (per-route `require_unlocked`,
deviation 42 pattern).

```
GET  /api/companies              Public. Returns all companies sorted
                                 by name. Used by the management UI.

POST /api/companies              Owner. Add a new company.
                                 Body: {name, ats, slug?, domain?,
                                        fit_hypothesis?, action?, notes?}
                                 422 if name already exists.

PATCH /api/companies/{name}      Owner. Update a company's metadata.
                                 Body: any subset of {ats, slug, domain,
                                        fit_hypothesis, action, notes}
                                 404 if not found.
                                 Note: PATCH is the first non-POST write
                                 endpoint — appropriate here because
                                 company seeds are mutable reference data,
                                 not an event log.

DELETE /api/companies/{name}     Owner. Hard delete — only for companies
                                 added by mistake with no collection
                                 history. If any corpus records exist for
                                 this company, return 409 with message
                                 "Company has corpus records — use
                                 action: remove instead."

GET  /api/companies/export       Owner. Export all companies as a
                                 downloadable YAML file.
                                 Returns Content-Type: text/yaml
                                 Content-Disposition: attachment;
                                   filename="company_seeds_{date}.yaml"
                                 Same format as the original
                                 company_seeds.yaml — can be used to
                                 seed a fresh install or restore from
                                 backup.
```

### 4.2 `POST /api/companies/probe-ats` (owner-gated)

Probes Greenhouse, Ashby, and Lever for a given company name. Returns
the first match found, or `{found: false}`.

```python
# Request
{"name": "Moveworks"}

# Response — found
{"found": true, "ats": "greenhouse", "slug": "moveworks"}

# Response — not found
{"found": false}
```

Probe logic: reuse `find_ats_slugs.py` slug generation + HTTP probes,
wrapped in a FastAPI endpoint. Timeout: 10s total across all probes.
Never blocks the UI — called on demand when the user clicks "Find ATS".

Runs server-side (avoids CORS, keeps probe logic in one place).

### 4.3 CLI export / import

```bash
# Export DB → YAML (backup, fresh install seeding, inspection)
python -m cli.seeds export company_seeds.yaml

# Import YAML → DB (one-shot migration + future re-sync)
python -m cli.seeds import company_seeds.yaml
```

The export produces a file identical in structure to the original
`company_seeds.yaml` including the header comment block. The import
is idempotent (`INSERT OR IGNORE`). Both are subcommands of a new
`cli/seeds.py` module.

### 4.4 `cli/collect.py` — read from SQLite

Replace `yaml.safe_load(open("company_seeds.yaml"))` with a SQLite
query:

```python
def load_company_seeds(db) -> list[dict]:
    rows = db.execute(
        "SELECT * FROM company_seeds WHERE action != 'remove' ORDER BY name"
    ).fetchall()
    return [dict(r) for r in rows]
```

`action: pause` and `action: remove` both skip collection (same as
current YAML behaviour). `ats: manual` entries skip collection (no
collector for manual).

Keep `company_seeds.yaml` as a fallback: if `company_seeds` table is
empty (fresh install before migration), fall back to YAML. Log a
warning.

---

## 5. Frontend — Company management view

A new view accessible from the sidebar navigation (owner-only — hidden
from public visitors).

### 5.1 Company table

```
─── Company Universe (109) ────────────────────────────────────────────
[+ Add company]                   [↓ Export YAML]   [Search: _____________]

Name               ATS          Domain                  Fit      Action
──────────────────────────────────────────────────────────────────────
Anthropic          greenhouse   frontier_ai             high     keep
Cohere             ashby        frontier_ai             medium   keep
Databricks         greenhouse   ai_data_platform        high     keep
...
Cognigy            greenhouse   ai_application_platform low      pause  ← muted row
Checkout.com       greenhouse   fintech_infrastructure  low      keep
```

Columns: Name, ATS (badge), Domain, Fit hypothesis (coloured badge),
Action (coloured badge), Notes (truncated). Sortable by any column.

**Inline edit:** clicking any editable cell (Domain, Fit, Action, Notes)
opens an inline edit — same row, no modal. Tab to move between fields.
Save on Enter or blur. Owner-only.

**Paused/removed companies:** muted/greyed row. Not hidden — visible in
the table but visually distinct.

**Row actions (owner only, on hover):**
```
[Edit]  [Pause]  [Remove]  [Delete]
```
- Edit → expand full edit form for that row
- Pause → sets `action: pause` immediately
- Remove → sets `action: remove` immediately
- Delete → confirms, checks for corpus records, hard deletes or 409

### 5.2 Add company form

Opens as a slide-in panel or modal on "+ Add company":

```
Add company
───────────────────────────────────────────

Company name *   [                          ]
                 [Find ATS →]

ATS *            [greenhouse ▾]  pre-filled if found
Slug             [           ]   pre-filled if found

Domain           [frontier_ai ▾]
Fit hypothesis   [high ▾]
Action           [keep ▾]
Notes            [                          ]

                              [Cancel]  [Save]
```

**"Find ATS" button flow:**
1. Click → show "Probing..." spinner
2. POST `/api/companies/probe-ats` with `{name}`
3. Found → pre-fill ATS and Slug fields, show "✓ Found: greenhouse  slug=moveworks"
4. Not found → show "Not found — set manually", ATS defaults to `manual`

ATS and Slug remain editable after auto-fill — the probe result is a
suggestion, not a lock.

---

## 6. CLAUDE.md deviation

This is the first use of `PATCH` in the API. Document as a deviation:

> **Company seeds use PATCH for updates** — unlike all other write
> endpoints which are POST-only (append-only event log pattern),
> `PATCH /api/companies/{name}` updates reference data in place.
> Company seeds are mutable reference data, not an event log. This is
> the only table where UPDATE semantics apply. All other interactive
> state (activity_log, annotations, cv_tailor_links) remains append-only.

---

## 7. Migration sequence

1. Add `company_seeds` table to `cli/db.py` `init_db()`
2. Add `cli/db_migrate.py --seeds` backfill function
3. Run backfill: `python -m cli.db_migrate --seeds company_seeds.yaml`
4. Verify row count matches YAML entry count
5. Update `cli/collect.py` to read from SQLite (with YAML fallback)
6. Build API router (`api/routers/companies.py`)
7. Build frontend company management view
8. Smoke test: add a company via UI, verify it appears in next collection

---

## 8. What does NOT change

- `company_seeds.yaml` — kept as export/backup, no longer the source
  of truth after migration
- Collection logic — same filters (`action != remove`, `ats != manual`)
- Yield report — unchanged, still reads from DB joined with corpus
- `SCHEMA_VERSION` — no bump (new table, no change to existing records)

---

## 9. Definition of Done

1. `company_seeds` table exists in SQLite with all 109 companies
2. `cli/collect.py` reads from SQLite (YAML fallback for fresh install)
3. `GET /api/companies` returns all companies
4. `POST /api/companies` adds a company (422 on duplicate)
5. `PATCH /api/companies/{name}` updates metadata
6. `DELETE /api/companies/{name}` hard deletes (409 if corpus records exist)
7. `POST /api/companies/probe-ats` probes and returns ATS/slug
8. `GET /api/companies/export` returns downloadable YAML
9. `python -m cli.seeds export` produces equivalent YAML file
10. Company management view visible to owner in sidebar
11. Inline edit works for domain, fit_hypothesis, action, notes
12. Add company form with "Find ATS" auto-discovery
13. "↓ Export YAML" button in company management view
14. Paused/removed companies visually distinct in table
15. All existing tests pass + new company seeds tests
16. `tsc -b` clean
