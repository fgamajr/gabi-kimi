import { useQuery } from "@tanstack/react-query";

import { getHighlights } from "@/lib/api";
import { readCachedValue, writeCachedValue } from "@/lib/clientCache";
import type { Document } from "@/types";

const HIGHLIGHTS_CACHE_KEY = "home-highlights";
const HIGHLIGHTS_CACHE_TTL_MS = 10 * 60 * 1000;

function normalizeSection(section?: string | null) {
  const raw = String(section || "").trim().toLowerCase();
  if (raw === "do2" || raw === "2") return "DO2" as const;
  if (raw === "do3" || raw === "3") return "DO3" as const;
  return "DO1" as const;
}

async function getHighlightsQueryFn(): Promise<Document[]> {
  const payload = await getHighlights(4);
  const value = payload.slice(0, 4).map((item) => ({
    id: item.id,
    title: item.title,
    summary: item.snippet || item.art_type || "Documento recente do corpus",
    section: normalizeSection(item.section),
    organ: item.issuing_organ || "Órgão não informado",
    publishedAt: item.pub_date || "",
    tags: [item.art_type, item.page ? `Página ${item.page}` : undefined].filter(Boolean) as string[],
    toc: [],
    body: "",
  }));
  writeCachedValue(HIGHLIGHTS_CACHE_KEY, value, HIGHLIGHTS_CACHE_TTL_MS);
  return value;
}

export function useHighlights() {
  return useQuery<Document[]>({
    queryKey: ["home-highlights"],
    queryFn: getHighlightsQueryFn,
    initialData: () => readCachedValue<Document[]>(HIGHLIGHTS_CACHE_KEY),
    staleTime: 3 * 60_000,
    gcTime: 15 * 60_000,
    refetchOnWindowFocus: false,
  });
}
