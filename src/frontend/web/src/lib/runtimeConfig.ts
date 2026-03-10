function normalizeBase(value: string | undefined, fallback: string) {
  const raw = (value || fallback).trim();
  if (!raw) return fallback;
  return raw.replace(/\/+$/, "");
}

export const API_BASE = normalizeBase(import.meta.env.VITE_API_BASE_URL, "/api");

/** Collapse multiple slashes into one (preserve protocol, e.g. https://). */
function collapseSlashes(url: string): string {
  return url.replace(/([^:])\/\/+/g, "$1/");
}

export function resolveApiUrl(path: string) {
  if (/^https?:\/\//i.test(path)) return path;
  if (!path.startsWith("/")) return collapseSlashes(`${API_BASE}/${path}`);
  const suffix = path.startsWith("/api/") ? path.slice(4) : path.replace(/^\//, "");
  const out = suffix ? `${API_BASE}/${suffix}` : API_BASE;
  return collapseSlashes(out);
}
