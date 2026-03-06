// =============================================================================
// DOU REIMAGINADO — Type Definitions
// =============================================================================

/**
 * DOU Document model
 */
export interface Document {
  id: string;
  id_materia?: string;
  art_type: string;
  art_type_raw?: string;
  art_category?: string;
  identifica?: string;
  ementa?: string;
  titulo?: string;
  sub_titulo?: string;
  body_plain?: string;
  body_html?: string;
  document_number?: string;
  document_year?: number;
  issuing_organ: string;
  page_number?: string;
  body_word_count?: number;
  publication_date: string;
  edition_number?: string;
  section: 1 | 2 | 3 | "e";
  is_extra?: boolean;
  status?: "vigente" | "revogado" | "retificado";
  normative_refs?: NormativeReference[];
  procedure_refs?: ProcedureReference[];
  signatures?: Signature[];
  media?: Media[];
  // UI state
  isRead?: boolean;
  isFavorited?: boolean;
  isNew?: boolean;
  snippet?: string;
}

export interface NormativeReference {
  reference_type: string;
  reference_number?: string;
  reference_date?: string;
  reference_text?: string;
}

export interface ProcedureReference {
  procedure_type: string;
  procedure_identifier: string;
}

export interface Signature {
  person_name: string;
  role_title?: string;
}

export interface Media {
  media_name: string;
  media_type?: string;
  file_extension?: string;
  size_bytes?: number;
  source_filename?: string;
  external_url?: string;
  sequence_in_document?: number;
  blob_url?: string;
}

/**
 * Search result from API
 */
export interface SearchResult {
  id: string;
  numero: string;
  tipo: string;
  orgao: {
    nome: string;
    sigla: string;
  };
  secao: 1 | 2 | 3 | "e";
  data: string;
  status: "vigente" | "revogado" | "retificado";
  ementa?: string;
  snippet?: string;
  score?: number;
}

/**
 * Search API response
 */
export interface SearchResponse {
  results: Document[];
  total: number;
  page: number;
  per_page: number;
  query_time_ms?: number;
  facets?: SearchFacets;
}

export interface SearchFacets {
  secao?: { value: string; count: number }[];
  orgao?: { value: string; count: number }[];
  tipo?: { value: string; count: number }[];
  status?: { value: string; count: number }[];
}

/**
 * Search filters
 */
export interface SearchFilters {
  q?: string;
  date_from?: string;
  date_to?: string;
  section?: string;
  art_type?: string;
  issuing_organ?: string;
  status?: string;
  page?: number;
  per_page?: number;
  sort?: "relevancia" | "data_desc" | "data_asc";
}

/**
 * Alert/Monitoring system
 */
export type AlertType = 
  | { type: "orgao"; orgaoSlug: string }
  | { type: "orgao_tipo"; orgaoSlug: string; tipoAto: string }
  | { type: "keyword"; terms: string[] }
  | { type: "entity"; cpfCnpj: string }
  | { type: "compound"; orgaoSlug?: string; terms?: string[]; tipoAto?: string };

export type AlertChannel = "push" | "email" | "webhook" | "rss";

export interface Alert {
  id: string;
  name: string;
  type: AlertType;
  channels: AlertChannel[];
  isActive: boolean;
  createdAt: string;
  lastTriggeredAt?: string;
  matchCount?: number;
}

/**
 * User preferences
 */
export interface UserPreferences {
  theme: "dark" | "light" | "system";
  fontSize: "small" | "medium" | "large";
  notifications: boolean;
  recentSearches: string[];
  favorites: string[];
  readingHistory: ReadingHistoryItem[];
}

export interface ReadingHistoryItem {
  documentId: string;
  openedAt: string;
  scrollPosition?: number;
  readPercentage?: number;
}

/**
 * Share state
 */
export interface ShareState {
  docId: string;
  scrollTo?: string;
  highlights?: string[];
  note?: string;
  fromQuery?: string;
}

/**
 * Download options
 */
export type DownloadFormat = "pdf" | "html" | "txt" | "json";

export interface DownloadOption {
  format: DownloadFormat;
  label: string;
  description: string;
  icon: string;
  size?: number;
}

/**
 * Bottom sheet / Modal state
 */
export interface SheetState {
  isOpen: boolean;
  content: "share" | "download" | "alert" | "filters" | null;
  data?: unknown;
}

/**
 * Navigation state
 */
export interface NavigationState {
  currentDocIndex: number;
  totalDocs: number;
  query?: string;
  results: Document[];
}

/**
 * App section for bottom nav
 */
export type AppSection = "search" | "today" | "alerts" | "profile";

/**
 * Suggestion item for search
 */
export interface Suggestion {
  type: "recent" | "popular" | "orgao" | "tema" | "exact";
  text: string;
  count?: number;
  icon?: string;
}

/**
 * API Error
 */
export interface ApiError {
  code: string;
  message: string;
  details?: unknown;
}

/**
 * Stats from API
 */
export interface Stats {
  search_backend: string;
  db_size: string;
  total_docs?: number;
  vocabulary_size?: number;
  avg_doc_length?: number;
  refreshed_at?: string;
  date_min?: string;
  date_max?: string;
  zip_count?: number;
  type_distribution?: { type: string; count: number }[];
}
