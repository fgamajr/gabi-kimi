import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import EditorialHighlights from '@/components/EditorialHighlights';
import { Header } from '@/components/Header';
import { Icons } from '@/components/Icons';
import { SearchBar } from '@/components/SearchBar';
import { ThemeToggle } from '@/components/ThemeToggle';
import { getEditorialHighlights, getRecentHighlights, getSearchExamples, getStats, getSuggestedTopics, getTrending } from '@/lib/api';
import type { EditorialHighlightsResponse, RecentHighlight, SearchExample, StatsResponse, SuggestedTopic, TrendingTopic } from '@/lib/api';

const HomePage: React.FC = () => {
  const navigate = useNavigate();
  const [stats, setStats] = useState<StatsResponse | null>(null);
  const [trendingTopics, setTrendingTopics] = useState<TrendingTopic[]>([]);
  const [recentHighlights, setRecentHighlights] = useState<RecentHighlight[]>([]);
  const [examples, setExamples] = useState<SearchExample[]>([]);
  const [suggestedTopics, setSuggestedTopics] = useState<SuggestedTopic[]>([]);
  const [editorial, setEditorial] = useState<EditorialHighlightsResponse | null>(null);

  useEffect(() => {
    Promise.allSettled([getStats(), getTrending(), getSearchExamples(), getRecentHighlights(), getSuggestedTopics(), getEditorialHighlights()]).then(
      ([statsRes, trendingRes, examplesRes, recentRes, suggestedRes, editorialRes]) => {
        if (statsRes.status === 'fulfilled') setStats(statsRes.value);
        if (trendingRes.status === 'fulfilled') setTrendingTopics((trendingRes.value || []).slice(0, 6));
        if (examplesRes.status === 'fulfilled') setExamples((examplesRes.value || []).slice(0, 6));
        if (recentRes.status === 'fulfilled') setRecentHighlights((recentRes.value || []).slice(0, 8));
        if (suggestedRes.status === 'fulfilled') setSuggestedTopics(suggestedRes.value || []);
        if (editorialRes.status === 'fulfilled') setEditorial(editorialRes.value);
      },
    );
  }, []);

  const formatDate = (d: string) => {
    try {
      return new Date(d).toLocaleDateString('pt-BR', { month: 'short', year: 'numeric' });
    } catch {
      return d;
    }
  };

  const formatDayMonth = (d: string) => {
    try {
      return new Date(d).toLocaleDateString('pt-BR', { day: '2-digit', month: 'short' });
    } catch {
      return d;
    }
  };

  const formatNumber = (value: number | undefined) => (value == null ? '—' : value.toLocaleString('pt-BR'));

  return (
    <div className="min-h-full">
      <Header actionsRight={<ThemeToggle />} />

      <section className="relative overflow-hidden px-4 pt-14 pb-12">
        <div className="pointer-events-none absolute inset-0 -z-10">
          <div className="absolute -top-20 -left-16 w-72 h-72 rounded-full bg-primary/10 blur-3xl" />
          <div className="absolute -bottom-20 -right-16 w-72 h-72 rounded-full bg-primary/15 blur-3xl" />
        </div>

        <div className="max-w-5xl mx-auto text-center">
          <p className="inline-flex items-center gap-2 mb-4 px-3 py-1.5 rounded-full bg-secondary text-text-secondary text-xs font-semibold uppercase tracking-wider">
            <Icons.book className="w-3.5 h-3.5" />
            GABI DOU
          </p>

          <h1 className="text-4xl md:text-6xl font-black tracking-tight leading-tight">
            Pesquise o Diario Oficial com
            <span className="block text-transparent bg-clip-text bg-gradient-to-r from-primary to-blue-500"> contexto editorial</span>
          </h1>

          <p className="mt-5 max-w-2xl mx-auto text-base md:text-lg text-text-secondary">
            Busque atos, portarias e decretos com filtros, tendências e visualização limpa para leitura documental.
          </p>

          <div className="mt-10 max-w-3xl mx-auto">
            <SearchBar />
            {stats?.date_range?.max && (
              <p className="mt-3 text-xs text-text-tertiary">
                Atualizado até {new Date(stats.date_range.max).toLocaleDateString('pt-BR')}
              </p>
            )}
          </div>

          {suggestedTopics.length > 0 && (
            <div className="mt-6 flex flex-wrap justify-center gap-2">
              {suggestedTopics.slice(0, 8).map((topic) => (
                <button
                  key={topic.query}
                  onClick={() =>
                    navigate(
                      `/search?q=${encodeURIComponent(topic.query)}${
                        topic.intent ? `&intent=${encodeURIComponent(topic.intent)}` : ''
                      }`,
                    )
                  }
                  className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full border border-border bg-card hover:border-primary/40 hover:text-primary transition-colors text-xs font-medium min-h-[36px]"
                >
                  <Icons.hash className="w-3.5 h-3.5" />
                  {topic.label}
                </button>
              ))}
            </div>
          )}
        </div>
      </section>

      <section className="bg-surface-sunken border-y border-border">
        <div className="max-w-6xl mx-auto px-4 py-8 grid grid-cols-2 md:grid-cols-4 gap-4">
          <Stat label="Publicações" value={formatNumber(stats?.total_documents)} />
          <Stat label="Cobertura" value="2002 - 2026" />
          <Stat label="Desde" value={stats?.date_range?.min ? formatDate(stats.date_range.min) : '—'} />
          <Stat label="Atualizado até" value={stats?.date_range?.max ? formatDate(stats.date_range.max) : '—'} />
        </div>
      </section>

      {editorial && Object.keys(editorial.categories).length > 0 ? (
        <>
          <EditorialHighlights data={editorial} />
          <main className="max-w-6xl mx-auto px-4 pb-10 space-y-10">
            {trendingTopics.length > 0 && (
              <section>
                <h2 className="text-2xl font-black tracking-tight">Em alta</h2>
                <p className="text-sm text-text-secondary mt-1 mb-4">Tópicos com maior tração nos últimos 7 dias</p>

                {trendingTopics.length < 3 ? (
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                    {trendingTopics.map((topic) => (
                      <TrendingCard
                        key={topic.query}
                        topic={topic}
                        onClick={() => navigate(`/search?q=${encodeURIComponent(topic.query)}&intent=trending&is_trending=true`)}
                      />
                    ))}
                  </div>
                ) : (
                  <div className="grid md:grid-cols-3 auto-rows-[minmax(140px,auto)] gap-3">
                    {trendingTopics.map((topic, idx) => (
                      <TrendingCard
                        key={topic.query}
                        topic={topic}
                        large={idx === 0}
                        onClick={() => navigate(`/search?q=${encodeURIComponent(topic.query)}&intent=trending&is_trending=true`)}
                      />
                    ))}
                  </div>
                )}
              </section>
            )}

            {examples.length > 0 && (
              <section>
                <h3 className="text-lg font-semibold mb-3">Exemplos de busca</h3>
                <ul className="grid sm:grid-cols-2 md:grid-cols-3 gap-2">
                  {examples.map((example) => (
                    <li key={example.query}>
                      <button
                        onClick={() => navigate(`/search?q=${encodeURIComponent(example.query)}`)}
                        className="w-full text-left rounded-xl border border-border bg-card px-4 py-3 hover:border-primary/40 transition-colors focus-ring"
                      >
                        <p className="font-semibold">{example.query}</p>
                        {example.description && <p className="text-sm text-text-secondary mt-1">{example.description}</p>}
                      </button>
                    </li>
                  ))}
                </ul>
              </section>
            )}
          </main>
        </>
      ) : (
        <main className="max-w-6xl mx-auto px-4 py-10 grid grid-cols-1 lg:grid-cols-[1fr_320px] gap-8">
          <div className="space-y-10">
            {trendingTopics.length > 0 && (
              <section>
                <h2 className="text-2xl font-black tracking-tight">Em alta</h2>
                <p className="text-sm text-text-secondary mt-1 mb-4">Tópicos com maior tração nos últimos 7 dias</p>

                {trendingTopics.length < 3 ? (
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                    {trendingTopics.map((topic) => (
                      <TrendingCard
                        key={topic.query}
                        topic={topic}
                        onClick={() => navigate(`/search?q=${encodeURIComponent(topic.query)}&intent=trending&is_trending=true`)}
                      />
                    ))}
                  </div>
                ) : (
                  <div className="grid md:grid-cols-3 auto-rows-[minmax(140px,auto)] gap-3">
                    {trendingTopics.map((topic, idx) => (
                      <TrendingCard
                        key={topic.query}
                        topic={topic}
                        large={idx === 0}
                        onClick={() => navigate(`/search?q=${encodeURIComponent(topic.query)}&intent=trending&is_trending=true`)}
                      />
                    ))}
                  </div>
                )}
              </section>
            )}

            {examples.length > 0 && (
              <section>
                <h3 className="text-lg font-semibold mb-3">Exemplos de busca</h3>
                <ul className="grid sm:grid-cols-2 gap-2">
                  {examples.map((example) => (
                    <li key={example.query}>
                      <button
                        onClick={() => navigate(`/search?q=${encodeURIComponent(example.query)}`)}
                        className="w-full text-left rounded-xl border border-border bg-card px-4 py-3 hover:border-primary/40 transition-colors focus-ring"
                      >
                        <p className="font-semibold">{example.query}</p>
                        {example.description && <p className="text-sm text-text-secondary mt-1">{example.description}</p>}
                      </button>
                    </li>
                  ))}
                </ul>
              </section>
            )}
          </div>

          <aside className="lg:sticky lg:top-24 h-fit">
            <h3 className="text-xs uppercase tracking-[0.2em] text-text-tertiary font-semibold mb-3">Destaques recentes</h3>
            {recentHighlights.length === 0 ? (
              <p className="text-sm text-text-secondary">Sem destaques recentes no momento.</p>
            ) : (
              <div className="space-y-2">
                {recentHighlights.slice(0, 6).map((item) => (
                  <button
                    key={item.id}
                    onClick={() => navigate(`/document/${encodeURIComponent(item.id)}`)}
                    className="w-full text-left rounded-xl border border-border bg-card px-3 py-3 hover:border-primary/40 transition-colors focus-ring"
                  >
                    <p className="text-sm font-semibold line-clamp-2">{item.title}</p>
                    <p className="text-xs text-text-tertiary mt-1">{formatDayMonth(item.pub_date)}</p>
                  </button>
                ))}
              </div>
            )}
          </aside>
        </main>
      )}
    </div>
  );
};

const Stat: React.FC<{ label: string; value: string }> = ({ label, value }) => (
  <div className="rounded-xl border border-border bg-card px-3 py-4 text-center">
    <p className="text-[11px] uppercase tracking-[0.18em] text-text-tertiary font-mono">{label}</p>
    <p className="text-2xl font-black mt-1">{value}</p>
  </div>
);

const TrendingCard: React.FC<{ topic: TrendingTopic; onClick: () => void; large?: boolean }> = ({ topic, onClick, large }) => {
  const trendSign = topic.trend_score > 0 ? '+' : '';
  return (
    <button
      onClick={onClick}
      className={`group relative overflow-hidden rounded-xl border border-border bg-card p-4 text-left hover:border-primary/40 transition-all animate-lift focus-ring ${
        large ? 'md:col-span-2 md:row-span-2' : ''
      }`}
    >
      {large && <Icons.trending className="absolute -right-2 -top-2 w-24 h-24 text-primary/10 pointer-events-none" />}
      <div className="relative z-10">
        <p className="text-xs uppercase tracking-[0.18em] text-text-tertiary font-semibold mb-2">
          {large ? 'Destaque da semana' : 'Tendência'}
        </p>
        <p className={`${large ? 'text-2xl' : 'text-lg'} font-bold leading-snug`}>{topic.label}</p>
        <p className={`${large ? 'text-4xl' : 'text-2xl'} font-black text-primary mt-3`}>
          {topic.doc_count_7d.toLocaleString('pt-BR')}
        </p>
        <p className="text-xs text-text-secondary">publicações nos últimos 7 dias</p>
        <p className="mt-2 text-xs font-medium text-text-tertiary">
          {trendSign}
          {topic.trend_score.toFixed(1)} de tendência
        </p>
      </div>
    </button>
  );
};

export default HomePage;
