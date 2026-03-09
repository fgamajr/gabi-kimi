import { useQuery } from "@tanstack/react-query";
import {
  getAnalytics,
  getDocument,
  searchDocuments,
  type DocumentDetail,
  type SearchResult as ApiSearchResult,
} from "@/lib/api";
import type { Document, DOSection, SearchFilters, SearchResult } from "@/types";
import { readCachedValue, writeCachedValue } from "@/lib/clientCache";

const FEATURED_CACHE_KEY = "featured-documents";
const FEATURED_CACHE_TTL_MS = 10 * 60 * 1000;

function normalizeSection(section?: string | null): DOSection {
  const raw = String(section || "").trim().toLowerCase();
  if (raw === "do2" || raw === "2") return "DO2";
  if (raw === "do3" || raw === "3") return "DO3";
  return "DO1";
}

function toSearchResult(item: ApiSearchResult): SearchResult {
  return {
    id: item.id,
    title: item.title,
    snippet: item.highlight || item.snippet || item.subtitle || "Documento disponível para leitura.",
    section: normalizeSection(item.section),
    organ: item.issuing_organ || "Órgão não informado",
    publishedAt: item.pub_date,
    relevance: 0.72,
    tags: [item.art_type, item.page ? `p.${item.page}` : undefined].filter(Boolean) as string[],
  };
}

function stripHtml(value?: string) {
  return String(value || "")
    .replace(/<style[\s\S]*?<\/style>/gi, " ")
    .replace(/<script[\s\S]*?<\/script>/gi, " ")
    .replace(/<[^>]+>/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function buildToc(detail: DocumentDetail) {
  const source = detail.body_plain || stripHtml(detail.body_html);
  return Array.from(source.matchAll(/(Art\.\s*\d+[°º]?)/g)).slice(0, 20).map((match, index) => ({
    id: `art-${index + 1}`,
    label: match[1],
    level: 1,
  }));
}

function toDocument(detail: DocumentDetail): Document {
  return {
    id: detail.id,
    title: detail.title,
    summary: detail.ementa || detail.subtitle || detail.issuing_organ || "Documento do DOU",
    body: detail.body_plain || stripHtml(detail.body_html),
    section: normalizeSection(detail.section),
    organ: detail.issuing_organ || "Órgão não informado",
    publishedAt: detail.pub_date,
    tags: [detail.art_type_name, detail.page ? `Página ${detail.page}` : undefined].filter(Boolean) as string[],
    toc: buildToc(detail),
  };
}

export function useDocuments() {
  return useQuery({
    queryKey: ["documents"],
    queryFn: async () => {
      const response = await searchDocuments({ q: "*", max: 12 });
      return response.results.map(toSearchResult);
    },
    staleTime: 60_000,
    gcTime: 10 * 60_000,
    refetchOnWindowFocus: false,
  });
}

export function useDocument(id: string) {
  return useQuery({
    queryKey: ["document", id],
    queryFn: async () => toDocument(await getDocument(id)),
    enabled: !!id,
  });
}

export async function getFeaturedDocumentsQueryFn(): Promise<Document[]> {
  const analytics = await getAnalytics();
  if (analytics.latest_documents.length > 0) {
    const value = analytics.latest_documents.slice(0, 4).map((item) => ({
      id: item.id,
      title: item.title,
      summary: item.snippet || item.art_type || "Documento recente do corpus",
      section: normalizeSection(item.section),
      organ: item.issuing_organ || "Órgão não informado",
      publishedAt: item.pub_date || "",
      tags: [item.art_type, item.page ? `Página ${item.page}` : undefined].filter(Boolean) as string[],
      body: "",
      toc: [],
    }));
    writeCachedValue(FEATURED_CACHE_KEY, value, FEATURED_CACHE_TTL_MS);
    return value;
  }
  const response = await searchDocuments({ q: "*", max: 4 });
  const value = response.results.map((item) => ({
    id: item.id,
    title: item.title,
    summary: item.highlight || item.snippet || item.subtitle || "Documento em destaque",
    section: normalizeSection(item.section),
    organ: item.issuing_organ || "Órgão não informado",
    publishedAt: item.pub_date,
    tags: [item.art_type].filter(Boolean) as string[],
    body: "",
    toc: [],
  }));
  writeCachedValue(FEATURED_CACHE_KEY, value, FEATURED_CACHE_TTL_MS);
  return value;
}

export function useFeaturedDocuments() {
  return useQuery<Document[]>({
    queryKey: ["documents", "featured"],
    queryFn: getFeaturedDocumentsQueryFn,
    initialData: () => readCachedValue<Document[]>(FEATURED_CACHE_KEY),
    staleTime: 3 * 60_000,
    gcTime: 15 * 60_000,
    refetchOnWindowFocus: false,
    select: (data) => {
      writeCachedValue(FEATURED_CACHE_KEY, data, FEATURED_CACHE_TTL_MS);
      return data;
    },
  });
}

export function useSearch(filters: SearchFilters) {
  return useQuery({
    queryKey: ["search", filters],
    queryFn: async () => {
      const response = await searchDocuments({
        q: filters.query,
        max: 20,
        section: filters.section?.toLowerCase(),
        issuing_organ: filters.organ,
        date_from: filters.dateFrom,
        date_to: filters.dateTo,
      });
      return response.results.map(toSearchResult);
    },
    enabled: filters.query.length > 0,
    staleTime: 30_000,
    gcTime: 5 * 60_000,
    refetchOnWindowFocus: false,
  });
}
