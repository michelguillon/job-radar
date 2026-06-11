# collectors/ — conventions (ATS API clients)

Each collector is a public-ATS JSON client: GET one endpoint, wrap each posting in
a Tier-4 `JDRecord` + a metadata sidecar (`CollectedJob`). Collectors **do not
extract or dedupe** — that is the labelling/pipeline step. Shared HTTP
(retry/backoff), record/meta builders, and the cursor filter live in `base.py`;
each collector is then just an endpoint URL + a field mapping.

## Hard rules

- **No extraction.** Every extraction/annotation field is left `None`; `raw_text`
  stays employer JD text only (title/location go to the sidecar, never `raw_text`).
- **Fail soft per company.** A 404 (unknown slug) or persistent 429 logs and
  returns `[]`, so a batch run continues past one bad company.
- **Uniform signature.** `fetch_company(slug, name, *, collected_at=None,
  updated_after=None, sleep=time.sleep)`. `sleep` is injected so tests exercise
  backoff without waiting; HTTP is mocked via `tests/fake_http.py` (no network).

## Encoding / shape gotchas (per source)

- **Greenhouse** `?content=true` returns the description **HTML-entity-escaped**
  (`&lt;p&gt;`) — `html.unescape()` before storing as `raw_html`. Exposes `title`
  + free-form `location.name`, but **no** workplace/country flag.
- **Lever** v0 returns a **bare JSON array** (not `{"jobs": [...]}`), with the JD
  **split** across `description` / `lists[].content` / `additional` — concatenate
  into one `raw_html`. Richest location signal (`workplaceType`, 2-letter `country`,
  `categories.allLocations`).
- **Ashby** returns `{"jobs": [...]}` with real HTML in `descriptionHtml`
  (preferred) or `descriptionPlain` fallback. `workplaceType`/`isRemote` are
  first-class; `country` comes from the postal address (full name).

## Company seeds — schema (`company_seeds.yaml`)

`cli.collect.load_companies` accepts **either** a bare top-level list (the v2
metadata format) **or** a `{companies: [...]}` mapping (v1.1) — both are valid.
Each entry is `{name, ats, slug}` plus optional **v2 metadata** (all default to
absent / a sensible value in consumers — existing seeds without them still work):

```yaml
- name: Writer
  ats: ashby                  # greenhouse | lever | ashby | manual
  slug: writer                # null for a manual watch entry
  domain: ai_application_platform   # company-level editorial classification
  fit_hypothesis: high        # high | medium | low | watch_only
  action: keep                # keep | promote | downgrade | pause | remove |
                              # investigate_ats | review_manually
  notes: "free text"
```

`domain`, `fit_hypothesis`, `action`, `notes` feed the **yield report**
(`cli.analyse --report yield`, `GET /api/report/yield`) — they are **not** scorer
input. `action` is **advisory in v1** (BACKLOG_YIELD_TRACKING §8): `pause` logs a
skip notice but still collects (auto-skip is a future enhancement);
`investigate_ats` is surfaced only in the yield report. `ats: manual` + `slug:
null` watch entries (e.g. Jack & Jill) are logged and skipped by `collect()` —
never an error.

## Incremental collection — capability matrix

The **public board APIs expose no server-side date filter** (Greenhouse's
`updated_after` is **Harvest API only**; Lever/Ashby boards take none). So
incremental collection is **client-side**: fetch the (single, cheap) full list and
keep only jobs at/after the cursor via `base.passes_cursor(job_ts, cutoff)`. The
real cost saved is **downstream Batch labelling** (≈O(new) records enter the paid
pipeline), not the one bulk GET.

| Source | `SUPPORTS_INCREMENTAL` | Timestamp field | Catches | Caveat |
|---|---|---|---|---|
| greenhouse | ✅ | `updated_at` | new **and** edited | — |
| ashby | ✅ | `publishedAt` | **new only** | no `updatedAt` on the public feed; edits reconciled by a periodic `--full` |
| lever | ❌ | *(none)* | — | v0 postings carry **no timestamp** → always full collection; relies on downstream dedupe |

Each collector module declares `SUPPORTS_INCREMENTAL` + `TIMESTAMP_FIELD`;
`collect.py` derives `INCREMENTAL_SOURCES` from those flags (never hand-maintained)
and only passes a cursor to incremental sources. **`passes_cursor` keeps any job
whose timestamp is missing/unparseable** — incremental collection must never
silently drop a posting; over-collecting is recovered by dedupe, under-collecting
is data loss. Cursor mechanics (per-source file, start-not-finish, `--full`,
advance rules) live in `collect.py` + `job_radar_SPEC §8`.

## Adding a collector

1. New `collectors/<ats>.py` with `API_TEMPLATE`, `SOURCE_ATS`, and
   `fetch_company(...)` (uniform signature) returning `list[CollectedJob]`.
2. Set `SUPPORTS_INCREMENTAL` + `TIMESTAMP_FIELD` from the API's real fields —
   verify against the **authoritative API docs**, not assumption (the board-vs-
   Harvest `updated_after` confusion is exactly this trap). If there's no usable
   timestamp, set `False` and document it in the matrix above.
3. Register the module in `collect.COLLECTOR_MODULES`; `COLLECTORS` +
   `INCREMENTAL_SOURCES` derive from it.
4. Add tests under `tests/test_<ats>.py` (mock HTTP via `fake_http`), including the
   incremental filter (or the no-op, for a non-incremental source).
