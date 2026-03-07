import React, { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { SearchBar } from "@/components/SearchBar";
import { SectionBadge } from "@/components/Badges";
import { Icons } from "@/components/Icons";
import { SkeletonBlock } from "@/components/Skeletons";
import { StatusIndicator } from "@/components/StatusIndicator";
import { getStats, getTopSearches, getSearchExamples } from "@/lib/api";
import type { SearchExample, StatsResponse, TopSearch } from "@/lib/api";
import { getRecentDocuments, type RecentDocumentItem } from "@/lib/history";

const FEATURED_DOCUMENT = {
  title: "PORTARIA Nº 344, DE 12 DE MAIO DE 1998",
  organ: "ANVISA — Agência Nacional de Vigilância Sanitária",
  snippet:
    "Aprova o Regulamento Técnico sobre substâncias e medicamentos sujeitos a controle especial.",
  section: "do1",
  pubDate: "1998-05-12",
  query: "portaria nº 344 anvisa",
};

const HomePage: React.FC = () => {
  const navigate = useNavigate();
  const [stats, setStats] = useState<StatsResponse | null>(null);
  const [topSearches, setTopSearches] = useState<TopSearch[]>([]);
  const [examples, setExamples] = useState<SearchExample[]>([]);
  const [recentDocs, setRecentDocs] = useState<RecentDocumentItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [placeholderIndex, setPlaceholderIndex] = useState(0);

  useEffect(() => {
    Promise.allSettled([getStats(), getTopSearches(), getSearchExamples()])
      .then(([statsResult, topResult, examplesResult]) => {
        if (statsResult.status === "fulfilled") setStats(statsResult.value);
        if (topResult.status === "fulfilled") setTopSearches(topResult.value?.slice(0, 8) || []);
        if (examplesResult.status === "fulfilled") setExamples(examplesResult.value?.slice(0, 6) || []);
      })
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    const syncRecentDocs = () => setRecentDocs(getRecentDocuments());
    syncRecentDocs();
    window.addEventListener("focus", syncRecentDocs);
    window.addEventListener("storage", syncRecentDocs);
    return () => {
      window.removeEventListener("focus", syncRecentDocs);
      window.removeEventListener("storage", syncRecentDocs);
    };
  }, []);

  useEffect(() => {
    if (!examples.length) return;
    const timer = window.setInterval(() => {
      setPlaceholderIndex((current) => (current + 1) % examples.length);
    }, 4000);
    return () => window.clearInterval(timer);
  }, [examples]);

  const placeholder = useMemo(() => {
    if (!examples.length) return "Pesquisar atos, portarias, decretos...";
    return examples[placeholderIndex]?.query || "Pesquisar atos, portarias, decretos...";
  }, [examples, placeholderIndex]);

  const formatNumber = (value?: number) => value?.toLocaleString("pt-BR") || "—";

  const formatRange = (min?: string, max?: string) => {
    if (!min || !max) return "—";
    try {
      const minYear = new Date(min).getFullYear();
      const maxYear = new Date(max).getFullYear();
      return `${minYear}–${maxYear}`;
    } catch {
      return `${min}–${max}`;
    }
  };

  const formatRelative = (value?: string) => {
    if (!value) return "Sem data";
    const diff = Date.now() - new Date(value).getTime();
    const hours = Math.max(0, Math.floor(diff / (1000 * 60 * 60)));
    if (hours < 1) return "há instantes";
    if (hours < 24) return `há ${hours}h`;
    try {
      return new Date(value).toLocaleDateString("pt-BR", { day: "2-digit", month: "short", year: "numeric" });
    } catch {
      return value;
    }
  };

  const statusKind = !stats
    ? "error"
    : stats.last_updated
      ? "ok"
      : "warn";

  const statusLabel = !stats
    ? "Indisponível"
    : stats.last_updated
      ? "Indexação OK"
      : "Modo demonstração";

  const statusDetail = !stats
    ? "Não foi possível carregar o estado operacional da base."
    : stats.last_updated
      ? `Base ativa · atualizada em ${new Date(stats.last_updated).toLocaleDateString("pt-BR")}`
      : "Dados simulados ou base parcial carregada para navegação.";

  return (
    <div className="min-h-screen bg-background pb-24 md:pb-8">
      <main className="max-w-4xl mx-auto px-4 py-6 md:py-8">
        <header className="mb-6 md:mb-8 animate-fade-in">
          <div className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full bg-secondary text-text-secondary text-xs font-medium mb-4">
            <Icons.book className="w-3.5 h-3.5" />
            Diário Oficial da União
          </div>
          <div className="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
            <div>
              <h1 className="text-2xl md:text-4xl font-semibold tracking-tight text-foreground">
                GABI · DOU
              </h1>
              <p className="mt-2 text-sm md:text-base text-text-secondary max-w-2xl">
                Pesquisa operacional para auditoria, contexto normativo e exploração documental do Diário Oficial.
              </p>
            </div>
          </div>
        </header>

        <section className="animate-fade-in" style={{ animationDelay: "80ms" }}>
          <SearchBar autoFocus placeholder={placeholder} />
        </section>

        <section className="mt-6 grid grid-cols-1 gap-3 md:grid-cols-3">
          {loading ? (
            [1, 2, 3].map((index) => (
              <div key={index} className="rounded-2xl border border-border bg-card p-4">
                <SkeletonBlock className="h-4 w-20 mb-3" />
                <SkeletonBlock className="h-8 w-28" />
              </div>
            ))
          ) : (
            <>
              <MetricCard
                label="Publicações"
                value={formatNumber(stats?.total_documents)}
                detail="Corpus indexado"
                icon={<Icons.document className="w-4 h-4" />}
                className="animate-spring-in"
              />
              <MetricCard
                label="Período"
                value={formatRange(stats?.date_range?.min, stats?.date_range?.max)}
                detail="Cobertura temporal"
                icon={<Icons.calendar className="w-4 h-4" />}
                className="animate-spring-in"
                style={{ animationDelay: "60ms" }}
              />
              <div className="rounded-2xl border border-border bg-card px-4 py-4 animate-spring-in" style={{ animationDelay: "120ms" }}>
                <p className="text-xs uppercase tracking-[0.16em] text-text-tertiary mb-3">Status operacional</p>
                <StatusIndicator status={statusKind} label={statusLabel} detail={statusDetail} />
              </div>
            </>
          )}
        </section>

        {topSearches.length > 0 ? (
          <section className="mt-6 animate-fade-in" style={{ animationDelay: "140ms" }}>
            <div className="flex items-center justify-between mb-3">
              <h2 className="text-xs font-semibold uppercase tracking-[0.16em] text-text-tertiary flex items-center gap-2">
                <Icons.trending className="w-3.5 h-3.5" />
                Mais pesquisados
              </h2>
            </div>
            <div className="overflow-x-auto pb-2">
              <div className="flex min-w-max gap-2">
                {topSearches.map((term, index) => (
                  <button
                    key={term.query}
                    onClick={() => navigate(`/search?q=${encodeURIComponent(term.query)}`)}
                    className="px-3 py-2 rounded-xl border border-border bg-card text-sm text-foreground hover:border-primary/30 hover:bg-secondary hover:-translate-y-px transition-all press-effect focus-ring min-h-[44px] whitespace-nowrap animate-float"
                    style={
                      {
                        ["--float-duration" as string]: `${5 + (index % 3)}s`,
                        ["--float-amplitude" as string]: `${-1 - (index % 2)}px`,
                      } as React.CSSProperties
                    }
                  >
                    {term.query}
                    {term.count ? <span className="ml-1.5 text-text-tertiary">({term.count})</span> : null}
                  </button>
                ))}
              </div>
            </div>
          </section>
        ) : null}

        <section className="mt-6 grid gap-4 lg:grid-cols-[1.2fr_0.95fr]">
          <div className="rounded-2xl border border-border bg-card/70 p-4 md:p-5 animate-fade-in" style={{ animationDelay: "180ms" }}>
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-xs font-semibold uppercase tracking-[0.16em] text-text-tertiary flex items-center gap-2">
                <Icons.clock className="w-3.5 h-3.5" />
                Vistos recentemente
              </h2>
            </div>

            {recentDocs.length > 0 ? (
              <div className="space-y-2">
                {recentDocs.map((doc, index) => (
                  <button
                    key={doc.id}
                    onClick={() => navigate(`/document/${encodeURIComponent(doc.id)}`)}
                    className="w-full text-left rounded-xl border border-border bg-background/70 px-4 py-3 hover:border-primary/30 hover:bg-secondary/40 transition-all press-effect focus-ring animate-slide-in-right"
                    style={{ animationDelay: `${index * 60}ms` }}
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <div className="flex items-center gap-2 mb-1.5">
                          {doc.section ? <SectionBadge section={doc.section} /> : null}
                          <span className="text-xs text-text-tertiary">{formatRelative(doc.viewedAt)}</span>
                        </div>
                        <p className="text-sm font-semibold text-foreground line-clamp-2">{doc.title}</p>
                        <p className="mt-1 text-xs text-text-secondary line-clamp-2">
                          {doc.snippet || doc.issuingOrgan || "Documento visitado recentemente na base."}
                        </p>
                      </div>
                      <Icons.chevronRight className="w-4 h-4 text-text-tertiary shrink-0 mt-1" />
                    </div>
                  </button>
                ))}
              </div>
            ) : (
              <div className="rounded-xl border border-dashed border-border px-4 py-8 text-center bg-background/50">
                <Icons.search className="w-10 h-10 text-text-tertiary mx-auto mb-3" />
                <p className="text-sm text-foreground font-medium">Pesquise um documento acima</p>
                <p className="text-xs text-text-secondary mt-1">
                  Seus acessos recentes aparecerão aqui para retomada rápida.
                </p>
              </div>
            )}
          </div>

          <button
            onClick={() => navigate(`/search?q=${encodeURIComponent(FEATURED_DOCUMENT.query)}`)}
            className="rounded-2xl border border-border bg-card p-5 text-left hover:border-primary/30 hover:shadow-[var(--shadow-lift)] transition-all press-effect focus-ring animate-breathe"
          >
            <div className="flex items-center justify-between gap-3 mb-4">
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.16em] text-text-tertiary">Documento em destaque</p>
                <p className="text-xs text-text-secondary mt-1">Tema clássico de controle sanitário</p>
              </div>
              <SectionBadge section={FEATURED_DOCUMENT.section} />
            </div>
            <h2 className="text-lg md:text-xl font-semibold text-foreground leading-snug">
              {FEATURED_DOCUMENT.title}
            </h2>
            <p className="mt-3 text-sm text-text-secondary leading-relaxed">{FEATURED_DOCUMENT.organ}</p>
            <p className="mt-3 text-sm text-text-secondary leading-relaxed">{FEATURED_DOCUMENT.snippet}</p>
            <div className="mt-5 flex items-center justify-between gap-3">
              <span className="text-xs text-text-tertiary">
                {new Date(FEATURED_DOCUMENT.pubDate).toLocaleDateString("pt-BR", {
                  day: "2-digit",
                  month: "long",
                  year: "numeric",
                })}
              </span>
              <span className="inline-flex items-center gap-1.5 text-sm font-medium text-text-accent">
                Explorar tema
                <Icons.chevronRight className="w-4 h-4" />
              </span>
            </div>
          </button>
        </section>
      </main>
    </div>
  );
};

const MetricCard: React.FC<{
  label: string;
  value: string;
  detail: string;
  icon: React.ReactNode;
  className?: string;
  style?: React.CSSProperties;
}> = ({ label, value, detail, icon, className = "", style }) => (
  <div className={`rounded-2xl border border-border bg-card px-4 py-4 ${className}`} style={style}>
    <div className="flex items-center gap-2 text-text-tertiary mb-3">
      {icon}
      <span className="text-xs uppercase tracking-[0.16em]">{label}</span>
    </div>
    <p className="text-2xl md:text-3xl font-semibold font-mono text-foreground">{value}</p>
    <p className="text-xs text-text-secondary mt-2">{detail}</p>
  </div>
);

export default HomePage;
