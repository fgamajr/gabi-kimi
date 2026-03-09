import React from "react";
import type { Section } from "@/lib/sectionParser";

interface DocumentTOCProps {
  sections: Section[];
  activeSectionId?: string | null;
  onSelect: (section: Section) => void;
}

export const DocumentTOC: React.FC<DocumentTOCProps> = ({ sections, activeSectionId, onSelect }) => {
  if (!sections.length) return null;

  const activeSection = sections.find((section) => section.id === activeSectionId);

  return (
    <nav aria-label="Índice do documento" className="reader-surface overflow-hidden rounded-[28px] p-4">
      <div className="mb-4 border-b border-white/6 pb-4">
        <div className="flex items-start justify-between gap-3">
          <div>
            <p className="mb-1 text-xs font-semibold uppercase tracking-[0.16em] text-text-tertiary">
              Índice
            </p>
            <p className="text-sm text-text-secondary">
              {activeSection ? activeSection.label : `${sections.length} pontos de leitura`}
            </p>
          </div>
          <span className="rounded-full border border-white/8 bg-white/[0.03] px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.14em] text-text-tertiary">
            {sections.length}
          </span>
        </div>
      </div>
      <div className="space-y-2">
        {sections.map((section, index) => {
          const active = section.id === activeSectionId;
          return (
            <button
              key={section.id}
              type="button"
              onClick={() => onSelect(section)}
              aria-current={active ? "location" : undefined}
              className={`flex min-h-[48px] w-full items-start gap-3 rounded-[20px] px-4 py-3 text-left text-sm transition-colors ${
                active
                  ? "border border-primary/15 bg-primary/12 text-primary"
                  : "border border-transparent text-text-secondary hover:bg-white/[0.04] hover:text-foreground"
              }`}
            >
              <span className={`mt-0.5 inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-[10px] font-semibold ${
                active ? "bg-primary/14 text-primary" : "bg-white/[0.04] text-text-tertiary"
              }`}>
                {index + 1}
              </span>
              <span className="min-w-0 flex-1 leading-relaxed">{section.label}</span>
            </button>
          );
        })}
      </div>
    </nav>
  );
};
