// API configuration and types for DOU search system

const API_BASE = '/api';

// --- Types ---

export type SourceFilter = 'dou' | 'tcu' | 'all';

export interface SearchParams {
  q: string;
  page?: number;
  max?: number;
  date_from?: string;
  date_to?: string;
  section?: string;
  art_type?: string;
  issuing_organ?: string;
  intent?: string;
  is_trending?: boolean;
  source?: SourceFilter;
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
  top_organ?: string;
  dou_url?: string;
  source_type?: 'dou' | 'tcu_acordao';
  // TCU-specific fields
  relator?: string;
  tipo_processo?: string;
  colegiado?: string;
  dispositivo_resumo?: string;
}

export interface SearchResponse {
  results: SearchResult[];
  total: number;
  page: number;
  max: number;
  query: string;
  took_ms?: number;
  intent?: IntentMetadata;
  suggestion?: string;
}

export interface IntentMetadata {
  detected: string;
  confidence: number;
  suggestion?: string;
  matched_alias?: string;
  topic?: string;
}

export interface LatestPublication {
  id: string;
  title: string;
  subtitle?: string;
  pub_date: string;
  section: string;
  page?: string;
  art_type?: string;
  issuing_organ?: string;
}

export interface RecentHighlight extends LatestPublication {
  relevance_score?: number;
  reasons?: string[];
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
  source_type?: 'dou' | 'tcu_acordao';
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
  primary_signer?: string;
  signers_all?: string[];
  // TCU-specific fields
  relator?: string;
  colegiado?: string;
  tipo_processo?: string;
  numero_processo?: string;
  numero_acordao?: number;
  ano_acordao?: number;
  acordao_id?: string;
  relatorio?: string;
  voto?: string;
  dispositivo_tipo?: string[];
  dispositivo_resumo?: string;
  entidade?: string;
  interessados?: string;
  assunto?: string;
  source_url?: string;
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

export interface TrendingTopic {
  label: string;
  query: string;
  doc_count_7d: number;
  trend_score: number;
  icon?: string;
}

export interface SearchExample {
  query: string;
  description?: string;
}

export interface SuggestedTopic {
  label: string;
  query: string;
  intent?: string;
  icon?: string;
}

export interface AutocompleteResult {
  suggestion: string;
  type?: string;
}

export interface EditorialHighlight {
  doc_id: string;
  title: string;
  summary: string;
  why: string;
  pub_date: string;
  section: string;
  edition_number?: string;
  issuing_organ: string;
  art_type: string;
  badge: string;
}

export interface EditorialHighlightsResponse {
  date: string | null;
  llm_used?: boolean;
  categories: {
    destaque?: EditorialHighlight;
    concursos?: EditorialHighlight;
    economia?: EditorialHighlight;
    politica?: EditorialHighlight;
  };
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
  if (params.intent) sp.set('intent', params.intent);
  if (params.is_trending) sp.set('is_trending', 'true');
  if (params.source) sp.set('source', params.source);
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

export function getTrending(): Promise<TrendingTopic[]> {
  return fetchJSON(`${API_BASE}/trending`);
}

export function getLatestPublications(limit = 8): Promise<LatestPublication[]> {
  return fetchJSON(`${API_BASE}/latest-publications?limit=${limit}`);
}

export function getRecentHighlights(limit = 8): Promise<RecentHighlight[]> {
  return fetchJSON(`${API_BASE}/recent-highlights?limit=${limit}`);
}

export function getSearchExamples(): Promise<SearchExample[]> {
  return fetchJSON(`${API_BASE}/search-examples`);
}

export function getSuggestedTopics(): Promise<SuggestedTopic[]> {
  return fetchJSON(`${API_BASE}/suggested-topics`);
}

export function getEditorialHighlights(): Promise<EditorialHighlightsResponse> {
  return fetchJSON(`${API_BASE}/editorial-highlights`);
}
