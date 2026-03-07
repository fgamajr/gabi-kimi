// API configuration and types for DOU search system

const API_BASE = "/api";

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
  backend?: string;
  interpreted_query?: string;
  inferred_filters?: Record<string, string | null | undefined>;
  applied_filters?: Record<string, string | null | undefined>;
}

export interface DocumentMedia {
  name: string;
  status: "available" | "missing" | "error" | "unknown";
  context_hint?: "table" | "signature" | "emblem" | "chart" | "photo" | "unknown";
  fallback_text?: string;
  original_url?: string;
  blob_url?: string;
  position_in_doc?: number;
  alt_text?: string;
  width_px?: number | null;
  height_px?: number | null;
}

export interface NormativeReference {
  reference_type?: string;
  reference_number?: string;
  reference_date?: string;
  reference_text?: string;
}

export interface ProcedureReference {
  procedure_type?: string;
  procedure_identifier?: string;
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
  images?: DocumentMedia[];
  identifica?: string;
  ementa?: string;
  assinatura?: string;
  normative_refs?: NormativeReference[];
  procedure_refs?: ProcedureReference[];
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

export interface DocumentGraphNode {
  id: string;
  title: string;
  subtitle?: string | null;
  query?: string | null;
  node_type?: "reference" | "procedure" | string;
  relation_type?: string | null;
}

export interface DocumentGraphBranch {
  seed: DocumentGraphNode;
  related_documents: SearchResult[];
}

export interface DocumentGraphResponse {
  document: {
    id: string;
    title: string;
    pub_date?: string;
    section?: string;
    page?: string | null;
    art_type?: string | null;
    issuing_organ?: string | null;
  };
  depth: number;
  per_seed: number;
  branches: DocumentGraphBranch[];
}

// --- API Functions ---

async function fetchJSON<T>(url: string): Promise<T> {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`API error: ${res.status}`);
  return res.json();
}

function titleCase(value?: string | null): string {
  if (!value) return "";
  return value
    .split(/[\s_-]+/u)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1).toLowerCase())
    .join(" ");
}

function normalizeSection(section?: string | null) {
  const raw = String(section || "").trim().toLowerCase();
  if (!raw) return "";
  if (raw === "1" || raw === "do1" || raw === "secao1") return "do1";
  if (raw === "2" || raw === "do2" || raw === "secao2") return "do2";
  if (raw === "3" || raw === "do3" || raw === "secao3") return "do3";
  if (raw === "e" || raw === "extra" || raw === "do1e") return "do1e";
  return raw;
}

function buildDouUrl(idMateria?: string | number | null) {
  if (!idMateria) return undefined;
  return `https://www.in.gov.br/web/dou/-/${idMateria}`;
}

function normalizeSearchResult(result: Record<string, unknown>): SearchResult {
  const section = normalizeSection(String(result.edition_section || result.section || ""));
  return {
    id: String(result.doc_id || result.id || ""),
    title: String(result.identifica || result.titulo || result.ementa || result.title || "Sem título"),
    subtitle: String(result.ementa || result.subtitle || "").trim() || undefined,
    snippet: String(result.snippet || "").trim() || undefined,
    highlight: String(result.highlight || "").trim() || undefined,
    pub_date: String(result.pub_date || result.publication_date || ""),
    section,
    page: result.page_number != null ? String(result.page_number) : undefined,
    art_type: String(result.art_type || "").trim() || undefined,
    issuing_organ: String(result.issuing_organ || "").trim() || undefined,
    dou_url: buildDouUrl(result.id_materia as string | number | null | undefined),
  };
}

function normalizeDocumentMedia(media: Record<string, unknown>): DocumentMedia {
  const status = String(media.status || media.availability_status || "unknown");
  return {
    name: String(media.media_name || media.name || ""),
    status: (status === "available" || status === "missing" || status === "error" || status === "unknown")
      ? status
      : "unknown",
    context_hint: (String(media.context_hint || "unknown") as DocumentMedia["context_hint"]),
    fallback_text: String(media.fallback_text || "").trim() || undefined,
    original_url: String(media.original_url || "").trim() || undefined,
    blob_url: String(media.blob_url || "").trim() || undefined,
    position_in_doc: media.position_in_doc != null ? Number(media.position_in_doc) : undefined,
    alt_text: String(media.alt_text || "").trim() || undefined,
    width_px: media.width_px != null ? Number(media.width_px) : null,
    height_px: media.height_px != null ? Number(media.height_px) : null,
  };
}

function normalizeSignature(signatures: Array<Record<string, unknown>> | undefined): string | undefined {
  if (!Array.isArray(signatures) || signatures.length === 0) {
    return undefined;
  }
  return signatures
    .map((item) => [item.person_name, item.role_title].filter(Boolean).join(" — "))
    .filter(Boolean)
    .join("\n");
}

export function searchDocuments(params: SearchParams): Promise<SearchResponse> {
  const sp = new URLSearchParams();
  sp.set('q', params.q);
  if (params.page) sp.set('page', String(params.page));
  if (params.max) sp.set('max', String(params.max));
  if (params.date_from) sp.set('date_from', params.date_from);
  if (params.date_to) sp.set('date_to', params.date_to);
  if (params.section) sp.set('section', normalizeSection(params.section));
  if (params.art_type) sp.set('art_type', params.art_type);
  if (params.issuing_organ) sp.set('issuing_organ', params.issuing_organ);
  return fetchJSON<Record<string, unknown>>(`${API_BASE}/search?${sp.toString()}`).then((payload) => ({
    results: Array.isArray(payload.results) ? payload.results.map((item) => normalizeSearchResult(item as Record<string, unknown>)) : [],
    total: Number(payload.total || 0),
    page: Number(payload.page || params.page || 1),
    max: Number(payload.page_size || params.max || 20),
    query: String(payload.query || params.q || ""),
    took_ms: payload.took_ms != null ? Number(payload.took_ms) : undefined,
    backend: String(payload.backend || "").trim() || undefined,
    interpreted_query: String(payload.interpreted_query || "").trim() || undefined,
    inferred_filters: (payload.inferred_filters as SearchResponse["inferred_filters"]) || undefined,
    applied_filters: (payload.applied_filters as SearchResponse["applied_filters"]) || undefined,
  }));
}

export function getAutocomplete(q: string, n = 8): Promise<AutocompleteResult[] | string[]> {
  return fetchJSON<Record<string, unknown>>(`${API_BASE}/autocomplete?q=${encodeURIComponent(q)}&n=${n}`).then((payload) => {
    const items = Array.isArray(payload.items) ? payload.items : [];
    return items.map((item) => (typeof item === "string" ? item : String((item as Record<string, unknown>).suggestion || ""))).filter(Boolean);
  });
}

export function getDocument(id: string): Promise<DocumentDetail> {
  return fetchJSON<Record<string, unknown>>(`${API_BASE}/document/${encodeURIComponent(id)}`).then((payload) => {
    const media = Array.isArray(payload.media)
      ? payload.media.map((item) => normalizeDocumentMedia(item as Record<string, unknown>))
      : [];
    const section = normalizeSection(String(payload.section || ""));
    return {
      id: String(payload.id || id),
      title: String(payload.identifica || payload.titulo || payload.ementa || "Sem título"),
      subtitle: String(payload.sub_titulo || payload.art_category || "").trim() || undefined,
      body_html: String(payload.body_html || "").trim() || undefined,
      body_plain: String(payload.body_plain || "").trim() || undefined,
      pub_date: String(payload.publication_date || ""),
      section,
      section_name: section ? `Seção ${section.replace(/^do/ui, "")}` : undefined,
      page: payload.page_number != null ? String(payload.page_number) : undefined,
      edition: payload.edition_number != null ? String(payload.edition_number) : undefined,
      art_type: String(payload.art_type || "").trim() || undefined,
      art_type_name: String(payload.art_type_raw || payload.art_type || "").trim()
        ? titleCase(String(payload.art_type_raw || payload.art_type))
        : undefined,
      issuing_organ: String(payload.issuing_organ || "").trim() || undefined,
      dou_url: buildDouUrl(payload.id_materia as string | number | null | undefined),
      media,
      images: media,
      identifica: String(payload.identifica || "").trim() || undefined,
      ementa: String(payload.ementa || "").trim() || undefined,
      assinatura: normalizeSignature(payload.signatures as Array<Record<string, unknown>> | undefined),
      normative_refs: Array.isArray(payload.normative_refs)
        ? payload.normative_refs.map((item) => {
            const row = item as Record<string, unknown>;
            return {
              reference_type: String(row.reference_type || "").trim() || undefined,
              reference_number: String(row.reference_number || "").trim() || undefined,
              reference_date: String(row.reference_date || "").trim() || undefined,
              reference_text: String(row.reference_text || "").trim() || undefined,
            };
          })
        : [],
      procedure_refs: Array.isArray(payload.procedure_refs)
        ? payload.procedure_refs.map((item) => {
            const row = item as Record<string, unknown>;
            return {
              procedure_type: String(row.procedure_type || "").trim() || undefined,
              procedure_identifier: String(row.procedure_identifier || "").trim() || undefined,
            };
          })
        : [],
    };
  });
}

export function getDocumentGraph(id: string, depth = 2, perSeed = 3): Promise<DocumentGraphResponse> {
  return fetchJSON<Record<string, unknown>>(
    `${API_BASE}/document/${encodeURIComponent(id)}/graph?depth=${depth}&per_seed=${perSeed}`
  ).then((payload) => ({
    document: {
      id: String((payload.document as Record<string, unknown> | undefined)?.id || id),
      title: String((payload.document as Record<string, unknown> | undefined)?.title || "Sem título"),
      pub_date: String((payload.document as Record<string, unknown> | undefined)?.pub_date || "").trim() || undefined,
      section: String((payload.document as Record<string, unknown> | undefined)?.section || "").trim() || undefined,
      page: (payload.document as Record<string, unknown> | undefined)?.page != null
        ? String((payload.document as Record<string, unknown>).page)
        : undefined,
      art_type: String((payload.document as Record<string, unknown> | undefined)?.art_type || "").trim() || undefined,
      issuing_organ: String((payload.document as Record<string, unknown> | undefined)?.issuing_organ || "").trim() || undefined,
    },
    depth: Number(payload.depth || depth),
    per_seed: Number(payload.per_seed || perSeed),
    branches: Array.isArray(payload.branches)
      ? payload.branches.map((branch) => {
          const row = branch as Record<string, unknown>;
          const seed = (row.seed as Record<string, unknown> | undefined) || {};
          return {
            seed: {
              id: String(seed.id || ""),
              title: String(seed.title || "Referência"),
              subtitle: String(seed.subtitle || "").trim() || undefined,
              query: String(seed.query || "").trim() || undefined,
              node_type: String(seed.node_type || "").trim() || undefined,
              relation_type: String(seed.relation_type || "").trim() || undefined,
            },
            related_documents: Array.isArray(row.related_documents)
              ? row.related_documents.map((item) => normalizeSearchResult(item as Record<string, unknown>))
              : [],
          };
        })
      : [],
  }));
}

export function getMediaUrl(docId: string, mediaName: string): string {
  return `${API_BASE}/media/${encodeURIComponent(docId)}/${encodeURIComponent(mediaName)}`;
}

export function getStats(): Promise<StatsResponse> {
  return fetchJSON<Record<string, unknown>>(`${API_BASE}/stats`).then((payload) => ({
    total_documents: Number(payload.total_docs || 0),
    total_sections: 4,
    date_range: {
      min: String(payload.date_min || ""),
      max: String(payload.date_max || ""),
    },
    last_updated: String(payload.refreshed_at || "").trim() || undefined,
    ...payload,
  }));
}

export function getTypes(): Promise<TypeOption[]> {
  return fetchJSON<Array<Record<string, unknown>>>(`${API_BASE}/types`).then((items) =>
    items.map((item) => ({
      value: String(item.type || item.value || ""),
      label: titleCase(String(item.type || item.label || "")),
      count: item.count != null ? Number(item.count) : undefined,
    })).filter((item) => item.value),
  );
}

export function getTopSearches(): Promise<TopSearch[]> {
  return fetchJSON<Record<string, unknown>>(`${API_BASE}/top-searches`).then((payload) => {
    const items = Array.isArray(payload.items) ? payload.items : [];
    return items.map((item) => ({
      query: String((item as Record<string, unknown>).term || (item as Record<string, unknown>).query || ""),
      count: Number((item as Record<string, unknown>).count || 0),
    })).filter((item) => item.query);
  });
}

export function getSearchExamples(): Promise<SearchExample[]> {
  return fetchJSON<Record<string, unknown>>(`${API_BASE}/search-examples`).then((payload) => {
    const items = Array.isArray(payload.items) ? payload.items : [];
    return items.map((item) => ({
      query: String((item as Record<string, unknown>).term || (item as Record<string, unknown>).query || ""),
      description: String((item as Record<string, unknown>).description || (item as Record<string, unknown>).source || "").trim() || undefined,
    })).filter((item) => item.query);
  });
}
