import React from 'react';
import { useNavigate } from 'react-router-dom';
import type { SearchResult } from '@/lib/api';
import { SectionBadge } from './Badges';
import { Icons } from './Icons';

interface ResultCardProps {
  result: SearchResult;
  index?: number;
  query?: string;
}

export const ResultCard: React.FC<ResultCardProps> = ({ result, index = 0, query }) => {
  const navigate = useNavigate();
  const docUrl = `/document/${encodeURIComponent(result.id)}${query ? `?q=${encodeURIComponent(query)}` : ''}`;
  const isTcu = result.source_type === 'tcu_acordao';

  const formatDate = (d: string) => {
    try {
      return new Date(d).toLocaleDateString('pt-BR', { day: '2-digit', month: 'long', year: 'numeric' }).toUpperCase();
    } catch { return d; }
  };

  const dispositivoLabel: Record<string, string> = {
    irregular: 'Irregular',
    regular: 'Regular',
    regular_com_ressalva: 'Regular c/ Ressalva',
    aplicar_multa: 'Multa',
    imputar_debito: 'Débito',
    determinar: 'Determinação',
    recomendar: 'Recomendação',
    dar_ciencia: 'Ciência',
    arquivar: 'Arquivamento',
    inabilitar: 'Inabilitação',
    declarar_inidoneidade: 'Inidoneidade',
  };

  return (
    <article
      className="group bg-card rounded-2xl border border-border/30 hover:bg-background transition-all duration-300 animate-fade-in"
      style={{ animationDelay: `${index * 40}ms` }}
    >
      <div className="p-6 sm:p-8">
        {/* Meta row */}
        <div className="flex flex-wrap items-center gap-2.5 mb-4">
          {isTcu ? (
            <span className="px-2 py-0.5 rounded-md bg-amber-500/15 text-amber-700 dark:text-amber-400 text-[10px] font-bold font-mono uppercase">
              TCU
            </span>
          ) : (
            result.section && <SectionBadge section={result.section} />
          )}
          {result.art_type && (
            <span className="px-2 py-0.5 rounded-md bg-destructive/10 text-destructive text-[10px] font-bold font-mono uppercase">
              {result.art_type}
            </span>
          )}
          {isTcu && result.colegiado && (
            <span className="px-2 py-0.5 rounded-md bg-blue-500/10 text-blue-700 dark:text-blue-400 text-[10px] font-bold font-mono uppercase">
              {result.colegiado}
            </span>
          )}
          {isTcu && result.dispositivo_resumo && (
            <span className={`px-2 py-0.5 rounded-md text-[10px] font-bold font-mono uppercase ${
              result.dispositivo_resumo === 'irregular' || result.dispositivo_resumo === 'imputar_debito'
                ? 'bg-red-500/10 text-red-700 dark:text-red-400'
                : result.dispositivo_resumo === 'aplicar_multa'
                ? 'bg-orange-500/10 text-orange-700 dark:text-orange-400'
                : 'bg-green-500/10 text-green-700 dark:text-green-400'
            }`}>
              {dispositivoLabel[result.dispositivo_resumo] || result.dispositivo_resumo}
            </span>
          )}
          <span className="w-1 h-1 rounded-full bg-muted-foreground/30" />
          <span className="text-muted-foreground font-mono text-[10px]">{formatDate(result.pub_date)}</span>
          {result.page && (
            <>
              <span className="w-1 h-1 rounded-full bg-muted-foreground/30" />
              <span className="text-muted-foreground font-mono text-[10px]">PÁGINA {result.page}</span>
            </>
          )}
          {!isTcu && result.top_organ && (
            <>
              <span className="w-1 h-1 rounded-full bg-muted-foreground/30" />
              <span className="px-2 py-0.5 rounded-md bg-primary/8 text-primary text-[10px] font-bold font-mono uppercase truncate max-w-[250px]">
                {result.top_organ}
              </span>
            </>
          )}
        </div>

        {/* Title with highlights */}
        <h3
          role="link"
          tabIndex={0}
          onClick={() => navigate(docUrl)}
          onKeyDown={(e) => e.key === 'Enter' && navigate(docUrl)}
          className="text-lg sm:text-xl font-bold text-foreground leading-snug mb-3 group-hover:text-primary transition-colors cursor-pointer"
          dangerouslySetInnerHTML={{ __html: result.highlight || result.title }}
        />

        {/* Snippet */}
        {result.snippet && (
          <p
            className="text-text-secondary text-sm leading-relaxed mb-6 line-clamp-3"
            dangerouslySetInnerHTML={{ __html: result.snippet }}
          />
        )}

        {/* Footer */}
        <div className="flex items-center justify-between pt-5 border-t border-border/30">
          <div className="flex items-center gap-2 min-w-0">
            <Icons.building className="w-4 h-4 text-primary shrink-0" />
            <span className="text-xs font-bold tracking-wider text-foreground uppercase truncate">
              {isTcu ? (result.relator ? `Rel. ${result.relator}` : 'TCU') : (result.issuing_organ || '—')}
            </span>
            {isTcu && result.tipo_processo && (
              <>
                <span className="w-1 h-1 rounded-full bg-muted-foreground/30" />
                <span className="text-xs text-muted-foreground uppercase truncate">
                  {result.tipo_processo}
                </span>
              </>
            )}
          </div>
          <div className="flex items-center gap-3 shrink-0">
            <button
              className="text-muted-foreground hover:text-primary transition-colors p-1"
              aria-label="Salvar"
              onClick={(e) => e.stopPropagation()}
            >
              <Icons.bookmark className="w-5 h-5" />
            </button>
            <a
              href={`/api/document/${encodeURIComponent(result.id)}/pdf`}
              target="_blank"
              rel="noopener noreferrer"
              onClick={(e) => e.stopPropagation()}
              className="flex items-center gap-1.5 px-3 py-1.5 bg-primary/5 hover:bg-primary/10 text-primary rounded-lg text-xs font-bold transition-all"
            >
              <Icons.download className="w-4 h-4" />
              PDF
            </a>
          </div>
        </div>
      </div>
    </article>
  );
};
