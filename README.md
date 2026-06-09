# jd-refinery

A CLI data pipeline that collects, cleans, deduplicates, labels, validates, and
exports job descriptions into a structured corpus (schema v1.2) for fine-tuning
and CV-tailoring workflows.

> Stub — completed post-build per the documentation standard.

## Pipeline

```
collect → clean/dedupe → label (Claude Batch API) → validate → export
```

Each phase writes a durable JSONL checkpoint under `corpus/`. The pipeline is
invoked on demand and is resumable at any stage.

## Documentation

- [docs/SPEC_JD_REFINERY.md](docs/SPEC_JD_REFINERY.md) — architecture spec (design intent)
- [docs/CORPUS_FINDINGS.md](docs/CORPUS_FINDINGS.md) — locked schema v1.2, labelling rules, JD records
- [docs/PROJECT_ARCHITECTURE.md](docs/PROJECT_ARCHITECTURE.md) — implemented system (post-build)
- [docs/PROJECT_RETROSPECTIVE.md](docs/PROJECT_RETROSPECTIVE.md) — retrospective (post-build)
- [docs/PROJECT_LEARNINGS.md](docs/PROJECT_LEARNINGS.md) — reusable lessons (post-build)

## Running locally

```bash
cp .env.example .env   # add your ANTHROPIC_API_KEY
docker compose build
```

> Build status reflects Step 0 (scaffold). Pipeline commands are added per
> docs/SPEC_JD_REFINERY.md §5 Steps 1–9.
