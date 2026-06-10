import type { Job } from "@/lib/api";
import { FIT_LABELS, LABEL_TEXT, STATUS_ORDER, type Filters } from "@/lib/jobs";

// Ported from ui/app.js buildFilterControls(): search, fit/priority ranges, location
// toggle, and frequency-counted checkbox groups for fit label / status / domain / role.

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

function Checks({
  values, selected, counts, onToggle, renderLabel,
}: {
  values: string[];
  selected: Set<string>;
  counts: Record<string, number>;
  onToggle: (v: string) => void;
  renderLabel: (v: string) => React.ReactNode;
  scroll?: boolean;
}) {
  if (!values.length) return <span className="muted">—</span>;
  return (
    <>
      {values.map((v) => (
        <label key={v}>
          <input type="checkbox" checked={selected.has(v)} onChange={() => onToggle(v)} />
          {renderLabel(v)}
          <span className="ct">{counts[v] || 0}</span>
        </label>
      ))}
    </>
  );
}

export function Sidebar({
  records, filters, setFilters, onReset,
}: {
  records: Job[];
  filters: Filters;
  setFilters: (next: Filters) => void;
  onReset: () => void;
}) {
  // Mutating a shared filters object then handing back a shallow clone keeps the Set
  // identities the views read; React re-renders because the wrapper object is new.
  const patch = (mut: (f: Filters) => void) => {
    mut(filters);
    setFilters({ ...filters });
  };
  const toggleIn = (set: Set<string>, v: string) => patch(() => (set.has(v) ? set.delete(v) : set.add(v)));
  const num = (key: "fitMin" | "fitMax" | "priMin" | "priMax", raw: string) => {
    const v = parseInt(raw, 10);
    patch((f) => { (f[key] as number) = Number.isFinite(v) ? v : key.endsWith("Min") ? 1 : 10; });
  };

  const present = (key: keyof Job) => new Set(records.map((r) => r[key] as unknown as string).filter(Boolean));

  return (
    <aside className="sidebar">
      <div className="filter-block">
        <input
          className="search-input" type="search" placeholder="Search company or role…"
          autoComplete="off" value={filters.search}
          onChange={(e) => patch((f) => { f.search = e.target.value.trim().toLowerCase(); })}
        />
      </div>

      <div className="filter-block">
        <label className="filter-title">Fit score</label>
        <div className="range-row">
          <input type="number" min={1} max={10} value={filters.fitMin} aria-label="min fit"
            onChange={(e) => num("fitMin", e.target.value)} />
          <span className="range-sep">–</span>
          <input type="number" min={1} max={10} value={filters.fitMax} aria-label="max fit"
            onChange={(e) => num("fitMax", e.target.value)} />
        </div>
      </div>

      <div className="filter-block">
        <label className="filter-title">Priority score</label>
        <div className="range-row">
          <input type="number" min={1} max={10} value={filters.priMin} aria-label="min priority"
            onChange={(e) => num("priMin", e.target.value)} />
          <span className="range-sep">–</span>
          <input type="number" min={1} max={10} value={filters.priMax} aria-label="max priority"
            onChange={(e) => num("priMax", e.target.value)} />
        </div>
      </div>

      <div className="filter-block">
        <label className="filter-title toggle-row">
          <span>Location workable only</span>
          <input type="checkbox" checked={filters.locWorkable}
            onChange={(e) => patch((f) => { f.locWorkable = e.target.checked; })} />
        </label>
      </div>

      <div className="filter-block">
        <label className="filter-title">Fit label</label>
        <div className="checks">
          <Checks
            values={FIT_LABELS.filter((l) => present("fit_label").has(l))}
            selected={filters.fitLabels} counts={countBy(records, "fit_label")}
            onToggle={(v) => toggleIn(filters.fitLabels, v)}
            renderLabel={(v) => <span className={`badge ${v}`}>{LABEL_TEXT[v] || v}</span>}
          />
        </div>
      </div>

      <div className="filter-block">
        <label className="filter-title">Status</label>
        <div className="checks">
          <Checks
            values={STATUS_ORDER.filter((s) => present("application_status").has(s))}
            selected={filters.statuses} counts={countBy(records, "application_status")}
            onToggle={(v) => toggleIn(filters.statuses, v)}
            renderLabel={(v) => v}
          />
        </div>
      </div>

      <div className="filter-block">
        <label className="filter-title">Domain</label>
        <div className="checks scroll">
          <Checks
            values={sortedByFreq(records, "domain")}
            selected={filters.domains} counts={countByList(records, "domain")}
            onToggle={(v) => toggleIn(filters.domains, v)}
            renderLabel={(v) => v}
          />
        </div>
      </div>

      <div className="filter-block">
        <label className="filter-title">Role type</label>
        <div className="checks scroll">
          <Checks
            values={sortedByFreq(records, "role_type")}
            selected={filters.roles} counts={countByList(records, "role_type")}
            onToggle={(v) => toggleIn(filters.roles, v)}
            renderLabel={(v) => v}
          />
        </div>
      </div>

      <button className="reset" onClick={onReset}>Reset filters</button>
    </aside>
  );
}
