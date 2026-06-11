import type { Job } from "@/lib/api";
import { cn } from "@/lib/utils";
import { fitBadgeClass, statusPillClass } from "@/lib/ui";
import { daysSince, effectiveStatus, fmtDate, isStaleApplied, LABEL_TEXT, sortRows, type Sort } from "@/lib/jobs";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

// Sortable, filterable table. Column widths are pinned (table-fixed + <colgroup>) so headers
// always sit over their column. blocked_fit rows recede (muted + struck-through role).
const COLUMNS: Array<{ label: string; num?: boolean; sort?: keyof Job; width: string }> = [
  { label: "Company", sort: "company", width: "11%" },
  { label: "Role", sort: "title", width: "26%" },
  { label: "Fit", sort: "fit_label", width: "8%" },
  { label: "Score", num: true, sort: "fit_score", width: "6%" },
  { label: "Pri", num: true, sort: "priority_score", width: "5%" },
  { label: "Location", sort: "location", width: "16%" },
  { label: "Status", sort: "application_status", width: "10%" },
  { label: "First seen", sort: "date_first_seen", width: "9%" },
  { label: "Link", width: "9%" },
];

function Badge({ label }: { label: string }) {
  return (
    <span className={cn("inline-block whitespace-nowrap rounded-full px-2 py-[2px] text-[11px] font-bold", fitBadgeClass(label))}>
      {LABEL_TEXT[label] || label}
    </span>
  );
}

export function BrowseView({
  rows, sort, onSort, onOpen,
}: {
  rows: Job[];
  sort: Sort;
  onSort: (key: keyof Job) => void;
  onOpen: (job: Job) => void;
}) {
  const sorted = sortRows(rows, sort);
  return (
    <div>
      <Table>
        <colgroup>{COLUMNS.map((c) => <col key={c.label} style={{ width: c.width }} />)}</colgroup>
        <TableHeader>
          <TableRow className="border-b-line">
            {COLUMNS.map((c) => {
              const on = !!c.sort && c.sort === sort.key;
              return (
                <TableHead
                  key={c.label}
                  onClick={c.sort ? () => onSort(c.sort!) : undefined}
                  className={cn(c.num && "text-right", c.sort ? "cursor-pointer hover:text-ink" : "cursor-default")}
                >
                  {c.label}
                  {on && <span className="text-brand">{sort.dir === "asc" ? " ▴" : " ▾"}</span>}
                </TableHead>
              );
            })}
          </TableRow>
        </TableHeader>
        <TableBody>
          {sorted.map((r) => {
            const blocked = r.fit_label === "blocked_fit";
            return (
              <TableRow
                key={r.job_id}
                onClick={(e) => { if ((e.target as HTMLElement).tagName !== "A") onOpen(r); }}
                className={cn("cursor-pointer hover:bg-rowhover", blocked && "text-ink-faint")}
              >
                <TableCell className={cn("font-semibold", blocked && "font-medium")}>{r.company}</TableCell>
                <TableCell className="whitespace-normal break-words">
                  <span className={cn(blocked && "line-through decoration-ink-faint")}>{r.title}</span>
                  {r.annotation_count > 0 && (
                    <span className="ml-[5px] align-middle text-[11px] text-[#b4540f]" title={`${r.annotation_count} scoring flag${r.annotation_count > 1 ? "s" : ""}`}>⚠</span>
                  )}
                  {r.has_fit_override && (
                    <span className="ml-[5px] align-middle rounded-full bg-[#fdf7e8] px-[5px] py-px text-[9.5px] font-bold uppercase tracking-wide text-[#8a5a14]" title={`Fit overridden — scorer said ${r.scorer_fit_label}`}>ovr</span>
                  )}
                </TableCell>
                <TableCell><Badge label={r.fit_label} /></TableCell>
                <TableCell className="text-right text-[15px] font-bold tabular-nums">{r.fit_score}</TableCell>
                <TableCell className="text-right tabular-nums text-ink-soft">{r.priority_score}</TableCell>
                <TableCell className="whitespace-normal break-words text-ink-soft">{r.location || "—"}</TableCell>
                <TableCell>
                  <span className={cn("inline-block rounded-[5px] px-2 py-[2px] text-[11px] font-semibold", statusPillClass(effectiveStatus(r)))}>
                    {effectiveStatus(r)}
                  </span>
                  {isStaleApplied(r) && (
                    <span className="ml-[5px] align-middle text-[11px] text-[#d07a1a]" title={`Applied ${daysSince(r.application_date)}d ago — no movement`}>●</span>
                  )}
                </TableCell>
                <TableCell className="whitespace-nowrap tabular-nums text-ink-faint">{fmtDate(r.date_first_seen)}</TableCell>
                <TableCell>
                  {r.source_url && (
                    <a className="text-[12px] text-brand hover:underline" href={r.source_url} target="_blank" rel="noopener">open ↗</a>
                  )}
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
      {!sorted.length && <p className="p-10 text-center text-ink-faint">No roles match the current filters.</p>}
    </div>
  );
}
