import { useEffect, useState } from "react";
import { api, ApiError, type Job } from "@/lib/api";
import { fmtDate, LABEL_TEXT, listText } from "@/lib/jobs";
import { useUnlock } from "@/components/UnlockProvider";

// Detail drawer — read fields ported from ui/app.js openDrawer(), PLUS owner-only write
// controls (job_radar_SPEC §10.6). Controls are hidden when writes aren't configured; when
// configured-but-locked, the first write opens the unlock dialog via requestUnlock().

type Toast = { kind: "ok" | "warn" | "err"; text: string } | null;

// annotation_type → (record field it concerns, the observed value to prefill).
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

const ANNOTATION_TYPES = [
  "role_type_incorrect", "domain_incorrect", "seniority_incorrect", "technical_depth_incorrect",
  "fit_score_disagree", "should_be_blocked", "false_block", "extraction_other",
];

function KV({ label, value }: { label: string; value: string }) {
  if (!value) return null;
  return (<><dt>{label}</dt><dd>{value}</dd></>);
}
function Chips({ items, cls = "" }: { items: string[]; cls?: string }) {
  return <div className="chips">{items.map((it, i) => <span key={i} className={`chip ${cls}`}>{it}</span>)}</div>;
}
function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return <div className="dsection"><h3>{title}</h3>{children}</div>;
}

function WriteControls({ job, onChanged }: { job: Job; onChanged: () => Promise<void> }) {
  const { requestUnlock } = useUnlock();
  const [toast, setToast] = useState<Toast>(null);
  const [busy, setBusy] = useState(false);
  const [noteText, setNoteText] = useState(job.notes || "");
  const [titleText, setTitleText] = useState(job.title || "");
  const [flagType, setFlagType] = useState(ANNOTATION_TYPES[0]);
  const [expected, setExpected] = useState("");
  const [reason, setReason] = useState("");

  // Reset the editable fields when the drawer switches to a different job.
  useEffect(() => {
    setNoteText(job.notes || ""); setTitleText(job.title || "");
    setFlagType(ANNOTATION_TYPES[0]); setExpected(""); setReason(""); setToast(null);
  }, [job.job_id]); // eslint-disable-line react-hooks/exhaustive-deps

  async function guarded(run: () => Promise<Toast>) {
    if (!(await requestUnlock())) return; // opens dialog if locked; false = cancelled
    setBusy(true);
    try {
      const t = await run();
      setToast(t);
      await onChanged();
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : e instanceof Error ? e.message : String(e);
      setToast({ kind: "err", text: msg });
    } finally {
      setBusy(false);
    }
  }

  const setStatus = (status: string) => guarded(async () => {
    if (status === "archived" && !window.confirm("Archive this role?")) return null;
    const res = await api.setStatus(job.job_id, status);
    return res.warning
      ? { kind: "warn", text: `Saved · ${res.warning}` }
      : { kind: "ok", text: `Status → ${status}` };
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

  const submitFlag = () => guarded(async () => {
    if (!reason.trim()) return { kind: "err", text: "Reason is required" };
    const { field, observed } = observedFor(flagType, job);
    await api.flagAnnotation({
      job_id: job.job_id, annotation_type: flagType, field,
      observed, expected: expected.trim(), reason: reason.trim(),
    });
    setExpected(""); setReason("");
    return { kind: "ok", text: "Flag submitted" };
  });

  const { observed } = observedFor(flagType, job);
  const STATUS_BTNS: Array<{ label: string; value: string; danger?: boolean }> = [
    { label: "Review", value: "review" },
    { label: "Shortlist", value: "shortlisted" },
    { label: "Apply", value: "applied" },
    { label: "Archive", value: "archived", danger: true },
  ];

  return (
    <>
      <div className="write-panel">
        <h3>Workflow</h3>
        <div className="wc-row">
          <span className="wc-label">Status</span>
          <div className="wc-status-btns">
            {STATUS_BTNS.map((b) => (
              <button key={b.value} disabled={busy}
                className={[b.danger ? "danger" : "", job.application_status === b.value ? "current" : ""].filter(Boolean).join(" ") || undefined}
                onClick={() => setStatus(b.value)}>
                {b.label}
              </button>
            ))}
          </div>
        </div>
        <div className="wc-row">
          <span className="wc-label">Notes</span>
          <input className="wc-input" value={noteText} placeholder="Add a note…"
            onChange={(e) => setNoteText(e.target.value)} disabled={busy} />
          <button className="wc-status-btns" style={{ padding: "5px 11px" }} onClick={saveNote} disabled={busy}>Save</button>
        </div>
        <div className="wc-row">
          <span className="wc-label">Title</span>
          <input className="wc-input" value={titleText} placeholder="Display title override…"
            onChange={(e) => setTitleText(e.target.value)} disabled={busy} />
          <button className="wc-status-btns" style={{ padding: "5px 11px" }} onClick={saveTitle} disabled={busy}>Override</button>
        </div>
        {toast && <div className={`wc-toast ${toast.kind}`}>{toast.text}</div>}
      </div>

      <div className="write-panel flag-form">
        <h3>Flag scoring issue</h3>
        <label>Type</label>
        <select value={flagType} onChange={(e) => setFlagType(e.target.value)} disabled={busy}>
          {ANNOTATION_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
        </select>
        <label>Observed (from record)</label>
        <input value={listText(observed)} readOnly disabled />
        <label>Expected</label>
        <input value={expected} placeholder="What it should be…" onChange={(e) => setExpected(e.target.value)} disabled={busy} />
        <label>Reason</label>
        <textarea value={reason} rows={2} placeholder="Why is the scoring wrong?" onChange={(e) => setReason(e.target.value)} disabled={busy} />
        <button className="wc-status-btns" style={{ padding: "6px 12px" }} onClick={submitFlag} disabled={busy}>Submit Flag</button>
      </div>
    </>
  );
}

export function DetailPanel({ job, onClose, onChanged }: { job: Job; onClose: () => void; onChanged: () => Promise<void> }) {
  const { configured } = useUnlock();
  const niceToHave = [...(job.nice_to_have_technologies || []), ...(job.nice_to_have_competencies || [])];

  return (
    <>
      <div className="drawer-scrim" onClick={onClose} />
      <aside className="drawer" aria-label="role detail">
        <div className="dh">
          <button className="close" title="Close (Esc)" onClick={onClose}>×</button>
          <div className="co">{job.company}</div>
          <h2>{job.title}</h2>
          <div className="dh-meta">
            <span className={`badge ${job.fit_label}`}>{LABEL_TEXT[job.fit_label] || job.fit_label}</span>
            <span className={`pill ${job.application_status}`}>{job.application_status}</span>
            {job.location && <span className="muted">{job.location}</span>}
          </div>
          <div className="scores">
            <div className="s"><div className="n">{job.fit_score}</div><div className="l">fit score</div></div>
            <div className="s"><div className="n">{job.priority_score}</div><div className="l">priority</div></div>
            {job.location_workable && <div className="s"><div className="n">{job.location_workable}</div><div className="l">location</div></div>}
          </div>
        </div>

        <div className="dbody">
          {configured && <WriteControls job={job} onChanged={onChanged} />}

          {job.fit_label_reason && <Section title="Assessment"><p className="reason">{job.fit_label_reason}</p></Section>}
          {!!(job.blocking_constraints || []).length && <Section title="Blocking constraints"><Chips items={job.blocking_constraints} cls="block" /></Section>}
          {!!(job.requirement_gaps || []).length && <Section title="Requirement gaps"><Chips items={job.requirement_gaps} cls="warn" /></Section>}
          {job.notes && <Section title="Notes"><p>{job.notes}</p></Section>}

          <Section title="Extraction">
            <dl className="kv">
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
          {job.raw_observations && <Section title="Raw observations"><p className="muted">{job.raw_observations}</p></Section>}
          {job.raw_text && <Section title="Full JD text"><div className="jd-text">{job.raw_text}</div></Section>}
          {job.source_url && <Section title="Source"><a className="link-out" href={job.source_url} target="_blank" rel="noopener">{job.source_url}</a></Section>}
        </div>
      </aside>
    </>
  );
}
