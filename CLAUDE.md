# jd-refinery — project memory

CLI data pipeline that collects, cleans, deduplicates, labels, validates, and
exports job descriptions into a structured corpus (schema **v1.2**) for
fine-tuning (Project 4) and CV-tailoring workflows.

## Sources of truth (authoritative — read before changing related code)

- **`docs/SPEC_JD_REFINERY.md`** — architecture spec / design intent, the
  implementation steps (§5), and the collection seed lists (§6).
- **`docs/CORPUS_FINDINGS.md`** — the **locked schema v1.2** (§1.1), labelling
  rules (§2), and all JD records (§5). This is the definitive schema reference.
- **`models/record.py`** — the executable schema: `JDRecord`, `SCHEMA_VERSION`,
  `validate()`. Must stay in sync with CORPUS_FINDINGS §1.1.

> Docs live in `docs/`. The spec file is `SPEC_JD_REFINERY.md` (some docs call it
> `PROJECT_SPEC.md` — same file). `PROJECT_DOCUMENTATION_STANDARD.md` is
> referenced by the docs but is not yet in the repo.

## Build / run / test — Docker only

Local Python lacks the dependencies (`bs4`, `anthropic`, …). Always use the
container:

```bash
docker compose build
docker compose run --rm jd-refinery python -m pytest -q        # tests
docker compose run --rm jd-refinery python collect.py --dry-run # a CLI
```

## Load-bearing conventions

- **Schema is v1.2 and LOCKED.** `SCHEMA_VERSION = "1.2"` everywhere. No new
  fields without a deliberate re-freeze (see spec §3.2); bump the version only on
  an intentional schema change. Records are **append-only** — never migrate in
  place; write new dated files.
- **JSONL files only** — no database, no web UI.
- **Labelling uses the Anthropic Batch API only** — no synchronous extraction.
- **Scraping uses BeautifulSoup only** — no Playwright/JS. Mark `requires_js`
  boards in `vc_boards.yaml` and skip them.
- **Two-schema boundary:** `extraction` fields are Claude-populated; `annotation`
  fields are human-only. Claude must never write annotation fields.
- **Dedup key = SHA-256 of normalised cleaned text** (the record `id`), not URL.
- **Every module gets pytest tests** under `tests/`.

## Build process

Work through `docs/SPEC_JD_REFINERY.md §5` steps **in order**. Each step has a
verification gate — do not start step N+1 until step N's verification passes.

## Secrets & ignored paths

- `.env` holds `ANTHROPIC_API_KEY` — never commit. `.env.example` is the template.
- `.gitignore` excludes `.env`, `*.jsonl`, `__pycache__`, `.pytest_cache`, and all
  `corpus/` data (the directory skeleton is kept via `.gitkeep`). The corpus —
  including `corpus/manual/*.jsonl` — is intentionally untracked.

## Recording learnings (do this continuously, not just post-build)

When a non-obvious decision, gotcha, or reusable lesson emerges during the build,
record it in the same change that introduces it:

- reusable engineering / AI-system lessons → `docs/PROJECT_LEARNINGS.md`
- what happened / what changed / why → `docs/PROJECT_RETROSPECTIVE.md`
- a convention or decision that should bind future work → the nearest `CLAUDE.md`

Keep these current — stale memory is worse than none. A `CLAUDE.md` states
conventions and decisions, **not** status logs (history belongs in the
retrospective).

## Keep CLAUDE.md distributed (manage the context budget)

- This root file loads **every session** — keep it lean: only cross-cutting,
  always-relevant rules.
- Add a **nested `CLAUDE.md` per area** (e.g. `collectors/`, `pipeline/`,
  `models/`, `tests/`) only when that area's conventions genuinely diverge.
  Nested files cost nothing until that subtree is read — don't create one per
  directory by default.
- Prefer nesting over `@import` for context economy. Update the nearest
  `CLAUDE.md` whenever a convention changes.

## Commit rules

- Commit/push only when asked.
- End commit messages with the `Co-Authored-By` trailer.
