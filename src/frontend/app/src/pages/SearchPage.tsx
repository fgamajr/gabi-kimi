import React, { useEffect, useState, useCallback } from 'react';
import { useSearchParams, useNavigate } from 'react-router-dom';
import { searchDocuments, getTypes } from '@/lib/api';
import type { SearchResponse, TypeOption, SearchParams, SourceFilter } from '@/lib/api';
import { Header } from '@/components/Header';
import { SearchBar } from '@/components/SearchBar';
import { ResultCard } from '@/components/ResultCard';
import { FilterChip } from '@/components/Badges';
import { BottomSheet } from '@/components/BottomSheet';
import { SkeletonCard } from '@/components/Skeletons';
import { Icons } from '@/components/Icons';
import { ThemeToggle } from '@/components/ThemeToggle';

const SECTIONS = [
  { value: '', label: 'Todas' },
  { value: '1', label: 'S1' },
  { value: '2', label: 'S2' },
  { value: '3', label: 'S3' },
  { value: 'e', label: 'Extra' },
];

const SOURCES: { value: SourceFilter | ''; label: string }[] = [
  { value: '', label: 'DOU' },
  { value: 'tcu', label: 'TCU' },
  { value: 'all', label: 'Todos' },
];

const DATE_PRESETS = [
  { label: 'Últimos 30 dias', days: 30 },
  { label: 'Últimos 6 meses', days: 180 },
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
  const intent = searchParams.get('intent') || '';
  const isTrending = searchParams.get('is_trending') === 'true';
  const source = (searchParams.get('source') || '') as SourceFilter | '';

  const [response, setResponse] = useState<SearchResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [types, setTypes] = useState<TypeOption[]>([]);
  const [showFilters, setShowFilters] = useState(false);

  // Local filter state
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
      if (intent) params.intent = intent;
      if (isTrending) params.is_trending = true;
      if (source) params.source = source as SourceFilter;
      const data = await searchDocuments(params);
      setResponse(data);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  }, [query, page, section, artType, dateFrom, dateTo, intent, isTrending, source]);

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

  const handleSearch = (q: string) => updateParams({ q, page: '1' });

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

  const applyDatePreset = (days: number) => {
    const to = new Date();
    const from = new Date();
    from.setDate(from.getDate() - days);
    setLocalDateFrom(from.toISOString().slice(0, 10));
    setLocalDateTo(to.toISOString().slice(0, 10));
  };

  const totalPages = response ? Math.ceil(response.total / (response.max || 20)) : 0;
  const currentMode = isTrending || intent === 'trending' ? 'trending' : 'relevance';

  return (
    <div className="min-h-full bg-background flex flex-col">
      <Header
        showBack
        onBack={() => navigate('/')}
        searchProps={{ defaultValue: query, onSearch: handleSearch, compact: true }}
        actionsRight={<ThemeToggle />}
      />

      <main className="max-w-7xl mx-auto w-full px-4 sm:px-8 pt-8 pb-24">
        {/* Search title + sort */}
        <div className="flex flex-col md:flex-row md:items-end justify-between gap-4 mb-8">
          <div>
            <h1 className="text-3xl sm:text-4xl md:text-5xl font-black tracking-tight leading-none text-foreground mb-2">
              "{query}"
            </h1>
            {response && !loading && (
              <p className="text-muted-foreground font-mono text-sm tracking-wider uppercase">
                {response.total.toLocaleString('pt-BR')} resultados encontrados
              </p>
            )}
          </div>
          <div className="flex items-center gap-4 flex-wrap">
            {/* Source toggle */}
            <div className="flex items-center gap-2">
              <span className="text-sm font-medium text-muted-foreground">Fonte</span>
              <div className="inline-flex items-center rounded-lg border border-border bg-card overflow-hidden">
                {SOURCES.map((s) => (
                  <button
                    key={s.value}
                    onClick={() => updateParams({ source: s.value, page: '1' })}
                    className={`px-3 py-2 text-sm font-semibold transition-colors ${
                      source === s.value
                        ? 'bg-primary text-primary-foreground'
                        : 'text-muted-foreground hover:text-foreground'
                    }`}
                  >
                    {s.label}
                  </button>
                ))}
              </div>
            </div>
            {/* Sort toggle */}
            <div className="flex items-center gap-2">
              <span className="text-sm font-medium text-muted-foreground">Ordenar por</span>
              <div className="inline-flex items-center rounded-lg border border-border bg-card overflow-hidden">
                <button
                  onClick={() => updateParams({ intent: '', is_trending: '', page: '1' })}
                  className={`px-4 py-2 text-sm font-semibold transition-colors ${
                    currentMode === 'relevance'
                      ? 'bg-primary text-primary-foreground'
                      : 'text-muted-foreground hover:text-foreground'
                  }`}
                >
                  Relevância
                </button>
                <button
                  onClick={() => updateParams({ intent: 'trending', is_trending: 'true', page: '1' })}
                  className={`px-4 py-2 text-sm font-semibold transition-colors ${
                    currentMode === 'trending'
                      ? 'bg-primary text-primary-foreground'
                      : 'text-muted-foreground hover:text-foreground'
                  }`}
                >
                  Mais recentes
                </button>
              </div>
            </div>
          </div>
        </div>

        <div className="flex gap-10">
          {/* Sidebar filters — desktop */}
          <aside className="hidden lg:flex flex-col gap-6 w-72 shrink-0 sticky top-24 h-fit bg-surface-sunken rounded-2xl p-6">
            <div>
              <h2 className="text-lg font-bold text-foreground">Filtros de Pesquisa</h2>
              <p className="text-muted-foreground text-sm">Refine sua busca no acervo</p>
            </div>

            {/* Date filter */}
            <div className="space-y-3">
              <div className="flex items-center gap-2 text-primary font-semibold text-sm">
                <Icons.calendar className="w-4 h-4" />
                <span>Intervalo de Data</span>
              </div>
              <div className="flex flex-col gap-1">
                {DATE_PRESETS.map((preset) => (
                  <label key={preset.days} className="flex items-center gap-3 p-2 rounded-lg hover:bg-card cursor-pointer text-sm transition-all">
                    <input
                      type="radio"
                      name="date_preset"
                      className="text-primary focus:ring-primary rounded-full"
                      checked={localDateFrom !== '' && Math.round((new Date(localDateTo || Date.now()).getTime() - new Date(localDateFrom).getTime()) / 86400000) === preset.days}
                      onChange={() => applyDatePreset(preset.days)}
                    />
                    <span className="text-foreground">{preset.label}</span>
                  </label>
                ))}
                <label className="flex items-center gap-3 p-2 rounded-lg hover:bg-card cursor-pointer text-sm transition-all">
                  <input
                    type="radio"
                    name="date_preset"
                    className="text-primary focus:ring-primary rounded-full"
                    checked={localDateFrom === '' && localDateTo === ''}
                    onChange={() => { setLocalDateFrom(''); setLocalDateTo(''); }}
                  />
                  <span className="text-foreground">Qualquer data</span>
                </label>
              </div>
            </div>

            {/* Section filter */}
            <div className="space-y-3">
              <div className="flex items-center gap-2 text-muted-foreground font-semibold text-sm">
                <Icons.document className="w-4 h-4" />
                <span>Seção do Diário</span>
              </div>
              <div className="grid grid-cols-4 gap-2">
                {SECTIONS.filter(s => s.value).map((s) => (
                  <button
                    key={s.value}
                    onClick={() => setLocalSection(localSection === s.value ? '' : s.value)}
                    className={`py-2 rounded-lg text-xs font-bold transition-all ${
                      localSection === s.value
                        ? 'bg-card text-primary shadow-sm border border-primary/20'
                        : 'bg-card/40 text-foreground border border-transparent hover:border-border'
                    }`}
                  >
                    {s.label}
                  </button>
                ))}
              </div>
            </div>

            {/* Art type filter */}
            {types.length > 0 && (
              <div className="space-y-3">
                <div className="flex items-center gap-2 text-muted-foreground font-semibold text-sm">
                  <Icons.filter className="w-4 h-4" />
                  <span>Tipo de Ato</span>
                </div>
                <select
                  value={localArtType}
                  onChange={(e) => setLocalArtType(e.target.value)}
                  className="w-full rounded-lg bg-card border border-border px-3 py-2 text-sm text-foreground focus-ring"
                >
                  <option value="">Todos os tipos</option>
                  {types.map(t => (
                    <option key={t.value} value={t.value}>{t.label}{t.count ? ` (${t.count})` : ''}</option>
                  ))}
                </select>
              </div>
            )}

            <button
              onClick={applyFilters}
              className="w-full bg-primary hover:bg-primary/90 text-primary-foreground font-bold py-3 rounded-xl shadow-lg shadow-primary/20 transition-all active:scale-95"
            >
              Aplicar Filtros
            </button>
            {(localSection || localArtType || localDateFrom) && (
              <button
                onClick={clearFilters}
                className="w-full text-muted-foreground hover:text-foreground text-sm font-medium transition-colors"
              >
                Limpar filtros
              </button>
            )}
          </aside>

          {/* Results */}
          <section className="flex-1 min-w-0">
            {/* Mobile filter button */}
            <div className="lg:hidden mb-4 flex items-center gap-2">
              <button
                onClick={() => {
                  setLocalSection(section);
                  setLocalArtType(artType);
                  setLocalDateFrom(dateFrom);
                  setLocalDateTo(dateTo);
                  setShowFilters(true);
                }}
                className="inline-flex items-center gap-1.5 px-4 py-2 rounded-xl bg-surface-sunken text-sm font-medium press-effect focus-ring"
              >
                <Icons.filter className="w-4 h-4" />
                Filtros
                {[section, artType, dateFrom].filter(Boolean).length > 0 && (
                  <span className="bg-primary text-primary-foreground text-xs px-1.5 py-0.5 rounded-full font-bold">
                    {[section, artType, dateFrom].filter(Boolean).length}
                  </span>
                )}
              </button>
              {section && <FilterChip label={`Seção ${section}`} active onRemove={() => updateParams({ section: '' })} />}
              {artType && <FilterChip label={artType} active onRemove={() => updateParams({ art_type: '' })} />}
            </div>

            {/* Loading */}
            {loading && (
              <div className="space-y-4 stagger-children">
                {Array.from({ length: 5 }).map((_, i) => <SkeletonCard key={i} />)}
              </div>
            )}

            {/* Results list */}
            {!loading && response && response.results.length > 0 && (
              <div className="space-y-4">
                {response.results.map((r, i) => (
                  <ResultCard key={r.id} result={r} index={i} query={query} />
                ))}
              </div>
            )}

            {/* Empty state */}
            {!loading && response && response.results.length === 0 && (
              <div className="text-center py-16 animate-fade-in">
                <Icons.search className="w-12 h-12 text-muted-foreground mx-auto mb-4" />
                <p className="text-foreground font-medium">Nenhum resultado encontrado</p>
                <p className="text-sm text-muted-foreground mt-1">Tente ajustar os termos ou filtros da busca</p>
              </div>
            )}

            {/* Pagination */}
            {!loading && response && totalPages > 1 && (
              <Pagination page={page} totalPages={totalPages} onPageChange={(p) => updateParams({ page: String(p) })} />
            )}
          </section>
        </div>
      </main>

      {/* Mobile filter bottom sheet */}
      <BottomSheet open={showFilters} onClose={() => setShowFilters(false)} title="Filtros de Pesquisa">
        <div className="space-y-6 mt-4">
          <div>
            <label className="text-xs font-semibold uppercase tracking-widest text-muted-foreground mb-2 block">Seção</label>
            <div className="flex flex-wrap gap-2">
              {SECTIONS.map(s => (
                <FilterChip key={s.value} label={s.label} active={localSection === s.value} onClick={() => setLocalSection(s.value)} />
              ))}
            </div>
          </div>
          {types.length > 0 && (
            <div>
              <label className="text-xs font-semibold uppercase tracking-widest text-muted-foreground mb-2 block">Tipo de ato</label>
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
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs font-semibold uppercase tracking-widest text-muted-foreground mb-2 block">Data início</label>
              <input type="date" value={localDateFrom} onChange={(e) => setLocalDateFrom(e.target.value)} className="w-full rounded-lg bg-secondary border border-border px-3 py-2.5 text-sm text-foreground focus-ring min-h-[44px]" />
            </div>
            <div>
              <label className="text-xs font-semibold uppercase tracking-widest text-muted-foreground mb-2 block">Data fim</label>
              <input type="date" value={localDateTo} onChange={(e) => setLocalDateTo(e.target.value)} className="w-full rounded-lg bg-secondary border border-border px-3 py-2.5 text-sm text-foreground focus-ring min-h-[44px]" />
            </div>
          </div>
          <div className="flex gap-3 pt-2">
            <button onClick={clearFilters} className="flex-1 px-4 py-3 rounded-xl border border-border text-sm font-medium text-foreground hover:bg-muted transition-colors min-h-[44px]">Limpar</button>
            <button onClick={applyFilters} className="flex-1 px-4 py-3 rounded-xl bg-primary text-primary-foreground text-sm font-medium hover:opacity-90 min-h-[44px]">Aplicar</button>
          </div>
        </div>
      </BottomSheet>
    </div>
  );
};

/* Numbered pagination matching the mockup */
const Pagination: React.FC<{ page: number; totalPages: number; onPageChange: (p: number) => void }> = ({ page, totalPages, onPageChange }) => {
  const pages: (number | '...')[] = [];

  if (totalPages <= 7) {
    for (let i = 1; i <= totalPages; i++) pages.push(i);
  } else {
    pages.push(1);
    if (page > 3) pages.push('...');
    for (let i = Math.max(2, page - 1); i <= Math.min(totalPages - 1, page + 1); i++) pages.push(i);
    if (page < totalPages - 2) pages.push('...');
    pages.push(totalPages);
  }

  return (
    <nav className="flex justify-center items-center gap-2 pt-10">
      <button
        disabled={page <= 1}
        onClick={() => onPageChange(page - 1)}
        className="w-10 h-10 flex items-center justify-center rounded-lg border border-border hover:bg-muted transition-colors text-muted-foreground disabled:opacity-30"
      >
        <Icons.chevronLeft className="w-5 h-5" />
      </button>
      {pages.map((p, i) =>
        p === '...' ? (
          <span key={`dots-${i}`} className="px-2 text-muted-foreground">...</span>
        ) : (
          <button
            key={p}
            onClick={() => onPageChange(p)}
            className={`w-10 h-10 flex items-center justify-center rounded-lg font-bold text-sm transition-all ${
              p === page
                ? 'bg-primary text-primary-foreground shadow-md shadow-primary/20'
                : 'border border-border hover:bg-muted text-muted-foreground'
            }`}
          >
            {p}
          </button>
        )
      )}
      <button
        disabled={page >= totalPages}
        onClick={() => onPageChange(page + 1)}
        className="w-10 h-10 flex items-center justify-center rounded-lg border border-border hover:bg-muted transition-colors text-muted-foreground disabled:opacity-30"
      >
        <Icons.chevronRight className="w-5 h-5" />
      </button>
    </nav>
  );
};

export default SearchPage;
