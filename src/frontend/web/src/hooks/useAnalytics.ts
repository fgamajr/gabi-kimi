import { useQuery } from "@tanstack/react-query";
import { getAnalytics } from "@/lib/api";
import type { AnalyticsData } from "@/types";
import { readCachedValue, writeCachedValue } from "@/lib/clientCache";

function normalizeSection(section?: string | null) {
  const raw = String(section || "").trim().toLowerCase();
  if (raw === "do2" || raw === "2") return "DO2" as const;
  if (raw === "do3" || raw === "3") return "DO3" as const;
  return "DO1" as const;
}

const ANALYTICS_CACHE_KEY = "analytics-summary-v2";
const ANALYTICS_CACHE_TTL_MS = 10 * 60 * 1000;

function computePercentChange(currentValue: number, previousValue: number) {
  if (previousValue <= 0) return undefined;
  return Math.round(((currentValue - previousValue) / previousValue) * 100);
}

export async function getAnalyticsViewQueryFn(): Promise<AnalyticsData> {
  const payload = await getAnalytics();
  const recentMonthlyTotals = payload.section_monthly.slice(-12).map((item) => item.total || 0);
  const currentMonthlyTotal = recentMonthlyTotals.at(-1) ?? 0;
  const previousMonthlyTotal = recentMonthlyTotals.at(-2) ?? 0;
  const publicationsChange = computePercentChange(currentMonthlyTotal, previousMonthlyTotal);
  const kpis = [
    {
      label: "Publicações",
      value: payload.overview.total_documents,
      change: publicationsChange,
      changeLabel: publicationsChange != null ? "vs. mês anterior" : "Série insuficiente",
      sparkline: recentMonthlyTotals,
    },
    {
      label: "Órgãos",
      value: payload.overview.total_organs,
      sparkline: payload.top_organs.slice(0, 12).map((item) => item.count),
      changeLabel: "Base indexada atual",
    },
    {
      label: "Tipos",
      value: payload.overview.total_types,
      sparkline: payload.top_types_monthly.series.slice(0, 12).map((item) => item.total),
      changeLabel: "Base indexada atual",
    },
  ];

  const actTypes = payload.top_types_monthly.series.slice(0, 6).map((item) => ({
    type: item.label,
    count: item.total,
      percentage: payload.overview.total_documents > 0 ? (item.total / payload.overview.total_documents) * 100 : 0,
  }));

  const sectionTotals = payload.section_totals.map((item) => ({
    section: normalizeSection(item.section),
    count: item.count,
    percentage: payload.overview.total_documents > 0 ? (item.count / payload.overview.total_documents) * 100 : 0,
  }));

  const value = {
    volume: payload.section_monthly.map((item) => ({
      date: item.month,
      do1: item.do1,
      do2: item.do2,
      do3: item.do3,
    })),
    organActivity: payload.top_organs.slice(0, 6).map((item) => ({
      organ: item.organ,
      count: item.count,
    })),
    actTypes,
    sectionTotals,
    kpis,
    latestDocuments: payload.latest_documents.slice(0, 4).map((item) => ({
      id: item.id,
      title: item.title,
      summary: item.snippet || item.art_type || "Documento recente do corpus",
      section: normalizeSection(item.section),
      organ: item.issuing_organ || "Órgão não informado",
      publishedAt: item.pub_date || "",
      tags: [item.art_type, item.page ? `Página ${item.page}` : undefined].filter(Boolean) as string[],
      toc: [],
      body: "",
    })),
  };
  writeCachedValue(ANALYTICS_CACHE_KEY, value, ANALYTICS_CACHE_TTL_MS);
  return value;
}

export function useAnalytics() {
  return useQuery<AnalyticsData>({
    queryKey: ["analytics"],
    queryFn: getAnalyticsViewQueryFn,
    initialData: () => readCachedValue<AnalyticsData>(ANALYTICS_CACHE_KEY),
    staleTime: 3 * 60_000,
    gcTime: 15 * 60_000,
    refetchOnWindowFocus: false,
  });
}
