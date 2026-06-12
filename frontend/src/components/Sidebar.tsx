import { Download } from "lucide-react";
import { YIELD_REPORT_URL, type Job } from "@/lib/api";
import { cn } from "@/lib/utils";
import { fitBadgeClass } from "@/lib/ui";
import { effectiveStatus, FIT_LABELS, LABEL_TEXT, STATUS_ORDER, type Filters } from "@/lib/jobs";
import { AddRoleModal } from "@/components/AddRoleModal";

// Search, fit/priority ranges, location toggle, and frequency-counted checkbox groups for
// fit label / status / domain / role. All Tailwind — no global classes.

function countBy(records: Job[], key: keyof Job): Record<string, number> {
  const m: Record<string, number> = {};
  for (const r of records) {
    const v = r[key] as unknown as string;
    if (v) m[v] = (m[v] || 0) + 1;
  }
  return m;
}
function countByList(records: Job[], key: keyof Job): Record<string, number> {
  const m: Record<string, number> = {};
  for (const r of records) for (const v of (r[key] as unknown as string[]) || []) m[v] = (m[v] || 0) + 1;
  return m;
}
function sortedByFreq(records: Job[], key: keyof Job): string[] {
  const m = countByList(records, key);
  return Object.keys(m).sort((a, b) => m[b] - m[a] || a.localeCompare(b));
}

const FILTER_TITLE = "mb-[6px] block text-[11px] font-bold uppercase tracking-wide text-ink-soft";
const NUM_INPUT = "w-full rounded-md border border-line px-2 py-[6px] text-center text-[13px] focus:border-brand focus:outline-none";

function Checks({
  values, selected, counts, onToggle, renderLabel, scroll,
}: {
  values: string[];
  selected: Set<string>;
  counts: Record<string, number>;
  onToggle: (v: string) => void;
  renderLabel: (v: string) => React.ReactNode;
  scroll?: boolean;
}) {
  if (!values.length) return <span className="text-ink-faint">—</span>;
  return (
    <div className={cn("flex flex-col gap-1", scroll && "max-h-[168px] overflow-y-auto pr-1")}>
      {values.map((v) => (
        <label key={v} className="flex cursor-pointer items-center gap-[7px] py-[1px] text-[12.5px] text-ink">
          <input type="checkbox" className="accent-brand" checked={selected.has(v)} onChange={() => onToggle(v)} />
          {renderLabel(v)}
          <span className="ml-auto text-[11px] text-ink-faint">{counts[v] || 0}</span>
        </label>
      ))}
    </div>
  );
}

export function Sidebar({
  records, filters, setFilters, onReset, onAdded,
}: {
  records: Job[];
  filters: Filters;
  setFilters: (next: Filters) => void;
  onReset: () => void;
  onAdded: () => Promise<void>;
}) {
  const patch = (mut: (f: Filters) => void) => { mut(filters); setFilters({ ...filters }); };
  const toggleIn = (set: Set<string>, v: string) => patch(() => (set.has(v) ? set.delete(v) : set.add(v)));
  const num = (key: "fitMin" | "fitMax" | "priMin" | "priMax", raw: string) => {
    const v = parseInt(raw, 10);
    patch((f) => { (f[key] as number) = Number.isFinite(v) ? v : key.endsWith("Min") ? 1 : 10; });
  };
  const present = (key: keyof Job) => new Set(records.map((r) => r[key] as unknown as string).filter(Boolean));

  // Status filter reads the effective (outcome-aware) status.
  const statusPresent = new Set(records.map(effectiveStatus));
  const statusCounts: Record<string, number> = {};
  for (const r of records) { const s = effectiveStatus(r); statusCounts[s] = (statusCounts[s] || 0) + 1; }

  return (
    <aside className="w-[232px] shrink-0 overflow-y-auto border-r border-line bg-panel px-[14px] pb-7 pt-[14px]">
      <div className="mb-4">
        <input
          type="search" placeholder="Search company or role…" autoComplete="off" value={filters.search}
          className="w-full rounded-md border border-line bg-white px-[10px] py-2 text-[13px] focus:border-brand focus:outline-none"
          onChange={(e) => patch((f) => { f.search = e.target.value.trim().toLowerCase(); })}
        />
      </div>

      <div className="mb-4">
        <label className={FILTER_TITLE}>Fit score</label>
        <div className="flex items-center gap-[6px]">
          <input type="number" min={1} max={10} value={filters.fitMin} aria-label="min fit" className={NUM_INPUT} onChange={(e) => num("fitMin", e.target.value)} />
          <span className="text-ink-faint">–</span>
          <input type="number" min={1} max={10} value={filters.fitMax} aria-label="max fit" className={NUM_INPUT} onChange={(e) => num("fitMax", e.target.value)} />
        </div>
      </div>

      <div className="mb-4">
        <label className={FILTER_TITLE}>Priority score</label>
        <div className="flex items-center gap-[6px]">
          <input type="number" min={1} max={10} value={filters.priMin} aria-label="min priority" className={NUM_INPUT} onChange={(e) => num("priMin", e.target.value)} />
          <span className="text-ink-faint">–</span>
          <input type="number" min={1} max={10} value={filters.priMax} aria-label="max priority" className={NUM_INPUT} onChange={(e) => num("priMax", e.target.value)} />
        </div>
      </div>

      <div className="mb-4">
        <label className="flex cursor-pointer items-center justify-between text-[12.5px] text-ink-soft">
          <span>Location workable only</span>
          <input type="checkbox" className="accent-brand" checked={filters.locWorkable} onChange={(e) => patch((f) => { f.locWorkable = e.target.checked; })} />
        </label>
      </div>

      <div className="mb-4">
        <label className={FILTER_TITLE}>Fit label</label>
        <Checks
          values={FIT_LABELS.filter((l) => present("fit_label").has(l))}
          selected={filters.fitLabels} counts={countBy(records, "fit_label")}
          onToggle={(v) => toggleIn(filters.fitLabels, v)}
          renderLabel={(v) => <span className={cn("inline-block rounded-full px-2 py-[2px] text-[11px] font-bold", fitBadgeClass(v))}>{LABEL_TEXT[v] || v}</span>}
        />
      </div>

      <div className="mb-4">
        <label className={FILTER_TITLE}>Status</label>
        <Checks
          values={STATUS_ORDER.filter((s) => statusPresent.has(s))}
          selected={filters.statuses} counts={statusCounts}
          onToggle={(v) => toggleIn(filters.statuses, v)}
          renderLabel={(v) => v}
        />
        <p className="mt-[6px] text-[10.5px] leading-[1.35] text-ink-faint">rejected &amp; archived are hidden by default — tick to show</p>
      </div>

      <div className="mb-4">
        <label className={FILTER_TITLE}>Domain</label>
        <Checks scroll
          values={sortedByFreq(records, "domain")}
          selected={filters.domains} counts={countByList(records, "domain")}
          onToggle={(v) => toggleIn(filters.domains, v)} renderLabel={(v) => v}
        />
      </div>

      <div className="mb-4">
        <label className={FILTER_TITLE}>Role type</label>
        <Checks scroll
          values={sortedByFreq(records, "role_type")}
          selected={filters.roles} counts={countByList(records, "role_type")}
          onToggle={(v) => toggleIn(filters.roles, v)} renderLabel={(v) => v}
        />
      </div>

      <button onClick={onReset} className="mt-1 w-full rounded-md border border-line bg-white py-[7px] text-[12.5px] text-ink-soft hover:bg-line-soft">
        Reset filters
      </button>

      {/* Read-only company yield report (BACKLOG_YIELD_TRACKING) — public download, no unlock. */}
      <a
        href={YIELD_REPORT_URL} download
        className="mt-[10px] flex w-full items-center justify-center gap-[6px] rounded-md border border-line bg-white py-[7px] text-[12.5px] text-ink-soft hover:bg-line-soft"
      >
        <Download className="h-3.5 w-3.5" /> Yield report
      </a>

      {/* Manual JD entry (job_radar_SPEC §11.1) — owner-only; the modal hides itself unless unlocked. */}
      <AddRoleModal onAdded={onAdded} />
    </aside>
  );
}
