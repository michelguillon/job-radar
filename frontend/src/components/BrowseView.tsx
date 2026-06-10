import type { Job } from "@/lib/api";
import { daysSince, fmtDate, isStaleApplied, LABEL_TEXT, sortRows, type Sort } from "@/lib/jobs";

// Ported from ui/app.js renderGrid(): sortable columns, fit badge, blocked_fit muting,
// row click → detail. Link cell click is swallowed so it doesn't open the drawer.
const COLUMNS: Array<{ key: keyof Job | null; label: string; num?: boolean; sort?: keyof Job }> = [
  { key: "company", label: "Company", sort: "company" },
  { key: "title", label: "Role", sort: "title" },
  { key: "fit_label", label: "Fit", sort: "fit_label" },
  { key: "fit_score", label: "Score", num: true, sort: "fit_score" },
  { key: "priority_score", label: "Pri", num: true, sort: "priority_score" },
  { key: "location", label: "Location", sort: "location" },
  { key: "application_status", label: "Status", sort: "application_status" },
  { key: "date_first_seen", label: "First seen", sort: "date_first_seen" },
  { key: null, label: "Link" },
];

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
      <table className="grid">
        <thead>
          <tr>
            {COLUMNS.map((c) => {
              const on = !!c.sort && c.sort === sort.key;
              const cls = [c.num ? "num" : "", on ? "sorted" : "", on && sort.dir === "asc" ? "asc" : ""]
                .filter(Boolean).join(" ");
              return (
                <th key={c.label} className={cls || undefined}
                  onClick={c.sort ? () => onSort(c.sort!) : undefined}
                  style={c.sort ? undefined : { cursor: "default" }}>
                  {c.label}
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          {sorted.map((r) => (
            <tr key={r.job_id} className={r.fit_label === "blocked_fit" ? "is-blocked" : undefined}
              onClick={(e) => { if ((e.target as HTMLElement).tagName !== "A") onOpen(r); }}>
              <td className="company">{r.company}</td>
              <td className="role"><span className="role-text">{r.title}</span></td>
              <td><span className={`badge ${r.fit_label}`}>{LABEL_TEXT[r.fit_label] || r.fit_label}</span></td>
              <td className="num score-cell">{r.fit_score}</td>
              <td className="num pri-cell">{r.priority_score}</td>
              <td className="loc">{r.location || "—"}</td>
              <td>
                <span className={`pill ${r.application_status}`}>{r.application_status}</span>
                {isStaleApplied(r) && (
                  <span className="stale-dot" title={`Applied ${daysSince(r.application_date)}d ago — no movement`}>●</span>
                )}
              </td>
              <td className="seen">{fmtDate(r.date_first_seen)}</td>
              <td>
                {r.source_url && (
                  <a className="link-out" href={r.source_url} target="_blank" rel="noopener">open ↗</a>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {!sorted.length && <p className="empty">No roles match the current filters.</p>}
    </div>
  );
}
