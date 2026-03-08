import React, { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Icons } from "@/components/Icons";
import { getDocumentGraph } from "@/lib/api";
import type { DocumentDetail, DocumentGraphBranch, DocumentGraphResponse } from "@/lib/api";
import { navigateToDocument } from "@/lib/navigation";

const RELATION_LABELS: Record<string, string> = {
  cita: "Cita",
  altera: "Altera",
  revoga: "Revoga",
  regulamenta: "Regulamenta",
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
  if (branch.seed.node_type === "incoming") {
    return "border-[#60a5fa]/25 bg-[#60a5fa]/10 text-[#93c5fd]";
  }
  return branch.seed.node_type === "procedure"
    ? "border-[#a78bfa]/25 bg-[#a78bfa]/10 text-[#c4b5fd]"
    : "border-primary/20 bg-primary/10 text-primary";
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

  const branches = useMemo(() => graph?.branches || [], [graph?.branches]);
  const relationCount = useMemo(
    () => branches.reduce((total, branch) => total + branch.related_documents.length, 0),
    [branches]
  );

  if (!loading && !error && branches.length === 0) return null;

  return (
    <section className="reader-surface overflow-hidden rounded-[28px] px-3 py-4 sm:px-5 sm:py-5">
      <div className="mb-4 flex items-start justify-between gap-3">
        <div>
          <p className="mb-1 text-xs font-semibold uppercase tracking-[0.16em] text-text-tertiary">
            Relações encontradas
          </p>
          <p className="text-xs text-text-secondary">
            Saltos normativos, vínculos procedimentais e documentos recuperados a partir do ato atual.
          </p>
        </div>
        <div className="text-right">
          <p className="text-sm font-semibold text-foreground">{branches.length}</p>
          <p className="text-[11px] text-text-tertiary">{relationCount} saltos encontrados</p>
        </div>
      </div>

      <div className="space-y-3">
        <div className="rounded-[22px] border border-primary/15 bg-primary/10 px-3 py-3 sm:px-4 sm:py-4">
          <div className="flex items-start gap-3">
            <span className="mt-1 h-2.5 w-2.5 rounded-full bg-primary" />
            <div className="min-w-0 flex-1">
              <p className="font-editorial text-lg leading-tight text-primary">{graph?.document.title || document.title}</p>
              <p className="text-xs text-text-secondary mt-1 truncate">
                {[document.issuing_organ, document.pub_date, document.section?.toUpperCase()].filter(Boolean).join(" · ")}
              </p>
            </div>
          </div>
        </div>

        {loading ? (
          <div className="rounded-2xl border border-white/6 bg-background/60 px-4 py-4 text-sm text-text-secondary">
            Construindo a rede de relações a partir do backend…
          </div>
        ) : null}

        {error ? (
          <div className="rounded-2xl border border-amber-500/25 bg-amber-500/5 px-4 py-4 text-sm text-text-secondary">
            Não foi possível carregar a rede agora. O leitor continua funcional e as referências seguem disponíveis no documento.
          </div>
        ) : null}

        {branches.map((branch) => {
          const isExpanded = expanded[branch.seed.id] ?? false;
          const relationLabel = humanizeRelation(branch.seed.relation_type);
          return (
            <div key={branch.seed.id} className="overflow-hidden rounded-[22px] border border-white/6 bg-background/55">
              <div className="flex items-stretch">
                <button
                  onClick={() =>
                    setExpanded((current) => ({
                      ...current,
                      [branch.seed.id]: !isExpanded,
                    }))
                  }
                  className="min-w-0 flex-1 rounded-l-[22px] px-3 py-3 text-left transition-colors hover:bg-white/[0.03] focus-ring sm:px-4 sm:py-4"
                >
                  <div className="flex flex-col items-start gap-2 sm:flex-row sm:gap-3">
                    <span className={`inline-flex max-w-full self-start rounded-full border px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.16em] ${branchTone(branch)}`}>
                      {relationLabel}
                    </span>
                    <div className="min-w-0 flex-1">
                      <p className="break-words font-editorial text-lg leading-tight text-foreground sm:truncate">{branch.seed.title}</p>
                      {branch.seed.subtitle ? (
                        <p className="mt-1 break-words text-xs text-text-secondary line-clamp-3">{branch.seed.subtitle}</p>
                      ) : null}
                      <p className="text-[11px] text-text-tertiary mt-2">
                        {branch.related_documents.length > 0
                          ? `${branch.related_documents.length} documento(s) neste ramo`
                          : "Sem documentos adicionais neste salto"}
                      </p>
                    </div>
                  </div>
                </button>

                <div className="flex shrink-0 items-center gap-1 px-2">
                  {branch.seed.query ? (
                    <button
                      onClick={() => navigate(`/search?q=${encodeURIComponent(branch.seed.query || "")}`)}
                      className="flex min-h-[40px] min-w-[40px] items-center justify-center rounded-xl border border-white/6 bg-card text-text-secondary transition-colors hover:bg-white/[0.05] hover:text-foreground focus-ring"
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
                      className="flex min-h-[40px] min-w-[40px] items-center justify-center rounded-xl border border-white/6 bg-card text-text-secondary transition-colors hover:bg-white/[0.05] hover:text-foreground focus-ring"
                      aria-label={isExpanded ? "Recolher ramo" : "Expandir ramo"}
                  >
                    <Icons.chevronRight className={`h-4 w-4 transition-transform ${isExpanded ? "rotate-90" : ""}`} />
                  </button>
                </div>
              </div>

              {isExpanded ? (
                <div className="space-y-2 border-t border-white/6 px-3 py-3 sm:px-4">
                  <div className="ml-1 space-y-2 border-l border-white/6 pl-3 sm:ml-2 sm:pl-4">
                    {branch.related_documents.map((result) => (
                      <button
                        key={`${branch.seed.id}-${result.id}`}
                        onClick={() => navigateToDocument(navigate, result.id, "document-graph")}
                        className="w-full overflow-hidden rounded-[20px] border border-white/6 bg-card px-3 py-3 text-left transition-colors hover:bg-white/[0.04] focus-ring sm:px-4 sm:py-4"
                      >
                        <div className="flex flex-col items-start gap-2 sm:flex-row sm:gap-3">
                          <span className="inline-flex self-start rounded-full bg-primary/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.16em] text-primary">
                            Encontrado por
                          </span>
                          <div className="min-w-0 flex-1">
                            <p className="break-words font-editorial text-base leading-tight text-foreground sm:truncate">{result.title}</p>
                            <p className="mt-1 break-words text-xs text-text-secondary sm:truncate">
                              {[result.issuing_organ, result.pub_date, result.section?.toUpperCase()].filter(Boolean).join(" · ")}
                            </p>
                            {result.snippet ? (
                              <p className="mt-2 break-words text-xs text-text-tertiary line-clamp-3">{result.snippet}</p>
                            ) : null}
                          </div>
                          <Icons.chevronRight className="mt-1 hidden h-4 w-4 shrink-0 text-text-tertiary sm:block" />
                        </div>
                      </button>
                    ))}

                    {branch.related_documents.length === 0 ? (
                      <div className="rounded-xl border border-dashed border-white/8 px-3 py-3 text-xs text-text-tertiary">
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
