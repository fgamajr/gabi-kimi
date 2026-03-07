import React from "react";

interface ReadingProgressProps {
  progress: number;
  activeLabel?: string;
}

export const ReadingProgress: React.FC<ReadingProgressProps> = ({ progress, activeLabel }) => {
  const percent = Math.max(0, Math.min(100, Math.round(progress * 100)));

  return (
    <div className="sticky top-[57px] z-30 px-4 py-2 bg-background/80 backdrop-blur-xl border-b border-border/60">
      <div className="flex items-center justify-between gap-3 mb-2">
        <span className="text-[11px] uppercase tracking-[0.16em] text-text-tertiary">Leitura</span>
        <span className="text-xs text-text-secondary truncate">
          {activeLabel || `${percent}% do documento`}
        </span>
      </div>
      <div className="h-1.5 rounded-full bg-secondary overflow-hidden">
        <div
          className="h-full rounded-full bg-primary transition-[width] duration-200 ease-out"
          style={{ width: `${percent}%` }}
        />
      </div>
    </div>
  );
};
