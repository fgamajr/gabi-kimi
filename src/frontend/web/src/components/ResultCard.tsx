import React from 'react';
import { useNavigate } from 'react-router-dom';
import type { SearchResult } from '@/lib/api';
import { SectionBadge } from './Badges';
import { navigateToDocument } from '@/lib/navigation';

function sanitizeSnippet(html: string) {
  return html
    .replace(/<(?!\/?(mark|em|strong|b)\b)[^>]+>/giu, "")
    .trim();
}

interface ResultCardProps {
  result: SearchResult;
  index?: number;
}

export const ResultCard: React.FC<ResultCardProps> = ({ result, index = 0 }) => {
  const navigate = useNavigate();

  const formatDate = (d: string) => {
    try {
      return new Date(d).toLocaleDateString('pt-BR', { day: '2-digit', month: 'short', year: 'numeric' });
    } catch { return d; }
  };

  return (
    <article
      role="link"
      tabIndex={0}
      onClick={() => navigateToDocument(navigate, result.id, "search-result")}
      onKeyDown={(e) => e.key === 'Enter' && navigateToDocument(navigate, result.id, "search-result")}
      className="group cursor-pointer overflow-hidden rounded-[26px] border border-white/8 bg-[linear-gradient(180deg,rgba(16,18,30,0.9),rgba(10,12,22,0.96))] p-4 transition-all hover:border-primary/20 hover:shadow-[var(--shadow-md)] press-effect focus-ring animate-fade-in animate-lift"
      style={{ animationDelay: `${index * 50}ms` }}
    >
      <div className="mb-3 flex flex-wrap items-center gap-2 text-xs">
        <SectionBadge section={result.section} />
        <span className="rounded-full border border-white/8 px-2.5 py-1 text-[11px] uppercase tracking-[0.14em] text-text-tertiary">
          {formatDate(result.pub_date)}
        </span>
        {result.page && <span className="text-text-tertiary">p. {result.page}</span>}
        {result.art_type && (
          <span className="text-text-tertiary hidden sm:inline">• {result.art_type}</span>
        )}
      </div>

      <h3 className="font-editorial mb-2 text-[1.35rem] leading-tight text-foreground transition-colors group-hover:text-primary line-clamp-2">
        {result.title}
      </h3>

      {(result.snippet || result.highlight) && (
        <p
          className="mb-3 text-sm leading-relaxed text-text-secondary line-clamp-3"
          dangerouslySetInnerHTML={{ __html: sanitizeSnippet(result.highlight || result.snippet || '') }}
        />
      )}

      <div className="flex items-end justify-between gap-3 border-t border-white/6 pt-3">
        <div className="min-w-0">
          {result.issuing_organ && (
            <p className="truncate text-xs uppercase tracking-[0.14em] text-text-tertiary">
              {result.issuing_organ}
            </p>
          )}
        </div>
        <span className="shrink-0 text-xs font-semibold uppercase tracking-[0.16em] text-primary">
          Abrir leitura
        </span>
      </div>
    </article>
  );
};
