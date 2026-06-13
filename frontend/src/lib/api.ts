// Typed client for the Job Radar FastAPI backend (job_radar_SPEC §10.4). All calls are
// same-origin /api/* — the Vite dev server (and prod nginx) proxy them to the api container,
// so the HttpOnly jr_write capability cookie is sent automatically. credentials:"include"
// keeps the cookie flowing even when dev runs cross-port behind the proxy.

const BASE = "/api";

// Read-only report downloads (job_radar_SPEC §11.1). Same-origin /api so the browser
// streams the text/plain attachment straight to disk — no fetch/JSON round-trip needed.
export const YIELD_REPORT_URL = `${BASE}/report/yield`;
export const CV_TAILOR_REPORT_URL = `${BASE}/report/cv_tailor`;

// Raised when an HTTP call fails; carries the status so callers can branch (401/403/404).
export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
    this.name = "ApiError";
  }
}

async function errorFrom(res: Response): Promise<ApiError> {
  let detail = `${res.status} ${res.statusText}`;
  try {
    const j = (await res.json()) as { detail?: string };
    if (j.detail) detail = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
  } catch {
    /* non-JSON error body */
  }
  return new ApiError(res.status, detail);
}

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`, { credentials: "include", cache: "no-store" });
  if (!res.ok) throw await errorFrom(res);
  return res.json() as Promise<T>;
}

async function post<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw await errorFrom(res);
  return res.json() as Promise<T>;
}

// One scoring flag embedded per job (job_radar_SPEC §10.11 Feature 2). observed/expected are
// whatever was flagged (a value or list), passed through from corpus/annotations.jsonl.
export interface Annotation {
  ts: string;
  annotation_type: string;
  field: string;
  observed: unknown;
  expected: unknown;
  reason: string;
  scorer_label: string | null;
  scorer_fit_score: number | null;
}

// cv-tailor run snapshot embedded per job (job_radar_SPEC §11.3). The cv-tailor run is the
// source of truth; the metrics mirror the cv-tailor UI — fit_score + coverage_score are
// 0.0–1.0 (shown as %), cv_quality_score is 0.0–10.0 (shown as X.X/10). {has_output:false}
// when no run has been recorded; the metric fields are present only when has_output is true.
export interface CvTailor {
  has_output: boolean;
  run_id?: string | null;
  fit_score?: number | null;
  coverage_score?: number | null;
  cv_quality_score?: number | null;
  cvcm_enabled?: boolean | null;
  tailoring_mode?: string | null;
  output_link?: string | null;
  notes?: string | null;
  ts?: string | null;
}

// One denormalised index row — score ⨝ JDRecord ⨝ sidecar ⨝ activity-log projection
// (built by cli.stats.build_index_rows; the API overlays live workflow state on read).
export interface Job {
  job_id: string;
  company: string;
  title: string;
  // scoring (ApplicationRecord) — fit_label/priority_score are the DISPLAY values (the
  // owner's fit override wins over the scorer here; scorer_* preserves the original).
  fit_score: number;
  fit_label: string;
  fit_label_reason: string;
  priority_score: number;
  requirement_gaps: string[];
  blocking_constraints: string[];
  scored_at: string;
  profile_version: string;
  // fit override (Feature 1): scorer verdict vs owner override, both preserved
  scorer_fit_label: string;
  scorer_fit_score: number;
  scorer_priority_score: number;
  user_fit_label: string | null;
  user_fit_reason: string | null;
  display_fit_label: string;
  display_priority_score: number;
  has_fit_override: boolean;
  // scoring flags (Feature 2)
  annotations: Annotation[];
  annotation_count: number;
  has_annotations: boolean;
  // cv-tailor run link (§11.3)
  cv_tailor: CvTailor;
  // live workflow state (activity-log projection)
  application_status: string;
  outcome: string | null;
  application_date: string | null;
  notes: string;
  // location + provenance
  location: string;
  location_workable: string;
  source_url: string;
  source_ats: string;
  tier: number | null;
  date_first_seen: string;
  raw_text: string;
  // extraction (filters + detail)
  domain: string[];
  role_type: string[];
  seniority: string;
  technical_depth: string;
  remote_policy: string;
  company_stage: string;
  company_size_signal: string;
  years_experience_required: string;
  required_technologies: string[];
  required_competencies: string[];
  nice_to_have_technologies: string[];
  nice_to_have_competencies: string[];
  delivery_motion: string[];
  leadership_geography: string[];
  culture_signals: string[];
  raw_observations: string;
}

export interface IndexStats {
  total: number;
  by_fit_label: Record<string, number>;
  by_application_status: Record<string, number>;
  fit_score_distribution: Record<string, number>;
  cost_to_date_usd: number;
}

export interface IndexResponse {
  schema_version: string | null;
  jdrecord_schema_version: string | null;
  generated_at: string | null;
  stats: IndexStats;
  records: Job[];
}

// Drives write-control rendering (job_radar_SPEC §10.5 table). configured but not
// unlocked → click shows the unlock dialog; not configured → controls hidden entirely.
export interface Capabilities {
  write_configured: boolean;
  write_unlocked: boolean;
}

export interface AnnotationPayload {
  job_id: string;
  annotation_type: string;
  field: string | null;   // null for a rejection_reason (about the role, not a field)
  observed: unknown;
  expected: unknown;
  reason: string;
}

// cv-tailor metrics POST body (job_radar_SPEC §11.3). fit_score + coverage_score are 0.0–1.0
// floats (the UI divides its 0–100 inputs by 100); cv_quality_score is 0.0–10.0 (the raw
// rubric score, sent as-is). All but run_id are optional.
export interface CvTailorResultPayload {
  job_id: string;
  cv_tailor_run_id: string;
  fit_score?: number | null;
  coverage_score?: number | null;
  cv_quality_score?: number | null;
  cvcm_enabled?: boolean | null;
  tailoring_mode?: string | null;
  output_link?: string | null;
  notes?: string | null;
}

// Manual JD entry (job_radar_SPEC §11.1). The owner pastes a JD; the backend runs the live
// pipeline synchronously (~10–20s) and returns the scored result. company/title/raw_text are
// required; source_url/notes optional.
export interface ManualIngestPayload {
  company: string;
  title: string;
  raw_text: string;
  source_url?: string;
  notes?: string;
}
export interface ManualIngestResult {
  job_id: string;
  company: string;
  title: string;
  fit_label: string;
  fit_score: number;
  priority_score: number;
  warnings: string[]; // advisory soft-validation findings (e.g. off-vocabulary role_type); [] when clean
}

export const api = {
  index: () => get<IndexResponse>("/index"),
  capabilities: () => get<Capabilities>("/capabilities"),
  health: () => get<{ status: string; service: string; records: number; last_indexed: string | null }>("/health"),

  unlock: (key: string) => post<{ write_unlocked: boolean }>("/unlock", { key }),
  lock: () => post<{ write_unlocked: boolean }>("/lock", {}),

  setStatus: (job_id: string, status: string, notes?: string) =>
    post<{ ok: boolean; status: string; warning: string | null }>("/status", { job_id, status, notes }),
  addNote: (job_id: string, text: string) => post<{ ok: boolean }>("/note", { job_id, text }),
  setTitle: (job_id: string, title: string) => post<{ ok: boolean; title: string }>("/title", { job_id, title }),
  setOutcome: (job_id: string, outcome: string, notes?: string) =>
    post<{ ok: boolean; outcome: string }>("/outcome", { job_id, outcome, notes }),
  // fit_label=null clears a prior override (job_radar_SPEC §10.11 Feature 1).
  setFitOverride: (job_id: string, fit_label: string | null, reason?: string) =>
    post<{ ok: boolean; fit_label: string | null }>("/fit-override", { job_id, fit_label, reason }),
  flagAnnotation: (payload: AnnotationPayload) =>
    post<{ ok: boolean; annotation_type: string }>("/annotations", payload),
  // Append a cv-tailor run snapshot for a scored role (owner-gated, §11.3).
  recordCvTailorResult: (payload: CvTailorResultPayload) =>
    post<{ job_id: string; cv_tailor_run_id: string }>("/cv-tailor-results", payload),
  // Paste-and-score a JD from outside the monitored universe (owner-gated, §11.1).
  manualIngest: (payload: ManualIngestPayload) => post<ManualIngestResult>("/manual-ingest", payload),
};
