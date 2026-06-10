# CLAUDE.md — ui/

The Phase 5 read-only browse/filter interface (job_radar_SPEC §9). Three static
files served by nginx: `index.html` (markup), `app.js` (logic), `style.css`.

## Conventions

- **Vanilla JS only** — no framework, no build step, no external CDN. Self-contained.
  Keep it that way: no npm, no bundler, no `<script src="https://…">`.
- **Strictly read-only** — the UI fetches `data/index.json` and renders. It must
  never POST, write a file, or invoke a CLI. "CLI writes, UI reads" (root CLAUDE.md)
  is enforced here by *not having* any write path. Don't add one.
- **Data contract = the join, not a JDRecord array.** `app.js` reads
  `{schema_version, jdrecord_schema_version, generated_at, stats, records}` where
  each `records[i]` is one **scored** job = `ApplicationRecord` ⨝ `JDRecord`
  extraction ⨝ sidecar ⨝ activity-log projection. Built by
  `python -m cli.stats --input "corpus/validated/validated_*.jsonl" --export-index`
  (deviation 27 / SPEC §9.4). If you add a field to the UI, add it to
  `cli.stats.build_index_rows` (and a default in `_EXTRACTION_DEFAULTS` if it's an
  extraction field) — never read a second file from the browser.
- **Regenerate before viewing.** `corpus/index.json` is a build artifact (gitignored).
  After any re-score / new collection, re-run `--export-index` or the UI shows stale
  data. The Docker `ui` service mounts the file read-only at `data/index.json`.
- **Enum orderings mirror `models/record.py`.** `FIT_LABELS` / `STATUS_ORDER` /
  `LABEL_TEXT` in `app.js` are hand-kept in sync with `FIT_LABEL` / `APPLICATION_STATUS`.
  If those enums change, update `app.js` (filters fall back to data-derived presence,
  so a missing label just won't show its canonical slot — but the colour/badge needs the entry).
- **`blocked_fit` recedes by design** — muted + struck-through in both the table and
  pipeline cards so it doesn't compete with `strong_fit`. Don't restyle it to parity.

## Serve

`docker compose --profile ui up` → http://localhost:8080. Profile-gated so it never
starts with the default `docker compose up`. The `ui/` mount is intentionally **not**
`:ro` (Docker creates the nested `data/` mountpoint inside it); only the `index.json`
file mount is `:ro`.
