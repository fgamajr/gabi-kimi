import React, { useEffect, useState, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import EditorialHighlights from '@/components/EditorialHighlights';
import { Icons } from '@/components/Icons';
import { ThemeToggle } from '@/components/ThemeToggle';
import { getAutocomplete, getEditorialHighlights, getRecentHighlights, getStats, getSuggestedTopics, getTrending } from '@/lib/api';
import type { AutocompleteResult, EditorialHighlightsResponse, RecentHighlight, StatsResponse, SuggestedTopic, TrendingTopic, SourceFilter } from '@/lib/api';

const HomePage: React.FC = () => {
  const navigate = useNavigate();
  const [stats, setStats] = useState<StatsResponse | null>(null);
  const [trendingTopics, setTrendingTopics] = useState<TrendingTopic[]>([]);
  const [recentHighlights, setRecentHighlights] = useState<RecentHighlight[]>([]);
  const [suggestedTopics, setSuggestedTopics] = useState<SuggestedTopic[]>([]);
  const [editorial, setEditorial] = useState<EditorialHighlightsResponse | null>(null);

  // Search state
  const [query, setQuery] = useState('');
  const [source, setSource] = useState<SourceFilter | ''>('');
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const [showSuggestions, setShowSuggestions] = useState(false);
  const [selectedIdx, setSelectedIdx] = useState(-1);
  const inputRef = useRef<HTMLInputElement>(null);
  const searchRef = useRef<HTMLDivElement>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout>>();

  useEffect(() => {
    Promise.allSettled([getStats(), getTrending(), getRecentHighlights(), getSuggestedTopics(), getEditorialHighlights()]).then(
      ([statsRes, trendingRes, recentRes, suggestedRes, editorialRes]) => {
        if (statsRes.status === 'fulfilled') setStats(statsRes.value);
        if (trendingRes.status === 'fulfilled') setTrendingTopics((trendingRes.value || []).slice(0, 6));
        if (recentRes.status === 'fulfilled') setRecentHighlights((recentRes.value || []).slice(0, 8));
        if (suggestedRes.status === 'fulfilled') setSuggestedTopics(suggestedRes.value || []);
        if (editorialRes.status === 'fulfilled') setEditorial(editorialRes.value);
      },
    );
  }, []);

  // Autocomplete
  const fetchSuggestions = async (q: string) => {
    if (q.length < 2) { setSuggestions([]); return; }
    try {
      const data = await getAutocomplete(q);
      const items = Array.isArray(data)
        ? data.map((d) => (typeof d === 'string' ? d : (d as AutocompleteResult).suggestion || ''))
        : [];
      setSuggestions(items.filter(Boolean));
    } catch { setSuggestions([]); }
  };

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const val = e.target.value;
    setQuery(val);
    setSelectedIdx(-1);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => fetchSuggestions(val), 200);
  };

  const submit = (q: string) => {
    const trimmed = q.trim();
    if (!trimmed) return;
    setShowSuggestions(false);
    setSuggestions([]);
    const params = new URLSearchParams({ q: trimmed });
    if (source) params.set('source', source);
    navigate(`/search?${params.toString()}`);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowDown') { e.preventDefault(); setSelectedIdx((i) => Math.min(i + 1, suggestions.length - 1)); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setSelectedIdx((i) => Math.max(i - 1, -1)); }
    else if (e.key === 'Enter') { e.preventDefault(); submit(selectedIdx >= 0 ? suggestions[selectedIdx] : query); }
    else if (e.key === 'Escape') { setShowSuggestions(false); }
  };

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (searchRef.current && !searchRef.current.contains(e.target as Node)) setShowSuggestions(false);
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const sourceLabel = source === 'tcu' ? 'Acórdãos do TCU' : source === 'all' ? 'Toda a Base' : 'Diário Oficial (DOU)';

  const formatNumber = (value: number | undefined) => {
    if (value == null) return '—';
    if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M+`;
    if (value >= 1_000) return `${(value / 1_000).toFixed(0)}K+`;
    return value.toLocaleString('pt-BR');
  };

  return (
    <div className="min-h-full flex flex-col">
      {/* Header */}
      <header className="sticky top-0 z-50 glass border-b border-border">
        <div className="flex justify-between items-center px-6 py-4 max-w-screen-2xl mx-auto w-full">
          <div className="flex items-center gap-8">
            <span className="text-xl font-black tracking-tighter text-foreground">Arquivo da República</span>
            <nav className="hidden md:flex gap-6 items-center">
              <button
                onClick={() => { setSource(''); inputRef.current?.focus(); }}
                className={`text-sm font-semibold tracking-tight transition-colors pb-1 ${
                  source !== 'tcu' ? 'text-primary border-b-2 border-primary' : 'text-muted-foreground hover:text-foreground'
                }`}
              >
                DOU
              </button>
              <button
                onClick={() => { setSource('tcu'); inputRef.current?.focus(); }}
                className={`text-sm font-semibold tracking-tight transition-colors pb-1 ${
                  source === 'tcu' ? 'text-primary border-b-2 border-primary' : 'text-muted-foreground hover:text-foreground'
                }`}
              >
                TCU
              </button>
            </nav>
          </div>
          <div className="flex items-center gap-2">
            <ThemeToggle />
          </div>
        </div>
      </header>

      <main className="flex-grow">
        {/* Hero */}
        <section className="relative pt-24 pb-32 px-6 overflow-hidden">
          <div className="absolute inset-0 z-0 opacity-10 pointer-events-none">
            <div className="absolute top-[-10%] left-[-10%] w-[40%] h-[60%] rounded-full bg-primary blur-[120px]" />
            <div className="absolute bottom-[-10%] right-[-10%] w-[40%] h-[60%] rounded-full bg-blue-500 blur-[120px]" />
          </div>
          <div className="max-w-5xl mx-auto text-center relative z-10">
            <h1 className="text-[2.5rem] sm:text-[3.5rem] font-black tracking-tighter leading-none text-foreground mb-8">
              O Arquivo da República
            </h1>

            {/* Integrated Search Bar */}
            <div ref={searchRef} className="relative max-w-3xl mx-auto">
              <div className="glass rounded-full p-2 pl-6 flex items-center shadow-lg border border-border/40">
                <div className="flex items-center gap-2 pr-4 border-r border-border/40">
                  <Icons.search className="w-5 h-5 text-primary" />
                  <select
                    value={source}
                    onChange={(e) => setSource(e.target.value as SourceFilter | '')}
                    className="bg-transparent border-none text-sm font-semibold text-foreground focus:ring-0 cursor-pointer pr-6"
                  >
                    <option value="">Diário Oficial</option>
                    <option value="tcu">Acórdãos TCU</option>
                    <option value="all">Toda a Base</option>
                  </select>
                </div>
                <input
                  ref={inputRef}
                  type="text"
                  value={query}
                  onChange={handleChange}
                  onFocus={() => suggestions.length > 0 && setShowSuggestions(true)}
                  onKeyDown={handleKeyDown}
                  placeholder="Pesquisar atos, decretos, leis ou acórdãos..."
                  className="flex-grow bg-transparent border-none focus:ring-0 text-foreground placeholder:text-muted-foreground/60 px-4"
                />
                <button
                  onClick={() => submit(query)}
                  className="bg-gradient-to-r from-primary to-blue-500 text-white px-8 py-3 rounded-full font-bold transition-transform active:scale-95 shadow-md text-sm"
                >
                  Pesquisar
                </button>
              </div>

              {/* Autocomplete dropdown */}
              {showSuggestions && suggestions.length > 0 && (
                <ul className="absolute z-50 top-full mt-2 w-full rounded-xl bg-popover border border-border shadow-lg overflow-hidden">
                  {suggestions.map((s, i) => (
                    <li
                      key={s}
                      className={`px-6 py-3 text-sm cursor-pointer transition-colors flex items-center gap-3 ${
                        i === selectedIdx ? 'bg-muted text-foreground' : 'text-secondary-foreground hover:bg-muted/50'
                      }`}
                      onMouseDown={() => { setQuery(s); submit(s); }}
                      onMouseEnter={() => setSelectedIdx(i)}
                    >
                      <Icons.search className="w-3.5 h-3.5 text-muted-foreground shrink-0" />
                      {s}
                    </li>
                  ))}
                </ul>
              )}
            </div>

            {/* Trending tags */}
            {suggestedTopics.length > 0 && (
              <div className="mt-8 flex flex-wrap justify-center gap-3 text-xs font-mono uppercase tracking-widest text-muted-foreground">
                <span>Tendências:</span>
                {suggestedTopics.slice(0, 4).map((topic) => (
                  <button
                    key={topic.query}
                    onClick={() => navigate(`/search?q=${encodeURIComponent(topic.query)}${topic.intent ? `&intent=${encodeURIComponent(topic.intent)}` : ''}`)}
                    className="hover:text-primary transition-colors"
                  >
                    #{topic.label.replace(/\s+/g, '')}
                  </button>
                ))}
              </div>
            )}
          </div>
        </section>

        {/* Stats Bar */}
        <section className="bg-surface-sunken border-y border-border py-12">
          <div className="max-w-7xl mx-auto px-8">
            <div className="grid grid-cols-1 md:grid-cols-3 gap-12 text-center">
              <div className="space-y-1">
                <p className="text-3xl font-black text-primary tracking-tighter">{formatNumber(stats?.total_documents)}</p>
                <p className="text-xs font-mono uppercase tracking-widest text-muted-foreground">Documentos DOU</p>
              </div>
              <div className="space-y-1">
                <p className="text-3xl font-black text-blue-600 dark:text-blue-400 tracking-tighter">519K+</p>
                <p className="text-xs font-mono uppercase tracking-widest text-muted-foreground">Acórdãos TCU</p>
              </div>
              <div className="space-y-1">
                <p className="text-3xl font-black text-foreground tracking-tighter">
                  {stats?.date_range?.min ? `${new Date().getFullYear() - new Date(stats.date_range.min).getFullYear()} Anos` : '—'}
                </p>
                <p className="text-xs font-mono uppercase tracking-widest text-muted-foreground">de História</p>
              </div>
            </div>
          </div>
        </section>

        {/* Editorial Highlights */}
        {editorial && Object.keys(editorial.categories).length > 0 && (
          <EditorialHighlights data={editorial} />
        )}

        {/* Trending + Recent */}
        <section className="py-16 px-8 max-w-7xl mx-auto">
          {trendingTopics.length > 0 && (
            <div className="mb-16">
              <div className="flex justify-between items-end mb-8">
                <div>
                  <h2 className="text-xs font-mono uppercase tracking-[0.2em] text-primary mb-2">Últimos 7 dias</h2>
                  <p className="text-2xl font-bold tracking-tight">Em Alta</p>
                </div>
              </div>
              <div className="grid md:grid-cols-3 gap-4">
                {trendingTopics.map((topic, idx) => (
                  <button
                    key={topic.query}
                    onClick={() => navigate(`/search?q=${encodeURIComponent(topic.query)}&intent=trending&is_trending=true`)}
                    className={`group relative overflow-hidden rounded-xl border border-border bg-card p-6 text-left hover:border-primary/40 transition-all ${
                      idx === 0 ? 'md:col-span-2 md:row-span-2' : ''
                    }`}
                  >
                    {idx === 0 && <Icons.trending className="absolute -right-2 -top-2 w-24 h-24 text-primary/10 pointer-events-none" />}
                    <p className="text-[10px] font-mono uppercase tracking-widest text-muted-foreground mb-2">
                      {idx === 0 ? 'Destaque da semana' : 'Tendência'}
                    </p>
                    <p className={`${idx === 0 ? 'text-2xl' : 'text-lg'} font-bold leading-snug group-hover:text-primary transition-colors`}>
                      {topic.label}
                    </p>
                    <p className={`${idx === 0 ? 'text-4xl' : 'text-2xl'} font-black text-primary mt-3`}>
                      {topic.doc_count_7d.toLocaleString('pt-BR')}
                    </p>
                    <p className="text-xs text-muted-foreground">publicações nos últimos 7 dias</p>
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* Recent highlights sidebar */}
          {recentHighlights.length > 0 && (
            <div>
              <h3 className="text-xs font-mono uppercase tracking-[0.2em] text-muted-foreground mb-4">Publicações recentes</h3>
              <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-3">
                {recentHighlights.slice(0, 8).map((item) => (
                  <button
                    key={item.id}
                    onClick={() => navigate(`/document/${encodeURIComponent(item.id)}`)}
                    className="text-left rounded-xl border border-border bg-card px-4 py-3 hover:border-primary/40 transition-colors"
                  >
                    <p className="text-sm font-semibold line-clamp-2">{item.title}</p>
                    <p className="text-[10px] text-muted-foreground mt-2 font-mono uppercase">
                      {item.pub_date ? new Date(item.pub_date).toLocaleDateString('pt-BR', { day: '2-digit', month: 'short' }) : ''}
                      {item.issuing_organ ? ` · ${item.issuing_organ}` : ''}
                    </p>
                  </button>
                ))}
              </div>
            </div>
          )}
        </section>
      </main>

      {/* Footer */}
      <footer className="mt-auto border-t border-border bg-surface-sunken">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-8 px-8 py-12 max-w-7xl mx-auto">
          <div className="space-y-3">
            <span className="text-lg font-black text-foreground">Arquivo da República</span>
            <p className="text-xs font-mono uppercase tracking-widest text-muted-foreground max-w-xs leading-relaxed">
              Integrando a transparência do Poder Executivo e do Controle Externo.
            </p>
          </div>
          <div className="grid grid-cols-2 gap-8">
            <div className="flex flex-col gap-3">
              <a className="text-xs uppercase tracking-widest text-muted-foreground hover:text-primary transition-colors" href="#">Privacidade</a>
              <a className="text-xs uppercase tracking-widest text-muted-foreground hover:text-primary transition-colors" href="#">Termos de Uso</a>
            </div>
            <div className="flex flex-col gap-3">
              <a className="text-xs uppercase tracking-widest text-muted-foreground hover:text-primary transition-colors" href="#">Acessibilidade</a>
              <a className="text-xs uppercase tracking-widest text-muted-foreground hover:text-primary transition-colors" href="#">Contato</a>
            </div>
          </div>
        </div>
        <div className="px-8 py-6 border-t border-border/50 text-center">
          <p className="text-xs uppercase tracking-widest text-muted-foreground">© 2025 Arquivo da República. Dados abertos do governo federal.</p>
        </div>
      </footer>
    </div>
  );
};

export default HomePage;
