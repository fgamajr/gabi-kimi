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
    <div className="rounded-[24px] border border-white/6 bg-white/[0.02] p-4">
      <p className="mb-4 text-xs font-semibold uppercase tracking-[0.16em] text-text-tertiary">
        Índice
      </p>
      <div className="space-y-2">
        {sections.map((section) => {
          const active = section.id === activeSectionId;
          return (
            <button
              key={section.id}
              onClick={() => onSelect(section)}
              className={`min-h-[44px] w-full rounded-2xl px-4 py-3 text-left text-sm transition-colors ${
                active
                  ? "border border-primary/15 bg-primary/14 text-primary"
                  : "text-text-secondary hover:bg-white/[0.04] hover:text-foreground"
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
