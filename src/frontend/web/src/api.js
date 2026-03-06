async function getJson(path, signal) {
  const response = await fetch(path, { signal, credentials: "same-origin" });
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`);
  }
  return response.json();
}

export function fetchStats(signal) {
  return getJson("/api/stats", signal);
}

export function fetchTopSearches(signal) {
  return getJson("/api/top-searches?n=6&period=week", signal);
}

export function fetchSearchExamples(signal) {
  return getJson("/api/search-examples?n=6", signal);
}

export function fetchTypes(signal) {
  return getJson("/api/types", signal);
}

export function fetchAutocomplete(query, signal) {
  return getJson(`/api/autocomplete?q=${encodeURIComponent(query)}&n=8`, signal);
}

export function fetchSearch(params, signal) {
  const qs = new URLSearchParams();
  qs.set("q", params.query);
  qs.set("max", String(params.max ?? 12));
  qs.set("page", String(params.page ?? 1));
  if (params.dateFrom) qs.set("date_from", params.dateFrom);
  if (params.dateTo) qs.set("date_to", params.dateTo);
  if (params.section) qs.set("section", params.section);
  if (params.artType) qs.set("art_type", params.artType);
  if (params.issuingOrgan) qs.set("issuing_organ", params.issuingOrgan);
  return getJson(`/api/search?${qs.toString()}`, signal);
}

export function fetchDocument(id, signal) {
  return getJson(`/api/document/${id}`, signal);
}
