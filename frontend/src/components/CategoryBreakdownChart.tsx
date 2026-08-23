// Code Sonar — findings-by-category breakdown chart.
//
// Renders a compact horizontal bar list summarising the distribution
// of findings across the six Finding categories. Sorts categories by
// count descending so the highest-debt areas surface at the top.
//
// Reads from the `findings_by_category` field on the scan response,
// which is already populated by the backend's scoring engine and is
// guaranteed to be a complete Record<Category, number>.

import type { Category } from "../api/analyzers";

interface CategoryBreakdownChartProps {
  findingsByCategory: Record<Category, number>;
}

interface Row {
  category: Category;
  count: number;
}

export function CategoryBreakdownChart({
  findingsByCategory,
}: CategoryBreakdownChartProps) {
  const rows: Row[] = (Object.keys(findingsByCategory) as Category[])
    .map((c) => ({ category: c, count: findingsByCategory[c] ?? 0 }))
    .sort((a, b) => b.count - a.count);

  const total = rows.reduce((sum, r) => sum + r.count, 0);
  const max = rows.reduce((m, r) => (r.count > m ? r.count : m), 0);

  return (
    <section className="rounded-lg border border-slate-800 bg-slate-800/40 p-6">
      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-lg font-semibold">Findings by category</h2>
        <span className="text-xs uppercase tracking-wide text-slate-400">
          {total} total
        </span>
      </div>

      {total === 0 ? (
        <p className="text-sm text-slate-400">
          No findings across any category. Looks clean.
        </p>
      ) : (
        <div className="space-y-3" data-testid="category-breakdown-rows">
          {rows.map((r) => {
            const pct = max > 0 ? (r.count / max) * 100 : 0;
            return (
              <div
                key={r.category}
                data-testid={`category-row-${r.category}`}
                className="flex items-center gap-3"
              >
                <div className="w-32 shrink-0 text-xs text-slate-300">
                  {r.category}
                </div>
                <div className="relative h-3 flex-1 overflow-hidden rounded-full bg-slate-700">
                  <div
                    className="absolute inset-y-0 left-0 rounded-full bg-sky-500"
                    style={{ width: `${pct}%` }}
                    aria-label={`${r.category}: ${r.count} findings`}
                  />
                </div>
                <div className="w-12 shrink-0 text-right font-mono text-xs text-slate-200">
                  {r.count}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}
