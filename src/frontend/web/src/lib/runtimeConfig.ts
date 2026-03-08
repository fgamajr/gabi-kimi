function normalizeBase(value: string | undefined, fallback: string) {
  const raw = (value || fallback).trim();
  if (!raw) return fallback;
  return raw.replace(/\/+$/, "");
}

export const API_BASE = normalizeBase(import.meta.env.VITE_API_BASE_URL, "/api");

export function resolveApiUrl(path: string) {
  if (/^https?:\/\//i.test(path)) return path;
  if (!path.startsWith("/")) return `${API_BASE}/${path}`;
  return `${API_BASE}${path.startsWith("/api/") ? path.slice(4) : path}`;
}
