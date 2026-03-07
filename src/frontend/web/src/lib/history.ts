export interface RecentDocumentItem {
  id: string;
  title: string;
  section?: string;
  pubDate?: string;
  issuingOrgan?: string;
  snippet?: string;
  viewedAt: string;
}

const RECENT_DOCS_KEY = "gabi-recent-documents";
const RECENT_SEARCHES_KEY = "gabi-recent-searches";
const MAX_RECENT_DOCS = 8;
const MAX_RECENT_SEARCHES = 8;

function readJson<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key);
    if (!raw) return fallback;
    return JSON.parse(raw) as T;
  } catch {
    return fallback;
  }
}

function writeJson<T>(key: string, value: T) {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    // Ignore quota/storage failures in client-only convenience state.
  }
}

export function getRecentDocuments(): RecentDocumentItem[] {
  return readJson<RecentDocumentItem[]>(RECENT_DOCS_KEY, []);
}

export function addRecentDocument(item: Omit<RecentDocumentItem, "viewedAt">) {
  const existing = getRecentDocuments().filter((entry) => entry.id !== item.id);
  const next: RecentDocumentItem[] = [
    {
      ...item,
      viewedAt: new Date().toISOString(),
    },
    ...existing,
  ].slice(0, MAX_RECENT_DOCS);
  writeJson(RECENT_DOCS_KEY, next);
  return next;
}

export function removeRecentDocument(id: string) {
  const next = getRecentDocuments().filter((entry) => entry.id !== id);
  writeJson(RECENT_DOCS_KEY, next);
  return next;
}

export function getRecentSearches(): string[] {
  return readJson<string[]>(RECENT_SEARCHES_KEY, []);
}

export function addRecentSearch(query: string) {
  const normalized = query.trim();
  if (!normalized) return getRecentSearches();
  const existing = getRecentSearches().filter((entry) => entry.toLowerCase() !== normalized.toLowerCase());
  const next = [normalized, ...existing].slice(0, MAX_RECENT_SEARCHES);
  writeJson(RECENT_SEARCHES_KEY, next);
  return next;
}
