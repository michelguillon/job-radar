import { useEffect, useState } from "react";
import { api, ApiError, type Annotation, type Job } from "@/lib/api";
import { cn } from "@/lib/utils";
import { CHIP, fitBadgeClass, statusPillClass, TOAST } from "@/lib/ui";
import {
  ANNOTATION_TYPES, daysSince, effectiveStatus, FIT_LABELS, fmtDate, isStaleApplied, LABEL_TEXT,
  listText, REJECTION_REASONS, rejectionStageFor, statusForOutcome,
} from "@/lib/jobs";
import { useUnlock } from "@/components/UnlockProvider";

// Centered modal — read fields plus owner-only write controls (job_radar_SPEC §10.6).
// Controls are hidden when writes aren't configured; when configured-but-locked, the first
// write opens the unlock dialog via requestUnlock(). All Tailwind, no global classes.

type Toast = { kind: "ok" | "warn" | "err"; text: string } | null;

// Contextual status controls (SPEC_WORKFLOW_UPDATE §3): only the moves that make sense from
// the current effective status are offered. Keyed by effective status → ordered button keys.
const STATUS_BUTTONS: Record<string, string[]> = {
  new:            ["review", "shortlisted", "applied", "will_not_apply", "archived"],
  review:         ["shortlisted", "applied", "will_not_apply", "archived"],
  shortlisted:    ["applied", "will_not_apply", "archived"],
  applied:        ["interviewing", "rejected", "withdraw"],
  interviewing:   ["offer", "rejected", "withdraw"],
  offer:          ["accepted", "declined"],
  rejected:       ["archived"],
  will_not_apply: ["archived", "restore"],
  archived:       ["restore"],
};
// Button key → display label. Keys that are statuses move the lane directly; "withdraw",
// "rejected", "accepted", "declined", "restore" are actions (see onButton).
const BUTTON_LABEL: Record<string, string> = {
  review: "Review", shortlisted: "Shortlist", applied: "Applied",
  will_not_apply: "Will not apply", archived: "Archive",
  interviewing: "Interviewing", offer: "Offer", rejected: "Rejected",
  withdraw: "Withdraw", restore: "Restore to new",
  accepted: "Accepted", declined: "Declined",
};
const DANGER_BUTTONS = new Set(["will_not_apply", "archived", "rejected", "withdraw", "declined"]);

function observedFor(type: string, r: Job): { field: string; observed: unknown } {
  switch (type) {
    case "role_type_incorrect": return { field: "role_type", observed: r.role_type };
    case "domain_incorrect": return { field: "domain", observed: r.domain };
    case "seniority_incorrect": return { field: "seniority", observed: r.seniority };
    case "technical_depth_incorrect": return { field: "technical_depth", observed: r.technical_depth };
    case "fit_score_disagree": return { field: "fit_score", observed: r.fit_score };
    case "should_be_blocked": return { field: "blocking_constraints", observed: r.blocking_constraints };
    case "false_block": return { field: "blocking_constraints", observed: r.blocking_constraints };
    default: return { field: "", observed: "" };
  }
}

const FIELD_INPUT = "w-full rounded-md border border-line px-[9px] py-[6px] text-[13px] focus:border-brand focus:outline-none disabled:opacity-50";
const BTN = "rounded-md border border-line bg-white px-[14px] py-[6px] text-[12.5px] font-semibold text-ink hover:border-brand hover:text-brand disabled:opacity-50";
const BTN_PRIMARY = "rounded-md border border-brand bg-brand px-[14px] py-[6px] text-[12.5px] font-semibold text-white hover:bg-[#245fd0] disabled:opacity-50";
const LABEL = "block text-[11px] text-ink-soft mb-[3px]";
const SECTION_H = "mb-[7px] text-[11px] font-bold uppercase tracking-wide text-ink-soft";

function KV({ label, value }: { label: string; value: string }) {
  if (!value) return null;
  return (<><dt className="text-ink-soft">{label}</dt><dd className="m-0">{value}</dd></>);
}
function Chips({ items, tone = "default" }: { items: string[]; tone?: keyof typeof CHIP }) {
  return (
    <div className="flex flex-wrap gap-[5px]">
      {items.map((it, i) => <span key={i} className={cn("rounded-[5px] px-2 py-[2px] text-[12px]", CHIP[tone])}>{it}</span>)}
    </div>
  );
}
function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return <div className="mt-[18px]"><h3 className={SECTION_H}>{title}</h3>{children}</div>;
}
function Pill({ status }: { status: string }) {
  return <span className={cn("inline-block rounded-[5px] px-2 py-[2px] text-[11px] font-semibold", statusPillClass(status))}>{status}</span>;
}
// cv-tailor scores are 0.0–1.0 floats on the wire (job_radar_SPEC §11.3); the UI shows + edits
// them as 0–100 percentages. Empty input → null (the field is optional, not zero).
function toPercentStr(v: number | null | undefined): string {
  return v == null ? "" : String(Math.round(v * 100));
}
function pctDisplay(v: number | null | undefined): string {
  return v == null ? "—" : `${Math.round(v * 100)}%`;
}
function toFraction(s: string): number | null {
  const t = s.trim();
  if (!t) return null;
  const n = Number(t);
  if (isNaN(n)) return null;
  return Math.max(0, Math.min(1, n / 100));
}

// cv_quality_score is the raw 0.0–10.0 rubric score — NOT a fraction. Input + display use the
// 0–10 scale directly (shown as X.X/10), unlike fit/coverage which are stored 0.0–1.0.
function qualityStr(v: number | null | undefined): string {
  return v == null ? "" : String(v);
}
function qualityDisplay(v: number | null | undefined): string {
  return v == null ? "—" : `${v}/10`;
}
function toQuality(s: string): number | null {
  const t = s.trim();
  if (!t) return null;
  const n = Number(t);
  if (isNaN(n)) return null;
  return Math.max(0, Math.min(10, n));
}

const CV_TAILOR_MODES = ["full", "targeted", "minimal"];

// CV-Tailor section (job_radar_SPEC §11.3). Read-only for everyone; the Add/Edit form is
// owner-gated (rendered only when unlocked, first write still goes through requestUnlock()).
// Records a manual snapshot of a cv-tailor run against this role — never mutates a score.
function CvTailorSection({ job, onChanged }: { job: Job; onChanged: () => Promise<void> }) {
  const { unlocked, requestUnlock } = useUnlock();
  const cv = job.cv_tailor || { has_output: false };
  // cv-tailor handoff (Phase 2, INTEGRATION_SPEC §5.1): a plain link, not a mutation — visible
  // to everyone, never lock-gated (cv-tailor's own key gate handles non-owner access). A run
  // exists → open it; none yet → start one pre-seeded with this job_id (cv-tailor fetches the
  // JD via the public GET /api/jobs/{job_id} built in Phase 1).
  const cvTailorUrl = cv.has_output
    ? `https://cv-tailor.michel-portfolio.co.uk/api/runs/${cv.run_id}/report`
    : `https://cv-tailor.michel-portfolio.co.uk/new?source=job_radar&job_id=${job.job_id}`;
  const cvTailorLabel = cv.has_output ? "Open in cv-tailor ↗" : "Create CV in cv-tailor ↗";
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState<Toast>(null);

  const [runId, setRunId] = useState(cv.run_id || "");
  const [fitScore, setFitScore] = useState(toPercentStr(cv.fit_score));
  const [coverage, setCoverage] = useState(toPercentStr(cv.coverage_score));
  const [cvQuality, setCvQuality] = useState(qualityStr(cv.cv_quality_score));
  const [cvcm, setCvcm] = useState(!!cv.cvcm_enabled);
  const [mode, setMode] = useState(cv.tailoring_mode || "full");
  const [link, setLink] = useState(cv.output_link || "");
  const [notes, setNotes] = useState(cv.notes || "");

  function resetForm() {
    setRunId(cv.run_id || ""); setFitScore(toPercentStr(cv.fit_score));
    setCoverage(toPercentStr(cv.coverage_score)); setCvQuality(qualityStr(cv.cv_quality_score));
    setCvcm(!!cv.cvcm_enabled); setMode(cv.tailoring_mode || "full");
    setLink(cv.output_link || ""); setNotes(cv.notes || "");
  }
  useEffect(() => { resetForm(); setEditing(false); setToast(null); }, [job.job_id]); // eslint-disable-line react-hooks/exhaustive-deps

  async function save() {
    if (!(await requestUnlock())) return;
    if (!runId.trim()) { setToast({ kind: "err", text: "Run ID is required" }); return; }
    setBusy(true);
    try {
      await api.recordCvTailorResult({
        job_id: job.job_id,
        cv_tailor_run_id: runId.trim(),
        fit_score: toFraction(fitScore),
        coverage_score: toFraction(coverage),
        cv_quality_score: toQuality(cvQuality),
        cvcm_enabled: cvcm,
        tailoring_mode: mode,
        output_link: link.trim() || null,
        notes: notes.trim() || null,
      });
      setEditing(false);
      setToast({ kind: "ok", text: "CV-Tailor metrics saved" });
      await onChanged();
    } catch (e) {
      setToast({ kind: "err", text: e instanceof ApiError ? e.message : e instanceof Error ? e.message : String(e) });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mt-[18px] rounded-lg border border-line bg-[#fbfcfe] p-[14px]">
      <h3 className="mb-[10px] text-[11px] font-bold uppercase tracking-wide text-brand">CV-Tailor</h3>

      {editing ? (
        <div className="space-y-2">
          <div>
            <label className={LABEL}>Run ID (required)</label>
            <input className={FIELD_INPUT} value={runId} placeholder="run_20260611_001" disabled={busy} onChange={(e) => setRunId(e.target.value)} />
          </div>
          <div className="grid grid-cols-3 gap-2">
            <div><label className={LABEL}>Fit score (0–100)</label><input className={FIELD_INPUT} inputMode="numeric" value={fitScore} disabled={busy} onChange={(e) => setFitScore(e.target.value)} /></div>
            <div><label className={LABEL}>Coverage (0–100)</label><input className={FIELD_INPUT} inputMode="numeric" value={coverage} disabled={busy} onChange={(e) => setCoverage(e.target.value)} /></div>
            <div><label className={LABEL}>CV Quality (0–10)</label><input className={FIELD_INPUT} inputMode="decimal" value={cvQuality} placeholder="8.1" disabled={busy} onChange={(e) => setCvQuality(e.target.value)} /></div>
          </div>
          <div className="flex flex-wrap items-end gap-3">
            <label className="flex items-center gap-[6px] text-[12.5px] text-ink">
              <input type="checkbox" checked={cvcm} disabled={busy} onChange={(e) => setCvcm(e.target.checked)} /> CVCM enabled
            </label>
            <div>
              <label className={LABEL}>Mode</label>
              <select className={cn(FIELD_INPUT, "w-auto min-w-[120px]")} value={mode} disabled={busy} onChange={(e) => setMode(e.target.value)}>
                {CV_TAILOR_MODES.map((m) => <option key={m} value={m}>{m}</option>)}
              </select>
            </div>
          </div>
          <div><label className={LABEL}>Output link</label><input className={FIELD_INPUT} value={link} placeholder="https://cv-tailor…/runs/…" disabled={busy} onChange={(e) => setLink(e.target.value)} /></div>
          <div><label className={LABEL}>Notes</label><textarea className={cn(FIELD_INPUT, "font-sans")} rows={2} value={notes} disabled={busy} onChange={(e) => setNotes(e.target.value)} /></div>
          <div className="flex gap-2">
            <button className={BTN_PRIMARY} onClick={save} disabled={busy}>Save</button>
            <button className={BTN} onClick={() => { resetForm(); setEditing(false); }} disabled={busy}>Cancel</button>
          </div>
        </div>
      ) : cv.has_output ? (
        <div className="text-[13px] text-ink">
          <div className="mb-[6px] flex flex-wrap items-center justify-between gap-2">
            <span><span className="text-ink-soft">Run:</span> <span className="font-semibold">{cv.run_id}</span></span>
            <span className="text-[11px] text-ink-faint">{fmtDate(cv.ts)}</span>
          </div>
          <div className="mb-[4px] flex flex-wrap gap-x-[18px] gap-y-1 tabular-nums">
            <span><span className="text-ink-soft">Fit:</span> {pctDisplay(cv.fit_score)}</span>
            <span><span className="text-ink-soft">Coverage:</span> {pctDisplay(cv.coverage_score)}</span>
            <span><span className="text-ink-soft">CV Quality:</span> {qualityDisplay(cv.cv_quality_score)}</span>
          </div>
          <div className="mb-[4px] flex flex-wrap gap-x-[18px] text-[12.5px] text-ink-soft">
            <span>CVCM: {cv.cvcm_enabled ? "enabled" : "disabled"}</span>
            {cv.tailoring_mode && <span>Mode: {cv.tailoring_mode}</span>}
          </div>
          {cv.notes && <p className="mb-[4px] text-[12.5px] text-ink-soft">Notes: {cv.notes}</p>}
          {unlocked && (
            <div className="mt-[10px]">
              <button className={BTN} onClick={() => { resetForm(); setEditing(true); }} disabled={busy}>Edit</button>
            </div>
          )}
        </div>
      ) : (
        <div className="text-[13px] text-ink-soft">
          <p className="mb-[8px]">{unlocked ? "No cv-tailor run recorded yet." : "No cv-tailor run recorded."}</p>
          {unlocked && <button className={BTN} onClick={() => { resetForm(); setEditing(true); }} disabled={busy}>Add cv-tailor metrics</button>}
        </div>
      )}

      {/* Handoff link (Phase 2) — always visible, never lock-gated; opens in a new tab. */}
      <div className="mt-[12px] border-t border-line-soft pt-[12px]">
        <a href={cvTailorUrl} target="_blank" rel="noopener" className={cn(BTN, "inline-block no-underline")}>{cvTailorLabel}</a>
      </div>

      {toast && <div className={cn("mt-2 rounded-md px-[9px] py-[6px] text-[12px]", TOAST[toast.kind])}>{toast.text}</div>}
    </div>
  );
}

function AnnotationItem({ a }: { a: Annotation }) {
  const exp = listText(a.expected);
  return (
    <div className="rounded-md border border-line-soft bg-white px-[10px] py-[7px]">
      <div className="mb-[2px] flex items-center justify-between gap-2">
        <span className="rounded-[4px] bg-[#eef1f6] px-[7px] py-px text-[11px] font-semibold text-ink-soft">{a.annotation_type}</span>
        <span className="text-[11px] text-ink-faint">{fmtDate(a.ts)}</span>
      </div>
      <p className="text-[12.5px] text-ink">{a.reason}</p>
      {exp && <p className="mt-[2px] text-[11.5px] text-ink-faint">expected: {exp}</p>}
    </div>
  );
}

function WriteControls({ job, companyActive, onChanged }: { job: Job; companyActive: boolean; onChanged: () => Promise<void> }) {
  const { requestUnlock } = useUnlock();
  const [toast, setToast] = useState<Toast>(null);
  const [flagToast, setFlagToast] = useState<Toast>(null);
  const [busy, setBusy] = useState(false);
  const [noteText, setNoteText] = useState(job.notes || "");
  const [titleText, setTitleText] = useState(job.title || "");
  const [flagType, setFlagType] = useState(ANNOTATION_TYPES[0]);
  const [expected, setExpected] = useState("");
  const [reason, setReason] = useState("");
  const [fitSel, setFitSel] = useState(job.user_fit_label || job.scorer_fit_label);
  const [fitReason, setFitReason] = useState(job.user_fit_reason || "");
  const [editingOverride, setEditingOverride] = useState(false);

  // Latest recorded rejection reason for this role (annotations are append-only, so the
  // most recent rejection_reason entry is the current one).
  const rejectionAnns = (job.annotations || []).filter((a) => a.annotation_type === "rejection_reason");
  const recordedReason = rejectionAnns.length ? String(rejectionAnns[rejectionAnns.length - 1].reason) : null;

  // Contextual terminal-action panel (SPEC_WORKFLOW_UPDATE §4): one panel at a time, revealed
  // below the status buttons so the move is confirmed (with optional reason) before it commits.
  const [pending, setPending] = useState<null | "willnot" | "withdraw" | "rejected">(null);
  const [rejReason, setRejReason] = useState("");     // reason dropdown (willnot / withdraw)
  const [rejectNotes, setRejectNotes] = useState(""); // free-text feedback (rejected)
  const [panelToast, setPanelToast] = useState<Toast>(null);

  useEffect(() => {
    setNoteText(job.notes || ""); setTitleText(job.title || "");
    setFlagType(ANNOTATION_TYPES[0]); setExpected(""); setReason("");
    setFitSel(job.user_fit_label || job.scorer_fit_label); setFitReason(job.user_fit_reason || "");
    setEditingOverride(false);
    setPending(null); setRejReason(""); setRejectNotes(""); setPanelToast(null);
    setToast(null); setFlagToast(null);
  }, [job.job_id]); // eslint-disable-line react-hooks/exhaustive-deps

  async function guarded(run: () => Promise<Toast>, setT: (t: Toast) => void = setToast) {
    if (!(await requestUnlock())) return;
    setBusy(true);
    try {
      setT(await run());
      await onChanged();
    } catch (e) {
      setT({ kind: "err", text: e instanceof ApiError ? e.message : e instanceof Error ? e.message : String(e) });
    } finally {
      setBusy(false);
    }
  }

  const setStatus = (status: string) => guarded(async () => {
    if (status === "archived" && !window.confirm("Archive this role?")) return null;
    const res = await api.setStatus(job.job_id, status);
    return res.warning ? { kind: "warn", text: `Saved · ${res.warning}` } : { kind: "ok", text: `Status → ${status}` };
  });
  const saveNote = () => guarded(async () => {
    if (!noteText.trim()) return { kind: "err", text: "Note is empty" };
    await api.addNote(job.job_id, noteText.trim());
    return { kind: "ok", text: "Note saved" };
  });
  const saveTitle = () => guarded(async () => {
    if (!titleText.trim()) return { kind: "err", text: "Title is empty" };
    await api.setTitle(job.job_id, titleText.trim());
    return { kind: "ok", text: "Title override saved" };
  });
  // Offer outcome buttons (Accepted / Declined): record the outcome + move the lane.
  // statusForOutcome maps offer_accepted→offer, offer_declined→will_not_apply.
  const recordOutcomeMove = (outcome: string) => guarded(async () => {
    await api.setOutcome(job.job_id, outcome);
    const lane = statusForOutcome(outcome);
    if (lane && lane !== job.application_status) await api.setStatus(job.job_id, lane);
    return { kind: "ok", text: `Recorded: ${outcome.replace(/_/g, " ")}` };
  });
  // A structured rejection reason is recorded only when a real REJECTION_REASON is chosen;
  // "withdrew" is the dropdown's default-no-reason sentinel (an OUTCOME, not a reason) and is
  // skipped here — the withdrawal itself is captured via POST /api/outcome.
  const postRejectionReason = async () => {
    if (rejReason && rejReason !== "withdrew") {
      await api.flagAnnotation({
        job_id: job.job_id, annotation_type: "rejection_reason", field: null,
        observed: [job.scorer_fit_label, String(job.scorer_fit_score)], expected: [], reason: rejReason,
      });
    }
  };
  // "Will not apply" — internal decision; status only (+ optional structured reason). §4.
  const confirmWillNot = () => guarded(async () => {
    await api.setStatus(job.job_id, "will_not_apply");
    await postRejectionReason();
    setPending(null);
    return { kind: "ok", text: rejReason ? `Will not apply · ${rejReason.replace(/_/g, " ")}` : "Will not apply" };
  }, setPanelToast);
  // "Withdraw" — leave an in-flight application; status will_not_apply + outcome withdrew. §4.
  const confirmWithdraw = () => guarded(async () => {
    await api.setStatus(job.job_id, "will_not_apply");
    await api.setOutcome(job.job_id, "withdrew");
    await postRejectionReason();
    setPending(null);
    return { kind: "ok", text: "Withdrawn" };
  }, setPanelToast);
  // "Rejected" — employer-initiated; free-text feedback carried on the auto-derived stage. §4.
  const confirmRejected = () => guarded(async () => {
    await api.setStatus(job.job_id, "rejected");
    if (rejectNotes.trim()) {
      await api.setOutcome(job.job_id, rejectionStageFor(job.application_status), rejectNotes.trim());
    }
    setPending(null);
    return { kind: "ok", text: "Marked rejected" };
  }, setPanelToast);
  const saveOverride = () => guarded(async () => {
    await api.setFitOverride(job.job_id, fitSel, fitReason.trim() || undefined);
    setEditingOverride(false);
    return { kind: "ok", text: `Fit override → ${LABEL_TEXT[fitSel] || fitSel}` };
  });
  const clearOverride = () => guarded(async () => {
    await api.setFitOverride(job.job_id, null);
    setEditingOverride(false);
    return { kind: "ok", text: "Override cleared" };
  });
  const submitFlag = () => guarded(async () => {
    if (!reason.trim()) return { kind: "err", text: "Reason is required" };
    const { field, observed } = observedFor(flagType, job);
    // Client-side duplicate check (job_radar_SPEC §10.11 Feature 2): same type + field +
    // reason as an existing flag. Courtesy warning — the API is the backstop (409).
    const dup = (job.annotations || []).some(
      (a) => a.annotation_type === flagType && a.field === field && a.reason === reason.trim(),
    );
    if (dup && !window.confirm("This flag already exists. Submit anyway?")) return null;
    await api.flagAnnotation({ job_id: job.job_id, annotation_type: flagType, field, observed, expected: expected.trim(), reason: reason.trim() });
    setExpected(""); setReason("");
    return { kind: "ok", text: "Flag submitted" };
  }, setFlagToast);

  const { observed } = observedFor(flagType, job);
  const eff = effectiveStatus(job);
  const buttons = STATUS_BUTTONS[eff] || STATUS_BUTTONS.new;
  function onButton(key: string) {
    switch (key) {
      // Pre-select "applied elsewhere (same company)" when this is a sibling of an active
      // application — the usual reason you're closing it out (SPEC_ACTIVE_COMPANY_FILTER §5).
      case "will_not_apply": setPending("willnot"); setRejReason(companyActive ? "applied_elsewhere_same_company" : ""); setPanelToast(null); break;
      case "withdraw": setPending("withdraw"); setRejReason("withdrew"); setPanelToast(null); break;
      case "rejected": setPending("rejected"); setRejectNotes(""); setPanelToast(null); break;
      case "restore": setStatus("new"); break;
      case "accepted": recordOutcomeMove("offer_accepted"); break;
      case "declined": recordOutcomeMove("offer_declined"); break;
      case "archived": setStatus("archived"); break;
      default: setStatus(key); break;   // review / shortlisted / applied / interviewing / offer
    }
  }
  const ageDays = daysSince(job.application_date);
  const stale = isStaleApplied(job);
  const hasApplied = !!job.application_date || ["applied", "interviewing", "offer", "rejected"].includes(eff);
  const wcLabel = "w-16 shrink-0 text-[12px] text-ink-soft";

  return (
    <>
      <div className="mt-[18px] rounded-lg border border-line bg-[#fbfcfe] p-[14px]">
        <h3 className="mb-[10px] text-[11px] font-bold uppercase tracking-wide text-brand">Fit assessment</h3>
        <div className="mb-[10px] text-[12.5px] text-ink-soft">
          <span className="font-semibold text-ink">Scorer</span>{" "}
          <span className={cn("ml-1 inline-block rounded-full px-2 py-px text-[11px] font-bold", fitBadgeClass(job.scorer_fit_label))}>{LABEL_TEXT[job.scorer_fit_label] || job.scorer_fit_label}</span>
          <span className="ml-2 tabular-nums">fit {job.scorer_fit_score} · priority {job.scorer_priority_score}</span>
        </div>

        {job.has_fit_override && !editingOverride ? (
          <div className="rounded-md border border-[#e2c98f] bg-[#fdf7e8] p-[10px]">
            <div className="mb-[6px] flex flex-wrap items-center gap-2 text-[12px]">
              <span className="font-bold uppercase tracking-wide text-[#8a5a14]">⚠ Manual override active</span>
              <span className={cn("inline-block rounded-full px-2 py-px text-[11px] font-bold", fitBadgeClass(job.user_fit_label || ""))}>{LABEL_TEXT[job.user_fit_label || ""] || job.user_fit_label}</span>
            </div>
            {job.user_fit_reason && <p className="mb-[8px] text-[12.5px] italic text-ink-soft">“{job.user_fit_reason}”</p>}
            <div className="flex flex-wrap gap-[6px]">
              <button className={BTN} onClick={() => { setFitSel(job.user_fit_label || job.scorer_fit_label); setFitReason(job.user_fit_reason || ""); setEditingOverride(true); }} disabled={busy}>Edit override</button>
              <button className={BTN} onClick={clearOverride} disabled={busy}>Clear override</button>
            </div>
          </div>
        ) : (
          <div className="flex flex-wrap items-end gap-2">
            <div>
              <label className={LABEL}>Override fit label</label>
              <select className={cn(FIELD_INPUT, "w-auto min-w-[150px]")} value={fitSel} disabled={busy} onChange={(e) => setFitSel(e.target.value)}>
                {FIT_LABELS.map((l) => <option key={l} value={l}>{LABEL_TEXT[l] || l}</option>)}
              </select>
            </div>
            <input className={cn(FIELD_INPUT, "min-w-[140px] flex-1")} value={fitReason} placeholder="Reason (recommended)…" disabled={busy} onChange={(e) => setFitReason(e.target.value)} />
            <button className={BTN_PRIMARY} onClick={saveOverride} disabled={busy}>Save override</button>
            {editingOverride && <button className={BTN} onClick={() => setEditingOverride(false)} disabled={busy}>Cancel</button>}
          </div>
        )}
      </div>

      <div className="mt-[18px] rounded-lg border border-line bg-[#fbfcfe] p-[14px]">
        <h3 className="mb-[10px] text-[11px] font-bold uppercase tracking-wide text-brand">Workflow</h3>

        <div className="mb-[10px] flex flex-wrap items-center gap-2">
          <span className={wcLabel}>Status</span>
          <Pill status={eff} />
        </div>
        <div className="mb-[10px] flex flex-wrap gap-[6px]">
          {buttons.map((key) => {
            const danger = DANGER_BUTTONS.has(key);
            const active = (key === "will_not_apply" && pending === "willnot") || key === pending;
            return (
              <button key={key} disabled={busy} onClick={() => onButton(key)}
                className={cn(
                  "rounded-md border px-[11px] py-[5px] text-[12.5px] font-semibold disabled:opacity-50",
                  active ? "border-brand bg-brand text-white"
                    : danger ? "border-line bg-white text-ink hover:border-[#c0392b] hover:text-[#c0392b]"
                    : "border-line bg-white text-ink hover:border-brand hover:text-brand",
                )}>
                {BUTTON_LABEL[key] || key}
              </button>
            );
          })}
        </div>

        {pending === "willnot" && (
          <div className="mb-[10px] rounded-md border border-dashed border-line bg-white p-[12px]">
            <p className="mb-[8px] text-[12.5px] font-semibold text-ink">You're marking this as “Will not apply”</p>
            <label className={LABEL}>Why? (optional)</label>
            <div className="flex flex-wrap items-center gap-2">
              <select className={cn(FIELD_INPUT, "w-auto min-w-[200px]")} value={rejReason} disabled={busy} onChange={(e) => setRejReason(e.target.value)}>
                <option value="">— select reason —</option>
                {REJECTION_REASONS.map((r) => <option key={r.value} value={r.value}>{r.label}</option>)}
              </select>
              <button className={BTN_PRIMARY} onClick={confirmWillNot} disabled={busy}>Confirm</button>
              <button className={BTN} onClick={() => setPending(null)} disabled={busy}>Cancel</button>
            </div>
          </div>
        )}

        {pending === "withdraw" && (
          <div className="mb-[10px] rounded-md border border-dashed border-line bg-white p-[12px]">
            <p className="mb-[8px] text-[12.5px] font-semibold text-ink">You're withdrawing from this application</p>
            <label className={LABEL}>Why? (optional)</label>
            <div className="flex flex-wrap items-center gap-2">
              <select className={cn(FIELD_INPUT, "w-auto min-w-[200px]")} value={rejReason} disabled={busy} onChange={(e) => setRejReason(e.target.value)}>
                <option value="withdrew">withdrew</option>
                {REJECTION_REASONS.map((r) => <option key={r.value} value={r.value}>{r.label}</option>)}
              </select>
              <button className={BTN_PRIMARY} onClick={confirmWithdraw} disabled={busy}>Confirm</button>
              <button className={BTN} onClick={() => setPending(null)} disabled={busy}>Cancel</button>
            </div>
          </div>
        )}

        {pending === "rejected" && (
          <div className="mb-[10px] rounded-md border border-dashed border-line bg-white p-[12px]">
            <p className="mb-[8px] text-[12.5px] font-semibold text-ink">Mark as rejected</p>
            <label className={LABEL}>What happened? (optional)</label>
            <div className="flex flex-wrap items-center gap-2">
              <input className={cn(FIELD_INPUT, "min-w-[220px] flex-1")} value={rejectNotes} placeholder="Feedback, stage reached, or “no response after X weeks”…" disabled={busy} onChange={(e) => setRejectNotes(e.target.value)} />
              <button className={BTN_PRIMARY} onClick={confirmRejected} disabled={busy}>Confirm</button>
              <button className={BTN} onClick={() => setPending(null)} disabled={busy}>Cancel</button>
            </div>
          </div>
        )}

        {panelToast && <div className={cn("mb-2 rounded-md px-[9px] py-[6px] text-[12px]", TOAST[panelToast.kind])}>{panelToast.text}</div>}

        <div className="mb-[10px] flex flex-wrap items-center gap-2">
          <span className={wcLabel}>Notes</span>
          <input className={cn(FIELD_INPUT, "min-w-[140px] flex-1")} value={noteText} placeholder="Add a note…" disabled={busy} onChange={(e) => setNoteText(e.target.value)} />
          <button className={BTN} onClick={saveNote} disabled={busy}>Save</button>
        </div>

        <div className="mb-[10px] flex flex-wrap items-center gap-2">
          <span className={wcLabel}>Title</span>
          <input className={cn(FIELD_INPUT, "min-w-[140px] flex-1")} value={titleText} placeholder="Display title override…" disabled={busy} onChange={(e) => setTitleText(e.target.value)} />
          <button className={BTN} onClick={saveTitle} disabled={busy}>Override</button>
        </div>

        {hasApplied && (
          <div className="mt-1 border-t border-dashed border-line pt-[10px]">
            <div className="mb-[10px] flex flex-wrap items-center gap-2">
              <span className={wcLabel}>Applied</span>
              <span className="text-[13px]">
                {job.application_date || <span className="text-ink-faint">date not recorded</span>}
                {ageDays !== null && <span className="text-ink-faint"> · {ageDays}d ago</span>}
                {stale && <span className="ml-2 rounded-full bg-[#f6e3d3] px-[7px] py-px text-[10.5px] font-bold uppercase tracking-wide text-[#b4540f]" title={`No movement for ${ageDays} days`}>stale</span>}
                {job.outcome && <span className="ml-2 rounded-[5px] bg-[#f3dede] px-2 py-px text-[11px] font-semibold text-[#9a3636]">{job.outcome.replace(/_/g, " ")}</span>}
              </span>
            </div>
          </div>
        )}

        {toast && <div className={cn("mt-2 rounded-md px-[9px] py-[6px] text-[12px]", TOAST[toast.kind])}>{toast.text}</div>}
      </div>

      {recordedReason && (eff === "will_not_apply" || eff === "rejected") && (
        <div className="mt-[18px] rounded-lg border border-line bg-[#fbfcfe] p-[14px]">
          <h3 className="mb-[8px] text-[11px] font-bold uppercase tracking-wide text-brand">Reason not pursued</h3>
          <span className="rounded-[5px] bg-[#f3e9e9] px-2 py-px text-[12px] font-semibold text-[#9a5252]">{recordedReason.replace(/_/g, " ")}</span>
        </div>
      )}

      <CvTailorSection job={job} onChanged={onChanged} />

      <div className="mt-[18px] rounded-lg border border-line bg-[#fbfcfe] p-[14px]">
        <h3 className="mb-[10px] text-[11px] font-bold uppercase tracking-wide text-brand">
          Flag scoring issue{!!(job.annotations || []).length && ` · ${job.annotations.length} existing`}
        </h3>
        {!!(job.annotations || []).length && (
          <div className="mb-[12px] space-y-[6px]">
            {job.annotations.map((a, i) => <AnnotationItem key={i} a={a} />)}
          </div>
        )}
        <label className={LABEL}>Type</label>
        <select className={cn(FIELD_INPUT, "mb-2")} value={flagType} disabled={busy} onChange={(e) => setFlagType(e.target.value)}>
          {ANNOTATION_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
        </select>
        <label className={LABEL}>Observed (from record)</label>
        <input className={cn(FIELD_INPUT, "mb-2")} value={listText(observed)} readOnly disabled />
        <label className={LABEL}>Expected</label>
        <input className={cn(FIELD_INPUT, "mb-2")} value={expected} placeholder="What it should be…" disabled={busy} onChange={(e) => setExpected(e.target.value)} />
        <label className={LABEL}>Reason</label>
        <textarea className={cn(FIELD_INPUT, "mb-2 font-sans")} rows={2} value={reason} placeholder="Why is the scoring wrong?" disabled={busy} onChange={(e) => setReason(e.target.value)} />
        <div className="flex justify-end">
          <button className={BTN_PRIMARY} onClick={submitFlag} disabled={busy}>Submit Flag</button>
        </div>
        {flagToast && <div className={cn("mt-2 rounded-md px-[9px] py-[6px] text-[12px]", TOAST[flagToast.kind])}>{flagToast.text}</div>}
      </div>
    </>
  );
}

export function DetailPanel({ job, activeCompanies, onClose, onChanged }: { job: Job; activeCompanies: Set<string>; onClose: () => void; onChanged: () => Promise<void> }) {
  const { configured } = useUnlock();
  const niceToHave = [...(job.nice_to_have_technologies || []), ...(job.nice_to_have_competencies || [])];
  // Application context (SPEC_ACTIVE_COMPANY_FILTER §12): on the applied role show the date;
  // on a sibling of an active company show a subtle "active application at X" cue.
  const eff = effectiveStatus(job);
  const isActiveRole = eff === "applied" || eff === "interviewing";
  const companyActive = activeCompanies.has(job.company.toLowerCase().trim());

  return (
    <>
      <div className="fixed inset-0 z-40 bg-[#141a26]/50" onClick={onClose} />
      <aside
        aria-label="role detail"
        className="fixed left-1/2 top-1/2 z-50 h-[80vh] max-h-[92vh] w-[80vw] max-w-[1040px] -translate-x-1/2 -translate-y-1/2 overflow-y-auto rounded-[14px] border border-line bg-panel shadow-[0_24px_70px_rgba(20,26,38,.32)]"
      >
        <div className="sticky top-0 z-10 rounded-t-[14px] border-b border-line bg-panel px-6 py-4">
          <button onClick={onClose} title="Close (Esc)" className="float-right text-[22px] leading-none text-ink-faint hover:text-ink">×</button>
          <div className="text-[12px] uppercase tracking-wide text-ink-soft">{job.company}</div>
          <h2 className="mb-[10px] mt-[2px] text-[19px] font-semibold">{job.title}</h2>
          <div className="flex flex-wrap items-center gap-2">
            <span className={cn("inline-block rounded-full px-2 py-[2px] text-[11px] font-bold", fitBadgeClass(job.fit_label))}>{LABEL_TEXT[job.fit_label] || job.fit_label}</span>
            {job.has_fit_override && <span className="rounded-full bg-[#fdf7e8] px-[7px] py-px text-[10.5px] font-bold uppercase tracking-wide text-[#8a5a14]" title={`Overridden — scorer said ${LABEL_TEXT[job.scorer_fit_label] || job.scorer_fit_label}`}>override</span>}
            <Pill status={effectiveStatus(job)} />
            {job.outcome && <span className="rounded-[5px] bg-[#f3dede] px-2 py-px text-[11px] font-semibold text-[#9a3636]">{job.outcome.replace(/_/g, " ")}</span>}
            {isStaleApplied(job) && <span className="rounded-full bg-[#f6e3d3] px-[7px] py-px text-[10.5px] font-bold uppercase tracking-wide text-[#b4540f]">stale</span>}
            {job.location && <span className="text-ink-faint">{job.location}</span>}
          </div>
          <div className="mt-3 flex gap-[22px]">
            <div><div className="text-[22px] font-extrabold">{job.fit_score}</div><div className="text-[10px] uppercase tracking-wide text-ink-soft">fit score</div></div>
            <div><div className="text-[22px] font-extrabold">{job.priority_score}</div><div className="text-[10px] uppercase tracking-wide text-ink-soft">priority</div></div>
            {job.location_workable && <div><div className="text-[22px] font-extrabold">{job.location_workable}</div><div className="text-[10px] uppercase tracking-wide text-ink-soft">location</div></div>}
          </div>
          {isActiveRole && job.application_date && (
            <div className="mt-[10px] text-[12.5px] text-ink-soft">Applied: {fmtDate(job.application_date)}</div>
          )}
          {!isActiveRole && companyActive && (
            <div className="mt-[10px] text-[12px] text-ink-faint">Active application at {job.company}</div>
          )}
        </div>

        <div className="mx-auto max-w-[760px] px-6 pb-12 pt-2">
          {configured && <WriteControls job={job} companyActive={companyActive} onChanged={onChanged} />}
          {/* Read-only-deploy fallback (no write key): WriteControls is hidden, but the
              cv-tailor snapshot should still be visible when present (job_radar_SPEC §11.3). */}
          {!configured && <CvTailorSection job={job} onChanged={onChanged} />}

          {job.fit_label_reason && <Section title="Assessment"><p className="rounded-md bg-line-soft px-[11px] py-[9px] italic text-ink">{job.fit_label_reason}</p></Section>}
          {!!(job.blocking_constraints || []).length && <Section title="Blocking constraints"><Chips items={job.blocking_constraints} tone="block" /></Section>}
          {!!(job.requirement_gaps || []).length && <Section title="Requirement gaps"><Chips items={job.requirement_gaps} tone="warn" /></Section>}
          {job.notes && <Section title="Notes"><p>{job.notes}</p></Section>}

          <Section title="Extraction">
            <dl className="grid grid-cols-[150px_1fr] gap-x-3 gap-y-1">
              <KV label="Role type" value={listText(job.role_type)} />
              <KV label="Domain" value={listText(job.domain)} />
              <KV label="Seniority" value={job.seniority} />
              <KV label="Technical depth" value={job.technical_depth} />
              <KV label="Remote policy" value={job.remote_policy} />
              <KV label="Company stage" value={job.company_stage} />
              <KV label="Company size" value={job.company_size_signal} />
              <KV label="Experience" value={job.years_experience_required} />
              <KV label="Delivery motion" value={listText(job.delivery_motion)} />
              <KV label="Source" value={job.source_ats} />
              <KV label="First seen" value={fmtDate(job.date_first_seen)} />
              {job.application_date && <KV label="Applied" value={job.application_date} />}
            </dl>
          </Section>

          {!!(job.required_technologies || []).length && <Section title="Required technologies"><Chips items={job.required_technologies} /></Section>}
          {!!(job.required_competencies || []).length && <Section title="Required competencies"><Chips items={job.required_competencies} /></Section>}
          {!!niceToHave.length && <Section title="Nice to have"><Chips items={niceToHave} /></Section>}
          {!!(job.culture_signals || []).length && <Section title="Culture signals"><Chips items={job.culture_signals} /></Section>}
          {job.raw_observations && <Section title="Raw observations"><p className="text-ink-faint">{job.raw_observations}</p></Section>}
          {job.raw_text && <Section title="Full JD text"><div className="max-h-[360px] overflow-y-auto whitespace-pre-wrap break-words rounded-[7px] border border-line-soft bg-[#fbfbfd] p-3 text-[12.5px] leading-[1.55] text-ink-soft">{job.raw_text}</div></Section>}
          {job.source_url && <Section title="Source"><a className="text-[12px] text-brand hover:underline" href={job.source_url} target="_blank" rel="noopener">{job.source_url}</a></Section>}
        </div>
      </aside>
    </>
  );
}
