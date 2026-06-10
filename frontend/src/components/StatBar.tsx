import type { IndexStats } from "@/lib/api";
import { STATUS_ORDER } from "@/lib/jobs";

// Ported from ui/app.js renderStatbar(): totals, strong-fit count, in-pipeline count,
// cost-to-date, and the fit_score 1–10 sparkline.
function Stat({ value, label }: { value: string | number; label: string }) {
  return (
    <div className="stat">
      <span className="v">{value}</span>
      <span className="k">{label}</span>
    </div>
  );
}

export function StatBar({ stats }: { stats: IndexStats | null }) {
  if (!stats) return null;
  const strong = stats.by_fit_label?.strong_fit ?? 0;
  const active = STATUS_ORDER
    .filter((k) => !["new", "rejected", "archived"].includes(k))
    .reduce((n, k) => n + (stats.by_application_status?.[k] ?? 0), 0);

  const dist = stats.fit_score_distribution || {};
  const max = Math.max(1, ...Object.values(dist));

  return (
    <div className="statbar">
      <Stat value={stats.total} label="roles" />
      <Stat value={strong} label="strong fit" />
      <Stat value={active} label="in pipeline" />
      {typeof stats.cost_to_date_usd === "number" && (
        <Stat value={`$${stats.cost_to_date_usd.toFixed(2)}`} label="cost to date" />
      )}
      <div className="stat">
        <div className="spark" title="fit_score distribution (1–10)">
          {Array.from({ length: 10 }, (_, i) => {
            const score = i + 1;
            const c = dist[String(score)] ?? 0;
            return (
              <div
                key={score}
                className={"bar" + (score < 6 ? " lo" : "")}
                style={{ height: `${Math.round((c / max) * 26)}px` }}
                title={`score ${score}: ${c}`}
              />
            );
          })}
        </div>
        <span className="k">score 1–10</span>
      </div>
    </div>
  );
}
