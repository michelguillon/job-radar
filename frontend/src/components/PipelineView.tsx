import type { Job } from "@/lib/api";
import { LABEL_TEXT, STATUS_ORDER } from "@/lib/jobs";

// Ported from ui/app.js renderPipeline(): cards grouped by application_status in funnel
// order, priority-sorted within each lane. Status changes happen in the detail panel
// (no drag-to-status in Phase 6 — SPEC §10.7).
export function PipelineView({ rows, onOpen }: { rows: Job[]; onOpen: (job: Job) => void }) {
  const byStatus: Record<string, Job[]> = {};
  for (const r of rows) (byStatus[r.application_status] ||= []).push(r);

  const order = STATUS_ORDER.filter((s) => byStatus[s]);
  if (!order.length) return <p className="empty">No roles match the current filters.</p>;

  return (
    <div>
      {order.map((status) => {
        const group = byStatus[status]
          .slice()
          .sort((a, b) => b.priority_score - a.priority_score || b.fit_score - a.fit_score);
        return (
          <div className="pipe-group" key={status}>
            <div className="pipe-head">
              <span>{status}</span>
              <span className="count">{group.length}</span>
              <span className="rule" />
            </div>
            {group.map((r) => (
              <div key={r.job_id}
                className={"pipe-card" + (r.fit_label === "blocked_fit" ? " is-blocked" : "")}
                onClick={() => onOpen(r)}>
                <div className="pc-score">{r.priority_score}</div>
                <div className="pc-main">
                  <div className="pc-co">{r.company}</div>
                  <div className="pc-role">{r.title}</div>
                </div>
                <span className={`badge ${r.fit_label}`}>{LABEL_TEXT[r.fit_label] || r.fit_label}</span>
              </div>
            ))}
          </div>
        );
      })}
    </div>
  );
}
