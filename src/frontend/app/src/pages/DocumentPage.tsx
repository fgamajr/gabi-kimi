import React, { useEffect, useState, useMemo } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { getDocument } from '@/lib/api';
import type { DocumentDetail } from '@/lib/api';
import { DocImage } from '@/components/DocImage';
import { SectionBadge } from '@/components/Badges';
import { BottomSheet } from '@/components/BottomSheet';
import { SkeletonDocument } from '@/components/Skeletons';
import { Icons } from '@/components/Icons';
import { Header } from '@/components/Header';
import { ThemeToggle } from '@/components/ThemeToggle';
import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from '@/components/ui/breadcrumb';

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

  // Process body: use body_html if available, otherwise convert body_plain to paragraphs
  const processedBody = useMemo(() => {
    if (doc?.body_html) return doc.body_html;
    const plain = doc?.body_plain || '';
    if (!plain) return '';
    // Split on double newlines for paragraphs, single newlines within
    return plain
      .split(/\n{2,}/)
      .filter(p => p.trim())
      .map(p => `<p>${p.replace(/\n/g, '<br/>')}</p>`)
      .join('\n');
  }, [doc]);

  // Separate media by position
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

  const shareDocument = () => {
    if (navigator.share) {
      navigator.share({ title: doc.title, url: window.location.href });
      return;
    }
    navigator.clipboard.writeText(window.location.href);
  };

  const openPdf = () => {
    window.open(`/api/document/${encodeURIComponent(doc.id)}/pdf`, '_blank');
  };

  const openDou = () => {
    if (doc.dou_url) window.open(doc.dou_url, '_blank');
  };

  return (
    <div className="min-h-full bg-background">
      <Header
        showBack
        onBack={() => navigate(-1)}
        actionsRight={
          <>
            <a
              href={`/api/document/${encodeURIComponent(doc.id)}/pdf`}
              target="_blank"
              rel="noopener noreferrer"
              className="p-2 rounded-lg hover:bg-muted transition-colors focus-ring min-w-[44px] min-h-[44px] flex items-center justify-center"
              aria-label="Baixar PDF"
            >
              <Icons.download className="w-5 h-5" />
            </a>
            <ThemeToggle />
            <button
              onClick={() => setShowActions(true)}
              className="lg:hidden p-2 rounded-lg hover:bg-muted transition-colors focus-ring min-w-[44px] min-h-[44px] flex items-center justify-center"
              aria-label="Ações"
            >
              <Icons.more className="w-5 h-5" />
            </button>
          </>
        }
      />

      <main className="max-w-5xl mx-auto px-4 py-8 lg:grid lg:grid-cols-[1fr_320px] lg:gap-12 animate-fade-in">
        <article>
          <Breadcrumb className="mb-4">
            <BreadcrumbList>
              <BreadcrumbItem>
                <BreadcrumbLink asChild>
                  <Link to="/">Início</Link>
                </BreadcrumbLink>
              </BreadcrumbItem>
              <BreadcrumbSeparator />
              <BreadcrumbItem>
                <BreadcrumbPage>{sectionName}</BreadcrumbPage>
              </BreadcrumbItem>
              {doc.art_type_name && (
                <>
                  <BreadcrumbSeparator />
                  <BreadcrumbItem>
                    <BreadcrumbPage>{doc.art_type_name}</BreadcrumbPage>
                  </BreadcrumbItem>
                </>
              )}
            </BreadcrumbList>
          </Breadcrumb>

          <header className="mb-8 border-b border-border pb-6">
            <div className="flex flex-wrap items-center gap-2 text-sm mb-4">
              <SectionBadge section={doc.section} />
              <span className="text-text-secondary">{formatDate(doc.pub_date)}</span>
              {doc.page && <span className="text-text-tertiary">Página {doc.page}</span>}
              {doc.edition && <span className="text-text-tertiary">Edição {doc.edition}</span>}
            </div>

            {doc.art_type_name && (
              <p className="text-xs uppercase tracking-widest text-text-accent font-semibold mb-3">{doc.art_type_name}</p>
            )}

            <h1 className="text-2xl md:text-4xl font-serif font-bold leading-tight">{doc.title}</h1>

            {doc.identifica && doc.identifica !== doc.title && (
              <p className="mt-3 text-base text-text-secondary italic font-serif">{doc.identifica}</p>
            )}

            {doc.ementa && (
              <blockquote className="mt-5 border-l-2 border-primary/40 pl-4 text-sm text-text-secondary italic leading-relaxed">
                {doc.ementa}
              </blockquote>
            )}
          </header>

          <div className="prose-doc" dangerouslySetInnerHTML={{ __html: processedBody }} />

          {trailingMedia.map((m, i) => (
            <DocImage key={m.name || i} media={m} docId={doc.id} pubDate={doc.pub_date} section={doc.section} page={doc.page} />
          ))}

          {(doc.assinatura || doc.primary_signer) && (
            <div className="mt-8 pt-6 border-t border-border">
              {doc.signers_all && doc.signers_all.length > 1 ? (
                doc.signers_all.map((s, i) => (
                  <p key={i} className="text-sm text-text-secondary font-serif">
                    {s}
                  </p>
                ))
              ) : (
                <p className="text-sm text-text-secondary font-serif whitespace-pre-line">{doc.primary_signer || doc.assinatura}</p>
              )}
            </div>
          )}
        </article>

        <aside className="hidden lg:block">
          <div className="sticky top-24 space-y-4">
            <section className="rounded-xl border border-border bg-card p-4">
              <h3 className="text-xs uppercase tracking-[0.2em] text-text-tertiary font-semibold mb-3">Ações</h3>
              <div className="space-y-2">
                <ActionItem icon={<Icons.download className="w-5 h-5" />} label="Baixar PDF Oficial" onClick={openPdf} primary />
                <ActionItem icon={<Icons.share className="w-5 h-5" />} label="Compartilhar" onClick={shareDocument} />
                <ActionItem icon={<Icons.printer className="w-5 h-5" />} label="Imprimir" onClick={() => window.print()} />
                {doc.dou_url && (
                  <ActionItem icon={<Icons.externalLink className="w-5 h-5" />} label="Ver no Diário Oficial" onClick={openDou} />
                )}
              </div>
            </section>

            <section className="rounded-xl border border-border bg-card p-4">
              <h3 className="text-xs uppercase tracking-[0.2em] text-text-tertiary font-semibold mb-3">Metadados</h3>
              <dl className="space-y-3">
                {doc.issuing_organ && <MetadataRow label="Órgão emissor" value={doc.issuing_organ} />}
                {doc.edition && <MetadataRow label="Edição" value={doc.edition} />}
                {doc.page && <MetadataRow label="Página" value={doc.page} />}
                <MetadataRow label="Data" value={formatDate(doc.pub_date)} />
                <MetadataRow label="Seção" value={sectionName} />
              </dl>
            </section>
          </div>
        </aside>
      </main>

      {/* Actions bottom sheet */}
      <BottomSheet open={showActions} onClose={() => setShowActions(false)} title="Ações">
        <div className="space-y-1 mt-2">
          {doc.dou_url && (
            <ActionItem
              icon={<Icons.externalLink className="w-5 h-5" />}
              label="Abrir no DOU"
              onClick={() => {
                openDou();
                setShowActions(false);
              }}
            />
          )}
          <ActionItem
            icon={<Icons.download className="w-5 h-5" />}
            label="Baixar PDF"
            onClick={() => {
              openPdf();
              setShowActions(false);
            }}
          />
          <ActionItem
            icon={<Icons.share className="w-5 h-5" />}
            label="Compartilhar"
            onClick={() => {
              shareDocument();
              setShowActions(false);
            }}
          />
          <ActionItem
            icon={<Icons.printer className="w-5 h-5" />}
            label="Imprimir"
            onClick={() => {
              window.print();
              setShowActions(false);
            }}
          />
        </div>
      </BottomSheet>
    </div>
  );
};

const ActionItem: React.FC<{ icon: React.ReactNode; label: string; onClick: () => void; primary?: boolean }> = ({
  icon,
  label,
  onClick,
  primary = false,
}) => (
  <button
    onClick={onClick}
    className={`w-full flex items-center gap-3 px-3 py-3 rounded-lg transition-colors text-sm press-effect focus-ring min-h-[44px] ${
      primary
        ? 'bg-primary text-primary-foreground hover:opacity-90'
        : 'hover:bg-muted text-foreground'
    }`}
  >
    <span className={primary ? 'text-primary-foreground' : 'text-text-secondary'}>{icon}</span>
    {label}
  </button>
);

const MetadataRow: React.FC<{ label: string; value: string }> = ({ label, value }) => (
  <div>
    <dt className="text-xs text-text-tertiary mb-1">{label}</dt>
    <dd className="text-sm font-medium text-foreground">{value}</dd>
  </div>
);

export default DocumentPage;
