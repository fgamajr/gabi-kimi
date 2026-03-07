import React, { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { BottomSheet } from "@/components/BottomSheet";
import { FilterChip } from "@/components/Badges";
import { Icons } from "@/components/Icons";
import { ResultCard } from "@/components/ResultCard";
import { SearchBar } from "@/components/SearchBar";
import { SkeletonCard } from "@/components/Skeletons";
import { getTypes, searchDocuments } from "@/lib/api";
import type { SearchParams, SearchResponse, TypeOption } from "@/lib/api";

const SECTIONS = [
  { value: "", label: "Todas" },
  { value: "do1", label: "Seção 1" },
  { value: "do2", label: "Seção 2" },
  { value: "do3", label: "Seção 3" },
  { value: "do1e", label: "Extra" },
];

const formatSectionLabel = (value: string) => {
  const normalized = value.toLowerCase();
  if (normalized === "do1") return "Seção 1";
  if (normalized === "do2") return "Seção 2";
  if (normalized === "do3") return "Seção 3";
  if (normalized === "do1e" || normalized === "e") return "Extra";
  return value;
};

const formatBackendFilterLabel = (key: string, value: string) => {
  if (key === "section") return formatSectionLabel(value);
  if (key === "art_type") return `Tipo: ${value}`;
  if (key === "issuing_organ") return `Órgão: ${value}`;
  return `${key}: ${value}`;
};

const SearchPage: React.FC = () => {
  const [searchParams, setSearchParams] = useSearchParams();
  const query = searchParams.get("q") || "";
  const page = parseInt(searchParams.get("page") || "1", 10);
  const section = searchParams.get("section") || "";
  const artType = searchParams.get("art_type") || "";
  const dateFrom = searchParams.get("date_from") || "";
  const dateTo = searchParams.get("date_to") || "";
  const issuingOrgan = searchParams.get("issuing_organ") || "";

  const [response, setResponse] = useState<SearchResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [types, setTypes] = useState<TypeOption[]>([]);
  const [showFilters, setShowFilters] = useState(false);

  const [localSection, setLocalSection] = useState(section);
  const [localArtType, setLocalArtType] = useState(artType);
  const [localDateFrom, setLocalDateFrom] = useState(dateFrom);
  const [localDateTo, setLocalDateTo] = useState(dateTo);
  const [localIssuingOrgan, setLocalIssuingOrgan] = useState(issuingOrgan);

  useEffect(() => {
    getTypes().then(setTypes).catch(() => {});
  }, []);

  useEffect(() => {
    setLocalSection(section);
    setLocalArtType(artType);
    setLocalDateFrom(dateFrom);
    setLocalDateTo(dateTo);
    setLocalIssuingOrgan(issuingOrgan);
  }, [section, artType, dateFrom, dateTo, issuingOrgan]);

  const doSearch = useCallback(async () => {
    if (!query) {
      setResponse(null);
      return;
    }
    setLoading(true);
    try {
      const params: SearchParams = { q: query, page, max: 20 };
      if (section) params.section = section;
      if (artType) params.art_type = artType;
      if (dateFrom) params.date_from = dateFrom;
      if (dateTo) params.date_to = dateTo;
      if (issuingOrgan) params.issuing_organ = issuingOrgan;
      const data = await searchDocuments(params);
      setResponse(data);
    } catch (error) {
      console.error(error);
      setResponse(null);
    } finally {
      setLoading(false);
    }
  }, [query, page, section, artType, dateFrom, dateTo, issuingOrgan]);

  useEffect(() => {
    doSearch();
  }, [doSearch]);

  const updateParams = (updates: Record<string, string>) => {
    const next = new URLSearchParams(searchParams);
    Object.entries(updates).forEach(([key, value]) => {
      if (value) next.set(key, value);
      else next.delete(key);
    });
    if (!updates.page) next.set("page", "1");
    setSearchParams(next);
  };

  const handleSearch = (nextQuery: string) => {
    updateParams({ q: nextQuery, page: "1" });
  };

  const applyFilters = () => {
    updateParams({
      section: localSection,
      art_type: localArtType,
      date_from: localDateFrom,
      date_to: localDateTo,
      issuing_organ: localIssuingOrgan.trim(),
      page: "1",
    });
    setShowFilters(false);
  };

  const clearFilters = () => {
    setLocalSection("");
    setLocalArtType("");
    setLocalDateFrom("");
    setLocalDateTo("");
    setLocalIssuingOrgan("");
    updateParams({
      section: "",
      art_type: "",
      date_from: "",
      date_to: "",
      issuing_organ: "",
      page: "1",
    });
    setShowFilters(false);
  };

  const activeFilterCount = [section, artType, dateFrom, dateTo, issuingOrgan].filter(Boolean).length;
  const totalPages = response ? Math.ceil(response.total / (response.max || 20)) : 0;

  const inferredFilterItems = useMemo(
    () =>
      Object.entries(response?.inferred_filters || {})
        .filter(([, value]) => value)
        .map(([key, value]) => ({ key, value: String(value) })),
    [response?.inferred_filters]
  );

  const appliedFilterItems = useMemo(
    () =>
      Object.entries(response?.applied_filters || {})
        .filter(([, value]) => value)
        .map(([key, value]) => ({ key, value: String(value) })),
    [response?.applied_filters]
  );

  return (
    <div className="min-h-screen bg-background flex flex-col pb-24 md:pb-8">
      <header className="sticky top-0 z-30 bg-background/85 backdrop-blur-xl border-b border-border">
        <div className="max-w-6xl mx-auto px-4 py-4 flex flex-col gap-4">
          <div>
            <p className="text-xs uppercase tracking-[0.16em] text-text-tertiary mb-2">Pesquisa estruturada</p>
            <SearchBar defaultValue={query} onSearch={handleSearch} compact />
          </div>

          <div className="hidden md:grid md:grid-cols-[repeat(4,minmax(0,1fr))] gap-3">
            <div className="rounded-2xl border border-border bg-card p-3">
              <label className="text-[11px] uppercase tracking-[0.16em] text-text-tertiary mb-2 block">Seção</label>
              <select
                value={localSection}
                onChange={(event) => setLocalSection(event.target.value)}
                className="w-full rounded-xl bg-secondary border border-border px-3 py-2.5 text-sm text-foreground focus-ring min-h-[44px]"
              >
                {SECTIONS.map((item) => (
                  <option key={item.value} value={item.value}>
                    {item.label}
                  </option>
                ))}
              </select>
            </div>

            <div className="rounded-2xl border border-border bg-card p-3">
              <label className="text-[11px] uppercase tracking-[0.16em] text-text-tertiary mb-2 block">Tipo de ato</label>
              <select
                value={localArtType}
                onChange={(event) => setLocalArtType(event.target.value)}
                className="w-full rounded-xl bg-secondary border border-border px-3 py-2.5 text-sm text-foreground focus-ring min-h-[44px]"
              >
                <option value="">Todos</option>
                {types.map((type) => (
                  <option key={type.value} value={type.value}>
                    {type.label}
                    {type.count ? ` (${type.count})` : ""}
                  </option>
                ))}
              </select>
            </div>

            <div className="rounded-2xl border border-border bg-card p-3">
              <label className="text-[11px] uppercase tracking-[0.16em] text-text-tertiary mb-2 block">Órgão emissor</label>
              <input
                type="text"
                value={localIssuingOrgan}
                onChange={(event) => setLocalIssuingOrgan(event.target.value)}
                placeholder="Ex.: Ministério da Saúde"
                className="w-full rounded-xl bg-secondary border border-border px-3 py-2.5 text-sm text-foreground placeholder:text-text-tertiary focus-ring min-h-[44px]"
              />
            </div>

            <div className="rounded-2xl border border-border bg-card p-3">
              <label className="text-[11px] uppercase tracking-[0.16em] text-text-tertiary mb-2 block">Janela temporal</label>
              <div className="grid grid-cols-2 gap-2">
                <input
                  type="date"
                  value={localDateFrom}
                  onChange={(event) => setLocalDateFrom(event.target.value)}
                  className="w-full rounded-xl bg-secondary border border-border px-2.5 py-2.5 text-sm text-foreground focus-ring min-h-[44px]"
                />
                <input
                  type="date"
                  value={localDateTo}
                  onChange={(event) => setLocalDateTo(event.target.value)}
                  className="w-full rounded-xl bg-secondary border border-border px-2.5 py-2.5 text-sm text-foreground focus-ring min-h-[44px]"
                />
              </div>
            </div>
          </div>

          <div className="hidden md:flex items-center justify-between gap-3">
            <p className="text-xs text-text-secondary">
              Use filtros jurídicos para restringir seção, tipo, órgão e período antes de aprofundar a leitura.
            </p>
            <div className="flex gap-2">
              <button
                onClick={clearFilters}
                className="px-4 py-2 rounded-xl border border-border text-sm font-medium text-foreground hover:bg-muted transition-colors press-effect focus-ring min-h-[44px]"
              >
                Limpar
              </button>
              <button
                onClick={applyFilters}
                className="px-4 py-2 rounded-xl bg-primary text-primary-foreground text-sm font-medium hover:opacity-90 transition-opacity press-effect focus-ring min-h-[44px]"
              >
                Aplicar filtros
              </button>
            </div>
          </div>
        </div>
      </header>

      <div className="max-w-6xl mx-auto px-4 w-full">
        <div className="flex items-center gap-2 py-3 overflow-x-auto scrollbar-none">
          <button
            onClick={() => setShowFilters(true)}
            className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium transition-colors press-effect focus-ring min-h-[44px] ${
              activeFilterCount > 0
                ? "bg-primary text-primary-foreground"
                : "bg-secondary text-secondary-foreground hover:bg-muted"
            }`}
          >
            <Icons.filter className="w-3.5 h-3.5" />
            Filtros
            {activeFilterCount > 0 ? ` (${activeFilterCount})` : ""}
          </button>

          {section ? <FilterChip label={formatSectionLabel(section)} active onRemove={() => updateParams({ section: "" })} /> : null}
          {artType ? <FilterChip label={`Tipo: ${artType}`} active onRemove={() => updateParams({ art_type: "" })} /> : null}
          {issuingOrgan ? (
            <FilterChip label={`Órgão: ${issuingOrgan}`} active onRemove={() => updateParams({ issuing_organ: "" })} />
          ) : null}
          {dateFrom || dateTo ? (
            <FilterChip
              label={[dateFrom, dateTo].filter(Boolean).join(" → ")}
              active
              onRemove={() => updateParams({ date_from: "", date_to: "" })}
            />
          ) : null}
        </div>
      </div>

      <main className="flex-1 max-w-6xl mx-auto px-4 pb-8 w-full">
        {response ? (
          <section className="rounded-2xl border border-border bg-card px-4 py-4 mb-4 animate-fade-in">
            <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
              <div className="min-w-0">
                <p className="text-xs font-semibold uppercase tracking-[0.16em] text-text-tertiary mb-2">Leitura da consulta</p>
                <p className="text-sm text-foreground leading-relaxed">
                  {response.interpreted_query || query}
                </p>
                {response.interpreted_query && response.interpreted_query !== query ? (
                  <p className="text-xs text-text-secondary mt-1">
                    Consulta normalizada a partir de “{query}”.
                  </p>
                ) : null}
              </div>
              <div className="text-sm text-text-secondary shrink-0">
                {response.total.toLocaleString("pt-BR")} resultado{response.total !== 1 ? "s" : ""}
                {response.took_ms != null ? <span className="text-text-tertiary"> · {response.took_ms}ms</span> : null}
              </div>
            </div>

            {(inferredFilterItems.length > 0 || appliedFilterItems.length > 0) ? (
              <div className="mt-4 grid gap-3 md:grid-cols-2">
                <div className="rounded-xl bg-background/70 border border-border px-3 py-3">
                  <p className="text-[11px] uppercase tracking-[0.16em] text-text-tertiary mb-2">Filtros inferidos</p>
                  {inferredFilterItems.length > 0 ? (
                    <div className="flex flex-wrap gap-2">
                      {inferredFilterItems.map((item) => (
                        <FilterChip key={`inferred-${item.key}-${item.value}`} label={formatBackendFilterLabel(item.key, item.value)} />
                      ))}
                    </div>
                  ) : (
                    <p className="text-xs text-text-secondary">Nenhum filtro inferido automaticamente nesta consulta.</p>
                  )}
                </div>
                <div className="rounded-xl bg-background/70 border border-border px-3 py-3">
                  <p className="text-[11px] uppercase tracking-[0.16em] text-text-tertiary mb-2">Filtros aplicados</p>
                  {appliedFilterItems.length > 0 ? (
                    <div className="flex flex-wrap gap-2">
                      {appliedFilterItems.map((item) => (
                        <FilterChip key={`applied-${item.key}-${item.value}`} label={formatBackendFilterLabel(item.key, item.value)} />
                      ))}
                    </div>
                  ) : (
                    <p className="text-xs text-text-secondary">Busca ampla sem restrições adicionais além da própria consulta.</p>
                  )}
                </div>
              </div>
            ) : null}
          </section>
        ) : null}

        {loading ? (
          <div className="space-y-3 stagger-children">
            {Array.from({ length: 6 }).map((_, index) => (
              <SkeletonCard key={index} />
            ))}
          </div>
        ) : null}

        {!loading && response && response.results.length > 0 ? (
          <div className="space-y-3">
            {response.results.map((result, index) => (
              <ResultCard key={result.id} result={result} index={index} />
            ))}
          </div>
        ) : null}

        {!loading && response && response.results.length === 0 ? (
          <div className="text-center py-16 animate-fade-in">
            <Icons.search className="w-12 h-12 text-text-tertiary mx-auto mb-4" />
            <p className="text-foreground font-medium">Nenhum resultado encontrado</p>
            <p className="text-sm text-text-secondary mt-1">Tente ajustar os filtros jurídicos ou reformular a consulta.</p>
          </div>
        ) : null}

        {!loading && response && totalPages > 1 ? (
          <div className="flex items-center justify-center gap-2 mt-8">
            <button
              disabled={page <= 1}
              onClick={() => updateParams({ page: String(page - 1) })}
              className="px-4 py-2 rounded-lg bg-card border border-border text-sm disabled:opacity-30 hover:bg-muted transition-colors press-effect focus-ring min-h-[44px]"
            >
              Anterior
            </button>
            <span className="text-sm text-text-secondary px-3 min-h-[44px] flex items-center">
              {page} / {totalPages}
            </span>
            <button
              disabled={page >= totalPages}
              onClick={() => updateParams({ page: String(page + 1) })}
              className="px-4 py-2 rounded-lg bg-card border border-border text-sm disabled:opacity-30 hover:bg-muted transition-colors press-effect focus-ring min-h-[44px]"
            >
              Próxima
            </button>
          </div>
        ) : null}
      </main>

      <BottomSheet open={showFilters} onClose={() => setShowFilters(false)} title="Filtros jurídicos">
        <div className="space-y-6 mt-4">
          <div>
            <label className="text-xs font-semibold uppercase tracking-widest text-text-tertiary mb-2 block">Seção</label>
            <div className="flex flex-wrap gap-2">
              {SECTIONS.map((item) => (
                <FilterChip
                  key={item.value}
                  label={item.label}
                  active={localSection === item.value}
                  onClick={() => setLocalSection(item.value)}
                />
              ))}
            </div>
          </div>

          {types.length > 0 ? (
            <div>
              <label className="text-xs font-semibold uppercase tracking-widest text-text-tertiary mb-2 block">Tipo de ato</label>
              <select
                value={localArtType}
                onChange={(event) => setLocalArtType(event.target.value)}
                className="w-full rounded-lg bg-secondary border border-border px-3 py-2.5 text-sm text-foreground focus-ring min-h-[44px]"
              >
                <option value="">Todos</option>
                {types.map((type) => (
                  <option key={type.value} value={type.value}>
                    {type.label}
                    {type.count ? ` (${type.count})` : ""}
                  </option>
                ))}
              </select>
            </div>
          ) : null}

          <div>
            <label className="text-xs font-semibold uppercase tracking-widest text-text-tertiary mb-2 block">Órgão emissor</label>
            <input
              type="text"
              value={localIssuingOrgan}
              onChange={(event) => setLocalIssuingOrgan(event.target.value)}
              placeholder="Ex.: Agência Nacional de Vigilância Sanitária"
              className="w-full rounded-lg bg-secondary border border-border px-3 py-2.5 text-sm text-foreground placeholder:text-text-tertiary focus-ring min-h-[44px]"
            />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs font-semibold uppercase tracking-widest text-text-tertiary mb-2 block">Data início</label>
              <input
                type="date"
                value={localDateFrom}
                onChange={(event) => setLocalDateFrom(event.target.value)}
                className="w-full rounded-lg bg-secondary border border-border px-3 py-2.5 text-sm text-foreground focus-ring min-h-[44px]"
              />
            </div>
            <div>
              <label className="text-xs font-semibold uppercase tracking-widest text-text-tertiary mb-2 block">Data fim</label>
              <input
                type="date"
                value={localDateTo}
                onChange={(event) => setLocalDateTo(event.target.value)}
                className="w-full rounded-lg bg-secondary border border-border px-3 py-2.5 text-sm text-foreground focus-ring min-h-[44px]"
              />
            </div>
          </div>

          <div className="rounded-xl border border-border bg-background/60 px-3 py-3">
            <p className="text-[11px] uppercase tracking-[0.16em] text-text-tertiary mb-1">Dicas de pesquisa</p>
            <p className="text-xs text-text-secondary leading-relaxed">
              Combine termos do ato, órgão e tema. Ex.: “portaria ministério da saúde” ou “pregão eletrônico” com seção DO3.
            </p>
          </div>

          <div className="flex gap-3 pt-2">
            <button
              onClick={clearFilters}
              className="flex-1 px-4 py-3 rounded-xl border border-border text-sm font-medium text-foreground hover:bg-muted transition-colors press-effect focus-ring min-h-[44px]"
            >
              Limpar
            </button>
            <button
              onClick={applyFilters}
              className="flex-1 px-4 py-3 rounded-xl bg-primary text-primary-foreground text-sm font-medium hover:opacity-90 transition-opacity press-effect focus-ring min-h-[44px]"
            >
              Aplicar
            </button>
          </div>
        </div>
      </BottomSheet>
    </div>
  );
};

export default SearchPage;
