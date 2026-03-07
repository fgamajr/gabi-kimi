import React, { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { SearchBar } from "@/components/SearchBar";
import { SectionBadge } from "@/components/Badges";
import { Icons } from "@/components/Icons";
import { SkeletonBlock } from "@/components/Skeletons";
import { getStats, getTopSearches, getSearchExamples } from "@/lib/api";
import type { SearchExample, StatsResponse, TopSearch } from "@/lib/api";
import { getRecentDocuments, type RecentDocumentItem } from "@/lib/history";
import { navigateToDocument } from "@/lib/navigation";

const FEATURED_DOCUMENTS = [
  {
    id: "3a5b145e-80e4-4470-bea2-823bd93d05f5",
    title: "PORTARIA Nº 344, DE 19 DE FEVEREIRO DE 2002",
    organ: "Ministério da Saúde",
    snippet: "Ato do Ministério da Saúde no corpus atual, publicado na Seção 1 do DOU de 20/02/2002.",
    section: "do1",
    pubDate: "2002-02-20",
  },
  {
    id: "01e8425e-aaaf-44d3-8fa9-1a8296ef11a6",
    title: "PORTARIA Nº 1, DE 2 DE JANEIRO DE 2002",
    organ: "Presidência da República",
    snippet: "Portaria da Casa Civil publicada no início do corpus de 2002, útil como ponto de navegação institucional.",
    section: "do2",
    pubDate: "2002-01-03",
  },
  {
    id: "9b0ad87e-fce7-4e30-b809-a7395475f82e",
    title: "PORTARIA CONJUNTA Nº 309, DE 28 DE DEZEMBRO DE 2001",
    organ: "Ministério da Agricultura, Pecuária e Abastecimento",
    snippet: "Documento real do acervo atual, publicado em 02/01/2002 e útil para validar leitura e exploração do corpus.",
    section: "do2",
    pubDate: "2002-01-02",
  },
];

const FALLBACK_SEARCHES: TopSearch[] = [
  { query: "portaria anvisa", count: 342 },
  { query: "decreto presidencial 2002", count: 281 },
  { query: "edital licitação", count: 256 },
  { query: "redistribuição servidores", count: 198 },
  { query: "nomeação cargo", count: 164 },
];

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

  const searchChips = topSearches.length ? topSearches.slice(0, 5) : FALLBACK_SEARCHES;

  const metricCards = useMemo(
    () => [
      {
        label: "Publicações indexadas",
        value: stats?.total_documents ? stats.total_documents.toLocaleString("pt-BR") : "12.847",
        accent: "↑ 12%",
        accentTone: "text-emerald-400",
        series: [74, 71, 69, 66, 62, 64, 59, 56, 52, 57, 49, 46],
        color: "#3B82F6",
      },
      {
        label: "Cobertura temporal",
        value: stats?.date_range?.min && stats?.date_range?.max
          ? `${new Date(stats.date_range.min).getFullYear()}–${new Date(stats.date_range.max).getFullYear()}`
          : "2002–2026",
        accent: `${examples.length || 156} sinais`,
        accentTone: "text-text-secondary",
        series: [36, 22, 42, 60, 34, 20, 46, 61, 39, 21, 43, 37],
        color: "#7C5CFC",
      },
      {
        label: "Atualização da base",
        value: stats?.last_updated
          ? new Date(stats.last_updated).toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit", year: "2-digit" })
          : "230 ms",
        accent: stats?.last_updated ? "Base ativa" : "↓ 8%",
        accentTone: stats?.last_updated ? "text-emerald-400" : "text-red-400",
        series: [20, 22, 24, 29, 26, 34, 18, 15, 12, 10, 8, 12],
        color: "#22C55E",
      },
    ],
    [examples.length, stats]
  );

  return (
    <div className="min-h-screen bg-background pb-24 md:pb-8">
      <main className="mx-auto max-w-[980px] px-6 py-8 md:px-10 md:py-10">
        <header className="animate-fade-in">
          <h1 className="text-[2rem] font-semibold tracking-tight text-foreground">GABI · DOU</h1>
          <p className="mt-1 text-lg text-text-secondary">Diário Oficial da União</p>
        </header>

        <section className="mt-8 animate-fade-in" style={{ animationDelay: "60ms" }}>
          <SearchBar autoFocus placeholder={placeholder} showShortcutHint />
        </section>

        <section className="mt-6 overflow-x-auto pb-1 animate-fade-in" style={{ animationDelay: "90ms" }}>
          <div className="flex min-w-max gap-2">
            {searchChips.map((term, index) => (
              <button
                key={term.query}
                onClick={() => navigate(`/search?q=${encodeURIComponent(term.query)}`)}
                className="inline-flex min-h-[40px] items-center gap-1.5 rounded-full border border-white/8 bg-white/[0.03] px-4 text-sm text-foreground transition-all hover:border-primary/20 hover:bg-white/[0.05] focus-ring animate-float"
                style={{
                  animationDelay: `${index * 40}ms`,
                  ["--float-amplitude" as string]: `${(index % 2 === 0 ? -1 : 1) * (1 + index * 0.15)}px`,
                  ["--float-duration" as string]: `${4.5 + index * 0.35}s`,
                }}
              >
                <span>{term.query}</span>
                {term.count ? <span className="text-text-tertiary">({term.count})</span> : null}
              </button>
            ))}
          </div>
        </section>

        <section className="mt-8 animate-fade-in" style={{ animationDelay: "120ms" }}>
          <SectionHeader icon={<Icons.document className="h-3.5 w-3.5" />} title="Documentos em destaque" />
          <div className="mt-4 space-y-3">
            {FEATURED_DOCUMENTS.map((doc, index) => (
              <button
                key={doc.title}
                onClick={() => navigateToDocument(navigate, doc.id, "recent-document")}
                className="w-full rounded-[20px] border border-white/8 bg-[linear-gradient(180deg,rgba(22,24,33,0.9),rgba(18,20,28,0.96))] px-4 py-4 text-left transition-all hover:border-primary/18 hover:bg-white/[0.03] focus-ring animate-lift animate-breathe"
                style={{ animationDelay: `${index * 60}ms`, ["--breathe-delay" as string]: `${index * 180}ms` }}
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="mb-2 flex items-center gap-2">
                      <SectionBadge section={doc.section} />
                      <span className="text-xs text-text-tertiary">
                        {new Date(doc.pubDate).toLocaleDateString("pt-BR")}
                      </span>
                    </div>
                    <p className="text-[1.05rem] font-semibold text-foreground">{doc.title}</p>
                    <p className="mt-2 text-sm text-text-secondary">{doc.snippet}</p>
                  </div>
                  <span className="hidden shrink-0 text-sm text-text-tertiary md:block">{doc.organ}</span>
                </div>
              </button>
            ))}
          </div>
        </section>

        <section className="mt-8 animate-fade-in" style={{ animationDelay: "150ms" }}>
          <SectionHeader icon={<Icons.clock className="h-3.5 w-3.5" />} title="Vistos recentemente" />
          <div className="mt-4 rounded-[22px] border border-dashed border-white/8 bg-[rgba(6,10,18,0.55)] p-6">
            {recentDocs.length > 0 ? (
              <div className="space-y-3">
                {recentDocs.map((doc, index) => (
                  <button
                    key={doc.id}
                    onClick={() => navigateToDocument(navigate, doc.id, "recent-document")}
                    className="flex w-full items-start justify-between gap-3 rounded-[18px] border border-white/8 bg-white/[0.03] px-4 py-4 text-left transition-all hover:border-primary/18 hover:bg-white/[0.05] focus-ring animate-slide-in-right animate-lift"
                    style={{ animationDelay: `${index * 50}ms` }}
                  >
                    <div className="min-w-0">
                      <div className="mb-2 flex items-center gap-2">
                        {doc.section ? <SectionBadge section={doc.section} /> : null}
                        <span className="text-xs text-text-tertiary">{formatRelative(doc.viewedAt)}</span>
                      </div>
                      <p className="text-sm font-semibold text-foreground line-clamp-2">{doc.title}</p>
                      <p className="mt-1 text-xs text-text-secondary line-clamp-2">
                        {doc.snippet || doc.issuingOrgan || "Documento visitado recentemente na base."}
                      </p>
                    </div>
                    <Icons.chevronRight className="mt-1 h-4 w-4 shrink-0 text-text-tertiary" />
                  </button>
                ))}
              </div>
            ) : (
              <div className="flex min-h-[140px] flex-col items-center justify-center text-center">
                <Icons.search className="mb-4 h-10 w-10 text-text-tertiary" />
                <p className="text-lg text-text-secondary">Pesquise um documento acima —</p>
                <p className="text-lg text-text-secondary">seus acessos recentes aparecerão aqui</p>
              </div>
            )}
          </div>
        </section>

        <section className="mt-8 grid gap-4 md:grid-cols-3">
          {loading
            ? [1, 2, 3].map((index) => (
                <div key={index} className="rounded-[22px] border border-white/8 bg-card p-5">
                  <SkeletonBlock className="mb-3 h-4 w-24" />
                  <SkeletonBlock className="mb-4 h-8 w-32" />
                  <SkeletonBlock className="h-16 w-full" />
                </div>
              ))
            : metricCards.map((item) => (
                <MetricCard key={item.label} {...item} />
              ))}
        </section>
      </main>
    </div>
  );
};

const MetricCard: React.FC<{
  label: string;
  value: string;
  accent: string;
  accentTone: string;
  series: number[];
  color: string;
}> = ({ label, value, accent, accentTone, series, color }) => (
  <div className="rounded-[22px] border border-white/8 bg-[linear-gradient(180deg,rgba(22,24,33,0.92),rgba(18,20,28,0.98))] px-4 py-4 animate-spring-in animate-lift">
    <div className="mb-3 flex items-center justify-between gap-3">
      <span className="text-[11px] uppercase tracking-[0.16em] text-text-tertiary">{label}</span>
      <span className={`text-sm ${accentTone}`}>{accent}</span>
    </div>
    <div className="flex items-end justify-between gap-3">
      <p className="font-mono text-[2rem] font-semibold text-foreground">{value}</p>
      <Sparkline series={series} color={color} />
    </div>
  </div>
);

const Sparkline: React.FC<{ series: number[]; color: string }> = ({ series, color }) => {
  const max = Math.max(...series);
  const min = Math.min(...series);
  const range = Math.max(1, max - min);
  const points = series
    .map((value, index) => {
      const x = (index / Math.max(1, series.length - 1)) * 120;
      const y = 44 - ((value - min) / range) * 28;
      return `${index === 0 ? "M" : "L"}${x},${y}`;
    })
    .join(" ");

  return (
    <svg viewBox="0 0 120 48" className="h-12 w-[120px]">
      <path d={points} fill="none" stroke={color} strokeWidth="2.4" strokeLinecap="round" />
    </svg>
  );
};

const SectionHeader: React.FC<{ icon: React.ReactNode; title: string }> = ({ icon, title }) => (
  <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.22em] text-text-tertiary">
    {icon}
    {title}
  </div>
);

export default HomePage;
