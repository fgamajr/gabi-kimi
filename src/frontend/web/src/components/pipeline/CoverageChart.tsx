import type { MonthData } from "@/types/pipeline";
import * as Progress from "@radix-ui/react-progress";

interface CoverageChartProps {
  months: MonthData[];
}

export default function CoverageChart({ months }: CoverageChartProps) {
  const byYear = new Map<number, { verified: number; total: number }>();

  for (const m of months) {
    const year = parseInt(m.year_month.slice(0, 4), 10);
    if (!byYear.has(year)) byYear.set(year, { verified: 0, total: 0 });
    const entry = byYear.get(year)!;
    entry.total += 1;
    if (m.status === "VERIFIED") entry.verified += 1;
  }

  const years = Array.from(byYear.entries()).sort(([a], [b]) => b - a);

  if (years.length === 0) {
    return (
      <p className="text-sm text-text-tertiary">No coverage data available.</p>
    );
  }

  return (
    <div className="space-y-3">
      {years.map(([year, { verified, total }]) => {
        const pct = total > 0 ? Math.round((verified / total) * 100) : 0;
        return (
          <div key={year} className="space-y-1">
            <div className="flex items-center justify-between text-xs">
              <span className="font-medium text-text-secondary">{year}</span>
              <span className="text-text-tertiary">
                {verified}/{total} ({pct}%)
              </span>
            </div>
            <Progress.Root
              value={pct}
              className="relative h-2 w-full overflow-hidden rounded-full bg-muted"
            >
              <Progress.Indicator
                className="h-full rounded-full bg-emerald-500 transition-all duration-300"
                style={{ width: `${pct}%` }}
              />
            </Progress.Root>
          </div>
        );
      })}
    </div>
  );
}
