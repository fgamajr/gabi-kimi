import React from "react";
import type { Section } from "@/lib/sectionParser";

interface DocumentTOCProps {
  sections: Section[];
  activeSectionId?: string | null;
  onSelect: (section: Section) => void;
}

export const DocumentTOC: React.FC<DocumentTOCProps> = ({ sections, activeSectionId, onSelect }) => {
  if (!sections.length) return null;

  return (
    <div className="rounded-2xl border border-border bg-card p-4">
      <p className="text-xs font-semibold uppercase tracking-[0.16em] text-text-tertiary mb-3">
        Índice
      </p>
      <div className="space-y-1.5">
        {sections.map((section) => {
          const active = section.id === activeSectionId;
          return (
            <button
              key={section.id}
              onClick={() => onSelect(section)}
              className={`w-full text-left rounded-xl px-3 py-2.5 text-sm transition-colors min-h-[44px] ${
                active
                  ? "bg-primary/12 text-primary border border-primary/20"
                  : "text-text-secondary hover:bg-secondary hover:text-foreground"
              }`}
            >
              {section.label}
            </button>
          );
        })}
      </div>
    </div>
  );
};
