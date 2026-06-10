"""Claude Batch API labelling (job_radar_SPEC §5.3 Step 7).

Submits cleaned JD records to the Claude **Message Batches** API for schema-v1.2
extraction, polls to completion, downloads results, and merges the extracted
fields back onto the records. Batch API only — never synchronous (CLAUDE.md).

Pipeline:
    run_batch(records)      -> batch_id
    poll_batch(batch_id)    -> batch_id   (returns once processing_status == "ended")
    download_results(batch_id) -> list[dict]   ({custom_id, status, extraction|error, usage})
    merge_results(records, results, tier) -> (labelled, failures)

Notes / deviations from the spec text:
- The model is "claude-opus-4-8"; extraction is prompt-driven JSON (the spec asks
  for "JSON only, no preamble"), parsed and then validated downstream in Step 8.
- ``custom_id`` must match ``^[a-zA-Z0-9_-]{1,64}$`` — a record's ``sha256:…`` id
  has an illegal ``:`` and is too long, so we key requests by index ("rec-{i}")
  and map back by position in ``merge_results``.
- ``download_results`` takes the ``batch_id`` and uses the SDK's
  ``batches.results(batch_id)`` iterator rather than fetching the raw
  ``results_url`` by hand (the SDK injects auth and parses the JSONL for us).
"""

from __future__ import annotations

import json
import logging
import re
import time

from models.record import (
    COMPANY_SIZE_SIGNAL,
    COMPANY_STAGE,
    DELIVERY_MOTION,
    DOMAIN,
    REMOTE_POLICY,
    ROLE_TYPE,
    ROLE_TYPE_MAX,
    SENIORITY,
    TECHNICAL_DEPTH,
    _EXTRACTION_FIELDS,
    JDRecord,
)

log = logging.getLogger(__name__)

MODEL = "claude-opus-4-8"
MAX_TOKENS = 2048

# Batch API = 50% of standard pricing. Opus 4.8 standard: $5 / $25 per 1M in/out;
# cache read 0.1x input, cache write 1.25x input. Batch halves all of these.
COST_PER_MTOK = {
    "input": 2.50,
    "output": 12.50,
    "cache_read": 0.25,
    "cache_write": 3.125,
}

# Neutral annotation defaults applied to a freshly-labelled record so it is
# schema-valid and ready for human annotation. These are placeholders set by the
# pipeline, NOT judgements — Claude's JSON only ever fills extraction fields, so
# the "Claude never populates annotation" boundary (CLAUDE.md) is preserved.
ANNOTATION_DEFAULTS = {
    "fit_score": None,
    "applied": False,
    "application_date": None,
    "application_decision": "pending",
    "application_decision_notes": "",
    "location_workable": "unknown",
    "location_notes": "",
    "domain_distance": "not_assessed",
    "blocking_constraints": [],
    "notes": "",
}


def _sorted(values) -> list[str]:
    return sorted(values)


def build_system_prompt() -> str:
    """Build the extraction system prompt from the locked v1.2 enums.

    Generated from ``models.record`` so the prompt can never drift from the
    executable schema (CLAUDE.md: models/record.py is the source of truth).
    """
    enums = {
        "role_type": (ROLE_TYPE, f"list (max {ROLE_TYPE_MAX})"),
        "seniority": (SENIORITY, "one value"),
        "technical_depth": (TECHNICAL_DEPTH, "one value"),
        "domain": (DOMAIN, "list"),
        "remote_policy": (REMOTE_POLICY, "one value"),
        "delivery_motion": (DELIVERY_MOTION, "list"),
        "company_size_signal": (COMPANY_SIZE_SIGNAL, "one value"),
        "company_stage": (COMPANY_STAGE, "one value"),
    }
    lines = [
        "You extract structured fields from a job description (JD) using the locked",
        "schema v1.2. Output ONLY a single JSON object — no markdown, no preamble,",
        "no explanation. The object must have EXACTLY these keys:",
        "",
        "  " + ", ".join(_EXTRACTION_FIELDS),
        "",
        "Closed-vocabulary fields (use only these values):",
    ]
    for field, (allowed, card) in enums.items():
        lines.append(f"  {field} ({card}): {', '.join(_sorted(allowed))}")
    lines += [
        "",
        "Role and domain disambiguation (avoid over-tagging):",
        "  - Product Marketing, Growth Marketing, and Demand Generation roles are \"GTM\",",
        "    NOT \"Product\". \"Product\" role_type is reserved for roles whose primary",
        "    responsibility is product strategy, roadmap, and delivery.",
        "  - \"AI Delivery\" is for roles that architect, build, and deploy AI solutions in",
        "    production. Customer Success, Account Management, and post-sales roles are",
        "    NOT \"AI Delivery\".",
        "  - \"Enterprise Software\" is a specific domain for B2B software companies selling",
        "    to enterprises. Do NOT use it as a default when no other domain clearly",
        "    matches. If no vocabulary domain clearly applies, return an empty list []",
        "    rather than padding with \"Enterprise Software\".",
        "",
        "Free-form fields:",
        "  years_experience_required (string): e.g. '10+', '5-7', or 'not_stated'.",
        "  location (string): as stated, or 'not_stated'.",
        "  required_technologies, required_competencies, nice_to_have_technologies,",
        "    nice_to_have_competencies, leadership_geography, culture_signals (lists",
        "    of short strings drawn from the JD).",
        "  raw_observations (string): one or two sentences of notable extraction notes.",
        "",
        "Ambiguity handling:",
        "  - Seniority ambiguous -> choose the MORE senior level, note it in raw_observations.",
        "  - Required vs nice-to-have unclear -> required only if the JD uses",
        "    must/essential/required language; otherwise nice-to-have.",
        "  - remote_policy not stated -> 'not_stated'. Never infer.",
        "  - company_stage not in the JD -> 'not_stated'. Never infer from the company name.",
        "  - location: if the JD body explicitly states a different work city plus",
        "    onsite days than the title (e.g. title says one city, body says the role",
        "    is based at an HQ in another city N days/week), extract the BODY work",
        "    location, not the title's. The real work location wins.",
        "  - A list field with nothing to extract -> [].",
        "",
        "ATS metadata block:",
        "  - The user message may begin with an [ATS METADATA] block — the structured",
        "    title and location the job board reported. Use it as authoritative context",
        "    for the role title and work location (it is cleaner than the body), but",
        "    still extract every field from the JOB DESCRIPTION that follows.",
        "",
        "Worked examples (JD excerpt -> JSON):",
        "",
    ]
    for ex in _FEWSHOT:
        lines.append("JD: " + ex["jd"])
        lines.append("JSON: " + json.dumps(ex["extraction"], ensure_ascii=False))
        lines.append("")
    return "\n".join(lines)


# Three Tier-1 worked examples (Airwallex, Mistral, Databricks) — abbreviated JD
# text plus the human-structured extraction from corpus/manual.
_FEWSHOT = [
    {
        "jd": (
            "Director, Solutions Engineering at Airwallex (London). Lead and scale the EMEA "
            "Solutions Engineering org: executive pre-sales technical solution design, E2E "
            "implementation, GTM strategy. 10+ years client-facing, 3+ in senior leadership. "
            "Payments/fintech knowledge advantageous. STEM degree preferred. Based in London (hybrid)."
        ),
        "extraction": {
            "role_type": ["Solutions Engineering"],
            "seniority": "director",
            "technical_depth": "hybrid",
            "years_experience_required": "10+",
            "required_technologies": ["API platform solutioning"],
            "required_competencies": [
                "pre-sales team leadership",
                "enterprise sales cycle management",
                "GTM strategy ownership",
                "executive communication",
                "solution design and architecture",
            ],
            "nice_to_have_technologies": ["payments ecosystem knowledge"],
            "nice_to_have_competencies": ["STEM background", "financial services domain experience"],
            "domain": ["FinTech", "Payments"],
            "remote_policy": "hybrid",
            "location": "London",
            "delivery_motion": ["pre_sales", "direct_delivery"],
            "leadership_geography": ["EMEA"],
            "company_size_signal": "scale_up",
            "company_stage": "pre_ipo",
            "culture_signals": ["founder-like energy", "show not tell", "builder mentality"],
            "raw_observations": "Covers pre-sales AND post-sales implementation; competency-driven with minimal hard tech requirements.",
        },
    },
    {
        "jd": (
            "AI Deployment Strategist at Mistral AI (London, onsite). Work with enterprise "
            "customers to architect end-to-end AI solutions with Mistral models, own pilots to "
            "production, facilitate executive workshops. 2+ years client-facing strategic/technical "
            "role; hands-on Python AI app building; C-level influence. MEDDPICC a plus."
        ),
        "extraction": {
            "role_type": ["Solutions Consulting", "Pre-Sales", "AI Delivery"],
            "seniority": "senior_ic",
            "technical_depth": "hands_on",
            "years_experience_required": "2+",
            "required_technologies": ["Python", "AI/ML frameworks", "LLM APIs"],
            "required_competencies": [
                "executive workshop facilitation",
                "AI adoption roadmap design",
                "end-to-end AI solution architecture",
                "pilot project ownership",
                "C-level communication and influence",
            ],
            "nice_to_have_technologies": [],
            "nice_to_have_competencies": ["MEDDPICC or value-based selling"],
            "domain": ["AI Platform", "Enterprise Software"],
            "remote_policy": "onsite",
            "location": "London",
            "delivery_motion": ["pre_sales", "direct_delivery"],
            "leadership_geography": [],
            "company_size_signal": "startup",
            "company_stage": "not_stated",
            "culture_signals": ["trusted advisor", "art of the possible"],
            "raw_observations": "Experience bar (2+ yrs) low relative to role complexity; only example with explicit onsite requirement.",
        },
    },
    {
        "jd": (
            "Lead Solutions Architect, Strategic Customers at Databricks (London, hybrid). Drive "
            "Data & AI transformation for the largest UKI enterprise customers at executive level; "
            "mentor the SA practice. Deep Python/SQL/Apache Spark/Databricks plus AWS/Azure/GCP. "
            "Enterprise architecture, commercial awareness, thought leadership. ~20-30% travel."
        ),
        "extraction": {
            "role_type": ["Solutions Architecture", "Pre-Sales"],
            "seniority": "lead",
            "technical_depth": "hands_on",
            "years_experience_required": "not_stated",
            "required_technologies": ["Python", "SQL", "Apache Spark", "Databricks platform", "AWS", "Azure", "GCP"],
            "required_competencies": [
                "enterprise architecture and technology strategy",
                "executive engagement and advisory",
                "commercial awareness and sales cycle understanding",
                "cross-functional team orchestration",
            ],
            "nice_to_have_technologies": [],
            "nice_to_have_competencies": [],
            "domain": ["AI Platform", "Data & Analytics"],
            "remote_policy": "hybrid",
            "location": "London",
            "delivery_motion": ["pre_sales"],
            "leadership_geography": [],
            "company_size_signal": "enterprise",
            "company_stage": "not_stated",
            "culture_signals": ["show not tell", "builder culture", "high velocity and growth"],
            "raw_observations": "Most technology-heavy JD; flat requirements list (no nice-to-have) signals a high bar.",
        },
    },
]


def _client():
    import anthropic

    return anthropic.Anthropic()


def _custom_id(i: int) -> str:
    return f"rec-{i}"


def _index_of(custom_id: str) -> int:
    return int(custom_id.split("-", 1)[1])


# Sidecar fields surfaced to the labeller as authoritative context (the structured
# title/location the JD body doesn't reliably state). Passed as a separate block —
# never injected into raw_text (which stays employer JD text only).
_META_CONTEXT_FIELDS = ("title", "location_str", "workplace_type", "country")


def build_user_content(record: JDRecord, meta: dict | None = None) -> str:
    """User message: an optional [ATS METADATA] context block, then the JD.

    The metadata block is the sidecar (pipeline.prefilter / collectors), passed as
    separate context per the Phase-3 decision — not merged into raw_text.
    """
    jd = record.raw_text or ""
    if not meta:
        return jd
    lines = [f"{f}: {meta[f]}" for f in _META_CONTEXT_FIELDS if meta.get(f)]
    if not lines:
        return jd
    return "[ATS METADATA]\n" + "\n".join(lines) + "\n\n[JOB DESCRIPTION]\n" + jd


def run_batch(
    records: list[JDRecord],
    *,
    client=None,
    model: str = MODEL,
    meta_index: dict[str, dict] | None = None,
) -> str:
    """Submit a batch of extraction requests; return the batch id.

    Each request is keyed ``rec-{i}`` by the record's position. The shared system
    prompt is marked for prompt caching so it is billed once across the batch.
    ``meta_index`` (by ``source_url``) supplies the per-record ATS metadata block.
    """
    from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
    from anthropic.types.messages.batch_create_params import Request

    client = client or _client()
    meta_index = meta_index or {}
    system = [{"type": "text", "text": build_system_prompt(), "cache_control": {"type": "ephemeral"}}]
    requests = [
        Request(
            custom_id=_custom_id(i),
            params=MessageCreateParamsNonStreaming(
                model=model,
                max_tokens=MAX_TOKENS,
                system=system,
                thinking={"type": "disabled"},
                messages=[{"role": "user", "content": build_user_content(r, meta_index.get(r.source_url))}],
            ),
        )
        for i, r in enumerate(records)
    ]
    batch = client.messages.batches.create(requests=requests)
    log.info("label: submitted batch %s (%d requests)", batch.id, len(requests))
    return batch.id


def poll_batch(batch_id: str, *, client=None, sleep=time.sleep, interval: int = 30, max_wait: int = 24 * 3600) -> str:
    """Poll until the batch's ``processing_status`` is ``ended``; return the id."""
    client = client or _client()
    waited = 0
    while True:
        batch = client.messages.batches.retrieve(batch_id)
        if batch.processing_status == "ended":
            log.info("label: batch %s ended", batch_id)
            return batch_id
        if waited >= max_wait:
            raise TimeoutError(f"batch {batch_id} not ended after {max_wait}s")
        log.info("label: batch %s status=%s — waiting %ds", batch_id, batch.processing_status, interval)
        sleep(interval)
        waited += interval


def download_results(batch_id: str, *, client=None) -> list[dict]:
    """Return one dict per result: ``{custom_id, status, extraction|error, usage}``."""
    client = client or _client()
    out: list[dict] = []
    for result in client.messages.batches.results(batch_id):
        entry: dict = {"custom_id": result.custom_id, "status": result.result.type}
        if result.result.type == "succeeded":
            msg = result.result.message
            text = next((b.text for b in msg.content if b.type == "text"), "")
            entry["raw_text"] = text
            usage = msg.usage
            entry["usage"] = {
                "input": getattr(usage, "input_tokens", 0) or 0,
                "output": getattr(usage, "output_tokens", 0) or 0,
                "cache_read": getattr(usage, "cache_read_input_tokens", 0) or 0,
                "cache_write": getattr(usage, "cache_creation_input_tokens", 0) or 0,
            }
        else:
            err = result.result.error if result.result.type == "errored" else None
            entry["error"] = str(getattr(err, "type", result.result.type))
        out.append(entry)
    return out


_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


def parse_extraction(text: str) -> dict:
    """Parse the model's JSON object out of ``text`` (tolerates stray prose)."""
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = _JSON_RE.search(text)
        if not m:
            raise
        return json.loads(m.group(0))


def merge_results(
    records: list[JDRecord], results: list[dict], *, tier: int
) -> tuple[list[JDRecord], list[dict]]:
    """Apply extracted fields onto records (setting ``tier``); collect failures.

    Returns ``(labelled_records, failures)``. A failure is recorded for an errored
    request, a missing/unparseable JSON body, or a missing extraction key.
    """
    labelled: list[JDRecord] = []
    failures: list[dict] = []
    for entry in results:
        idx = _index_of(entry["custom_id"])
        record = records[idx]
        if entry["status"] != "succeeded":
            failures.append({"custom_id": entry["custom_id"], "company": record.company, "error": entry.get("error", entry["status"])})
            continue
        try:
            extraction = parse_extraction(entry.get("raw_text", ""))
            for field in _EXTRACTION_FIELDS:
                setattr(record, field, extraction[field])
        except (json.JSONDecodeError, KeyError) as exc:
            failures.append({"custom_id": entry["custom_id"], "company": record.company, "error": f"parse: {exc}"})
            continue
        record.tier = tier
        # Seed neutral annotation defaults so the record is schema-valid and
        # ready for human annotation (Claude itself never sets these).
        for field, default in ANNOTATION_DEFAULTS.items():
            if getattr(record, field) is None:
                setattr(record, field, default)
        labelled.append(record)
    return labelled, failures


def estimate_cost(results: list[dict]) -> dict:
    """Sum token usage across succeeded results and apply batch (50%) rates."""
    totals = {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0}
    for entry in results:
        for k, v in entry.get("usage", {}).items():
            totals[k] = totals.get(k, 0) + v
    cost = sum(totals[k] * COST_PER_MTOK[k] for k in totals) / 1_000_000
    return {"model": MODEL, "tokens": totals, "cost_usd": round(cost, 6)}
