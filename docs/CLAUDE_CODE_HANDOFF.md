# CLAUDE_CODE_HANDOFF.md — jd-refinery
## Setup Instructions + Initial Claude Code Prompt

---

## 1. Folder setup (do this before opening Claude Code)

```bash
# On your M720q home server
mkdir -p ~/dev/jd-refinery
cd ~/dev/jd-refinery

# Copy all documentation files into the repo root
# From this conversation's outputs:
cp SPEC_JD_REFINERY.md ~/dev/jd-refinery/PROJECT_SPEC.md
cp CORPUS_FINDINGS.md ~/dev/jd-refinery/CORPUS_FINDINGS.md
cp README.md ~/dev/jd-refinery/README.md
cp PROJECT_ARCHITECTURE.md ~/dev/jd-refinery/PROJECT_ARCHITECTURE.md
cp PROJECT_RETROSPECTIVE.md ~/dev/jd-refinery/PROJECT_RETROSPECTIVE.md
cp PROJECT_LEARNINGS.md ~/dev/jd-refinery/PROJECT_LEARNINGS.md
cp PROJECT_DOCUMENTATION_STANDARD.md ~/dev/jd-refinery/PROJECT_DOCUMENTATION_STANDARD.md

# Initialise git
git init
git add PROJECT_SPEC.md CORPUS_FINDINGS.md README.md \
        PROJECT_ARCHITECTURE.md PROJECT_RETROSPECTIVE.md \
        PROJECT_LEARNINGS.md PROJECT_DOCUMENTATION_STANDARD.md
git commit -m "docs: initial project documentation before build"

# Create GitHub repo (via GitHub CLI or manually)
gh repo create jd-refinery --private --source=. --push
# or: create repo on GitHub, then git remote add origin ...
```

**File checklist before starting Claude Code:**

- [ ] `PROJECT_SPEC.md` — architecture spec (renamed from SPEC_JD_REFINERY.md)
- [ ] `CORPUS_FINDINGS.md` — schema v1.2, labelling rules, 10 JD records
- [ ] `README.md` — landing page stub
- [ ] `PROJECT_ARCHITECTURE.md` — architecture stub
- [ ] `PROJECT_RETROSPECTIVE.md` — retrospective stub
- [ ] `PROJECT_LEARNINGS.md` — learnings stub
- [ ] `PROJECT_DOCUMENTATION_STANDARD.md` — documentation standard

---

## 2. Environment setup

```bash
# .env file (create manually, never commit)
ANTHROPIC_API_KEY=your_key_here
```

---

## 3. Initial Claude Code prompt

Copy this exactly into Claude Code to start the build:

---

```
You are helping build jd-refinery, a CLI data pipeline for collecting,
cleaning, labelling, and exporting job descriptions into a structured
corpus for fine-tuning and CV-tailoring workflows.

Read these files before writing any code:
- PROJECT_SPEC.md — full architecture spec, implementation steps, schema
- CORPUS_FINDINGS.md — schema v1.2 (locked), labelling rules, 10 JD records

We work through the implementation steps in PROJECT_SPEC.md §5 in order.
Do not skip steps. Do not move to the next step until the current one
passes its verification check.

Start with Step 0 — Project scaffold.

Step 0 requirements:
1. Create the full directory structure defined in PROJECT_SPEC.md §5 Step 0
2. Create all Python modules as empty files with a module docstring
3. Create company_seeds.yaml with the seed companies from PROJECT_SPEC.md §6
4. Create vc_boards.yaml with the 8 VC boards from PROJECT_SPEC.md §3.5,
   status: active for all, selectors: empty (to be populated manually)
5. Create Docker setup: python:3.13-slim, one service, bind-mount to /app
6. Create .env.example with ANTHROPIC_API_KEY placeholder
7. Create .gitignore: corpus/, .env, *.jsonl, __pycache__, .pytest_cache
8. Write the 10 Tier 1/2 JSONL records from CORPUS_FINDINGS.md §5 into
   corpus/manual/manual_20260606.jsonl exactly as written
9. Do not write any pipeline logic yet

Verify: docker compose build succeeds. Directory tree matches spec.
corpus/manual/manual_20260606.jsonl exists with 10 records.

After Step 0 passes verification, stop and wait for confirmation before
proceeding to Step 1.

Rules for this build:
- Read PROJECT_SPEC.md before each step — the spec is authoritative
- Schema version is 1.2 throughout — use CORPUS_FINDINGS.md §1.1 as the
  definitive schema definition
- Write tests for every module — pytest, placed in tests/
- No web UI, no database — JSONL files only
- Batch API only for labelling — no synchronous extraction calls
- Follow the diagram standard from PROJECT_DOCUMENTATION_STANDARD.md
  for any documentation updates (arrows only, no Mermaid)
```

---

## 4. Step-by-step confirmation protocol

After each step Claude Code completes:

1. Run the verification check from PROJECT_SPEC.md
2. Confirm it passes
3. Tell Claude Code: "Step N verified. Proceed to Step N+1."

If verification fails: "Step N failed — [describe what failed]. Fix before proceeding."

Never skip verification. Never confirm a step that hasn't passed.

---

## 5. Mid-build reference

If Claude Code loses context or starts a new session:

```
You are continuing the build of jd-refinery.
Read PROJECT_SPEC.md and CORPUS_FINDINGS.md to restore context.
We completed Steps [X] and are starting Step [Y].
The verification for Step [X] passed: [describe what was verified].
```

---

## 6. Post-build documentation prompt

When all 9 steps are complete and end-to-end verified:

```
The jd-refinery pipeline is complete and verified end-to-end.
Read PROJECT_SPEC.md, CORPUS_FINDINGS.md, PROJECT_DOCUMENTATION_STANDARD.md,
and all source files in the repository.

Update two documents in place:

1. README.md — complete all [Complete post-build] sections. Add actual
   key findings and lessons learned from the build. Update running locally
   instructions to reflect the actual commands.

2. PROJECT_ARCHITECTURE.md — complete all [Claude Code completes post-build]
   sections. Describe the system as implemented, not as planned. Note any
   deviations from PROJECT_SPEC.md and explain why. Follow the diagram
   standard throughout.

Do not modify PROJECT_SPEC.md — it is the historical planning document.
Do not modify CORPUS_FINDINGS.md — it is maintained separately.
```
