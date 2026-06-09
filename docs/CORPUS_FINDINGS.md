# CORPUS_FINDINGS.md — job-radar
## Corpus Schema, Labelling Rules, and JD Records

**Project:** job-radar (Project 4)  
**Schema version:** 1.3 (project) — `JDRecord` envelope frozen at 1.2 (not migrated)  
**Last updated:** 2026-06-09  
**Records:** 10 (Tier 1: 6, Tier 2: 4)  
**Status:** Tier 1 complete ✅ — Tier 2 in progress; Phase 2 `ApplicationRecord` added (§1.4)

---

## 1. Locked Schema v1.2

### 1.1 — Extraction schema

```python
SCHEMA_VERSION = "1.2"

@dataclass
class JDRecord:
    # --- Identity ---
    id: str                      # SHA-256 of normalised text
    source_url: str
    source_ats: str              # "greenhouse"|"lever"|"ashby"|"vc_board"|"manual"
    company: str
    collected_at: str            # ISO datetime
    tier: int                    # 1 / 2 / 3 / 4

    # --- Raw content ---
    raw_html: str | None
    raw_text: str

    # --- Extraction schema (Claude-populated Tier 3+, human-structured Tier 1-2) ---

    role_type: list[str]         # max 3 values
                                 # "Solutions Engineering" | "Solutions Consulting" |
                                 # "Solutions Architecture" | "AI Delivery" |
                                 # "Delivery Leadership" | "Pre-Sales" |
                                 # "Strategic Pursuits" | "Partner SA" |
                                 # "Product" | "GTM"

    seniority: str               # "ic" | "senior_ic" | "lead" | "manager" |
                                 # "director" | "vp" | "exec"
                                 # "lead" = player-coach, hands-on + team leadership

    technical_depth: str         # "hands_on" | "hybrid" | "leadership"

    years_experience_required: str  # e.g. "10+" | "5+" | "2+" | "not_stated"
                                    # never inferred — only extracted if explicit

    required_technologies: list[str]
    required_competencies: list[str]
    nice_to_have_technologies: list[str]
    nice_to_have_competencies: list[str]

    domain: list[str]            # "AI Platform" | "AI/ML" | "Data & Analytics" |
                                 # "FinTech" | "Payments" | "Financial Services" |
                                 # "Product Design" | "SaaS" | "Enterprise Software" |
                                 # "Consulting" | "AdTech" | "Infrastructure" |
                                 # "Developer Tools" | "Customer Experience" |
                                 # "Revenue Technology"

    remote_policy: str           # "remote" | "hybrid" | "onsite" | "not_stated"
                                 # "based in [city]" with no further detail = "hybrid"

    location: str                # verbatim from JD — e.g. "London" | "New York" |
                                 # "remote / global" | "not_stated"
                                 # never normalised or inferred

    delivery_motion: list[str]   # "pre_sales" | "direct_delivery" | "partner_delivery" |
                                 # "partner_enablement" | "customer_success" |
                                 # "professional_services"

    leadership_geography: list[str]  # e.g. ["EMEA"] | ["EMEA", "APAC", "LATAM"] |
                                     # ["Global"] | []
                                     # empty list for IC roles or scope not stated

    company_size_signal: str     # "startup" | "scale_up" | "enterprise" | "not_stated"

    company_stage: str           # "seed" | "series_a" | "series_b" | "series_c_plus" |
                                 # "pre_ipo" | "listed" | "not_stated"
                                 # only when explicitly stated or unambiguously inferable

    culture_signals: list[str]   # verbatim phrases, no interpretation

    raw_observations: str        # free text — anything schema doesn't capture

    # --- Annotation schema (human-only, never extraction targets) ---
    fit_score: int | None        # 1–10 integer; None if not reviewed
    applied: bool
    application_date: str | None
    application_decision: str    # "applied" | "want_to_apply" | "pending" |
                                 # "not_applied_fit" | "not_applied_structural" |
                                 # "not_applied_timing"
                                 # want_to_apply = strong intent, not yet submitted
    application_decision_notes: str
    location_workable: str       # "yes" | "no" | "conditional" | "unknown"
    location_notes: str
    domain_distance: str         # "low" | "medium" | "high" | "not_assessed"
                                 # gap between Michel's domain background and JD domain
    blocking_constraints: list[str]
    notes: str
```

### 1.2 — Schema version history

| Version | Changes | Triggered by |
|---|---|---|
| 1.0 | Seed schema | Initial spec |
| 1.1 | Split required_skills → 4 fields; add company_stage, culture_signals, application_decision, location, location_workable, location_notes, blocking_constraints; seniority "lead" added; role_type → list[str]; fit_score → 1–10; "AI Platform" domain added | Tier 1 (6 JDs) |
| 1.2 | Add delivery_motion, leadership_geography, domain_distance; application_decision "want_to_apply" added; "Customer Experience" and "Revenue Technology" domain values added | Tier 2 (4 JDs) |
| 1.3 | Add `ApplicationRecord` record type (Phase 2 scoring output, §1.4) with `FIT_LABEL`/`APPLICATION_STATUS` enums. `JDRecord` schema **unchanged** — its on-disk envelope stays tagged `1.2` (Option A: not migrated). The `1.3` tag applies to `ApplicationRecord` only. | Phase 2 (Option A) |

---

### 1.4 — ApplicationRecord (Phase 2 scoring output, v1.3)

Personal-assessment / workflow-state layer. Produced by `scoring/scorer.py`
(one per `JDRecord`), written to `corpus/scored/scored_{ts}.jsonl`. Single-owner
record — serialises as a **flat** envelope (no extraction/annotation grouping).
The scorer reads `JDRecord` *extraction* fields only; it never reads or writes
`JDRecord`'s legacy annotation stub (Option A, `docs/job_radar_PHASE2_PLAN.md`).

```python
@dataclass
class ApplicationRecord:
    job_id: str               # links to JDRecord.id
    profile_version: str      # candidate_profile.yaml profile_version used
    scored_at: str            # ISO datetime the score was produced
    fit_score: int            # 1–10 (Stage 1 structural fit)
    fit_label: str            # "strong_fit" | "good_fit" | "stretch" |
                              # "blocked_fit" | "interview_practice" | "income_bridge"
    fit_label_reason: str     # one sentence, shown in UI
    requirement_gaps: list[str]
    blocking_constraints: list[str]
    priority_score: int       # 1–10 (fit + urgency adjustments)
    application_status: str   # "new" | "review" | "shortlisted" | "applied" |
                              # "interviewing" | "offer" | "rejected" | "archived"
                              # scorer always emits "new"
    notes: str                # free-form, "" from scorer
```

`validate_application_record()` mirrors `validate()`: enum checks on
`fit_label`/`application_status`, 1–10 range on `fit_score`/`priority_score`,
list-of-str on `requirement_gaps`/`blocking_constraints`, and
`schema_version == "1.3"`.

---

## 2. Labelling Rules

| Rule | Definition |
|---|---|
| Remote policy default | `"based in [city]"` with no further qualification = `"hybrid"`. Only `"onsite"` if explicitly stated. |
| Location extraction | Extract verbatim. Never normalise. `"not_stated"` when absent. Never infer from company HQ knowledge. |
| Location workable | `"yes"` = London or remote. `"no"` = relocation outside commutable range. `"conditional"` = nearby city hybrid workable if expenses covered. `"unknown"` = not stated. |
| Years not stated | Never infer from context. `"not_stated"` if not explicit. Qualitative signal goes in `raw_observations`. |
| No external knowledge | Extract only what the JD states. No company policy knowledge imported into extraction fields. |
| Technology vs competency | Tool/system = technology. Behaviour/capability = competency. "Collaborating with X" is a competency. |
| Proprietary platforms | Extract as stated, note in `raw_observations` that platform is proprietary. |
| company_stage | Explicit or unambiguously inferable only. Never from company name alone. Default `"not_stated"`. |
| Sparse culture signals | Do not pad. A short list is a valid signal. |
| role_type pairing | `"Solutions Consulting"` paired with `"Pre-Sales"` or `"AI Delivery"` where motion is clear. |
| Nice-to-have | Only populate if JD explicitly signals optionality. Never infer from context. |
| Contamination rule | Claude extraction on Tier 1 JDs runs only after human labels saved. |
| delivery_motion | Reflects how the role delivers value, not what function it performs. Can co-exist: `["pre_sales", "direct_delivery"]` for roles spanning both. |
| leadership_geography | Empty list `[]` for IC roles. Populate only when scope is explicitly stated or clearly implied by role title (e.g. "EMEA Director"). |

---

## 3. Schema Observations (Deferred)

Fields observed but not yet promoted. Promote when pattern appears in 3+ JDs.

| Field | Observed in | Current count | Notes |
|---|---|---|---|
| `deal_motion` | Zendesk, Outreach | 2 | `"enterprise_pursuit"`, `"proof_of_value"`, `"strategic_accounts"`. Promote if appears in 1 more Tier 2 JD. |

---

## 4. Corpus Summary Table

| # | Company | Role | Seniority | Tech Depth | Fit | Decision | Tier |
|---|---|---|---|---|---|---|---|
| 1 | Airwallex | Director, SE | director | hybrid | 7 | applied | 1 |
| 2 | JP Morgan Chase | SE Lead | lead | hands_on | 5 | applied | 1 |
| 3 | AI Consultancy | Principal SD | director | hybrid | 4 | not_applied_fit | 1 |
| 4 | Figma | Director, SC | director | leadership | 7 | applied | 1 |
| 5 | Mistral AI | AI Deployment Strategist | senior_ic | hands_on | 7 | applied | 1 |
| 6 | Databricks | Lead SA | lead | hands_on | 5 | not_applied_structural | 1 |
| 7 | Writer | SA Manager | manager | hybrid | 8 | want_to_apply | 2 |
| 8 | Zendesk | Strategic Pursuits Lead | senior_ic | hybrid | 4 | not_applied_structural | 2 |
| 9 | Outreach | Lead SC | lead | hybrid | 5 | not_applied_fit | 2 |
| 10 | Fin (Intercom) | Senior AI Deployment Consultant | senior_ic | hybrid | 8 | want_to_apply | 2 |

---

## 5. JSONL Records

---

### Record 1 — Airwallex

```json
{
  "schema_version": "1.2",
  "id": "sha256:pending",
  "source_url": "unknown",
  "source_ats": "manual",
  "company": "Airwallex",
  "collected_at": "2026-06-06",
  "tier": 1,
  "raw_html": null,
  "raw_text": "stored separately",
  "extraction": {
    "role_type": ["Solutions Engineering"],
    "seniority": "director",
    "technical_depth": "hybrid",
    "years_experience_required": "10+",
    "required_technologies": [
      "API platform solutioning"
    ],
    "required_competencies": [
      "pre-sales team leadership",
      "enterprise sales cycle management",
      "GTM strategy ownership",
      "executive communication",
      "solution design and architecture",
      "RFP and POC delivery",
      "EMEA multi-regional management"
    ],
    "nice_to_have_technologies": [
      "payments ecosystem knowledge",
      "fintech platforms"
    ],
    "nice_to_have_competencies": [
      "STEM background",
      "financial services domain experience"
    ],
    "domain": ["FinTech", "Payments"],
    "remote_policy": "hybrid",
    "location": "London",
    "delivery_motion": ["pre_sales", "direct_delivery"],
    "leadership_geography": ["EMEA"],
    "company_size_signal": "scale_up",
    "company_stage": "pre_ipo",
    "culture_signals": [
      "founder-like energy",
      "real impact",
      "accelerated learning",
      "true ownership",
      "move fast with good judgment",
      "show not tell",
      "builder mentality"
    ],
    "raw_observations": "Role covers pre-sales AND post-sales implementation — broader than typical SE director. Required technologies almost absent — purely competency-driven role."
  },
  "annotation": {
    "fit_score": 7,
    "applied": true,
    "application_date": "2026-06-06",
    "application_decision": "applied",
    "application_decision_notes": "",
    "location_workable": "yes",
    "location_notes": "London hybrid — no issue",
    "domain_distance": "low",
    "blocking_constraints": [],
    "notes": "Strong fit on leadership and GTM scope. EMEA SE director maps directly to Xandr SC org experience. Fintech domain adjacent not native. Technical depth bar manageable — credibility over hands-on."
  }
}
```

---

### Record 2 — JP Morgan Chase

```json
{
  "schema_version": "1.2",
  "id": "sha256:pending",
  "source_url": "unknown",
  "source_ats": "manual",
  "company": "JP Morgan Chase",
  "collected_at": "2026-06-06",
  "tier": 1,
  "raw_html": null,
  "raw_text": "stored separately",
  "extraction": {
    "role_type": ["Solutions Engineering", "AI Delivery"],
    "seniority": "lead",
    "technical_depth": "hands_on",
    "years_experience_required": "not_stated",
    "required_technologies": [
      "cloud-based AI technologies",
      "AI/ML solutions delivery"
    ],
    "required_competencies": [
      "team leadership and mentoring",
      "client collaboration on AI goals",
      "solution architecture for scale and reliability",
      "data scientist and engineer collaboration",
      "cross-functional collaboration across product and engineering",
      "AI delivery best practices",
      "platform adoption advocacy"
    ],
    "nice_to_have_technologies": [
      "Fusion platform or equivalent enterprise AI platform",
      "cloud-native architectures in financial services"
    ],
    "nice_to_have_competencies": [
      "driving platform adoption through technical enablement",
      "mentoring and developing engineering talent",
      "delivering innovative AI solutions at scale"
    ],
    "domain": ["Financial Services", "AI/ML"],
    "remote_policy": "not_stated",
    "location": "not_stated",
    "delivery_motion": ["direct_delivery"],
    "leadership_geography": [],
    "company_size_signal": "enterprise",
    "company_stage": "listed",
    "culture_signals": [
      "champion best practices",
      "foster strong collaboration",
      "passion for mentoring and developing engineering talent"
    ],
    "raw_observations": "Extremely sparse JD — no location, no years, minimal tech stack. Fusion is a proprietary internal JPMC AI platform, not a market product. Low-information JDs will be a consistent challenge for automated extraction."
  },
  "annotation": {
    "fit_score": 5,
    "applied": true,
    "application_date": "2026-06-06",
    "application_decision": "applied",
    "application_decision_notes": "",
    "location_workable": "unknown",
    "location_notes": "No location stated — assumed London/hybrid given JPMC UK presence but not confirmed",
    "domain_distance": "medium",
    "blocking_constraints": [],
    "notes": ""
  }
}
```

---

### Record 3 — AI Consultancy

```json
{
  "schema_version": "1.2",
  "id": "sha256:pending",
  "source_url": "unknown",
  "source_ats": "manual",
  "company": "AI Consultancy",
  "collected_at": "2026-06-06",
  "tier": 1,
  "raw_html": null,
  "raw_text": "stored separately",
  "extraction": {
    "role_type": ["Delivery Leadership", "AI Delivery"],
    "seniority": "director",
    "technical_depth": "hybrid",
    "years_experience_required": "not_stated",
    "required_technologies": [
      "Python",
      "JavaScript",
      "Azure",
      "AWS"
    ],
    "required_competencies": [
      "multi-project delivery leadership",
      "client stakeholder management",
      "business-technical translation",
      "SOW preparation and ownership",
      "executive communication and presentation",
      "workshop design and facilitation",
      "cross-functional team alignment",
      "product ownership for client deliverables",
      "risk identification and escalation"
    ],
    "nice_to_have_technologies": [],
    "nice_to_have_competencies": [
      "regulated industry experience",
      "compliance and audit navigation",
      "governance and quality control delivery"
    ],
    "domain": ["AI/ML", "Consulting"],
    "remote_policy": "remote",
    "location": "Remote",
    "delivery_motion": ["direct_delivery"],
    "leadership_geography": [],
    "company_size_signal": "not_stated",
    "company_stage": "not_stated",
    "culture_signals": [
      "lead from the front",
      "real, tangible progress for clients",
      "not a behind-the-scenes role",
      "challenge assumptions constructively",
      "without micromanaging solutions"
    ],
    "raw_observations": "No years stated. Seniority and scope imply 10+ but not extractable. Technologies listed as background credentials not active role requirements — role is delivery leadership not technical delivery."
  },
  "annotation": {
    "fit_score": 4,
    "applied": false,
    "application_date": null,
    "application_decision": "not_applied_fit",
    "application_decision_notes": "Fit score below threshold. Pure delivery leadership without enough AI platform angle.",
    "location_workable": "yes",
    "location_notes": "Remote — no location issue",
    "domain_distance": "low",
    "blocking_constraints": [],
    "notes": ""
  }
}
```

---

### Record 4 — Figma

```json
{
  "schema_version": "1.2",
  "id": "sha256:pending",
  "source_url": "unknown",
  "source_ats": "manual",
  "company": "Figma",
  "collected_at": "2026-06-06",
  "tier": 1,
  "raw_html": null,
  "raw_text": "stored separately",
  "extraction": {
    "role_type": ["Solutions Consulting", "Pre-Sales"],
    "seniority": "director",
    "technical_depth": "leadership",
    "years_experience_required": "10+",
    "required_technologies": [],
    "required_competencies": [
      "SC or SE team leadership across multiple countries",
      "partnering with sales leadership on GTM strategy",
      "performance management and data-driven processes",
      "executive engagement and relationship building",
      "recruiting and developing SC leadership",
      "cross-functional influence across product and engineering",
      "SC process development and scaling"
    ],
    "nice_to_have_technologies": [
      "Figma platform",
      "design tooling"
    ],
    "nice_to_have_competencies": [
      "managing managers",
      "MEDDICC sales qualification framework",
      "design or development background"
    ],
    "domain": ["Product Design", "SaaS"],
    "remote_policy": "hybrid",
    "location": "not_stated",
    "delivery_motion": ["pre_sales"],
    "leadership_geography": ["EMEA", "APAC", "LATAM"],
    "company_size_signal": "scale_up",
    "company_stage": "pre_ipo",
    "culture_signals": [
      "think creatively",
      "lift constraints that block our imagination",
      "make design accessible to all",
      "grow as you go",
      "smart, curious people who are excited to learn",
      "fast-paced, evolving environment"
    ],
    "raw_observations": "Required technologies empty — pure leadership role. Role scope is international EMEA/APAC/LATAM — captured in leadership_geography."
  },
  "annotation": {
    "fit_score": 7,
    "applied": true,
    "application_date": "2026-06-06",
    "application_decision": "applied",
    "application_decision_notes": "",
    "location_workable": "yes",
    "location_notes": "Hybrid, no specific city stated — assumed London-compatible",
    "domain_distance": "medium",
    "blocking_constraints": [],
    "notes": "Strong fit on leadership profile. High-conviction application."
  }
}
```

---

### Record 5 — Mistral AI

```json
{
  "schema_version": "1.2",
  "id": "sha256:pending",
  "source_url": "https://jobs.lever.co/mistral/e59555e3-899d-4e1e-875f-90b825bc1e28",
  "source_ats": "manual",
  "company": "Mistral AI",
  "collected_at": "2026-06-06",
  "tier": 1,
  "raw_html": null,
  "raw_text": "stored separately",
  "extraction": {
    "role_type": ["Solutions Consulting", "Pre-Sales", "AI Delivery"],
    "seniority": "senior_ic",
    "technical_depth": "hands_on",
    "years_experience_required": "2+",
    "required_technologies": [
      "Python",
      "AI/ML frameworks",
      "LLM APIs"
    ],
    "required_competencies": [
      "executive workshop facilitation",
      "AI adoption roadmap design",
      "client-facing strategic advisory",
      "end-to-end AI solution architecture",
      "pilot project ownership",
      "C-level communication and influence",
      "business acumen and structured problem solving"
    ],
    "nice_to_have_technologies": [],
    "nice_to_have_competencies": [
      "MEDDPICC or value-based selling",
      "experience in data science consulting or value engineering"
    ],
    "domain": ["AI Platform", "Enterprise Software"],
    "remote_policy": "onsite",
    "location": "London",
    "delivery_motion": ["pre_sales", "direct_delivery"],
    "leadership_geography": [],
    "company_size_signal": "startup",
    "company_stage": "not_stated",
    "culture_signals": [
      "trusted advisor",
      "art of the possible",
      "deploy solutions in production",
      "reusable assets and playbooks"
    ],
    "raw_observations": "Stated experience bar (2+ years) notably low relative to role complexity. Likely filtering on potential and technical capability. Only JD in set with explicit onsite requirement."
  },
  "annotation": {
    "fit_score": 7,
    "applied": true,
    "application_date": "2026-05-26",
    "application_decision": "applied",
    "application_decision_notes": "",
    "location_workable": "yes",
    "location_notes": "London onsite — no issue",
    "domain_distance": "low",
    "blocking_constraints": [],
    "notes": "Applied before AI learning track started — portfolio built since significantly strengthens fit. Current fit higher than at time of application."
  }
}
```

---

### Record 6 — Databricks

```json
{
  "schema_version": "1.2",
  "id": "sha256:pending",
  "source_url": "unknown",
  "source_ats": "manual",
  "company": "Databricks",
  "collected_at": "2026-06-06",
  "tier": 1,
  "raw_html": null,
  "raw_text": "stored separately",
  "extraction": {
    "role_type": ["Solutions Architecture", "Pre-Sales"],
    "seniority": "lead",
    "technical_depth": "hands_on",
    "years_experience_required": "not_stated",
    "required_technologies": [
      "Python",
      "SQL",
      "Apache Spark",
      "Databricks platform",
      "AWS",
      "Azure",
      "GCP"
    ],
    "required_competencies": [
      "enterprise architecture and technology strategy",
      "executive engagement and advisory",
      "commercial awareness and sales cycle understanding",
      "data and AI market knowledge",
      "thought leadership and content creation",
      "cross-functional team orchestration",
      "explaining complex technology to non-technical leaders",
      "strategic account planning"
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
    "culture_signals": [
      "show not tell",
      "builder culture",
      "inspire customer CTOs to think bigger",
      "high velocity and growth",
      "democratising data and AI",
      "demonstrate thought leadership"
    ],
    "raw_observations": "Most technology-heavy JD in the set. No nice-to-have section — flat requirements list signals high hiring bar. Stack specificity makes role domain-locked."
  },
  "annotation": {
    "fit_score": 5,
    "applied": false,
    "application_date": null,
    "application_decision": "not_applied_structural",
    "application_decision_notes": "Technical stack depth gap — Spark and Databricks platform expertise not in current profile.",
    "location_workable": "yes",
    "location_notes": "London hybrid — no location issue",
    "domain_distance": "medium",
    "blocking_constraints": ["technical stack depth gap — Spark and Databricks platform"],
    "notes": ""
  }
}
```

---

### Record 7 — Writer

```json
{
  "schema_version": "1.2",
  "id": "sha256:pending",
  "source_url": "unknown",
  "source_ats": "manual",
  "company": "Writer",
  "collected_at": "2026-06-06",
  "tier": 2,
  "raw_html": null,
  "raw_text": "stored separately",
  "extraction": {
    "role_type": ["Solutions Architecture", "Pre-Sales"],
    "seniority": "manager",
    "technical_depth": "hybrid",
    "years_experience_required": "8+",
    "required_technologies": [
      "Python",
      "AWS",
      "Azure",
      "GCP",
      "LLMs / generative AI",
      "AI/ML frameworks"
    ],
    "required_competencies": [
      "SA team leadership and scaling",
      "enterprise pre-sales ownership",
      "POC execution and value realisation",
      "executive technical sponsorship",
      "AI solution architecture",
      "data pipeline and model deployment oversight",
      "product roadmap influence"
    ],
    "nice_to_have_technologies": [],
    "nice_to_have_competencies": [],
    "domain": ["AI Platform", "Enterprise Software"],
    "remote_policy": "hybrid",
    "location": "London",
    "delivery_motion": ["pre_sales", "direct_delivery"],
    "leadership_geography": [],
    "company_size_signal": "scale_up",
    "company_stage": "series_c_plus",
    "culture_signals": [
      "Connect",
      "Challenge",
      "Own",
      "thinks big and moves fast",
      "builders and scalers"
    ],
    "raw_observations": "Generative AI, LLMs, ML, cloud-native architectures and Python are explicit requirements. Security/compliance appears as part of implementation responsibility rather than a separate preferred skill. No explicit nice-to-have section in JD."
  },
  "annotation": {
    "fit_score": 8,
    "applied": false,
    "application_date": null,
    "application_decision": "want_to_apply",
    "application_decision_notes": "Very strong fit across enterprise pre-sales leadership, AI platform adoption, executive sponsorship and roadmap influence. Main question is depth of hands-on AI/ML implementation relative to current experience. Applying this week.",
    "location_workable": "yes",
    "location_notes": "London hybrid — fully workable",
    "domain_distance": "low",
    "blocking_constraints": [],
    "notes": "One of the strongest matches. Strong overlap with Xandr leadership, Utiq solution design and current AI portfolio work."
  }
}
```

---

### Record 8 — Zendesk

```json
{
  "schema_version": "1.2",
  "id": "sha256:pending",
  "source_url": "unknown",
  "source_ats": "manual",
  "company": "Zendesk",
  "collected_at": "2026-06-06",
  "tier": 2,
  "raw_html": null,
  "raw_text": "stored separately",
  "extraction": {
    "role_type": ["Strategic Pursuits", "Pre-Sales"],
    "seniority": "senior_ic",
    "technical_depth": "hybrid",
    "years_experience_required": "10+",
    "required_technologies": [],
    "required_competencies": [
      "strategic enterprise deal leadership",
      "CX and contact centre domain expertise",
      "consultative selling",
      "business case and ROI modelling",
      "executive communication and C-suite influence",
      "competitive positioning",
      "cross-functional orchestration",
      "AI application in customer service domain"
    ],
    "nice_to_have_technologies": [],
    "nice_to_have_competencies": [
      "platform architecture understanding",
      "public speaking and thought leadership"
    ],
    "domain": ["SaaS", "Customer Experience"],
    "remote_policy": "remote",
    "location": "remote / global",
    "delivery_motion": ["pre_sales"],
    "leadership_geography": [],
    "company_size_signal": "enterprise",
    "company_stage": "listed",
    "culture_signals": [
      "sense of calm to the chaotic world of customer service",
      "purposefully come together in person",
      "exceptional employer"
    ],
    "raw_observations": "Heavily domain-specific role — 10+ years CX/contact centre consulting is a hard requirement. AI applied within CX domain specifically, not general AI. Role is commercial/deal-focused rather than technical SA. Required technologies empty — pure commercial pursuit role."
  },
  "annotation": {
    "fit_score": 4,
    "applied": false,
    "application_date": null,
    "application_decision": "not_applied_structural",
    "application_decision_notes": "Strong pursuit leadership overlap but significant structural gap in CX/contact-centre domain expertise and AI application specifically within customer service.",
    "location_workable": "yes",
    "location_notes": "Remote role — no location issue",
    "domain_distance": "high",
    "blocking_constraints": [
      "10+ years consulting in customer service / contact centre / CX",
      "5+ years applying AI in customer service domain"
    ],
    "notes": "Good negative example. Functional alignment reasonably high but domain alignment too weak."
  }
}
```

---

### Record 9 — Outreach

```json
{
  "schema_version": "1.2",
  "id": "sha256:pending",
  "source_url": "unknown",
  "source_ats": "manual",
  "company": "Outreach",
  "collected_at": "2026-06-06",
  "tier": 2,
  "raw_html": null,
  "raw_text": "stored separately",
  "extraction": {
    "role_type": ["Solutions Consulting", "Pre-Sales"],
    "seniority": "lead",
    "technical_depth": "hybrid",
    "years_experience_required": "7+",
    "required_technologies": [
      "CRM platforms",
      "sales execution platforms"
    ],
    "required_competencies": [
      "enterprise pre-sales and SC",
      "MEDDPICC qualification",
      "value-based selling and ROI analysis",
      "outcome-based demo execution",
      "POV / proof of value ownership",
      "executive advisory to CROs and COOs",
      "deal coaching and SC mentoring",
      "vertical playbook creation"
    ],
    "nice_to_have_technologies": [
      "Outreach platform (Amplify, Kaia, Research Agent)",
      "Salesforce"
    ],
    "nice_to_have_competencies": [
      "Demo2Win framework",
      "enablement content creation"
    ],
    "domain": ["SaaS", "Revenue Technology"],
    "remote_policy": "hybrid",
    "location": "not_stated",
    "delivery_motion": ["pre_sales"],
    "leadership_geography": ["EMEA"],
    "company_size_signal": "scale_up",
    "company_stage": "not_stated",
    "culture_signals": [
      "leadership without title",
      "fast-growth environment",
      "no two days are the same",
      "multiplier for others"
    ],
    "raw_observations": "Revenue execution / CRM domain is significant distance from Michel's background. MEDDPICC and Demo2Win are hard framework requirements. Outreach AI agents (Amplify, Kaia, Research Agent) are proprietary — listed as preferred not required."
  },
  "annotation": {
    "fit_score": 5,
    "applied": false,
    "application_date": null,
    "application_decision": "not_applied_fit",
    "application_decision_notes": "Strong overlap with enterprise pre-sales and SC leadership but significant distance from revenue technology and CRM domain.",
    "location_workable": "unknown",
    "location_notes": "EMEA stated but no specific working model or office requirement provided",
    "domain_distance": "medium",
    "blocking_constraints": [
      "Revenue technology / CRM domain distance",
      "MEDDPICC and Demo2Win appear central to success"
    ],
    "notes": "Good middle-ground example. Strong functional fit, weaker sector fit."
  }
}
```

---

### Record 10 — Fin (Intercom)

```json
{
  "schema_version": "1.2",
  "id": "sha256:pending",
  "source_url": "unknown",
  "source_ats": "manual",
  "company": "Fin (Intercom)",
  "collected_at": "2026-06-06",
  "tier": 2,
  "raw_html": null,
  "raw_text": "stored separately",
  "extraction": {
    "role_type": ["AI Delivery", "Partner SA"],
    "seniority": "senior_ic",
    "technical_depth": "hybrid",
    "years_experience_required": "6+",
    "required_technologies": [
      "APIs",
      "integrations",
      "data flows",
      "Fin / Intercom platform",
      "Workflows"
    ],
    "required_competencies": [
      "customer-facing deployment leadership",
      "partner enablement",
      "partner escalation management",
      "technical discovery",
      "multi-stakeholder project delivery",
      "deployment methodology ownership",
      "technical coaching",
      "certification program delivery",
      "quality assurance of partner delivery",
      "customer success orientation"
    ],
    "nice_to_have_technologies": [
      "Zendesk",
      "Salesforce",
      "customer experience platforms"
    ],
    "nice_to_have_competencies": [
      "training content creation",
      "partner certification design",
      "system integrator ecosystem experience"
    ],
    "domain": ["AI Platform", "Customer Experience"],
    "remote_policy": "hybrid",
    "location": "London",
    "delivery_motion": ["partner_delivery", "partner_enablement"],
    "leadership_geography": [],
    "company_size_signal": "scale_up",
    "company_stage": "not_stated",
    "culture_signals": [
      "push boundaries",
      "build with speed and intensity",
      "relentlessly deliver incredible value",
      "radically open and accepting culture",
      "focus on doing incredible work"
    ],
    "raw_observations": "Role sits at intersection of deployment consulting, partner enablement, and scaled delivery quality assurance. Success measured by partner capability and deployment outcomes more than direct implementation volume. Strong overlap with SC leadership patterns despite IC title. 'Fin' is rebranded Intercom — same product, new AI-first positioning."
  },
  "annotation": {
    "fit_score": 8,
    "applied": false,
    "application_date": null,
    "application_decision": "want_to_apply",
    "application_decision_notes": "Very strong overlap with partner enablement, technical escalation ownership, cross-functional leadership, deployment methodology, and AI platform adoption. Main gap is direct experience with customer support platform deployment — learnable rather than structural.",
    "location_workable": "yes",
    "location_notes": "London hybrid 3 days/week — fully workable",
    "domain_distance": "low",
    "blocking_constraints": [],
    "notes": "Higher probability than Writer, lower upside. Closer to proven strengths — better hiring story. Strong bridge between current profile and AI-native companies. Role is scaled delivery quality through partners, not traditional professional services — maps well to semiconductor ecosystem support and SC leadership background."
  }
}
```

---

## 6. Tier 2 Remaining Plan

**Target:** 15 JDs total for Tier 2. 4 complete, 11 remaining.

**Coverage gaps to fill:**
- Pure IC roles (`"ic"` seniority — none in corpus yet)
- Non-EMEA roles (tests `remote_policy` and regional signal behaviour)
- Product/GTM roles (in target corpus but absent so far)
- At least 2 JDs from Greenhouse API output (not manual) to validate collector format

**Schema freeze:** After Tier 2 complete. Resolve `deal_motion` observation — appears in 2 JDs, needs 1 more to promote. No new fields after freeze.

**Open questions to resolve in remaining Tier 2:**
- `deal_motion` — promote if appears in 1 more JD
- Any new pattern appearing in 3+ remaining JDs

---

## 7. Next Steps

**Immediate (job search):**
- Apply to Writer this week
- Apply to Fin (Intercom) — flagged as want_to_apply

**Corpus build:**
- Copy raw JD text for all 10 records to `corpus/manual/` as `.txt` files
- Compute SHA-256 hashes, replace `sha256:pending` in each record
- Write final records to `corpus/manual/manual_20260606.jsonl`
- Continue Tier 2 — 11 more JDs needed

**Claude Code:**
- Start with Steps 0–1 (scaffold + JDRecord model at schema v1.2)
- Tier 2 tooling (Step 6) built before remaining 11 Tier 2 JDs
