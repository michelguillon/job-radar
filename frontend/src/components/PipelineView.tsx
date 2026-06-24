import { useState } from "react";
import type { Job } from "@/lib/api";
import { cn } from "@/lib/utils";
import { fitBadgeClass } from "@/lib/ui";
import { effectiveStatus, LABEL_TEXT, PIPELINE_ORDER } from "@/lib/jobs";

// Cards grouped by effective status in pipeline order (active stages above the new backlog,
// terminal at the bottom). Status changes happen in the detail panel (no drag in Phase 6).
// Each stage collapses independently — all collapsed by default (session-only, not persisted)
// so you scan one stage at a time; the title + count stay visible while collapsed.
export function PipelineView({ rows, onOpen }: { rows: Job[]; onOpen: (job: Job) => void }) {
  const [open, setOpen] = useState<Set<string>>(new Set());
  const toggle = (status: string) =>
    setOpen((prev) => {
      const next = new Set(prev);
      next.has(status) ? next.delete(status) : next.add(status);
      return next;
    });

  const byStatus: Record<string, Job[]> = {};
  for (const r of rows) (byStatus[effectiveStatus(r)] ||= []).push(r);

  const order = PIPELINE_ORDER.filter((s) => byStatus[s]);
  if (!order.length) return <p className="p-10 text-center text-ink-faint">No roles match the current filters.</p>;

  return (
    <div>
      {order.map((status) => {
        const expanded = open.has(status);
        const group = byStatus[status]
          .slice()
          .sort((a, b) => b.priority_score - a.priority_score || b.fit_score - a.fit_score);
        return (
          <div className="mb-[22px]" key={status}>
            <button
              type="button"
              onClick={() => toggle(status)}
              aria-expanded={expanded}
              className="mb-2 flex w-full select-none items-center gap-[10px] text-[13px] font-bold text-ink"
            >
              <span className={cn("text-[10px] text-ink-faint transition-transform", expanded && "rotate-90")}>▶</span>
              <span className="hover:text-brand">{status}</span>
              <span className="font-semibold text-ink-faint">{group.length}</span>
              <span className="h-px flex-1 bg-line" />
            </button>
            {expanded && group.map((r) => {
              const blocked = r.fit_label === "blocked_fit";
              return (
                <div
                  key={r.job_id}
                  onClick={() => onOpen(r)}
                  className={cn(
                    "mb-[6px] flex cursor-pointer items-center gap-3 rounded-[7px] border border-line-soft bg-panel px-3 py-[9px] hover:border-brand hover:bg-rowhover",
                    blocked && "opacity-60",
                  )}
                >
                  <div className="min-w-[26px] text-center text-[15px] font-bold">{r.priority_score}</div>
                  <div className="min-w-0 flex-1">
                    <div className="font-semibold">{r.company}</div>
                    <div className={cn("truncate text-[12.5px] text-ink-soft", blocked && "line-through")}>{r.title}</div>
                  </div>
                  <span className={cn("inline-block whitespace-nowrap rounded-full px-2 py-[2px] text-[11px] font-bold", fitBadgeClass(r.fit_label))}>
                    {LABEL_TEXT[r.fit_label] || r.fit_label}
                  </span>
                </div>
              );
            })}
          </div>
        );
      })}
    </div>
  );
}
