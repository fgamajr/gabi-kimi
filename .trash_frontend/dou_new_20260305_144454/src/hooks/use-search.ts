"use client";

import { useQuery } from "@tanstack/react-query";
import { useCallback, useEffect, useState } from "react";
import { useSearchParams, useRouter, usePathname } from "next/navigation";
import type { SearchFilters, SearchResponse, Document, Suggestion } from "@/types";

// =============================================================================
// Search Hook — URL State + React Query
// =============================================================================

// Use relative URLs when served from same origin (production)
// Use localhost:8000 for development
const API_BASE = typeof window !== "undefined" && window.location.port === "8000" 
  ? ""  // Same origin - use relative URLs
  : (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000");

// Build search URL from filters
function buildSearchUrl(filters: SearchFilters): string {
  const params = new URLSearchParams();
  
  if (filters.q) params.set("q", filters.q);
  if (filters.date_from) params.set("date_from", filters.date_from);
  if (filters.date_to) params.set("date_to", filters.date_to);
  if (filters.section) params.set("section", filters.section);
  if (filters.art_type) params.set("art_type", filters.art_type);
  if (filters.issuing_organ) params.set("issuing_organ", filters.issuing_organ);
  if (filters.page) params.set("page", String(filters.page));
  if (filters.per_page) params.set("max", String(filters.per_page));
  
  return `${API_BASE}/api/search?${params.toString()}`;
}

// Fetch search results
async function fetchSearch(filters: SearchFilters): Promise<SearchResponse> {
  const url = buildSearchUrl(filters);
  const response = await fetch(url);
  
  if (!response.ok) {
    throw new Error("Erro na busca");
  }
  
  const data = await response.json();
  
  // Transform API response to our type
  // API returns doc_id but we use id
  const results = (data.results || []).map((r: Record<string, unknown>) => {
    const editionSection = r.edition_section as string | undefined;
    return {
      ...r,
      id: (r.doc_id || r.id) as string,
      publication_date: (r.pub_date || r.publication_date) as string,
      section: (editionSection?.replace("do", "") || r.section) as string,
      issuing_organ: (r.identifica || r.issuing_organ) as string,
    };
  });
  
  return {
    results,
    total: data.total || 0,
    page: filters.page || 1,
    per_page: filters.per_page || 20,
    query_time_ms: data.query_time_ms,
    facets: data.facets,
  };
}

// Fetch suggestions
async function fetchSuggestions(query: string): Promise<Suggestion[]> {
  if (query.length < 2) return [];
  
  const response = await fetch(`${API_BASE}/api/suggest?q=${encodeURIComponent(query)}`);
  
  if (!response.ok) return [];
  
  const data = await response.json();
  
  return (data.suggestions || []).map((s: string | { term?: string; text?: string }) => {
    // Handle both string and object formats from API
    const text = typeof s === "string" ? s : (s.term || s.text || String(s));
    return {
      type: "exact" as const,
      text,
    };
  });
}

// =============================================================================
// useSearch Hook
// =============================================================================

export function useSearch() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  
  // Parse URL state
  const getFiltersFromUrl = useCallback((): SearchFilters => {
    return {
      q: searchParams.get("q") || "",
      date_from: searchParams.get("date_from") || undefined,
      date_to: searchParams.get("date_to") || undefined,
      section: searchParams.get("section") || undefined,
      art_type: searchParams.get("art_type") || undefined,
      issuing_organ: searchParams.get("issuing_organ") || undefined,
      page: parseInt(searchParams.get("page") || "1", 10),
      per_page: 20,
      sort: (searchParams.get("sort") as SearchFilters["sort"]) || "relevancia",
    };
  }, [searchParams]);
  
  const [filters, setFiltersState] = useState<SearchFilters>(getFiltersFromUrl);
  
  // Sync with URL
  useEffect(() => {
    setFiltersState(getFiltersFromUrl());
  }, [getFiltersFromUrl, searchParams]);
  
  // Update URL and state
  const setFilters = useCallback(
    (newFilters: Partial<SearchFilters>) => {
      const updated = { ...filters, ...newFilters };
      setFiltersState(updated);
      
      // Build new URL
      const params = new URLSearchParams();
      if (updated.q) params.set("q", updated.q);
      if (updated.date_from) params.set("date_from", updated.date_from);
      if (updated.date_to) params.set("date_to", updated.date_to);
      if (updated.section) params.set("section", updated.section);
      if (updated.art_type) params.set("art_type", updated.art_type);
      if (updated.issuing_organ) params.set("issuing_organ", updated.issuing_organ);
      if (updated.page && updated.page > 1) params.set("page", String(updated.page));
      
      const newUrl = `${pathname}?${params.toString()}`;
      router.push(newUrl, { scroll: false });
    },
    [filters, pathname, router]
  );
  
  // Clear search
  const clearSearch = useCallback(() => {
    setFiltersState({ page: 1, per_page: 20 });
    router.push(pathname);
  }, [pathname, router]);
  
  // Search query
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ["search", filters],
    queryFn: () => fetchSearch(filters),
    enabled: filters.q !== undefined && filters.q !== "",
    staleTime: 60 * 1000,
  });
  
  // Suggestions query
  const [suggestionQuery, setSuggestionQuery] = useState("");
  
  const { data: suggestions, isLoading: isLoadingSuggestions } = useQuery({
    queryKey: ["suggestions", suggestionQuery],
    queryFn: () => fetchSuggestions(suggestionQuery),
    enabled: suggestionQuery.length >= 2,
    staleTime: 30 * 1000,
  });
  
  // Recent searches (from localStorage)
  const [recentSearches, setRecentSearches] = useState<string[]>([]);
  
  useEffect(() => {
    const stored = localStorage.getItem("dou_recent_searches");
    if (stored) {
      try {
        setRecentSearches(JSON.parse(stored));
      } catch {
        setRecentSearches([]);
      }
    }
  }, []);
  
  const addRecentSearch = useCallback((query: string) => {
    if (!query.trim()) return;
    
    setRecentSearches((prev) => {
      const updated = [query, ...prev.filter((s) => s !== query)].slice(0, 10);
      localStorage.setItem("dou_recent_searches", JSON.stringify(updated));
      return updated;
    });
  }, []);
  
  const removeRecentSearch = useCallback((query: string) => {
    setRecentSearches((prev) => {
      const updated = prev.filter((s) => s !== query);
      localStorage.setItem("dou_recent_searches", JSON.stringify(updated));
      return updated;
    });
  }, []);
  
  return {
    filters,
    setFilters,
    clearSearch,
    results: data?.results || [],
    total: data?.total || 0,
    queryTime: data?.query_time_ms,
    facets: data?.facets,
    isLoading,
    error,
    refetch,
    suggestions: suggestions || [],
    isLoadingSuggestions,
    setSuggestionQuery,
    recentSearches,
    addRecentSearch,
    removeRecentSearch,
  };
}

// =============================================================================
// useDocument Hook
// =============================================================================

export function useDocument(docId: string | null) {
  return useQuery({
    queryKey: ["document", docId],
    queryFn: async (): Promise<Document> => {
      if (!docId) throw new Error("No document ID");
      
      const url = `${API_BASE}/api/document/${docId}`;
      console.log("Fetching document:", url);
      
      const response = await fetch(url);
      
      if (!response.ok) {
        const errorText = await response.text().catch(() => "Unknown error");
        console.error("Document fetch error:", response.status, errorText);
        throw new Error(`Documento não encontrado (${response.status})`);
      }
      
      const data = await response.json();
      console.log("Document loaded:", data.id || "unknown");
      return data;
    },
    enabled: !!docId,
    staleTime: 5 * 60 * 1000, // 5 minutes
    retry: 1,
  });
}

// =============================================================================
// useStats Hook
// =============================================================================

export function useStats() {
  return useQuery({
    queryKey: ["stats"],
    queryFn: async () => {
      const response = await fetch(`${API_BASE}/api/stats`);
      
      if (!response.ok) {
        throw new Error("Erro ao carregar estatísticas");
      }
      
      return response.json();
    },
    staleTime: 5 * 60 * 1000,
  });
}
