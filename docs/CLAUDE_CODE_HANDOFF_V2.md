# CLAUDE_CODE_HANDOFF.md — job-radar
## Setup, Rename, and Continuation Instructions

**Version:** 2 (updated for Job Radar respec)
**Previous project name:** jd-refinery
**New project name:** job-radar
**Build state:** Steps 0–2 complete, 42 tests passing

---

## 1. Rename checklist (do before opening Claude Code)

The directory rename from `jd-refinery` to `job-radar` requires manual
steps. Claude Code cannot do this safely.

```bash
# 1. Rename the directory
mv ~/dev/jd-refinery ~/dev/job-radar

# 2. CRITICAL — copy Claude memory before it's lost
# The memory dir is keyed to the old path and will NOT follow the rename
cp -r "~/.claude/projects/c--Users-miche-OneDrive-dev-jd-refinery/" \
      "~/.claude/projects/c--Users-miche-OneDrive-dev-job-radar/"
# Adjust path separators for your OS if needed

# 3. Rename GitHub repo (if already pushed)
cd ~/dev/job-radar
gh repo rename job-radar
# or rename manually on GitHub → Settings → Repository name

# 4. Update git remote if needed
git remote set-url origin https://github.com/michelguillon/job-radar
```

**Files that need manual string replacement after rename:**

| File | String to find | Replace with |
|---|---|---|
| `docker-compose.yml` | `jd-refinery` | `job-radar` |
| `CLAUDE.md` | `jd-refinery` | `job-radar` |
| `docs/README.md` | `jd-refinery` | `job-radar` |

---

## 2. Replace documentation files

Copy these files from this handoff into `~/dev/job-radar/docs/`:

| Source file | Destination |
|---|---|
| `SPEC_JOB_RADAR.md` | `docs/SPEC_JOB_RADAR.md` (replaces nothing — new file) |
| `README_JOBRADAR.md` | `docs/job_radar_README.md` |
| `CORPUS_FINDINGS.md` | `docs/CORPUS_FINDINGS.md` (updated) |
| `job_radar_ARCHITECTURE.html` | `docs/job_radar_ARCHITECTURE.html` (updated) |
| `CLAUDE_MD_JOBRADAR.md` | `CLAUDE.md` (root — replaces existing) |

Delete from `docs/`: `SPEC_JD_REFINERY.md`, `CLAUDE_CODE_HANDOFF.md`

---

## 3. Verification before starting Claude Code

```bash
cd ~/dev/job-radar
docker compose run --rm job-radar python -m pytest -q
# Must show: 42 passed
```

If tests fail after the rename, check `docker-compose.yml` service name
was updated and `conftest.py` paths are still correct.

---

## 4. Initial Claude Code prompt (continuation from Step 3)

```
You are continuing the build of job-radar (formerly jd-refinery).

Context:
- Steps 0–2 are complete. 42 tests pass. Do not re-implement.
- The project has been renamed from jd-refinery to job-radar.
- The spec has been updated. Read docs/SPEC_JOB_RADAR.md before anything.
- The schema is v1.2, locked. Defined in models/record.py (executable
  source of truth) and docs/CORPUS_FINDINGS.md §1.1 (must stay in sync).

Before writing any code:
1. Read docs/SPEC_JOB_RADAR.md in full
2. Read CLAUDE.md for build conventions
3. Read docs/CORPUS_FINDINGS.md §1.1 for the locked schema

Start with Step 3 — Greenhouse collector — defined in
docs/SPEC_JOB_RADAR.md §5.3 Step 3.

Also run the Step 2 backfill as part of Step 3:
- Read raw JD texts from corpus/manual/JD_SOURCE_TEXTS.md
- Populate raw_text fields in corpus/manual/manual_20260606.jsonl
- Run clean() → record_hash() on each
- Replace all sha256:pending ids with real hashes
- Verify no two records have the same hash

Rules:
- Docker only for build/run/test
- Schema v1.2 locked — no changes without explicit instruction
- Batch API only for labelling
- BeautifulSoup only for scraping
- No web UI, no database — JSONL files only
- Tests for every new module
- Record learnings in CLAUDE.md as you go
- Stop after each step and wait for verification confirmation
```

---

## 5. Step confirmation protocol

After each step completes:

1. Run the verification check from `docs/SPEC_JOB_RADAR.md §5.3`
2. Confirm it passes
3. Tell Claude Code: **"Step N verified. Proceed to Step N+1."**

If it fails: **"Step N failed — [describe failure]. Fix before proceeding."**

Never skip verification. Never confirm a step that hasn't passed.

---

## 6. Context restoration prompt (new sessions)

```
You are continuing the build of job-radar.
Read docs/SPEC_JOB_RADAR.md and CLAUDE.md to restore context.
Steps completed so far: [list them]
Current step: Step [N]
Last verification passed: [describe what passed]
```

---

## 7. Phase 2 start prompt (after Phase 1 complete)

```
Phase 1 of job-radar is complete and verified end-to-end.
Read docs/SPEC_JOB_RADAR.md §6 — Phase 2 Scoring Engine.
Read docs/CORPUS_FINDINGS.md §1.1 for the current schema.

Phase 2 adds:
1. candidate_profile.yaml — candidate definition
2. models/record.py additions — JobPosting and ApplicationRecord dataclasses
3. scoring/scorer.py — rule-based scoring engine
4. scoring/profile.py — candidate profile loader
5. score.py — CLI entry point

Start by creating candidate_profile.yaml. Ask me to review it before
building the scorer. The profile must reflect my actual background —
do not invent content.
```

---

## 8. Post-Phase-1 documentation prompt

```
Phase 1 of job-radar is complete and verified end-to-end.
Read docs/SPEC_JOB_RADAR.md, docs/CORPUS_FINDINGS.md,
PROJECT_DOCUMENTATION_STANDARD.md, and all source files.

Update two documents in place:
1. docs/README.md — complete all stub sections with actual findings
2. docs/PROJECT_ARCHITECTURE.md — complete all stub sections with
   implemented system details. Note any deviations from SPEC_JOB_RADAR.md.

Follow the arrows-only diagram standard from PROJECT_DOCUMENTATION_STANDARD.md.
Do not modify SPEC_JOB_RADAR.md or CORPUS_FINDINGS.md.
```
