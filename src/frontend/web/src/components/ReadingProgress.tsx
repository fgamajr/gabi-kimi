import React from "react";

interface ReadingProgressProps {
  progress: number;
  activeLabel?: string;
}

export const ReadingProgress: React.FC<ReadingProgressProps> = ({ progress, activeLabel }) => {
  const percent = Math.max(0, Math.min(100, Math.round(progress * 100)));

  return (
    <div className="sticky top-[57px] z-30 border-b border-white/6 bg-background/78 px-4 py-2.5 backdrop-blur-xl">
      <div className="mx-auto flex max-w-[1180px] items-center gap-3">
        <div className="min-w-0 flex-1">
          <div className="mb-2 flex items-center justify-between gap-3">
            <span className="text-[11px] font-semibold uppercase tracking-[0.16em] text-text-tertiary">Leitura</span>
            <span className="truncate text-xs text-text-secondary">
              {activeLabel || `${percent}% do documento`}
            </span>
          </div>
          <div className="h-1.5 overflow-hidden rounded-full bg-secondary">
            <div
              className="h-full rounded-full bg-[linear-gradient(90deg,hsl(var(--primary)),hsl(var(--accent)))] transition-[width] duration-200 ease-out"
              style={{ width: `${percent}%` }}
            />
          </div>
        </div>
        <div className="hidden shrink-0 rounded-full border border-white/8 bg-white/[0.03] px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.14em] text-text-secondary sm:inline-flex">
          {percent}%
        </div>
      </div>
    </div>
  );
};
