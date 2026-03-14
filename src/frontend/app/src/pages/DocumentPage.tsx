import React, { useEffect, useState, useMemo } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { getDocument } from '@/lib/api';
import type { DocumentDetail, DocumentMedia } from '@/lib/api';
import { DocImage, ImageFallbackCard } from '@/components/DocImage';
import { SectionBadge } from '@/components/Badges';
import { BottomSheet } from '@/components/BottomSheet';
import { SkeletonDocument } from '@/components/Skeletons';
import { Icons } from '@/components/Icons';

const DocumentPage: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [doc, setDoc] = useState<DocumentDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [showActions, setShowActions] = useState(false);

  useEffect(() => {
    if (!id) return;
    setLoading(true);
    setError(false);
    getDocument(id)
      .then(setDoc)
      .catch(() => setError(true))
      .finally(() => setLoading(false));
  }, [id]);

  const formatDate = (d: string) => {
    try {
      return new Date(d).toLocaleDateString('pt-BR', {
        weekday: 'long', day: '2-digit', month: 'long', year: 'numeric'
      });
    } catch { return d; }
  };

  // Process body HTML to integrate images
  const processedBody = useMemo(() => {
    if (!doc?.body_html) return doc?.body_plain || '';
    return doc.body_html;
  }, [doc]);

  // Separate media by position
  const mediaByPosition = useMemo(() => {
    if (!doc?.media) return new Map<number, DocumentMedia>();
    const map = new Map<number, DocumentMedia>();
    doc.media.forEach(m => {
      if (m.position_in_doc != null) map.set(m.position_in_doc, m);
    });
    return map;
  }, [doc]);

  // Media without position (show at end)
  const trailingMedia = useMemo(() => {
    return doc?.media?.filter(m => m.position_in_doc == null) || [];
  }, [doc]);

  if (loading) return <SkeletonDocument />;

  if (error || !doc) {
    return (
      <div className="min-h-screen bg-background flex items-center justify-center px-4">
        <div className="text-center animate-fade-in">
          <Icons.document className="w-12 h-12 text-text-tertiary mx-auto mb-4" />
          <p className="text-foreground font-medium">Documento não encontrado</p>
          <button
            onClick={() => navigate(-1)}
            className="mt-4 px-4 py-2 rounded-lg bg-card border border-border text-sm hover:bg-muted transition-colors press-effect focus-ring min-h-[44px]"
          >
            Voltar
          </button>
        </div>
      </div>
    );
  }

  const sectionName = doc.section_name || `Seção ${doc.section}`;

  return (
    <div className="min-h-screen bg-background">
      {/* Header bar */}
      <header className="sticky top-0 z-40 bg-background/80 backdrop-blur-xl border-b border-border">
        <div className="max-w-3xl mx-auto px-4 py-3 flex items-center justify-between">
          <button
            onClick={() => navigate(-1)}
            className="p-2 rounded-lg hover:bg-muted transition-colors focus-ring min-w-[44px] min-h-[44px] flex items-center justify-center"
            aria-label="Voltar"
          >
            <Icons.back className="w-5 h-5" />
          </button>
          <button
            onClick={() => setShowActions(true)}
            className="p-2 rounded-lg hover:bg-muted transition-colors focus-ring min-w-[44px] min-h-[44px] flex items-center justify-center"
            aria-label="Ações"
          >
            <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor">
              <circle cx="12" cy="5" r="2" /><circle cx="12" cy="12" r="2" /><circle cx="12" cy="19" r="2" />
            </svg>
          </button>
        </div>
      </header>

      {/* Publication masthead */}
      <div className="border-b border-border">
        <div className="max-w-3xl mx-auto px-4 py-6 animate-fade-in">
          {/* DOU Masthead */}
          <div className="text-center mb-6">
            <div className="inline-flex items-center gap-2 text-xs tracking-[0.2em] uppercase text-text-tertiary font-medium">
              <div className="w-6 h-px bg-border" />
              Diário Oficial da União
              <div className="w-6 h-px bg-border" />
            </div>
          </div>

          {/* Meta grid */}
          <div className="flex flex-wrap items-center justify-center gap-x-4 gap-y-2 text-sm mb-5">
            <SectionBadge section={doc.section} />
            <span className="text-text-secondary">{formatDate(doc.pub_date)}</span>
            {doc.page && <span className="text-text-tertiary">Página {doc.page}</span>}
            {doc.edition && <span className="text-text-tertiary">Ed. {doc.edition}</span>}
          </div>

          {/* Art type */}
          {doc.art_type_name && (
            <p className="text-center text-xs uppercase tracking-widest text-text-accent font-semibold mb-4">
              {doc.art_type_name}
            </p>
          )}

          {/* Title */}
          <h1 className="text-xl sm:text-2xl md:text-3xl font-bold font-serif text-foreground text-center leading-snug">
            {doc.title}
          </h1>

          {/* Identifica */}
          {doc.identifica && doc.identifica !== doc.title && (
            <p className="text-base text-text-secondary text-center mt-3 font-serif italic">
              {doc.identifica}
            </p>
          )}

          {/* Issuing organ */}
          {doc.issuing_organ && (
            <p className="text-center text-sm text-text-tertiary mt-3 flex items-center justify-center gap-1.5">
              <Icons.building className="w-3.5 h-3.5" />
              {doc.issuing_organ}
            </p>
          )}

          {/* Ementa */}
          {doc.ementa && (
            <blockquote className="mt-5 border-l-2 border-primary/40 pl-4 text-sm text-text-secondary italic leading-relaxed max-w-xl mx-auto">
              {doc.ementa}
            </blockquote>
          )}
        </div>
      </div>

      {/* Document body */}
      <main className="max-w-3xl mx-auto px-4 py-8 animate-fade-in" style={{ animationDelay: '100ms' }}>
        <div
          className="prose-editorial"
          dangerouslySetInnerHTML={{ __html: processedBody }}
        />

        {/* Trailing media */}
        {trailingMedia.map((m, i) => (
          <DocImage
            key={m.name || i}
            media={m}
            docId={doc.id}
            pubDate={doc.pub_date}
            section={doc.section}
            page={doc.page}
          />
        ))}

        {/* Signature */}
        {doc.assinatura && (
          <div className="mt-8 pt-6 border-t border-border text-center">
            <p className="text-sm text-text-secondary font-serif whitespace-pre-line">
              {doc.assinatura}
            </p>
          </div>
        )}

        {/* Source link */}
        {doc.dou_url && (
          <div className="mt-8 pt-6 border-t border-border text-center">
            <a
              href={doc.dou_url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-2 text-sm text-text-accent hover:underline min-h-[44px]"
            >
              <Icons.externalLink className="w-4 h-4" />
              Ver no Diário Oficial
            </a>
          </div>
        )}
      </main>

      {/* Actions bottom sheet */}
      <BottomSheet open={showActions} onClose={() => setShowActions(false)} title="Ações">
        <div className="space-y-1 mt-2">
          {doc.dou_url && (
            <ActionItem
              icon={<Icons.externalLink className="w-5 h-5" />}
              label="Abrir no DOU"
              onClick={() => window.open(doc.dou_url, '_blank')}
            />
          )}
          <ActionItem
            icon={<Icons.share className="w-5 h-5" />}
            label="Compartilhar"
            onClick={() => {
              if (navigator.share) {
                navigator.share({ title: doc.title, url: window.location.href });
              } else {
                navigator.clipboard.writeText(window.location.href);
              }
              setShowActions(false);
            }}
          />
        </div>
      </BottomSheet>
    </div>
  );
};

const ActionItem: React.FC<{ icon: React.ReactNode; label: string; onClick: () => void }> = ({ icon, label, onClick }) => (
  <button
    onClick={onClick}
    className="w-full flex items-center gap-3 px-3 py-3 rounded-lg hover:bg-muted transition-colors text-foreground text-sm press-effect focus-ring min-h-[44px]"
  >
    <span className="text-text-secondary">{icon}</span>
    {label}
  </button>
);

export default DocumentPage;
