import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { SearchBar } from '@/components/SearchBar';
import { Icons } from '@/components/Icons';
import { ThemeToggle } from '@/components/ThemeToggle';
import { getStats, getTrending, getSearchExamples, getRecentHighlights, getSuggestedTopics } from '@/lib/api';
import type { StatsResponse, TrendingTopic, SearchExample, RecentHighlight, SuggestedTopic } from '@/lib/api';

const HomePage: React.FC = () => {
  const navigate = useNavigate();
  const [stats, setStats] = useState<StatsResponse | null>(null);
  const [trendingTopics, setTrendingTopics] = useState<TrendingTopic[]>([]);
  const [recentHighlights, setRecentHighlights] = useState<RecentHighlight[]>([]);
  const [examples, setExamples] = useState<SearchExample[]>([]);
  const [suggestedTopics, setSuggestedTopics] = useState<SuggestedTopic[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.allSettled([getStats(), getTrending(), getSearchExamples(), getRecentHighlights(), getSuggestedTopics()])
      .then(([s, t, e, l, st]) => {
        if (s.status === 'fulfilled') setStats(s.value);
        if (t.status === 'fulfilled') setTrendingTopics(t.value?.slice(0, 6) || []);
        if (e.status === 'fulfilled') setExamples(e.value?.slice(0, 6) || []);
        if (l.status === 'fulfilled') setRecentHighlights(l.value || []);
        if (st.status === 'fulfilled') setSuggestedTopics(st.value || []);
      })
      .finally(() => setLoading(false));
  }, []);

  const formatNumber = (n: number) => n?.toLocaleString('pt-BR') || '—';

  const formatDate = (d: string) => {
    try {
      return new Date(d).toLocaleDateString('pt-BR', { month: 'short', year: 'numeric' });
    } catch {
      return d;
    }
  };

  const formatRecentDate = (d: string) => {
    try {
      return new Date(d).toLocaleDateString('pt-BR', { day: '2-digit', month: 'short' });
    } catch {
      return d;
    }
  };

  return (
    <div className="min-h-screen bg-background flex flex-col relative">
      <div className="absolute top-4 right-4 z-10">
        <ThemeToggle />
      </div>

      <header className="flex-1 flex flex-col items-center justify-center px-4 pt-16 pb-8 max-w-2xl mx-auto w-full">
        <div className="mb-8 text-center animate-fade-in">
          <div className="inline-flex items-center gap-2 mb-4 px-3 py-1.5 rounded-full bg-secondary text-text-secondary text-xs font-medium">
            <Icons.book className="w-3.5 h-3.5" />
            Diário Oficial da União
          </div>
          <h1 className="text-3xl sm:text-4xl md:text-5xl font-bold text-foreground tracking-tight font-serif leading-tight">
            Pesquise o
            <br />
            <span className="text-primary">Diário Oficial</span>
          </h1>
          <p className="mt-3 text-text-secondary text-sm sm:text-base max-w-md mx-auto">
            Acesse publicações históricas do DOU com busca inteligente e leitura editorial.
          </p>
        </div>

        <div className="w-full animate-fade-in" style={{ animationDelay: '100ms' }}>
          <SearchBar autoFocus placeholder="Pesquisar atos, portarias, decretos..." />
          {stats?.date_range?.max && (
            <p className="text-center text-xs text-text-tertiary mt-2">
              Atualizado até{' '}
              {new Date(stats.date_range.max).toLocaleDateString('pt-BR', {
                day: '2-digit',
                month: 'long',
                year: 'numeric',
              })}
            </p>
          )}
        </div>

        {loading ? (
          <div className="mt-8 w-full grid grid-cols-3 gap-3">
            {[1, 2, 3].map((i) => (
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

      <section className="bg-surface-sunken border-t border-border px-4 py-8">
        <div className="max-w-6xl mx-auto grid gap-8 lg:grid-cols-[minmax(0,1fr)_320px] lg:items-start">
          <div className="space-y-8">
            {suggestedTopics.length > 0 && (
            <div className="animate-fade-in">
              <h2 className="text-xs font-semibold uppercase tracking-widest text-text-tertiary mb-3 flex items-center gap-2">
                <Icons.hash className="w-3.5 h-3.5" />
                Tópicos sugeridos
              </h2>
              <div className="flex flex-wrap gap-2">
                {suggestedTopics.map((topic) => (
                  <button
                    key={topic.query}
                    onClick={() => {
                      const params = new URLSearchParams({ q: topic.query });
                      if (topic.intent) params.set('intent', topic.intent);
                      if (topic.intent === 'trending') params.set('is_trending', 'true');
                      navigate(`/search?${params.toString()}`);
                    }}
                    className="px-3 py-2 rounded-lg bg-card border border-border text-sm text-foreground hover:border-primary/30 hover:text-primary transition-colors press-effect focus-ring min-h-[44px]"
                  >
                    {topic.label}
                  </button>
                ))}
              </div>
            </div>
            )}

            {trendingTopics.length > 0 && (
              <div className="animate-fade-in">
                <div className="flex items-center justify-between gap-3 mb-3">
                  <h2 className="text-xs font-semibold uppercase tracking-widest text-text-tertiary flex items-center gap-2">
                    <Icons.trending className="w-3.5 h-3.5" />
                    Em alta no DOU
                  </h2>
                  <span className="text-xs text-text-tertiary">Últimos 7 dias</span>
                </div>
                <div className="grid gap-3 sm:grid-cols-2">
                  {trendingTopics.map((topic) => (
                    <button
                      key={topic.query}
                      onClick={() => navigate(`/search?q=${encodeURIComponent(topic.query)}&intent=trending&is_trending=true`)}
                      className="rounded-xl bg-card border border-border p-4 text-left hover:border-primary/30 transition-colors press-effect focus-ring"
                    >
                      <div className="flex items-start justify-between gap-3">
                        <div>
                          <p className="text-sm font-medium text-foreground">{topic.label}</p>
                          <p className="text-xs text-text-tertiary mt-1">
                            {topic.doc_count_7d.toLocaleString('pt-BR')} publicações recentes
                          </p>
                        </div>
                        <span className="text-lg shrink-0">
                          {topic.trend_score >= 6 ? '🔥' : topic.trend_score >= 3 ? '↗' : '•'}
                        </span>
                      </div>
                    </button>
                  ))}
                </div>
              </div>
            )}

            {recentHighlights.length > 0 && (
              <div className="animate-fade-in lg:hidden">
                <h2 className="text-xs font-semibold uppercase tracking-widest text-text-tertiary mb-3 flex items-center gap-2">
                  <Icons.clock className="w-3.5 h-3.5" />
                  Recentes relevantes
                </h2>
                <div className="space-y-2">
                  {recentHighlights.slice(0, 5).map((publication) => (
                    <button
                      key={publication.id}
                      onClick={() => navigate(`/document/${encodeURIComponent(publication.id)}`)}
                      className="w-full rounded-lg bg-card border border-border px-4 py-3 text-left hover:border-primary/30 transition-colors press-effect focus-ring"
                    >
                      <div className="flex items-center gap-2 text-xs text-text-tertiary mb-1">
                        {publication.art_type && <span>{publication.art_type}</span>}
                        <span>·</span>
                        <span>{formatRecentDate(publication.pub_date)}</span>
                      </div>
                      <p className="text-sm font-medium text-foreground line-clamp-2">{publication.title}</p>
                      {publication.issuing_organ && (
                        <p className="text-xs text-text-tertiary mt-1 truncate">{publication.issuing_organ}</p>
                      )}
                      {publication.reasons && publication.reasons.length > 0 && (
                        <p className="text-[11px] text-primary mt-1 truncate">
                          {publication.reasons.join(' · ')}
                        </p>
                      )}
                    </button>
                  ))}
                </div>
              </div>
            )}

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

          {recentHighlights.length > 0 && (
            <aside className="hidden lg:block animate-fade-in">
              <div className="sticky top-24 rounded-2xl border border-border bg-card p-4">
                <div className="flex items-center gap-2 mb-4">
                  <Icons.clock className="w-4 h-4 text-text-tertiary" />
                  <h2 className="text-xs font-semibold uppercase tracking-widest text-text-tertiary">
                    Recentes relevantes
                  </h2>
                </div>
                <div className="space-y-3">
                  {recentHighlights.map((publication) => (
                    <button
                      key={publication.id}
                      onClick={() => navigate(`/document/${encodeURIComponent(publication.id)}`)}
                      className="w-full rounded-xl border border-transparent px-1 py-1 text-left hover:border-primary/20 transition-colors"
                    >
                      <div className="flex items-center gap-2 text-[11px] text-text-tertiary mb-1">
                        {publication.art_type && <span>{publication.art_type}</span>}
                        <span>·</span>
                        <span>{formatRecentDate(publication.pub_date)}</span>
                      </div>
                      <p className="text-sm font-medium text-foreground line-clamp-3">{publication.title}</p>
                      {publication.issuing_organ && (
                        <p className="text-xs text-text-tertiary mt-1 line-clamp-1">{publication.issuing_organ}</p>
                      )}
                      {publication.reasons && publication.reasons.length > 0 && (
                        <p className="text-[11px] text-primary mt-1 line-clamp-1">
                          {publication.reasons.join(' · ')}
                        </p>
                      )}
                    </button>
                  ))}
                </div>
              </div>
            </aside>
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
