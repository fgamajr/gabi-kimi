import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { SearchBar } from '@/components/SearchBar';
import { SkeletonBlock } from '@/components/Skeletons';
import { Icons } from '@/components/Icons';
import { getStats, getTopSearches, getSearchExamples } from '@/lib/api';
import type { StatsResponse, TopSearch, SearchExample } from '@/lib/api';

const HomePage: React.FC = () => {
  const navigate = useNavigate();
  const [stats, setStats] = useState<StatsResponse | null>(null);
  const [topSearches, setTopSearches] = useState<TopSearch[]>([]);
  const [examples, setExamples] = useState<SearchExample[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.allSettled([getStats(), getTopSearches(), getSearchExamples()])
      .then(([s, t, e]) => {
        if (s.status === 'fulfilled') setStats(s.value);
        if (t.status === 'fulfilled') setTopSearches(t.value?.slice(0, 8) || []);
        if (e.status === 'fulfilled') setExamples(e.value?.slice(0, 6) || []);
      })
      .finally(() => setLoading(false));
  }, []);

  const formatNumber = (n: number) => n?.toLocaleString('pt-BR') || '—';

  const formatDate = (d: string) => {
    try { return new Date(d).toLocaleDateString('pt-BR', { month: 'short', year: 'numeric' }); }
    catch { return d; }
  };

  return (
    <div className="min-h-screen bg-background flex flex-col">
      {/* Hero */}
      <header className="flex-1 flex flex-col items-center justify-center px-4 pt-16 pb-8 max-w-2xl mx-auto w-full">
        <div className="mb-8 text-center animate-fade-in">
          <div className="inline-flex items-center gap-2 mb-4 px-3 py-1.5 rounded-full bg-secondary text-text-secondary text-xs font-medium">
            <Icons.book className="w-3.5 h-3.5" />
            Diário Oficial da União
          </div>
          <h1 className="text-3xl sm:text-4xl md:text-5xl font-bold text-foreground tracking-tight font-serif leading-tight">
            Pesquise o<br />
            <span className="text-primary">Diário Oficial</span>
          </h1>
          <p className="mt-3 text-text-secondary text-sm sm:text-base max-w-md mx-auto">
            Acesse publicações históricas do DOU com busca inteligente e leitura editorial.
          </p>
        </div>

        <div className="w-full animate-fade-in" style={{ animationDelay: '100ms' }}>
          <SearchBar autoFocus placeholder="Pesquisar atos, portarias, decretos..." />
        </div>

        {/* Stats */}
        {loading ? (
          <div className="mt-8 w-full grid grid-cols-3 gap-3">
            {[1, 2, 3].map(i => (
              <div key={i} className="rounded-lg bg-card p-3">
                <div className="skeleton h-6 w-16 mb-1" />
                <div className="skeleton h-3 w-20" />
              </div>
            ))}
          </div>
        ) : stats && (
          <div className="mt-8 w-full grid grid-cols-3 gap-3 animate-fade-in" style={{ animationDelay: '200ms' }}>
            <StatCard
              value={formatNumber(stats.total_documents)}
              label="Publicações"
              icon={<Icons.document className="w-4 h-4" />}
            />
            <StatCard
              value={stats.date_range?.min ? formatDate(stats.date_range.min) : '—'}
              label="Desde"
              icon={<Icons.calendar className="w-4 h-4" />}
            />
            <StatCard
              value={stats.date_range?.max ? formatDate(stats.date_range.max) : '—'}
              label="Até"
              icon={<Icons.clock className="w-4 h-4" />}
            />
          </div>
        )}
      </header>

      {/* Bottom section */}
      <section className="bg-surface-sunken border-t border-border px-4 py-8">
        <div className="max-w-2xl mx-auto space-y-8">
          {/* Top searches */}
          {topSearches.length > 0 && (
            <div className="animate-fade-in">
              <h2 className="text-xs font-semibold uppercase tracking-widest text-text-tertiary mb-3 flex items-center gap-2">
                <Icons.trending className="w-3.5 h-3.5" />
                Mais pesquisados
              </h2>
              <div className="flex flex-wrap gap-2">
                {topSearches.map((ts) => (
                  <button
                    key={ts.query}
                    onClick={() => navigate(`/search?q=${encodeURIComponent(ts.query)}`)}
                    className="px-3 py-2 rounded-lg bg-card border border-border text-sm text-foreground hover:border-primary/30 hover:text-primary transition-colors press-effect focus-ring min-h-[44px]"
                  >
                    {ts.query}
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* Examples */}
          {examples.length > 0 && (
            <div className="animate-fade-in" style={{ animationDelay: '100ms' }}>
              <h2 className="text-xs font-semibold uppercase tracking-widest text-text-tertiary mb-3 flex items-center gap-2">
                <Icons.search className="w-3.5 h-3.5" />
                Exemplos de busca
              </h2>
              <div className="space-y-2">
                {examples.map((ex) => (
                  <button
                    key={ex.query}
                    onClick={() => navigate(`/search?q=${encodeURIComponent(ex.query)}`)}
                    className="w-full text-left px-4 py-3 rounded-lg bg-card border border-border hover:border-primary/30 transition-colors press-effect focus-ring flex items-center gap-3 min-h-[44px]"
                  >
                    <Icons.chevronRight className="w-4 h-4 text-muted-foreground shrink-0" />
                    <div>
                      <p className="text-sm text-foreground">{ex.query}</p>
                      {ex.description && <p className="text-xs text-text-tertiary mt-0.5">{ex.description}</p>}
                    </div>
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>
      </section>
    </div>
  );
};

const StatCard: React.FC<{ value: string; label: string; icon: React.ReactNode }> = ({ value, label, icon }) => (
  <div className="rounded-lg bg-card border border-border p-3 text-center">
    <div className="flex items-center justify-center gap-1.5 text-text-tertiary mb-1">
      {icon}
    </div>
    <p className="text-lg font-bold text-foreground font-mono">{value}</p>
    <p className="text-xs text-text-secondary">{label}</p>
  </div>
);

export default HomePage;
