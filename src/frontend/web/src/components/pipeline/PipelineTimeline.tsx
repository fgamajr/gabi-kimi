import { useState, useRef, useMemo } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import { usePipelineMonths } from "@/hooks/usePipeline";
import type { MonthData } from "@/types/pipeline";
import MonthCard from "./MonthCard";
import { cn } from "@/lib/utils";
import WorkerUnavailableState from "./WorkerUnavailableState";

const CURRENT_YEAR = new Date().getFullYear();
const YEARS = Array.from({ length: CURRENT_YEAR - 2002 + 1 }, (_, i) => CURRENT_YEAR - i);

function groupByMonth(data: MonthData[]): Map<string, MonthData[]> {
  const map = new Map<string, MonthData[]>();
  for (const d of data) {
    const existing = map.get(d.year_month);
    if (existing) {
      existing.push(d);
    } else {
      map.set(d.year_month, [d]);
    }
  }
  return map;
}

export default function PipelineTimeline() {
  const [selectedYear, setSelectedYear] = useState<number>(CURRENT_YEAR);
  const { data: months, isLoading, isError, error } = usePipelineMonths(selectedYear);
  const parentRef = useRef<HTMLDivElement>(null);

  const grouped = useMemo(() => {
    if (!months) return [];
    const map = groupByMonth(months);
    return Array.from(map.entries())
      .sort(([a], [b]) => b.localeCompare(a));
  }, [months]);

  const virtualizer = useVirtualizer({
    count: grouped.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => 120,
    overscan: 5,
  });

  return (
    <div className="space-y-4">
      {/* Year filter */}
      <div className="flex gap-1 overflow-x-auto pb-1">
        {YEARS.map((year) => (
          <button
            key={year}
            onClick={() => setSelectedYear(year)}
            className={cn(
              "shrink-0 rounded-lg px-3 py-1.5 text-xs font-medium transition-colors",
              year === selectedYear
                ? "bg-primary text-primary-foreground"
                : "bg-muted text-text-tertiary hover:text-text-secondary"
            )}
          >
            {year}
          </button>
        ))}
      </div>

      {/* Content */}
      {isLoading ? (
        <div className="space-y-3">
          {[1, 2, 3, 4].map((i) => (
            <div key={i} className="h-16 rounded-xl bg-surface-elevated animate-pulse" />
          ))}
        </div>
      ) : isError ? (
        <WorkerUnavailableState
          title="Timeline indisponível"
          message={(error as Error | undefined)?.message}
        />
      ) : grouped.length === 0 ? (
        <div className="flex items-center justify-center py-20">
          <p className="text-sm text-text-tertiary">
            No data for {selectedYear}.
          </p>
        </div>
      ) : (
        <div
          ref={parentRef}
          className="max-h-[calc(100vh-280px)] overflow-auto rounded-xl"
        >
          <div
            style={{ height: `${virtualizer.getTotalSize()}px`, position: "relative" }}
          >
            {virtualizer.getVirtualItems().map((virtualItem) => {
              const [month, files] = grouped[virtualItem.index];
              return (
                <div
                  key={virtualItem.key}
                  data-index={virtualItem.index}
                  ref={virtualizer.measureElement}
                  style={{
                    position: "absolute",
                    top: 0,
                    left: 0,
                    width: "100%",
                    transform: `translateY(${virtualItem.start}px)`,
                  }}
                  className="pb-2"
                >
                  <MonthCard month={month} files={files} />
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
