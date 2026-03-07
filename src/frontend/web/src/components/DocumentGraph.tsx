import React, { useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { Icons } from "@/components/Icons";
import type { DocumentDetail } from "@/lib/api";

interface GraphNode {
  id: string;
  title: string;
  subtitle?: string;
  href: string;
  emphasis?: "current" | "reference" | "procedure";
}

export const DocumentGraph: React.FC<{ document: DocumentDetail }> = ({ document }) => {
  const navigate = useNavigate();

  const nodes = useMemo<GraphNode[]>(() => {
    const items: GraphNode[] = [
      {
        id: document.id,
        title: document.title,
        subtitle: [document.issuing_organ, document.pub_date].filter(Boolean).join(" · "),
        href: `/document/${encodeURIComponent(document.id)}`,
        emphasis: "current",
      },
    ];

    (document.normative_refs || []).slice(0, 5).forEach((ref, index) => {
      const query = [ref.reference_type, ref.reference_number].filter(Boolean).join(" ").trim() || ref.reference_text || "";
      items.push({
        id: `normative-${index}`,
        title: [ref.reference_type, ref.reference_number].filter(Boolean).join(" ").trim() || "Referência normativa",
        subtitle: ref.reference_text || ref.reference_date || undefined,
        href: `/search?q=${encodeURIComponent(query)}`,
        emphasis: "reference",
      });
    });

    (document.procedure_refs || []).slice(0, 4).forEach((procedure, index) => {
      const query = [procedure.procedure_type, procedure.procedure_identifier].filter(Boolean).join(" ").trim();
      items.push({
        id: `procedure-${index}`,
        title: [procedure.procedure_type, procedure.procedure_identifier].filter(Boolean).join(" · ") || "Procedimento relacionado",
        subtitle: "Abrir busca correlata",
        href: `/search?q=${encodeURIComponent(query)}`,
        emphasis: "procedure",
      });
    });

    return items;
  }, [document]);

  if (nodes.length <= 1) return null;

  return (
    <section className="rounded-2xl border border-border bg-card px-4 py-4">
      <div className="flex items-start justify-between gap-3 mb-4">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.16em] text-text-tertiary mb-1">Rede de referências</p>
          <p className="text-xs text-text-secondary">
            Navegue para normas e procedimentos relacionados sem sair do fluxo de investigação.
          </p>
        </div>
        <Icons.gitBranch className="w-4 h-4 text-text-tertiary shrink-0 mt-0.5" />
      </div>

      <div className="space-y-2">
        {nodes.map((node, index) => (
          <button
            key={node.id}
            onClick={() => navigate(node.href)}
            className={`w-full text-left rounded-xl border px-3 py-3 transition-colors press-effect focus-ring ${
              node.emphasis === "current"
                ? "border-primary/25 bg-primary/8"
                : "border-border bg-background/70 hover:bg-secondary/50"
            }`}
            style={{ marginLeft: node.emphasis === "current" ? 0 : "1.25rem" }}
          >
            <div className="flex items-start gap-3">
              <div className="flex flex-col items-center">
                <span
                  className={`mt-1 h-2.5 w-2.5 rounded-full ${
                    node.emphasis === "current"
                      ? "bg-primary"
                      : node.emphasis === "procedure"
                        ? "bg-amber-400"
                        : "bg-text-tertiary"
                  }`}
                />
                {index < nodes.length - 1 ? <span className="mt-1 w-px h-8 bg-border" /> : null}
              </div>
              <div className="min-w-0 flex-1">
                <p className={`text-sm font-medium truncate ${node.emphasis === "current" ? "text-primary" : "text-foreground"}`}>
                  {node.title}
                </p>
                {node.subtitle ? <p className="text-xs text-text-secondary mt-1 line-clamp-2">{node.subtitle}</p> : null}
              </div>
              <Icons.chevronRight className="w-4 h-4 text-text-tertiary shrink-0 mt-1" />
            </div>
          </button>
        ))}
      </div>
    </section>
  );
};
