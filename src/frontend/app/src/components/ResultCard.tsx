import React from 'react';
import { useNavigate } from 'react-router-dom';
import type { SearchResult } from '@/lib/api';
import { SectionBadge } from './Badges';

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
      onClick={() => navigate(`/document/${encodeURIComponent(result.id)}`)}
      onKeyDown={(e) => e.key === 'Enter' && navigate(`/document/${encodeURIComponent(result.id)}`)}
      className="group rounded-lg bg-card border border-border p-4 cursor-pointer transition-all hover:border-primary/30 hover:shadow-[var(--shadow-md)] press-effect focus-ring animate-fade-in"
      style={{ animationDelay: `${index * 50}ms` }}
    >
      {/* Meta row */}
      <div className="flex items-center gap-2 mb-2 text-xs">
        <SectionBadge section={result.section} />
        <span className="text-text-tertiary">{formatDate(result.pub_date)}</span>
        {result.page && <span className="text-text-tertiary">p. {result.page}</span>}
        {result.art_type && (
          <span className="text-text-tertiary hidden sm:inline">• {result.art_type}</span>
        )}
      </div>

      {/* Title */}
      <h3 className="font-semibold text-foreground leading-snug mb-1 group-hover:text-primary transition-colors line-clamp-2">
        {result.title}
      </h3>

      {/* Snippet */}
      {(result.snippet || result.highlight) && (
        <p
          className="text-sm text-text-secondary leading-relaxed line-clamp-2 mb-2"
          dangerouslySetInnerHTML={{ __html: result.highlight || result.snippet || '' }}
        />
      )}

      {/* Footer */}
      {result.issuing_organ && (
        <p className="text-xs text-text-tertiary truncate">
          {result.issuing_organ}
        </p>
      )}
    </article>
  );
};
