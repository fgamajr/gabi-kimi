import React from 'react';
import type { DocumentMedia } from '@/lib/api';
import { getMediaUrl } from '@/lib/api';

interface ImageFallbackCardProps {
  media: DocumentMedia;
  docId: string;
  pubDate?: string;
  section?: string;
  page?: string;
}

const CONTEXT_LABELS: Record<string, { title: string; description: string }> = {
  table: { title: 'Tabela indisponível', description: 'Tabela disponível apenas no documento original' },
  signature: { title: 'Assinatura', description: 'Assinatura — conteúdo não disponível digitalmente' },
  emblem: { title: 'Brasão institucional', description: 'Brasão/logotipo institucional' },
  chart: { title: 'Gráfico indisponível', description: 'Gráfico disponível apenas no documento original' },
  photo: { title: 'Imagem indisponível', description: 'Fotografia não disponível digitalmente' },
  unknown: { title: 'Imagem indisponível', description: 'Conteúdo gráfico não disponível' },
};

const ContextIcon: React.FC<{ hint?: string }> = ({ hint }) => {
  const cls = "w-8 h-8 text-text-tertiary";
  switch (hint) {
    case 'table':
      return (
        <svg className={cls} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
          <rect x="3" y="3" width="18" height="18" rx="2" />
          <line x1="3" y1="9" x2="21" y2="9" /><line x1="3" y1="15" x2="21" y2="15" />
          <line x1="9" y1="3" x2="9" y2="21" /><line x1="15" y1="3" x2="15" y2="21" />
        </svg>
      );
    case 'signature':
      return (
        <svg className={cls} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
          <path d="M2 18c2-2 4-6 6-2s4 4 6 0 4-2 6 0" />
        </svg>
      );
    case 'emblem':
      return (
        <svg className={cls} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
          <circle cx="12" cy="12" r="9" /><circle cx="12" cy="12" r="4" />
          <line x1="12" y1="3" x2="12" y2="8" /><line x1="12" y1="16" x2="12" y2="21" />
        </svg>
      );
    default:
      return (
        <svg className={cls} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
          <rect x="3" y="3" width="18" height="18" rx="2" />
          <circle cx="8.5" cy="8.5" r="1.5" /><path d="m21 15-5-5L5 21" />
        </svg>
      );
  }
};

export const ImageFallbackCard: React.FC<ImageFallbackCardProps> = ({ media, docId, pubDate, section, page }) => {
  const hint = media.context_hint || 'unknown';
  const info = CONTEXT_LABELS[hint] || CONTEXT_LABELS.unknown;
  const fallbackText = media.fallback_text || info.description;

  const formatDate = (d?: string) => {
    if (!d) return '';
    try { return new Date(d).toLocaleDateString('pt-BR'); } catch { return d; }
  };

  return (
    <div className="my-6 rounded-lg border border-border bg-muted/50 p-5 flex flex-col items-center text-center gap-3" role="img" aria-label={info.title}>
      <div className="w-14 h-14 rounded-full bg-secondary flex items-center justify-center">
        <ContextIcon hint={hint} />
      </div>
      <div>
        <p className="text-sm font-medium text-foreground">{info.title}</p>
        <p className="text-xs text-text-secondary mt-1">{fallbackText}</p>
      </div>
      {(pubDate || section || page) && (
        <p className="text-xs text-text-tertiary">
          {[formatDate(pubDate), section && `Seção ${section}`, page && `p. ${page}`].filter(Boolean).join(' · ')}
        </p>
      )}
      {media.original_url && (
        <a
          href={media.original_url}
          target="_blank"
          rel="noopener noreferrer"
          className="text-xs text-text-accent hover:underline mt-1 min-h-[44px] flex items-center"
        >
          Consultar DOU original ↗
        </a>
      )}
    </div>
  );
};

interface DocImageProps {
  media: DocumentMedia;
  docId: string;
  pubDate?: string;
  section?: string;
  page?: string;
}

export const DocImage: React.FC<DocImageProps> = ({ media, docId, pubDate, section, page }) => {
  const [error, setError] = React.useState(false);

  if (media.status === 'missing' || media.status === 'unknown' || media.status === 'error' || error) {
    return <ImageFallbackCard media={media} docId={docId} pubDate={pubDate} section={section} page={page} />;
  }

  const src = media.blob_url || getMediaUrl(docId, media.name);

  return (
    <figure className="my-6">
      <img
        src={src}
        alt={media.fallback_text || media.name}
        onError={() => setError(true)}
        loading="lazy"
        className="max-w-full rounded-lg border border-border mx-auto"
      />
    </figure>
  );
};
