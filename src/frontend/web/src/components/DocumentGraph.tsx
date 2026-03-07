import React, { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Icons } from "@/components/Icons";
import { getDocumentGraph } from "@/lib/api";
import type { DocumentDetail, DocumentGraphBranch, DocumentGraphResponse } from "@/lib/api";

const RELATION_LABELS: Record<string, string> = {
  cita: "Cita",
  altera: "Altera",
  revoga: "Revoga",
  prorroga: "Prorroga",
  complementa: "Complementa",
  procedimento: "Procedimento",
};

function humanizeRelation(value?: string | null) {
  const key = String(value || "").trim().toLowerCase();
  if (!key) return "Relação";
  return RELATION_LABELS[key] || key.replace(/[_-]+/g, " ");
}

function branchTone(branch: DocumentGraphBranch) {
  return branch.seed.node_type === "procedure"
    ? "border-amber-400/30 bg-amber-500/5 text-amber-200"
    : "border-primary/25 bg-primary/8 text-primary";
}

export const DocumentGraph: React.FC<{ document: DocumentDetail }> = ({ document }) => {
  const navigate = useNavigate();
  const [graph, setGraph] = useState<DocumentGraphResponse | null>(null);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(false);

    getDocumentGraph(document.id, 2, 3)
      .then((payload) => {
        if (cancelled) return;
        setGraph(payload);
        setExpanded(
          payload.branches.reduce<Record<string, boolean>>((acc, branch, index) => {
            acc[branch.seed.id] = index === 0;
            return acc;
          }, {})
        );
      })
      .catch(() => {
        if (!cancelled) setError(true);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [document.id]);

  const branches = graph?.branches || [];
  const relationCount = useMemo(
    () => branches.reduce((total, branch) => total + branch.related_documents.length, 0),
    [branches]
  );

  if (!loading && !error && branches.length === 0) return null;

  return (
    <section className="rounded-2xl border border-border bg-card px-4 py-4">
      <div className="flex items-start justify-between gap-3 mb-4">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.16em] text-text-tertiary mb-1">
            Workspace de relações
          </p>
          <p className="text-xs text-text-secondary">
            Expanda cada ramo para navegar por referências normativas, procedimentos e documentos encontrados a partir delas.
          </p>
        </div>
        <div className="text-right">
          <p className="text-sm font-semibold text-foreground">{branches.length}</p>
          <p className="text-[11px] text-text-tertiary">{relationCount} saltos encontrados</p>
        </div>
      </div>

      <div className="space-y-3">
        <div className="rounded-xl border border-primary/25 bg-primary/8 px-3 py-3">
          <div className="flex items-start gap-3">
            <span className="mt-1 h-2.5 w-2.5 rounded-full bg-primary" />
            <div className="min-w-0 flex-1">
              <p className="text-sm font-medium text-primary truncate">{graph?.document.title || document.title}</p>
              <p className="text-xs text-text-secondary mt-1 truncate">
                {[document.issuing_organ, document.pub_date, document.section?.toUpperCase()].filter(Boolean).join(" · ")}
              </p>
            </div>
          </div>
        </div>

        {loading ? (
          <div className="rounded-xl border border-border bg-background/60 px-4 py-4 text-sm text-text-secondary">
            Construindo a rede de relações a partir do backend…
          </div>
        ) : null}

        {error ? (
          <div className="rounded-xl border border-amber-500/25 bg-amber-500/5 px-4 py-4 text-sm text-text-secondary">
            Não foi possível carregar a rede agora. O leitor continua funcional e as referências seguem disponíveis no documento.
          </div>
        ) : null}

        {branches.map((branch) => {
          const isExpanded = expanded[branch.seed.id] ?? false;
          const relationLabel = humanizeRelation(branch.seed.relation_type);
          return (
            <div key={branch.seed.id} className="rounded-xl border border-border bg-background/60">
              <div className="flex items-stretch">
                <button
                  onClick={() =>
                    setExpanded((current) => ({
                      ...current,
                      [branch.seed.id]: !isExpanded,
                    }))
                  }
                  className="flex-1 px-4 py-3 text-left hover:bg-secondary/40 transition-colors focus-ring rounded-l-xl"
                >
                  <div className="flex items-start gap-3">
                    <span className={`mt-1 inline-flex rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.16em] ${branchTone(branch)}`}>
                      {relationLabel}
                    </span>
                    <div className="min-w-0 flex-1">
                      <p className="text-sm font-medium text-foreground truncate">{branch.seed.title}</p>
                      {branch.seed.subtitle ? (
                        <p className="text-xs text-text-secondary mt-1 line-clamp-2">{branch.seed.subtitle}</p>
                      ) : null}
                      <p className="text-[11px] text-text-tertiary mt-2">
                        {branch.related_documents.length > 0
                          ? `${branch.related_documents.length} documento(s) neste ramo`
                          : "Sem documentos adicionais neste salto"}
                      </p>
                    </div>
                  </div>
                </button>

                <div className="flex items-center gap-1 px-2">
                  {branch.seed.query ? (
                    <button
                      onClick={() => navigate(`/search?q=${encodeURIComponent(branch.seed.query || "")}`)}
                      className="min-h-[40px] min-w-[40px] rounded-xl border border-border bg-card text-text-secondary hover:text-foreground hover:bg-secondary transition-colors focus-ring flex items-center justify-center"
                      aria-label={`Buscar por ${branch.seed.title}`}
                    >
                      <Icons.search className="h-4 w-4" />
                    </button>
                  ) : null}
                  <button
                    onClick={() =>
                      setExpanded((current) => ({
                        ...current,
                        [branch.seed.id]: !isExpanded,
                      }))
                    }
                    className="min-h-[40px] min-w-[40px] rounded-xl border border-border bg-card text-text-secondary hover:text-foreground hover:bg-secondary transition-colors focus-ring flex items-center justify-center"
                    aria-label={isExpanded ? "Recolher ramo" : "Expandir ramo"}
                  >
                    <Icons.chevronRight className={`h-4 w-4 transition-transform ${isExpanded ? "rotate-90" : ""}`} />
                  </button>
                </div>
              </div>

              {isExpanded ? (
                <div className="border-t border-border px-4 py-3 space-y-2">
                  <div className="ml-2 border-l border-border pl-4 space-y-2">
                    {branch.related_documents.map((result) => (
                      <button
                        key={`${branch.seed.id}-${result.id}`}
                        onClick={() => navigate(`/document/${encodeURIComponent(result.id)}`)}
                        className="w-full rounded-xl border border-border bg-card px-3 py-3 text-left hover:bg-secondary/50 transition-colors focus-ring"
                      >
                        <div className="flex items-start gap-3">
                          <span className="mt-1 inline-flex rounded-full bg-primary/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.16em] text-primary">
                            Encontrado por
                          </span>
                          <div className="min-w-0 flex-1">
                            <p className="text-sm text-foreground truncate">{result.title}</p>
                            <p className="text-xs text-text-secondary mt-1 truncate">
                              {[result.issuing_organ, result.pub_date, result.section?.toUpperCase()].filter(Boolean).join(" · ")}
                            </p>
                            {result.snippet ? (
                              <p className="text-xs text-text-tertiary mt-2 line-clamp-2">{result.snippet}</p>
                            ) : null}
                          </div>
                          <Icons.chevronRight className="h-4 w-4 text-text-tertiary shrink-0 mt-1" />
                        </div>
                      </button>
                    ))}

                    {branch.related_documents.length === 0 ? (
                      <div className="rounded-lg border border-dashed border-border px-3 py-3 text-xs text-text-tertiary">
                        Nenhum documento adicional foi encontrado para este ramo, mas a consulta correlata continua disponível para exploração manual.
                      </div>
                    ) : null}
                  </div>
                </div>
              ) : null}
            </div>
          );
        })}
      </div>
    </section>
  );
};
