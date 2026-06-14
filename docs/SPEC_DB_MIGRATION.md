# SPEC_DB_MIGRATION.md
## Phase 6.5 — Persistence Hardening (JSONL → SQLite for interactive state)

**Status:** Steps 1–5 ✅ built and deployed. Step 6 pending 1 week dual-write.
**Trigger:** After Langfuse instrumentation is stable — ✅ met
**Scope:** Interactive/stateful data only — pipeline artefacts stay JSONL
**Last updated:** 2026-06-14

---

## 1. Why now, and why not everything

### The actual problem

Job Radar was designed as a pipeline tool with a read-only UI. The spec
still says "files all the way down." Reality has moved past that:

- Live writes from the browser (status, notes, fit overrides, manual ingest)
- SSE live updates triggering re-reads on every write
- cv-tailor callbacks posting metrics machine-to-machine
- Langfuse traces linking across systems
- Cross-app state via `cv_tailor_links.jsonl`
- Annotations, rejection reasons, run history

JSONL append-only files are excellent for pipeline artefacts — ordered,
auditable, cheap to write, easy to inspect. They are poorly suited to
interactive product state that needs to be queried, joined, and updated
frequently by multiple writers.

### The boundary

```
STAYS JSONL (pipeline artefacts — read-heavy, append-once, no joins needed):
  corpus/raw/raw_*.jsonl               — collected raw records
  corpus/raw/meta_*.jsonl              — ATS metadata sidecars
  corpus/filtered/filtered_*.jsonl     — prefilter survivors
  corpus/labelled/labelled_*.jsonl     — Claude extractions
  corpus/validated/validated_*.jsonl   — validated JDRecords
  corpus/scored/scored_*.jsonl         — ApplicationRecords (scorer output)
  corpus/calibration/                  — regression corpus
  corpus/stats.json                    — cost tracking
  corpus/watchlist/                    — GTM observation log

MOVES TO SQLITE (interactive product state — write-heavy, query-heavy):
  corpus/activity_log.jsonl            → activity_log table
  corpus/annotations.jsonl             → annotations table
  corpus/cv_tailor_links.jsonl         → cv_tailor_links table
  corpus/index.json                    → replaced by SQL queries (see §5)
```

The fit_override events currently in `activity_log.jsonl` naturally move
with the activity log — no separate migration needed.

---

## 2. Design principles (preserved from JSONL)

### Append-only is a discipline, not a file format

SQLite supports append-only perfectly. The constraint is enforced at the
application layer — no `UPDATE`, no `DELETE`, ever. The same event-
sourcing pattern translates directly:

```sql
-- Same semantics as JSONL append, now queryable
INSERT INTO activity_log (ts, job_id, event, value, notes)
VALUES ('2026-06-13T...', 'sha256:abc', 'status', 'shortlisted', '')
-- never UPDATE, never DELETE
```

`project()` — the function that derives current workflow state from the
event log — stays conceptually identical. It becomes a SQL query instead
of a Python loop over a loaded file:

```sql
-- Latest status per job_id
SELECT value FROM activity_log
WHERE job_id = ? AND event = 'status'
ORDER BY ts DESC LIMIT 1
```

### What you gain over JSONL

- **Indexed queries** — `WHERE job_id = ?` is O(log n), not O(n)
- **Transactions** — a write touching activity_log + cv_tailor_links
  either both commits or both rolls back. Currently two JSONL appends
  can get out of sync on a crash between them.
- **Concurrent read safety** — SQLite WAL mode handles multiple readers
  (API + CLI) without file locking issues
- **Full audit trail preserved** — every event is still an INSERT,
  never an overwrite

---

## 3. SQLite schema

Database: `corpus/job_radar.db` (gitignored, same as JSONL corpus files)

### 3.1 `activity_log`

Direct translation of `corpus/activity_log.jsonl`:

```sql
CREATE TABLE activity_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TEXT NOT NULL,           -- ISO datetime
    job_id      TEXT NOT NULL,           -- sha256:...
    event       TEXT NOT NULL,           -- status|outcome|note|title|fit_override
    value       TEXT,                    -- event-specific value (JSON for complex)
    notes       TEXT DEFAULT '',
    v           INTEGER DEFAULT 1,
    created_at  TEXT DEFAULT (datetime('now'))
);

CREATE INDEX idx_activity_log_job_id ON activity_log (job_id);
CREATE INDEX idx_activity_log_event  ON activity_log (event);
CREATE INDEX idx_activity_log_ts     ON activity_log (ts DESC);
```

### 3.2 `annotations`

Direct translation of `corpus/annotations.jsonl`:

```sql
CREATE TABLE annotations (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    ts                  TEXT NOT NULL,
    job_id              TEXT NOT NULL,
    annotation_type     TEXT NOT NULL,   -- ANNOTATION_TYPE enum
    field               TEXT,            -- nullable (rejection_reason has null)
    observed            TEXT,            -- JSON array stored as text
    expected            TEXT,            -- JSON array stored as text
    reason              TEXT NOT NULL,
    scorer_label        TEXT,
    scorer_fit_score    INTEGER,
    v                   INTEGER DEFAULT 1,
    created_at          TEXT DEFAULT (datetime('now')),
    -- Duplicate prevention index (same as current 409 check)
    UNIQUE (job_id, annotation_type, field, reason)
);

CREATE INDEX idx_annotations_job_id ON annotations (job_id);
CREATE INDEX idx_annotations_type   ON annotations (annotation_type);
```

### 3.3 `cv_tailor_links`

Direct translation of `corpus/cv_tailor_links.jsonl`:

```sql
CREATE TABLE cv_tailor_links (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    ts                  TEXT NOT NULL,
    job_id              TEXT NOT NULL,
    cv_tailor_run_id    TEXT NOT NULL,
    fit_score           REAL,            -- 0.0–1.0
    coverage_score      REAL,            -- 0.0–1.0
    cv_quality_score    REAL,            -- 0.0–10.0
    cvcm_enabled        INTEGER,         -- 0|1 (SQLite has no bool)
    tailoring_mode      TEXT,            -- demo|full
    output_link         TEXT,
    notes               TEXT DEFAULT '',
    source              TEXT DEFAULT 'manual',  -- manual|cv_tailor_api
    v                   INTEGER DEFAULT 1,
    created_at          TEXT DEFAULT (datetime('now'))
);

CREATE INDEX idx_cv_tailor_links_job_id ON cv_tailor_links (job_id);
CREATE INDEX idx_cv_tailor_links_run_id ON cv_tailor_links (cv_tailor_run_id);
```

### 3.4 Schema versioning

```sql
CREATE TABLE schema_version (
    version     INTEGER NOT NULL,
    applied_at  TEXT DEFAULT (datetime('now'))
);
INSERT INTO schema_version (version) VALUES (1);
```

---

## 4. Migration plan (six steps, each independently verifiable)

### Step 1 — Add SQLite schema + DB initialisation ✅ built

> Two corrections to the DDL above were made in `cli/db.py` (see LEARNINGS,
> "Phase 6.5 Step 1"): `schema_version.version` is the PRIMARY KEY (so
> `INSERT OR IGNORE` is idempotent), and the annotations dedup key is a unique
> **expression index** over `IFNULL(field,'')` (a plain `UNIQUE` would not dedupe
> the NULL-field `rejection_reason` rows — deviation 39).

Create `cli/db.py`:
- `get_db() -> sqlite3.Connection` — opens `corpus/job_radar.db`,
  enables WAL mode, returns connection
- `init_db()` — creates tables if not exist (idempotent)
- `get_db_path()` — reads `JR_DB_PATH` env var, defaults to
  `corpus/job_radar.db`

No app changes yet. Just the schema + init function.

**Verify:** `python -m cli.db init` creates the DB, tables exist,
schema_version = 1.

### Step 2 — Backfill from existing JSONL ✅ built

> Idempotency note: `annotations` dedupes on the UNIQUE expression index
> (`INSERT OR IGNORE`), but `activity_log` and `cv_tailor_links` have no DB
> constraint (an append log may legitimately repeat), so their backfill is
> idempotent via a NULL-safe content pre-check (`_row_exists`, `col IS ?`) on a
> natural key — `(ts, job_id, event, value, notes)` and `(ts, job_id,
> cv_tailor_run_id)` respectively. The JSONL↔SQL row mapping lives once in
> `cli/db.py` (`insert_*` + `_enc`/`_dec`/`_bool_to_int`) so backfill, dual-write
> and dual-read share it. cv-tailor records are run through
> `_migrate_cv_tailor_fields` (deviation 43) before insert.

Create `cli/db_migrate.py`:
- `backfill_activity_log()` — reads `corpus/activity_log.jsonl`,
  inserts each record into `activity_log` table (idempotent — skip
  duplicates on `ts + job_id + event`)
- `backfill_annotations()` — same for `corpus/annotations.jsonl`
- `backfill_cv_tailor_links()` — same for
  `corpus/cv_tailor_links.jsonl`

**Verify:** row counts match JSONL line counts. Run twice — second run
is a no-op (idempotent).

### Step 3 — Dual-read comparison ✅ built

> Implemented as `cli/stats.py --export-index --source {jsonl|sqlite|both}`
> (default `jsonl` until Step 5). `both` builds the index rows from each source and
> runs `compare_index_rows` (by job_id, per-field), printing divergences and exiting
> non-zero if any. The SQLite read paths live in `cli/db.py`
> (`load_events_sqlite` / `load_annotations_sqlite` / `load_cv_tailor_links_sqlite`)
> as drop-in equivalents of the `cli.track`/`cli.stats` JSONL loaders. **Correction
> to the sketch below:** `load_events_sqlite` returns a FLAT list (not a per-job_id
> dict) — `project()` folds a flat list, so the grouped shape would break it.
> Verified: `--source both` reports 0 divergences across the full 53-job live corpus.

`--source both` runs both read paths, computes the joined index from
each, and asserts they produce identical output for every `job_id`.
Any divergence is a bug in the SQLite schema or backfill — fix before
proceeding.

**Verify:** `python -m cli.stats --export-index --source both` exits
cleanly with "0 divergences" for the full live corpus.

### Step 4 — Switch API writes to SQLite ✅ built

> Every write endpoint now writes BOTH stores via thin `cli/db.py` helpers
> (`write_activity_event` / `write_annotation` / `write_cv_tailor_link`:
> open → INSERT → commit → close; each `init_db()`s defensively, and the API
> inits at lifespan startup). `workflow.py` funnels all five events through
> `_append`; `manual_ingest.py` dual-writes its owner-note event too.
> **Annotations 409 now comes from the SQLite UNIQUE index (IntegrityError),
> replacing the load-JSONL-and-scan check** — SQLite is written first so a dup is
> rejected before any JSONL append (no orphan line). Test isolation: an autouse
> `conftest._isolate_db` fixture points `JR_DB_PATH` at a per-test tmp DB.

Update the write endpoints to write to SQLite **and** continue writing
to JSONL (dual-write for safety):

- `api/routers/workflow.py` — `add_note`, `set_title`, `post_status`,
  `post_outcome`, `post_fit_override` → INSERT into `activity_log`
- `api/routers/annotations.py` → INSERT into `annotations`
- `api/routers/cv_tailor.py` → INSERT into `cv_tailor_links`

The duplicate-check for annotations moves from "load JSONL, scan for
match" to a SQL UNIQUE constraint violation (409 on IntegrityError).

**Verify:** make a write via the UI, confirm the record appears in
both SQLite (via `sqlite3` CLI) and the JSONL file.

### Step 5 — Switch API reads to SQLite ✅ built

> Done via **auto-detect**, not a hard switch. `cli.db.use_sqlite()` returns
> `get_db_path().exists()`. Source-aware read entry points were added so the
> auto-detect doesn't disturb the pure JSONL loaders the `--source both`
> comparison depends on: `cli.track.load_activity_events` and
> `cli.stats.load_{annotations,cv_tailor_links,all_cv_tailor_links}_auto` (the bare
> `load_*` stay pure JSONL). The API overlay (`index.py`), `reports.py`,
> `workflow.py`'s current-status read, `manual_ingest.py`'s rebuild, and the CLI
> tools (`track list`, `analyse`, `digest`) all call the auto variants;
> `cli.stats --export-index` default `--source` flipped to `sqlite`.
> **index.json — Option A chosen** (§5): keep it as the pre-built *pipeline* cache;
> the live overlay supplies interactive state from SQLite on every request.
> **Deploy ordering (important):** `use_sqlite()` is existence-based, so an empty
> DB created before the backfill would hide all interactive state. The API lifespan
> deliberately does NOT create the DB. On deploy, run `python -m cli.db_migrate`
> (backfill) **before** serving writes / running the sqlite-default export.
> Verified: `--source both` still reports 0 divergences across the 53-job corpus.

Update the loaders called by `GET /api/index` live overlay:
- `load_events()` → query `activity_log`
- `load_annotations()` → query `annotations`
- `load_cv_tailor_links()` → query `cv_tailor_links`

Run `--source both` again to confirm the overlay now reads from SQLite
and still matches JSONL.

**Verify:** full integration test — new write → SSE event → frontend
re-fetch → data appears, consistent with JSONL file.

### Step 6 — Stop JSONL writes, keep files as audit archive

Once dual-write has run cleanly for 1 week in production (no
divergences, no rollbacks):
- Remove JSONL write from API endpoints (write to SQLite only)
- Keep existing JSONL files in place as audit archive — never delete
- Add a comment in each endpoint: `# JSONL archived at corpus/...jsonl`

**Verify:** write a status update, confirm JSONL file does NOT get a
new line, SQLite has the new row, UI updates correctly.

---

## 5. The index.json question

`corpus/index.json` is currently a pre-built join rebuilt on demand.
The live overlay in `GET /api/index` already re-projects activity_log,
annotations, and cv_tailor_links on every request.

Once Steps 4–5 are complete, the API reads all interactive state from
SQLite. `corpus/index.json` becomes a cache of the JSONL pipeline
artefacts (scored ApplicationRecords ⨝ JDRecords ⨝ sidecar metadata)
with no interactive state in it.

**Two options — decide at Step 5:**

**Option A — Keep index.json as pipeline cache:** rebuild it after each
scoring run (same as now). The live overlay queries SQLite for
interactive state. `index.json` only contains static pipeline output.

**Option B — Drop index.json entirely:** `GET /api/index` joins
everything live — SQLite for interactive state, loaded JSONL for
pipeline artefacts. No pre-built file. Slightly more CPU on each
request, simpler overall.

Recommendation: Option A initially (less change, safe rollback).
Option B when the PostgreSQL migration happens (if it happens).

---

## 6. CLI loaders

The CLI tools (`cli/track.py`, `cli/stats.py`, `cli/analyse.py`,
`cli/digest.py`) currently load JSONL directly. After Step 5:

- Add `--db` flag to read from SQLite (default: auto-detect — if
  `corpus/job_radar.db` exists, use it; else fall back to JSONL)
- This keeps the CLI working during and after migration without
  breaking existing workflows

---

## 7. SQLite operational notes

**WAL mode** — enable on every connection open:
```python
conn.execute("PRAGMA journal_mode=WAL")
conn.execute("PRAGMA foreign_keys=ON")
```
WAL allows concurrent readers while a writer is active. Essential for
the API (writing) + CLI (reading) running simultaneously.

**Backup** — `corpus/job_radar.db` is gitignored corpus data. Add to
the existing M720q backup cron:
```bash
sqlite3 corpus/job_radar.db ".backup /var/backups/job-radar/db_$DATE.sqlite"
```
SQLite's `.backup` command is safe under concurrent access.

**No new infrastructure** — SQLite is stdlib (`import sqlite3`). No
new Docker service, no new container, no new env vars beyond
`JR_DB_PATH`.

---

## 8. What does NOT move (ever)

The pipeline artefacts in JSONL are permanent:

- `corpus/raw/`, `corpus/filtered/`, `corpus/labelled/`,
  `corpus/validated/`, `corpus/scored/` — Claude's extraction and
  scoring output. Never in a DB. The scorer is regenerable from
  these files; they are the ground truth for fine-tuning.
- `corpus/calibration/` — scorer regression corpus. Stays as files.
- `corpus/stats.json` — cost ledger. Simple enough to stay as JSON.

---

## 9. Future: PostgreSQL

SQLite is the right choice for single-user home server. If and when
Job Radar becomes multi-user (friends using the same tooling, apps
converging), the migration path from SQLite to PostgreSQL is:

1. Same schema — PostgreSQL supports the same DDL with minor syntax
   changes (no AUTOINCREMENT → SERIAL, TEXT → VARCHAR/TEXT is fine)
2. `pg_dump`-compatible export from SQLite via standard tools
3. No application logic changes — `sqlite3` → `psycopg2`/`asyncpg`,
   connection handling updates

SQLite → PostgreSQL is a known, well-tooled path. This is not a dead
end — it's the right starting point for this scale.

---

## 10. Definition of Done

1. ✅ `corpus/job_radar.db` exists and has the correct schema
2. ✅ All three JSONL state files backfilled with zero divergences
3. ✅ `cli/stats.py --export-index --source both` exits clean (0
   divergences) against the full live corpus
4. ✅ API writes go to SQLite; JSONL dual-write active for 1 week
   *(dual-write started 2026-06-14 — Step 6 gate: 2026-06-21)*
5. ✅ API reads (live overlay) come from SQLite
6. ✅ `cli/track.py`, `cli/analyse.py` auto-detect SQLite
7. 🔲 JSONL writes removed; files preserved as audit archive (Step 6)
8. ✅ Backup cron updated for `job_radar.db`
9. ✅ All existing 481+ tests pass; new migration tests added
10. 🔲 `SPEC_DB_MIGRATION.md` §4 steps all marked ✅

---

## 11. Relationship to §11.5 UI overhaul

The UI overhaul (Cursor experiment) is gated on this migration because:
- The new frontend should query SQLite-backed endpoints, not load a
  monolithic `index.json` blob
- The SSE `index_updated` event becomes a trigger for a targeted SQL
  query rather than a full file reload
- The API contract becomes cleaner — specific endpoints return specific
  data, not one joined blob

The UI overhaul is NOT gated on completing all six steps — it can start
once Step 5 (API reads from SQLite) is done.
