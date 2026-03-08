import React, { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Icons } from "@/components/Icons";
import { getAnalytics, getStats, getTopSearches } from "@/lib/api";
import type { AnalyticsResponse, AnalyticsSectionMonthlyPoint, AnalyticsTypeSeries, StatsResponse, TopSearch } from "@/lib/api";

const AnalyticsPage: React.FC = () => {
  const navigate = useNavigate();
  const [analytics, setAnalytics] = useState<AnalyticsResponse | null>(null);
  const [stats, setStats] = useState<StatsResponse | null>(null);
  const [topSearches, setTopSearches] = useState<TopSearch[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.allSettled([getAnalytics(), getStats(), getTopSearches(8, "week")])
      .then(([analyticsResult, statsResult, topSearchesResult]) => {
        if (analyticsResult.status === "fulfilled") setAnalytics(analyticsResult.value);
        if (statsResult.status === "fulfilled") setStats(statsResult.value);
        if (topSearchesResult.status === "fulfilled") setTopSearches(topSearchesResult.value);
      })
      .finally(() => setLoading(false));
  }, []);

  const summaryCards = useMemo(
    () => [
      {
        label: "Documentos",
        value: analytics?.overview.total_documents?.toLocaleString("pt-BR") || "0",
        detail: analytics?.overview.date_max ? `até ${formatMonth(analytics.overview.date_max)}` : "sem corte final",
      },
      {
        label: "Órgãos",
        value: analytics?.overview.total_organs?.toLocaleString("pt-BR") || "0",
        detail: analytics?.top_organs[0] ? `líder: ${analytics.top_organs[0].organ}` : "sem liderança",
      },
      {
        label: "Tipos líderes",
        value: analytics?.top_types_monthly.series.length?.toLocaleString("pt-BR") || "0",
        detail: analytics?.top_types_monthly.series[0] ? analytics.top_types_monthly.series[0].label : "sem série",
      },
      {
        label: "Backend",
        value: String(stats?.search_backend || "n/d").toUpperCase(),
        detail: stats?.cluster_status ? `cluster ${String(stats.cluster_status).toUpperCase()}` : "sem status",
      },
    ],
    [analytics, stats]
  );

  return (
    <div className="min-h-screen bg-background">
      <div className="mx-auto max-w-[1180px] px-6 py-8 md:px-10 md:py-10">
        <header className="border-b border-white/6 pb-6">
          <button
            onClick={() => navigate(-1)}
            className="inline-flex min-h-[44px] items-center gap-3 rounded-xl text-foreground transition-colors hover:text-primary focus-ring"
          >
            <Icons.back className="h-5 w-5" />
            <span className="font-editorial text-[2rem] leading-none">Analytics</span>
          </button>
          <p className="mt-4 max-w-3xl text-sm text-text-secondary">
            Painéis operacionais alimentados por agregações reais do corpus: volumes por seção, tipos líderes, órgãos dominantes e sinais de uso da busca.
          </p>
        </header>

        <main className="mt-8 space-y-8">
          <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
            {summaryCards.map((card) => (
              <div key={card.label} className="reader-surface rounded-[24px] px-5 py-5">
                <p className="text-[11px] uppercase tracking-[0.16em] text-text-tertiary">{card.label}</p>
                <p className="mt-3 font-mono text-[2rem] text-foreground">{card.value}</p>
                <p className="mt-2 text-sm text-text-secondary">{card.detail}</p>
              </div>
            ))}
          </section>

          <ChartCard
            title="Volume mensal por seção"
            description="Série real agregada do corpus. Cada coluna empilha Seção 1, 2, 3 e Extra."
            badge={loading ? "CARREGANDO" : `${analytics?.section_monthly.length || 0} PONTOS`}
          >
            <PublicationVolumeChart data={analytics?.section_monthly || []} />
          </ChartCard>

          <ChartCard
            title="Tipos líderes ao longo do tempo"
            description="Linhas mensais dos tipos de ato mais representativos do acervo atual."
            badge={loading ? "SÉRIES" : `${analytics?.top_types_monthly.series.length || 0} TIPOS`}
          >
            <ActsLineChart
              months={analytics?.top_types_monthly.months || []}
              series={analytics?.top_types_monthly.series || []}
            />
          </ChartCard>

          <section className="grid gap-8 lg:grid-cols-[0.95fr_1.05fr]">
            <ChartCard
              title="Órgãos líderes"
              description="Participação acumulada dos órgãos com maior volume de publicações."
              badge={loading ? "RANKING" : `${analytics?.top_organs.length || 0} ÓRGÃOS`}
            >
              <TopOrgansPanel organs={analytics?.top_organs || []} />
            </ChartCard>

            <ChartCard
              title="Consultas frequentes"
              description="Termos mais usados na busca semanal, úteis para calibrar launchpad, autocomplete e filtros."
              badge={loading ? "BUSCA" : `${topSearches.length} CONSULTAS`}
            >
              <TopSearchesPanel topSearches={topSearches} />
            </ChartCard>
          </section>
        </main>
      </div>
    </div>
  );
};

const ChartCard: React.FC<{
  title: string;
  description: string;
  badge: string;
  children: React.ReactNode;
}> = ({ title, description, badge, children }) => (
  <section className="reader-surface rounded-[30px] px-7 py-7 shadow-[0_24px_80px_rgba(0,0,0,0.18)]">
    <div className="mb-6 flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
      <div>
        <h2 className="font-editorial text-[2rem] leading-none text-foreground">{title}</h2>
        <p className="mt-3 max-w-3xl text-sm leading-relaxed text-text-secondary">{description}</p>
      </div>
      <span className="inline-flex rounded-full border border-white/8 bg-white/[0.03] px-4 py-2 text-[11px] font-semibold tracking-[0.18em] text-text-tertiary">
        {badge}
      </span>
    </div>
    {children}
  </section>
);

const PublicationVolumeChart: React.FC<{ data: AnalyticsSectionMonthlyPoint[] }> = ({ data }) => {
  if (data.length === 0) {
    return <EmptyChart text="Sem série mensal disponível para renderizar o volume por seção." />;
  }

  const maxTotal = Math.max(...data.map((item) => item.total), 1);
  const chartBottom = 244;
  const usableHeight = 184;
  const barWidth = Math.max(18, Math.floor(720 / Math.max(1, data.length * 1.5)));
  const gap = 10;

  return (
    <div className="overflow-x-auto">
      <svg viewBox={`0 0 ${Math.max(980, data.length * (barWidth + gap) + 120)} 286`} className="w-full min-w-[900px]">
        <line x1="48" y1="26" x2="48" y2="244" stroke="rgba(255,255,255,0.08)" />
        <line x1="48" y1="244" x2="940" y2="244" stroke="rgba(255,255,255,0.08)" />
        {[0.25, 0.5, 0.75].map((ratio, index) => (
          <line key={ratio} x1="48" y1={244 - usableHeight * ratio} x2="940" y2={244 - usableHeight * ratio} stroke="rgba(255,255,255,0.05)" strokeDasharray="5 7" />
        ))}

        {[maxTotal, Math.round(maxTotal / 2), 0].map((label, index) => (
          <text key={label + index} x="36" y={index === 0 ? 30 : index === 1 ? 142 : 248} fill="#64748b" fontSize="11" textAnchor="end">
            {label.toLocaleString("pt-BR")}
          </text>
        ))}

        {data.map((item, index) => {
          const x = 72 + index * (barWidth + gap);
          const extraHeight = (item.extra / maxTotal) * usableHeight;
          const do3Height = (item.do3 / maxTotal) * usableHeight;
          const do2Height = (item.do2 / maxTotal) * usableHeight;
          const do1Height = (item.do1 / maxTotal) * usableHeight;
          const totalHeight = (item.total / maxTotal) * usableHeight;
          const top = chartBottom - totalHeight;
          return (
            <g key={item.month}>
              {item.extra > 0 ? <rect x={x} y={chartBottom - extraHeight} width={barWidth} height={extraHeight} rx="5" fill="#eab308" opacity="0.9" /> : null}
              {item.do3 > 0 ? <rect x={x} y={chartBottom - extraHeight - do3Height} width={barWidth} height={do3Height} rx="5" fill="#ec4899" opacity="0.85" /> : null}
              {item.do2 > 0 ? <rect x={x} y={chartBottom - extraHeight - do3Height - do2Height} width={barWidth} height={do2Height} rx="5" fill="#a78bfa" opacity="0.88" /> : null}
              {item.do1 > 0 ? <rect x={x} y={top} width={barWidth} height={do1Height} rx="5" fill="#4b8bf5" opacity="0.92" /> : null}
              <text x={x + barWidth / 2} y="272" fill="#64748b" fontSize="10" textAnchor="middle">
                {new Date(item.month).toLocaleDateString("pt-BR", { month: "short" })}
              </text>
            </g>
          );
        })}
      </svg>

      <div className="mt-5 flex flex-wrap items-center justify-end gap-x-6 gap-y-3 text-[12px] text-text-secondary">
        <LegendSwatch color="#4b8bf5" label="DO1" />
        <LegendSwatch color="#a78bfa" label="DO2" />
        <LegendSwatch color="#ec4899" label="DO3" />
        <LegendSwatch color="#eab308" label="Extra" />
      </div>
    </div>
  );
};

const ActsLineChart: React.FC<{ months: string[]; series: AnalyticsTypeSeries[] }> = ({ months, series }) => {
  if (months.length === 0 || series.length === 0) {
    return <EmptyChart text="Sem séries temporais de tipos disponíveis." />;
  }

  const palette = ["#7c6cf0", "#4b8bf5", "#60a5fa", "#a78bfa", "#ec4899"];
  const maxPoint = Math.max(...series.flatMap((item) => item.points), 1);
  const width = Math.max(980, months.length * 64 + 90);

  const buildPath = (points: number[]) =>
    points
      .map((point, index) => {
        const x = 54 + index * 64;
        const y = 228 - (point / maxPoint) * 156;
        return `${index === 0 ? "M" : "L"}${x},${y}`;
      })
      .join(" ");

  return (
    <div className="overflow-x-auto">
      <svg viewBox={`0 0 ${width} 286`} className="w-full min-w-[900px]">
        <line x1="48" y1="24" x2="48" y2="222" stroke="rgba(255,255,255,0.08)" />
        <line x1="48" y1="222" x2={width - 40} y2="222" stroke="rgba(255,255,255,0.08)" />

        {series.map((item, index) => (
          <path
            key={item.key}
            d={buildPath(item.points)}
            fill="none"
            stroke={palette[index % palette.length]}
            strokeWidth="3"
            strokeLinecap="round"
          />
        ))}

        {months.map((month, index) => (
          <text key={month} x={54 + index * 64} y="256" fill="#64748b" fontSize="10" textAnchor="middle">
            {new Date(month).toLocaleDateString("pt-BR", { month: "short" })}
          </text>
        ))}
      </svg>

      <div className="mt-5 flex flex-wrap items-center gap-x-8 gap-y-3 text-[12px] text-text-secondary">
        {series.map((item, index) => (
          <LegendSwatch key={item.key} color={palette[index % palette.length]} label={`${item.label} (${item.total.toLocaleString("pt-BR")})`} />
        ))}
      </div>
    </div>
  );
};

const TopOrgansPanel: React.FC<{ organs: AnalyticsResponse["top_organs"] }> = ({ organs }) => {
  if (organs.length === 0) {
    return <EmptyChart text="Sem ranking de órgãos disponível." />;
  }

  const max = Math.max(...organs.map((item) => item.count), 1);
  return (
    <div className="space-y-4">
      {organs.map((item) => (
        <div key={item.organ}>
          <div className="mb-1 flex items-center justify-between gap-3">
            <span className="truncate text-sm text-foreground">{item.organ}</span>
            <span className="shrink-0 text-xs text-text-tertiary">{item.count.toLocaleString("pt-BR")}</span>
          </div>
          <div className="h-2 overflow-hidden rounded-full bg-white/[0.05]">
            <div
              className="h-full rounded-full bg-[linear-gradient(90deg,hsl(var(--primary)),hsl(var(--accent)))]"
              style={{ width: `${(item.count / max) * 100}%` }}
            />
          </div>
        </div>
      ))}
    </div>
  );
};

const TopSearchesPanel: React.FC<{ topSearches: TopSearch[] }> = ({ topSearches }) => {
  if (topSearches.length === 0) {
    return <EmptyChart text="Sem sinais de consultas frequentes disponíveis." />;
  }

  return (
    <div className="space-y-3">
      {topSearches.map((item, index) => (
        <div key={item.query} className="rounded-[18px] border border-white/8 bg-white/[0.03] px-4 py-4">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <p className="text-[11px] uppercase tracking-[0.16em] text-text-tertiary">Consulta #{index + 1}</p>
              <p className="mt-2 font-editorial text-xl leading-tight text-foreground">{item.query}</p>
            </div>
            <span className="rounded-full border border-white/8 px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.14em] text-text-tertiary">
              {item.count.toLocaleString("pt-BR")}
            </span>
          </div>
        </div>
      ))}
    </div>
  );
};

const LegendSwatch: React.FC<{ color: string; label: string }> = ({ color, label }) => (
  <div className="flex items-center gap-2">
    <svg width="18" height="10" viewBox="0 0 18 10" aria-hidden="true">
      <line x1="0" y1="5" x2="18" y2="5" stroke={color} strokeWidth="3" />
    </svg>
    <span>{label}</span>
  </div>
);

const EmptyChart: React.FC<{ text: string }> = ({ text }) => (
  <div className="flex min-h-[200px] items-center justify-center text-center text-sm text-text-secondary">
    {text}
  </div>
);

function formatMonth(value?: string | null) {
  if (!value) return "n/d";
  try {
    return new Date(value).toLocaleDateString("pt-BR", { month: "short", year: "numeric" });
  } catch {
    return value;
  }
}

export default AnalyticsPage;
