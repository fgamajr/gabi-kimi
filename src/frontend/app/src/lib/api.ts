// API configuration and types for DOU search system

const API_BASE = '/api';

// --- Types ---

export interface SearchParams {
  q: string;
  page?: number;
  max?: number;
  date_from?: string;
  date_to?: string;
  section?: string;
  art_type?: string;
  issuing_organ?: string;
}

export interface SearchResult {
  id: string;
  title: string;
  subtitle?: string;
  snippet?: string;
  highlight?: string;
  pub_date: string;
  section: string;
  page?: string;
  art_type?: string;
  issuing_organ?: string;
  dou_url?: string;
}

export interface SearchResponse {
  results: SearchResult[];
  total: number;
  page: number;
  max: number;
  query: string;
  took_ms?: number;
}

export interface DocumentMedia {
  name: string;
  status: 'available' | 'missing' | 'error';
  context_hint?: 'table' | 'signature' | 'emblem' | 'chart' | 'photo' | 'unknown';
  fallback_text?: string;
  original_url?: string;
  blob_url?: string;
  position_in_doc?: number;
}

export interface DocumentDetail {
  id: string;
  title: string;
  subtitle?: string;
  body_html?: string;
  body_plain?: string;
  pub_date: string;
  section: string;
  section_name?: string;
  page?: string;
  edition?: string;
  art_type?: string;
  art_type_name?: string;
  issuing_organ?: string;
  dou_url?: string;
  media?: DocumentMedia[];
  identifica?: string;
  ementa?: string;
  assinatura?: string;
}

export interface StatsResponse {
  total_documents: number;
  total_sections: number;
  date_range: { min: string; max: string };
  last_updated?: string;
  [key: string]: unknown;
}

export interface TypeOption {
  value: string;
  label: string;
  count?: number;
}

export interface TopSearch {
  query: string;
  count: number;
}

export interface SearchExample {
  query: string;
  description?: string;
}

export interface AutocompleteResult {
  suggestion: string;
  type?: string;
}

// --- API Functions ---

async function fetchJSON<T>(url: string): Promise<T> {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`API error: ${res.status}`);
  return res.json();
}

export function searchDocuments(params: SearchParams): Promise<SearchResponse> {
  const sp = new URLSearchParams();
  sp.set('q', params.q);
  if (params.page) sp.set('page', String(params.page));
  if (params.max) sp.set('max', String(params.max));
  if (params.date_from) sp.set('date_from', params.date_from);
  if (params.date_to) sp.set('date_to', params.date_to);
  if (params.section) sp.set('section', params.section);
  if (params.art_type) sp.set('art_type', params.art_type);
  if (params.issuing_organ) sp.set('issuing_organ', params.issuing_organ);
  return fetchJSON(`${API_BASE}/search?${sp.toString()}`);
}

export function getAutocomplete(q: string, n = 8): Promise<AutocompleteResult[] | string[]> {
  return fetchJSON(`${API_BASE}/autocomplete?q=${encodeURIComponent(q)}&n=${n}`);
}

export function getDocument(id: string): Promise<DocumentDetail> {
  return fetchJSON(`${API_BASE}/document/${encodeURIComponent(id)}`);
}

export function getMediaUrl(docId: string, mediaName: string): string {
  return `${API_BASE}/media/${encodeURIComponent(docId)}/${encodeURIComponent(mediaName)}`;
}

export function getStats(): Promise<StatsResponse> {
  return fetchJSON(`${API_BASE}/stats`);
}

export function getTypes(): Promise<TypeOption[]> {
  return fetchJSON(`${API_BASE}/types`);
}

export function getTopSearches(): Promise<TopSearch[]> {
  return fetchJSON(`${API_BASE}/top-searches`);
}

export function getSearchExamples(): Promise<SearchExample[]> {
  return fetchJSON(`${API_BASE}/search-examples`);
}
