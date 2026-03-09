import { cn } from "@/lib/utils";
import type { AnalyticsData } from "@/types";

const CHART_COLORS = {
  do1: "hsl(var(--do1))",
  do2: "hsl(var(--do2))",
  do3: "hsl(var(--do3))",
};

const PIE_COLORS = [
  CHART_COLORS.do1, CHART_COLORS.do2, CHART_COLORS.do3,
  "hsl(var(--status-updated))", "hsl(var(--text-tertiary))", "hsl(var(--status-archived))",
];

const CHART_WIDTH = 640;
const CHART_HEIGHT = 220;
const CHART_PADDING = { top: 12, right: 8, bottom: 28, left: 8 };

function formatCount(value: number) {
  return value.toLocaleString("pt-BR");
}

function formatPercent(value: number) {
  return `${value.toFixed(1)}%`;
}

function getConicGradient(values: AnalyticsData["actTypes"]) {
  let accumulated = 0;

  const stops = values.map((item, index) => {
    const start = accumulated;
    accumulated += item.percentage;
    return `${PIE_COLORS[index % PIE_COLORS.length]} ${start}% ${accumulated}%`;
  });

  if (accumulated < 100) {
    stops.push(`hsl(var(--border)) ${accumulated}% 100%`);
  }

  return `conic-gradient(${stops.join(", ")})`;
}

function buildAreaPath(points: Array<{ x: number; y: number }>, baseline: number) {
  if (points.length === 0) return "";
  const line = points.map(({ x, y }, index) => `${index === 0 ? "M" : "L"} ${x.toFixed(2)} ${y.toFixed(2)}`).join(" ");
  const close = points
    .slice()
    .reverse()
    .map(({ x }) => `L ${x.toFixed(2)} ${baseline.toFixed(2)}`)
    .join(" ");
  return `${line} ${close} Z`;
}

function StackedAreaSvg({ data }: { data: AnalyticsData["volume"] }) {
  if (data.length === 0) {
    return <div className="flex h-[220px] items-center justify-center text-sm text-text-tertiary">Sem série temporal disponível.</div>;
  }

  const plotWidth = CHART_WIDTH - CHART_PADDING.left - CHART_PADDING.right;
  const plotHeight = CHART_HEIGHT - CHART_PADDING.top - CHART_PADDING.bottom;
  const baseline = CHART_PADDING.top + plotHeight;
  const maxTotal = Math.max(...data.map((point) => point.do1 + point.do2 + point.do3), 1);
  const safeDivisor = Math.max(data.length - 1, 1);

  const xAt = (index: number) => CHART_PADDING.left + (index / safeDivisor) * plotWidth;
  const yAt = (value: number) => CHART_PADDING.top + plotHeight - (value / maxTotal) * plotHeight;

  const do1Points = data.map((point, index) => ({ x: xAt(index), y: yAt(point.do1) }));
  const do12Points = data.map((point, index) => ({ x: xAt(index), y: yAt(point.do1 + point.do2) }));
  const do123Points = data.map((point, index) => ({ x: xAt(index), y: yAt(point.do1 + point.do2 + point.do3) }));

  const gridLines = 4;

  return (
    <div className="overflow-hidden rounded-2xl border border-border/70 bg-background/30 p-3">
      <svg viewBox={`0 0 ${CHART_WIDTH} ${CHART_HEIGHT}`} className="h-[220px] w-full" role="img" aria-label="Volume mensal por seção">
        {Array.from({ length: gridLines + 1 }, (_, index) => {
          const y = CHART_PADDING.top + (plotHeight / gridLines) * index;
          return (
            <line
              key={y}
              x1={CHART_PADDING.left}
              y1={y}
              x2={CHART_WIDTH - CHART_PADDING.right}
              y2={y}
              stroke="hsl(var(--border))"
              strokeDasharray="4 6"
              strokeWidth="1"
            />
          );
        })}

        <path d={buildAreaPath(do123Points, baseline)} fill={CHART_COLORS.do3} fillOpacity="0.22" />
        <path d={buildAreaPath(do12Points, baseline)} fill={CHART_COLORS.do2} fillOpacity="0.26" />
        <path d={buildAreaPath(do1Points, baseline)} fill={CHART_COLORS.do1} fillOpacity="0.32" />

        {[
          { points: do123Points, color: CHART_COLORS.do3 },
          { points: do12Points, color: CHART_COLORS.do2 },
          { points: do1Points, color: CHART_COLORS.do1 },
        ].map(({ points, color }, index) => (
          <polyline
            key={color}
            points={points.map(({ x, y }) => `${x},${y}`).join(" ")}
            fill="none"
            stroke={color}
            strokeWidth={index === 2 ? 2.5 : 2}
            strokeLinejoin="round"
            strokeLinecap="round"
          />
        ))}

        {data.map((point, index) => (
          <text
            key={point.date}
            x={xAt(index)}
            y={CHART_HEIGHT - 8}
            textAnchor={index === 0 ? "start" : index === data.length - 1 ? "end" : "middle"}
            fontSize="10"
            fill="hsl(var(--text-tertiary))"
          >
            {point.date.slice(5)}
          </text>
        ))}
      </svg>

      <div className="mt-3 flex flex-wrap gap-3 text-[11px] text-text-secondary">
        <span className="inline-flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-full bg-do1" />DO1</span>
        <span className="inline-flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-full bg-do2" />DO2</span>
        <span className="inline-flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-full bg-do3" />DO3</span>
      </div>
    </div>
  );
}

const Panel = ({ title, children, className }: { title: string; children: React.ReactNode; className?: string }) => (
  <div className={cn("rounded-xl border border-border bg-surface-elevated p-4 md:p-5", className)}>
    <h3 className="mb-4 text-xs font-semibold uppercase tracking-wider text-text-secondary">{title}</h3>
    {children}
  </div>
);

export default function AnalyticsCharts({ data }: { data: AnalyticsData }) {
  const recentMonths = data.volume.slice(-6);

  return (
    <>
      <Panel title="Volume Mensal por Seção">
        <StackedAreaSvg data={data.volume} />
        <div className="mt-4 overflow-x-auto">
          <table className="min-w-full text-left text-xs">
            <thead className="text-text-tertiary">
              <tr>
                <th className="pb-2 pr-4 font-medium">Mês</th>
                <th className="pb-2 pr-4 font-medium">DO1</th>
                <th className="pb-2 pr-4 font-medium">DO2</th>
                <th className="pb-2 pr-4 font-medium">DO3</th>
                <th className="pb-2 font-medium">Total</th>
              </tr>
            </thead>
            <tbody>
              {recentMonths.map((point) => {
                const total = point.do1 + point.do2 + point.do3;
                return (
                  <tr key={point.date} className="border-t border-border/60 text-text-secondary">
                    <td className="py-2 pr-4">{point.date}</td>
                    <td className="py-2 pr-4">{formatCount(point.do1)}</td>
                    <td className="py-2 pr-4">{formatCount(point.do2)}</td>
                    <td className="py-2 pr-4">{formatCount(point.do3)}</td>
                    <td className="py-2 font-medium text-foreground">{formatCount(total)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Panel>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <Panel title="Atividade por Órgão">
          <ul className="space-y-3">
            {data.organActivity.map((item, index) => {
              const maxCount = data.organActivity[0]?.count || 1;
              const width = `${Math.max((item.count / maxCount) * 100, 8)}%`;

              return (
                <li key={item.organ} className="space-y-2">
                  <div className="flex items-center justify-between gap-3 text-sm">
                    <span className="min-w-0 truncate text-text-secondary">{item.organ}</span>
                    <strong className="shrink-0 text-foreground">{formatCount(item.count)}</strong>
                  </div>
                  <div className="h-2.5 overflow-hidden rounded-full bg-background/60">
                    <div
                      className="h-full rounded-full transition-[width] duration-500"
                      style={{
                        width,
                        background:
                          index % 2 === 0
                            ? "linear-gradient(90deg, hsl(var(--do1)), hsl(var(--do2)))"
                            : "linear-gradient(90deg, hsl(var(--do2)), hsl(var(--do3)))",
                      }}
                    />
                  </div>
                </li>
              );
            })}
          </ul>
        </Panel>

        <Panel title="Tipos de Ato">
          <div className="flex flex-col gap-5 md:flex-row md:items-center">
            <div className="mx-auto flex flex-col items-center gap-3 md:mx-0">
              <div
                className="relative h-40 w-40 rounded-full border border-border/80"
                style={{ background: getConicGradient(data.actTypes) }}
                aria-hidden="true"
              >
                <div className="absolute inset-[22%] rounded-full border border-border bg-surface-elevated/95" />
                <div className="absolute inset-0 flex flex-col items-center justify-center text-center">
                  <span className="text-[11px] font-semibold uppercase tracking-[0.18em] text-text-tertiary">
                    Top 6
                  </span>
                  <span className="mt-2 text-2xl font-semibold text-foreground">
                    {formatCount(data.actTypes.reduce((sum, item) => sum + item.count, 0))}
                  </span>
                  <span className="mt-1 text-xs text-text-secondary">atos mapeados</span>
                </div>
              </div>
              <div className="flex flex-wrap justify-center gap-2">
                {data.actTypes.map((at, index) => (
                  <span key={at.type} className="flex items-center gap-1 text-[10px] text-text-secondary">
                    <span className="h-2 w-2 rounded-full" style={{ background: PIE_COLORS[index % PIE_COLORS.length] }} />
                    {at.type}
                  </span>
                ))}
              </div>
            </div>
            <ul className="min-w-0 flex-1 space-y-3">
              {data.actTypes.map((item, index) => (
                <li key={item.type} className="space-y-1.5">
                  <div className="flex items-center justify-between gap-3 text-sm">
                    <span className="min-w-0 truncate text-text-secondary">{item.type}</span>
                    <span className="shrink-0 text-foreground">{formatPercent(item.percentage)}</span>
                  </div>
                  <div className="h-2 overflow-hidden rounded-full bg-background/60">
                    <div
                      className="h-full rounded-full"
                      style={{
                        width: `${Math.max(item.percentage, 4)}%`,
                        background: PIE_COLORS[index % PIE_COLORS.length],
                      }}
                    />
                  </div>
                </li>
              ))}
            </ul>
          </div>
          <div className="mt-4 overflow-x-auto">
            <table className="min-w-full text-left text-xs">
              <thead className="text-text-tertiary">
                <tr>
                  <th className="pb-2 pr-4 font-medium">Tipo</th>
                  <th className="pb-2 pr-4 font-medium">Volume</th>
                  <th className="pb-2 font-medium">Participação</th>
                </tr>
              </thead>
              <tbody>
                {data.actTypes.map((item) => (
                  <tr key={item.type} className="border-t border-border/60 text-text-secondary">
                    <td className="py-2 pr-4">{item.type}</td>
                    <td className="py-2 pr-4">{formatCount(item.count)}</td>
                    <td className="py-2">{formatPercent(item.percentage)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
      </div>

      <Panel title="Distribuição por Seção">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          {data.sectionTotals.map((section) => (
            <div key={section.section} className="rounded-xl border border-border bg-background/40 p-4">
              <p className="text-xs font-semibold uppercase tracking-wider text-text-tertiary">{section.section}</p>
              <p className="mt-2 text-2xl font-bold text-foreground">{formatCount(section.count)}</p>
              <p className="mt-1 text-sm text-text-secondary">{formatPercent(section.percentage)} do corpus</p>
            </div>
          ))}
        </div>
      </Panel>

      <Panel title="Documentos Recentes">
        <ul className="space-y-3">
          {data.latestDocuments.map((doc) => (
            <li key={doc.id} className="rounded-xl border border-border bg-background/40 p-4">
              <p className="text-xs uppercase tracking-wider text-text-tertiary">{doc.section} · {doc.organ}</p>
              <p className="mt-2 font-medium text-foreground">{doc.title}</p>
              <p className="mt-1 text-sm text-text-secondary">{doc.summary}</p>
            </li>
          ))}
        </ul>
      </Panel>
    </>
  );
}
