import React from "react";
import { useNavigate } from "react-router-dom";
import { Icons } from "@/components/Icons";

const publicationData = [
  { month: "Jan", do1: 110, do2: 120, do3: 40 },
  { month: "Fev", do1: 96, do2: 132, do3: 52 },
  { month: "Mar", do1: 84, do2: 104, do3: 48 },
  { month: "Abr", do1: 118, do2: 138, do3: 58 },
  { month: "Mai", do1: 124, do2: 154, do3: 66 },
  { month: "Jun", do1: 102, do2: 126, do3: 46 },
  { month: "Jul", do1: 76, do2: 94, do3: 36 },
  { month: "Ago", do1: 112, do2: 140, do3: 60 },
  { month: "Set", do1: 104, do2: 128, do3: 52 },
  { month: "Out", do1: 138, do2: 166, do3: 72 },
  { month: "Nov", do1: 192, do2: 238, do3: 88 },
  { month: "Dez", do1: 214, do2: 274, do3: 104 },
];

const lineSeries = [
  { label: "Portarias", color: "#3B82F6", points: [56, 61, 52, 63, 67, 58, 49, 65, 60, 71, 82, 78] },
  { label: "Decretos", color: "#8B5CF6", points: [16, 15, 18, 19, 18, 16, 14, 20, 18, 21, 23, 21] },
  { label: "Editais", color: "#2DD4BF", points: [24, 26, 22, 28, 27, 26, 20, 29, 26, 31, 34, 32] },
  { label: "Extratos contrato", color: "#EF4444", points: [8, 9, 10, 12, 14, 11, 9, 15, 18, 22, 46, 38] },
  { label: "Resoluções", color: "#FBBF24", points: [8, 8, 7, 9, 8, 7, 6, 8, 8, 9, 10, 9], dashed: true },
];

const heatmapRows = [
  [1, 1, 2, 2, 2, 1, 2, 2, 2, 1, 2, 2, 3, 2, 2, 1, 1, 2, 2, 3, 3, 4, 5, 5, 5, 4, 4, 5, 5, 4, 4, 5, 4, 5, 5, 4, 5, 5, 5, 4, 3, 3, 2, 2, 1, 1, 2, 2],
  [1, 2, 2, 3, 2, 2, 2, 2, 3, 1, 2, 2, 3, 2, 2, 1, 2, 2, 2, 3, 3, 4, 5, 5, 5, 4, 5, 5, 5, 4, 5, 5, 5, 5, 5, 4, 5, 5, 5, 5, 4, 3, 2, 2, 2, 1, 2, 2],
  [1, 1, 2, 2, 2, 1, 2, 3, 2, 1, 2, 2, 3, 2, 2, 1, 2, 2, 2, 3, 3, 4, 4, 5, 4, 4, 5, 5, 4, 4, 4, 5, 4, 5, 5, 4, 5, 4, 5, 4, 4, 3, 2, 2, 1, 1, 2, 2],
  [1, 1, 2, 2, 2, 1, 2, 2, 2, 1, 2, 3, 3, 2, 2, 1, 2, 2, 2, 3, 3, 4, 5, 5, 5, 4, 4, 5, 5, 4, 4, 5, 4, 5, 5, 4, 5, 5, 5, 4, 4, 3, 2, 2, 1, 1, 2, 2],
  [1, 1, 2, 2, 2, 1, 2, 2, 2, 1, 2, 2, 3, 2, 2, 1, 2, 2, 2, 3, 3, 4, 5, 5, 5, 4, 4, 5, 5, 4, 5, 5, 5, 5, 5, 4, 5, 5, 5, 4, 4, 3, 2, 2, 1, 1, 2, 3],
];

const heatmapColors = ["bg-[#1a1630]", "bg-[#2c2057]", "bg-[#5138a0]", "bg-[#7c5cfc]", "bg-[#ef4444]"];
const months = ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez"];

const AnalyticsPage: React.FC = () => {
  const navigate = useNavigate();

  return (
    <div className="min-h-screen bg-background">
      <div className="mx-auto max-w-[1120px] px-6 py-8 md:px-10 md:py-10">
        <header className="border-b border-white/6 pb-6">
          <button
            onClick={() => navigate(-1)}
            className="inline-flex min-h-[44px] items-center gap-3 rounded-xl text-foreground transition-colors hover:text-primary focus-ring"
          >
            <Icons.back className="h-5 w-5" />
            <span className="text-[1.75rem] font-semibold tracking-tight">Analytics</span>
          </button>
          <p className="mt-4 max-w-2xl text-sm text-text-secondary">
            Visualizações temporais do Diário Oficial da União para auditoria, variação operacional e detecção de padrões.
          </p>
        </header>

        <main className="mt-10 space-y-8">
          <ChartCard
            title="Volume de Publicações DOU"
            description="Publicações mensais por seção. Anomalias em volume podem indicar eventos legislativos importantes."
            badge="ALTA PRIORIDADE"
            badgeTone="violet"
            footerTags={["Audit scoping", "Detecção de anomalias", "Sazonalidade"]}
          >
            <PublicationVolumeChart />
          </ChartCard>

          <ChartCard
            title="Tipos de Atos ao Longo do Tempo"
            description="Distribuição de portarias, decretos, editais, extratos e resoluções. Picos em extratos de contrato antes do fim do exercício fiscal são red flags."
            badge="RED FLAGS"
            badgeTone="red"
            footerTags={["Detecção de fraude", "Ciclo orçamentário", "Padrão de contratação"]}
          >
            <ActsLineChart />
          </ChartCard>

          <ChartCard
            title="Heatmap de Atividade"
            description="Estilo GitHub contributions. Cada célula é um dia, cor = volume de publicações. Padrões visuais destacam fim de exercício e recessos."
            badge="PATTERN DETECTION"
            badgeTone="red"
          >
            <HeatmapChart />
          </ChartCard>
        </main>
      </div>
    </div>
  );
};

const ChartCard: React.FC<{
  title: string;
  description: string;
  badge: string;
  badgeTone: "violet" | "red";
  footerTags?: string[];
  children: React.ReactNode;
}> = ({ title, description, badge, badgeTone, footerTags = [], children }) => (
  <section className="rounded-[28px] border border-white/8 bg-[linear-gradient(180deg,rgba(24,27,36,0.92),rgba(18,20,28,0.96))] px-7 py-7 shadow-[0_24px_80px_rgba(0,0,0,0.24)]">
    <div className="mb-6 flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
      <div>
        <h2 className="text-[1.65rem] font-semibold tracking-tight text-foreground">{title}</h2>
        <p className="mt-2 max-w-2xl text-sm leading-relaxed text-text-secondary">{description}</p>
      </div>
      <span
        className={`inline-flex rounded-full px-4 py-2 text-[11px] font-semibold tracking-[0.18em] ${
          badgeTone === "violet" ? "bg-primary/15 text-primary" : "bg-red-500/12 text-red-400"
        }`}
      >
        {badge}
      </span>
    </div>
    {children}
    {footerTags.length ? (
      <div className="mt-6 flex flex-wrap gap-2 border-t border-white/6 pt-5">
        {footerTags.map((tag) => (
          <span key={tag} className="rounded-lg bg-white/[0.03] px-3 py-1.5 text-xs text-text-secondary">
            {tag}
          </span>
        ))}
      </div>
    ) : null}
  </section>
);

const PublicationVolumeChart: React.FC = () => {
  const maxTotal = Math.max(...publicationData.map((item) => item.do1 + item.do2 + item.do3));
  const chartBottom = 244;
  const usableHeight = 186;
  const averagePoints = publicationData
    .map((item, index) => {
      const total = item.do1 + item.do2 + item.do3;
      const x = 93 + index * 76;
      const y = chartBottom - (total / maxTotal) * usableHeight;
      return `${index === 0 ? "M" : "L"}${x},${y}`;
    })
    .join(" ");

  return (
    <div>
      <svg viewBox="0 0 980 286" className="w-full">
        <line x1="48" y1="26" x2="48" y2="244" stroke="rgba(255,255,255,0.08)" />
        <line x1="48" y1="244" x2="940" y2="244" stroke="rgba(255,255,255,0.08)" />
        <line x1="48" y1="64" x2="940" y2="64" stroke="rgba(255,255,255,0.06)" strokeDasharray="5 7" />
        <line x1="48" y1="138" x2="940" y2="138" stroke="rgba(255,255,255,0.06)" strokeDasharray="5 7" />

        {[600, 300, 0].map((label, index) => (
          <text key={label} x="36" y={index === 0 ? 30 : index === 1 ? 142 : 248} fill="#666d7d" fontSize="11" textAnchor="end">
            {label}
          </text>
        ))}

        {publicationData.map((item, index) => {
          const total = item.do1 + item.do2 + item.do3;
          const x = 72 + index * 76;
          const barWidth = 42;
          const do3Height = (item.do3 / maxTotal) * usableHeight;
          const do2Height = (item.do2 / maxTotal) * usableHeight;
          const do1Height = (item.do1 / maxTotal) * usableHeight;
          const totalHeight = (total / maxTotal) * usableHeight;
          const top = chartBottom - totalHeight;
          return (
            <g key={item.month}>
              <rect x={x} y={chartBottom - do3Height} width={barWidth} height={do3Height} rx="5" fill="#a73a72" opacity="0.82" />
              <rect x={x} y={chartBottom - do3Height - do2Height} width={barWidth} height={do2Height} rx="5" fill="#6940c8" opacity="0.9" />
              <rect x={x} y={top} width={barWidth} height={do1Height} rx="5" fill="#3f7dff" opacity="0.92" />
              <text x={x + barWidth / 2} y="274" fill="#666d7d" fontSize="11" textAnchor="middle">
                {item.month}
              </text>
            </g>
          );
        })}

        <path d={averagePoints} fill="none" stroke="#f2b82f" strokeWidth="3" strokeDasharray="10 6" />
        <line x1="826" y1="58" x2="826" y2="146" stroke="#ef4444" strokeWidth="2" strokeDasharray="5 4" />
        <circle cx="826" cy="56" r="5" fill="#ef4444" />
        <text x="840" y="60" fill="#ef4444" fontSize="12" fontWeight="700">
          ANOMALIA: +127% v/o
        </text>
      </svg>

      <div className="mt-5 flex flex-wrap items-center justify-end gap-x-6 gap-y-3 text-[12px] text-text-secondary">
        <LegendSwatch color="#3f7dff" label="DO1" />
        <LegendSwatch color="#6940c8" label="DO2" />
        <LegendSwatch color="#a73a72" label="DO3" />
        <LegendSwatch color="#f2b82f" label="Média 3m" dashed />
      </div>
    </div>
  );
};

const ActsLineChart: React.FC = () => {
  const maxPoint = Math.max(...lineSeries.flatMap((series) => series.points));

  const buildPath = (points: number[]) =>
    points
      .map((point, index) => {
        const x = 54 + index * 75;
        const y = 232 - (point / maxPoint) * 150;
        return `${index === 0 ? "M" : "L"}${x},${y}`;
      })
      .join(" ");

  return (
    <div>
      <svg viewBox="0 0 980 286" className="w-full">
        <line x1="48" y1="24" x2="48" y2="222" stroke="rgba(255,255,255,0.08)" />
        <line x1="48" y1="222" x2="940" y2="222" stroke="rgba(255,255,255,0.08)" />
        <rect x="786" y="40" width="158" height="182" rx="16" fill="rgba(239,68,68,0.08)" />
        <text x="830" y="56" fill="#ef4444" fontSize="12" fontWeight="700">RED FLAG</text>
        <text x="810" y="74" fill="#ef4444" fontSize="11">Pico de contratos</text>

        {lineSeries.map((series) => (
          <path
            key={series.label}
            d={buildPath(series.points)}
            fill="none"
            stroke={series.color}
            strokeWidth="3"
            strokeDasharray={series.dashed ? "8 6" : undefined}
          />
        ))}

        <circle cx="866" cy="136" r="5" fill="#ef4444" />

        {months.map((month, index) => (
          <text key={month} x={54 + index * 75} y="256" fill="#666d7d" fontSize="11" textAnchor="middle">
            {month}
          </text>
        ))}
      </svg>

      <div className="mt-5 flex flex-wrap items-center gap-x-8 gap-y-3 text-[12px] text-text-secondary">
        {lineSeries.map((series) => (
          <LegendSwatch key={series.label} color={series.color} label={series.label} dashed={series.dashed} />
        ))}
      </div>
    </div>
  );
};

const LegendSwatch: React.FC<{ color: string; label: string; dashed?: boolean }> = ({ color, label, dashed }) => (
  <div className="flex items-center gap-2">
    <svg width="18" height="10" viewBox="0 0 18 10" aria-hidden="true">
      <line x1="0" y1="5" x2="18" y2="5" stroke={color} strokeWidth="3" strokeDasharray={dashed ? "7 5" : undefined} />
    </svg>
    <span>{label}</span>
  </div>
);

const HeatmapChart: React.FC = () => (
  <div className="overflow-x-auto">
    <div className="min-w-[900px]">
      <div className="mb-3 grid grid-cols-[48px_repeat(12,minmax(0,1fr))] gap-2 text-[12px] text-text-secondary">
        <div />
        {months.map((month) => (
          <div key={month}>{month}</div>
        ))}
      </div>

      <div className="space-y-2">
        {["Seg", "Ter", "Qua", "Qui", "Sex"].map((label, rowIndex) => (
          <div key={label} className="grid grid-cols-[48px_1fr] items-center gap-2">
            <div className="text-[12px] text-text-secondary">{label}</div>
            <div className="grid grid-cols-12 gap-2">
              {Array.from({ length: 12 }).map((_, monthIndex) => (
                <div key={`${label}-${monthIndex}`} className="grid grid-cols-4 gap-1">
                  {heatmapRows[rowIndex].slice(monthIndex * 4, monthIndex * 4 + 4).map((value, cellIndex) => (
                    <div
                      key={`${label}-${monthIndex}-${cellIndex}`}
                      className={`h-5 rounded-[4px] ${heatmapColors[Math.max(0, value - 1)]}`}
                    />
                  ))}
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>

      <div className="mt-6 flex items-center justify-between gap-4 border-t border-white/6 pt-4">
        <div className="flex items-center gap-3 text-xs text-text-secondary">
          <span>Menos</span>
          {heatmapColors.map((color, index) => (
            <span key={index} className={`h-4 w-4 rounded-[4px] ${color}`} />
          ))}
          <span>Mais</span>
        </div>
        <div className="rounded-xl bg-red-500/10 px-4 py-3 text-right text-xs text-red-400">
          <p className="font-semibold uppercase tracking-[0.16em]">Fim do exercício</p>
          <p>Nov-Dez: +340% vol.</p>
        </div>
      </div>
    </div>
  </div>
);

export default AnalyticsPage;
