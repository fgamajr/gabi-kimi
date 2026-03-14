import React, { useEffect, useState, useCallback } from 'react';
import { useSearchParams, useNavigate } from 'react-router-dom';
import { searchDocuments, getTypes } from '@/lib/api';
import type { SearchResponse, SearchResult, TypeOption, SearchParams } from '@/lib/api';
import { SearchBar } from '@/components/SearchBar';
import { ResultCard } from '@/components/ResultCard';
import { FilterChip } from '@/components/Badges';
import { BottomSheet } from '@/components/BottomSheet';
import { SkeletonCard } from '@/components/Skeletons';
import { Icons } from '@/components/Icons';

const SECTIONS = [
  { value: '', label: 'Todas' },
  { value: '1', label: 'Seção 1' },
  { value: '2', label: 'Seção 2' },
  { value: '3', label: 'Seção 3' },
  { value: 'e', label: 'Extra' },
];

const SearchPage: React.FC = () => {
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();
  const query = searchParams.get('q') || '';
  const page = parseInt(searchParams.get('page') || '1', 10);
  const section = searchParams.get('section') || '';
  const artType = searchParams.get('art_type') || '';
  const dateFrom = searchParams.get('date_from') || '';
  const dateTo = searchParams.get('date_to') || '';

  const [response, setResponse] = useState<SearchResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [types, setTypes] = useState<TypeOption[]>([]);
  const [showFilters, setShowFilters] = useState(false);

  // Local filter state for bottom sheet
  const [localSection, setLocalSection] = useState(section);
  const [localArtType, setLocalArtType] = useState(artType);
  const [localDateFrom, setLocalDateFrom] = useState(dateFrom);
  const [localDateTo, setLocalDateTo] = useState(dateTo);

  useEffect(() => {
    getTypes().then(setTypes).catch(() => {});
  }, []);

  const doSearch = useCallback(async () => {
    if (!query) return;
    setLoading(true);
    try {
      const params: SearchParams = { q: query, page, max: 20 };
      if (section) params.section = section;
      if (artType) params.art_type = artType;
      if (dateFrom) params.date_from = dateFrom;
      if (dateTo) params.date_to = dateTo;
      const data = await searchDocuments(params);
      setResponse(data);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  }, [query, page, section, artType, dateFrom, dateTo]);

  useEffect(() => { doSearch(); }, [doSearch]);

  const updateParams = (updates: Record<string, string>) => {
    const next = new URLSearchParams(searchParams);
    Object.entries(updates).forEach(([k, v]) => {
      if (v) next.set(k, v);
      else next.delete(k);
    });
    if (!updates.page) next.set('page', '1');
    setSearchParams(next);
  };

  const handleSearch = (q: string) => {
    updateParams({ q, page: '1' });
  };

  const applyFilters = () => {
    updateParams({
      section: localSection,
      art_type: localArtType,
      date_from: localDateFrom,
      date_to: localDateTo,
      page: '1',
    });
    setShowFilters(false);
  };

  const clearFilters = () => {
    setLocalSection('');
    setLocalArtType('');
    setLocalDateFrom('');
    setLocalDateTo('');
    updateParams({ section: '', art_type: '', date_from: '', date_to: '', page: '1' });
    setShowFilters(false);
  };

  const activeFilterCount = [section, artType, dateFrom, dateTo].filter(Boolean).length;
  const totalPages = response ? Math.ceil(response.total / (response.max || 20)) : 0;

  return (
    <div className="min-h-screen bg-background flex flex-col">
      {/* Sticky header */}
      <header className="sticky top-0 z-40 bg-background/80 backdrop-blur-xl border-b border-border">
        <div className="max-w-3xl mx-auto px-4 py-3 flex items-center gap-3">
          <button
            onClick={() => navigate('/')}
            className="p-2 rounded-lg hover:bg-muted transition-colors focus-ring min-w-[44px] min-h-[44px] flex items-center justify-center shrink-0"
            aria-label="Voltar"
          >
            <Icons.back className="w-5 h-5" />
          </button>
          <div className="flex-1">
            <SearchBar defaultValue={query} onSearch={handleSearch} compact />
          </div>
        </div>
      </header>

      {/* Active filters bar */}
      <div className="max-w-3xl mx-auto px-4 w-full">
        <div className="flex items-center gap-2 py-3 overflow-x-auto scrollbar-none">
          <button
            onClick={() => {
              setLocalSection(section);
              setLocalArtType(artType);
              setLocalDateFrom(dateFrom);
              setLocalDateTo(dateTo);
              setShowFilters(true);
            }}
            className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium transition-colors press-effect focus-ring min-h-[44px]
              ${activeFilterCount > 0
                ? 'bg-primary text-primary-foreground'
                : 'bg-secondary text-secondary-foreground hover:bg-muted'}`}
          >
            <Icons.filter className="w-3.5 h-3.5" />
            Filtros{activeFilterCount > 0 && ` (${activeFilterCount})`}
          </button>

          {section && (
            <FilterChip
              label={`Seção ${section}`}
              active
              onRemove={() => updateParams({ section: '' })}
            />
          )}
          {artType && (
            <FilterChip
              label={artType}
              active
              onRemove={() => updateParams({ art_type: '' })}
            />
          )}
          {(dateFrom || dateTo) && (
            <FilterChip
              label={[dateFrom, dateTo].filter(Boolean).join(' → ')}
              active
              onRemove={() => updateParams({ date_from: '', date_to: '' })}
            />
          )}
        </div>
      </div>

      {/* Results */}
      <main className="flex-1 max-w-3xl mx-auto px-4 pb-8 w-full">
        {/* Status */}
        {response && !loading && (
          <div className="flex items-center justify-between mb-4 text-sm text-text-secondary">
            <span>
              {response.total.toLocaleString('pt-BR')} resultado{response.total !== 1 ? 's' : ''}
              {response.took_ms != null && <span className="text-text-tertiary"> · {response.took_ms}ms</span>}
            </span>
            {totalPages > 1 && (
              <span className="text-text-tertiary">
                Página {page} de {totalPages}
              </span>
            )}
          </div>
        )}

        {/* Loading */}
        {loading && (
          <div className="space-y-3 stagger-children">
            {Array.from({ length: 6 }).map((_, i) => <SkeletonCard key={i} />)}
          </div>
        )}

        {/* Results list */}
        {!loading && response && response.results.length > 0 && (
          <div className="space-y-3">
            {response.results.map((r, i) => (
              <ResultCard key={r.id} result={r} index={i} />
            ))}
          </div>
        )}

        {/* Empty state */}
        {!loading && response && response.results.length === 0 && (
          <div className="text-center py-16 animate-fade-in">
            <Icons.search className="w-12 h-12 text-text-tertiary mx-auto mb-4" />
            <p className="text-foreground font-medium">Nenhum resultado encontrado</p>
            <p className="text-sm text-text-secondary mt-1">Tente ajustar os termos ou filtros da busca</p>
          </div>
        )}

        {/* Pagination */}
        {!loading && response && totalPages > 1 && (
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
        )}
      </main>

      {/* Filter bottom sheet */}
      <BottomSheet open={showFilters} onClose={() => setShowFilters(false)} title="Filtros">
        <div className="space-y-6 mt-4">
          {/* Section */}
          <div>
            <label className="text-xs font-semibold uppercase tracking-widest text-text-tertiary mb-2 block">Seção</label>
            <div className="flex flex-wrap gap-2">
              {SECTIONS.map(s => (
                <FilterChip
                  key={s.value}
                  label={s.label}
                  active={localSection === s.value}
                  onClick={() => setLocalSection(s.value)}
                />
              ))}
            </div>
          </div>

          {/* Type */}
          {types.length > 0 && (
            <div>
              <label className="text-xs font-semibold uppercase tracking-widest text-text-tertiary mb-2 block">Tipo de ato</label>
              <select
                value={localArtType}
                onChange={(e) => setLocalArtType(e.target.value)}
                className="w-full rounded-lg bg-secondary border border-border px-3 py-2.5 text-sm text-foreground focus-ring min-h-[44px]"
              >
                <option value="">Todos</option>
                {types.map(t => (
                  <option key={t.value} value={t.value}>{t.label}{t.count ? ` (${t.count})` : ''}</option>
                ))}
              </select>
            </div>
          )}

          {/* Date range */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs font-semibold uppercase tracking-widest text-text-tertiary mb-2 block">Data início</label>
              <input
                type="date"
                value={localDateFrom}
                onChange={(e) => setLocalDateFrom(e.target.value)}
                className="w-full rounded-lg bg-secondary border border-border px-3 py-2.5 text-sm text-foreground focus-ring min-h-[44px]"
              />
            </div>
            <div>
              <label className="text-xs font-semibold uppercase tracking-widest text-text-tertiary mb-2 block">Data fim</label>
              <input
                type="date"
                value={localDateTo}
                onChange={(e) => setLocalDateTo(e.target.value)}
                className="w-full rounded-lg bg-secondary border border-border px-3 py-2.5 text-sm text-foreground focus-ring min-h-[44px]"
              />
            </div>
          </div>

          {/* Actions */}
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
