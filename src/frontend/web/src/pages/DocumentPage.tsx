import React, { useEffect, useId, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import { toast } from "sonner";
import { AccessKeyPrompt } from "@/components/AccessKeyPrompt";
import { SectionBadge } from "@/components/Badges";
import { BottomSheet } from "@/components/BottomSheet";
import { DocumentTOC } from "@/components/DocumentTOC";
import { DocumentBody } from "@/components/DocumentRenderer";
import { DocumentGraph } from "@/components/DocumentGraph";
import { DocImage } from "@/components/DocImage";
import { Icons } from "@/components/Icons";
import { MobileActionsBar } from "@/components/MobileActionsBar";
import { ReadingProgress } from "@/components/ReadingProgress";
import { SkeletonDocument } from "@/components/Skeletons";
import { createAccessSession, ApiAuthError } from "@/lib/auth";
import { getDocument } from "@/lib/api";
import type { DocumentDetail } from "@/lib/api";
import { addRecentDocument } from "@/lib/history";
import { getDocumentNavigationState } from "@/lib/navigation";
import { downloadServerPdf, prefersPrintPdfFallback } from "@/lib/pdfExport";
import type { Section } from "@/lib/sectionParser";
import { generateShareUrl, useDeepLink } from "@/hooks/useDeepLink";
import { useDocumentSectionNavigation } from "@/hooks/useDocumentSectionNavigation";
import { usePageMetadata } from "@/hooks/usePageMetadata";
import { useReadingPosition } from "@/hooks/useReadingPosition";
import { formatLongDate, formatTime } from "@/lib/intl";

const DocumentPage: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const location = useLocation();
  const navigate = useNavigate();
  const [doc, setDoc] = useState<DocumentDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [needsAuth, setNeedsAuth] = useState(false);
  const [authError, setAuthError] = useState<string | null>(null);
  const [authPending, setAuthPending] = useState(false);
  const [reloadNonce, setReloadNonce] = useState(0);
  const [showToc, setShowToc] = useState(false);
  const contentRef = useRef<HTMLDivElement>(null);
  const resumeToastShownRef = useRef<string | null>(null);
  const titleId = useId();
  const tocSheetId = useId();

  useEffect(() => {
    if (!id) return;
    setLoading(true);
    setError(false);
    setNeedsAuth(false);
    setAuthError(null);
    getDocument(id)
      .then(setDoc)
      .catch((cause: unknown) => {
        if (cause instanceof ApiAuthError) {
          setNeedsAuth(true);
          setDoc(null);
          return;
        }
        setError(true);
      })
      .finally(() => setLoading(false));
  }, [id, reloadNonce]);

  useEffect(() => {
    if (!doc) return;
    addRecentDocument({
      id: doc.id,
      title: doc.title,
      section: doc.section,
      pubDate: doc.pub_date,
      issuingOrgan: doc.issuing_organ,
      snippet: doc.ementa || doc.subtitle,
    });
  }, [doc]);

  usePageMetadata(doc?.title || "Documento", {
    description: doc?.ementa || doc?.subtitle || doc?.issuing_organ || "Leitura editorial e navegação contextual de documento do Diário Oficial.",
  });

  const {
    activeSectionId,
    activeSectionLabel,
    scrollToSection,
    sections,
    sectionsReady,
  } = useDocumentSectionNavigation(doc, contentRef);

  const { savedPosition, scrollPercent, scrollToSaved } = useReadingPosition(
    doc?.id,
    contentRef,
    sections.map((section) => section.id)
  );

  useDeepLink(contentRef, Boolean(doc) && sectionsReady);

  useEffect(() => {
    if (!doc || !savedPosition) return;
    if (resumeToastShownRef.current === doc.id) return;
    resumeToastShownRef.current = doc.id;
    toast("Continuar de onde parou?", {
      description: savedPosition.nearestSectionId
        ? `Retomar em ${savedPosition.nearestSectionId.replace(/-/g, " ")}`
        : "Retomar no ponto salvo de leitura.",
      action: {
        label: "Continuar",
        onClick: () => scrollToSaved(),
      },
      duration: 6000,
    });
  }, [doc, savedPosition, scrollToSaved]);

  const trailingMedia = useMemo(() => doc?.media?.filter((item) => item.position_in_doc == null) || [], [doc]);
  const continuousEntry = Boolean(getDocumentNavigationState(location.state));

  const documentMetaItems = useMemo(
    () => [
      doc?.art_type ? `Tipo ${doc.art_type}` : null,
      doc?.page ? `Página ${doc.page}` : null,
      doc?.edition ? `Edição ${doc.edition}` : null,
      sections.length > 0 ? `${sections.length} seções` : null,
    ].filter(Boolean) as string[],
    [doc?.art_type, doc?.edition, doc?.page, sections.length]
  );

  const activityItems = useMemo(
    () => [
      {
        label: "Publicação no DOU",
        detail: formatLongDate(doc?.pub_date, doc?.pub_date || ""),
        meta: doc?.pub_date || "",
      },
      {
        label: "Indexação GABI",
        detail: "Disponível para busca e navegação contextual.",
        meta: doc?.pub_date || "",
      },
      {
        label: "Consulta",
        detail: "Agora",
        meta: formatTime(new Date()),
      },
    ],
    [doc?.pub_date]
  );

  const handleSectionSelect = (section: Section) => {
    setShowToc(false);
    scrollToSection(section);
  };

  const handleShare = async () => {
    if (!doc) return;
    const sectionId = activeSectionId || sections[0]?.id || savedPosition?.nearestSectionId || undefined;
    const shareUrl = generateShareUrl(sectionId, sectionId ? undefined : scrollPercent);
    try {
      await navigator.clipboard.writeText(shareUrl);
      toast("Link copiado", { description: "A URL do documento foi copiada com o ponto atual de leitura." });
    } catch {
      toast("Não foi possível copiar o link agora.");
    }
  };

  const handlePdf = async () => {
    if (!contentRef.current || !doc) return;
    if (prefersPrintPdfFallback()) {
      window.print();
      toast("Exportacao PDF no mobile", {
        description: "A exportacao direta ainda nao esta confiavel no mobile. Use o dialogo de impressao para salvar como PDF.",
      });
      return;
    }
    try {
      await downloadServerPdf(doc.id, {
        title: doc.title,
        section: doc.section,
        pubDate: doc.pub_date,
      });
      toast("PDF exportado", { description: "Versão gerada no servidor baixada com sucesso." });
      return;
    } catch (cause) {
      if (cause instanceof ApiAuthError) {
        setNeedsAuth(true);
        toast("Acesso necessário", { description: "Valide a chave de acesso para baixar o PDF." });
        return;
      }
      toast("PDF indisponível", {
        description: "O backend não conseguiu gerar o PDF neste ambiente. Verifique as dependências do servidor.",
      });
    }
  };

  if (loading) return <SkeletonDocument />;

  if (needsAuth) {
    return (
      <AccessKeyPrompt
        title="Documento protegido"
        description="Este documento, suas imagens e a versão em PDF exigem uma chave de acesso do ambiente."
        submitLabel="Abrir documento"
        error={authError}
        pending={authPending}
        onSubmit={async (accessKey) => {
          setAuthPending(true);
          setAuthError(null);
          try {
            await createAccessSession(accessKey);
            setNeedsAuth(false);
            setReloadNonce((value) => value + 1);
          } catch (cause) {
            if (cause instanceof ApiAuthError) {
              setAuthError("Chave inválida ou sem permissão para este ambiente.");
            } else {
              setAuthError("Não foi possível abrir a sessão protegida agora.");
            }
          } finally {
            setAuthPending(false);
          }
        }}
      />
    );
  }

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

  return (
    <div className="min-h-screen bg-background pb-40 md:pb-0">
      <header className={`document-chrome sticky top-0 z-40 border-b border-white/6 bg-background/85 backdrop-blur-xl ${continuousEntry ? "animate-route-settle" : ""}`}>
        <div className="mx-auto flex max-w-[1180px] items-center justify-between px-6 py-4 md:px-10">
          <button
            onClick={() => navigate(-1)}
            className="flex min-h-[44px] min-w-[44px] items-center justify-center rounded-xl text-foreground transition-colors hover:bg-white/[0.04] focus-ring"
            aria-label="Voltar"
          >
            <Icons.back className="w-5 h-5" />
          </button>
          <div className="hidden items-center gap-3 text-sm text-text-secondary md:flex">
            <SectionBadge section={doc.section} />
            <span>{doc.page ? `Página ${doc.page}` : "Documento"}</span>
            {activeSectionLabel ? <span className="truncate max-w-[18rem]">{activeSectionLabel}</span> : null}
          </div>
          <div className="flex items-center gap-1">
            <button
              type="button"
              onClick={() => setShowToc(true)}
              className="hidden min-h-[44px] min-w-[44px] items-center justify-center rounded-xl text-text-secondary transition-colors hover:bg-white/[0.04] hover:text-foreground focus-ring md:flex"
              aria-label="Abrir índice"
              aria-haspopup="dialog"
              aria-expanded={showToc}
              aria-controls={tocSheetId}
            >
              <Icons.book className="h-5 w-5" />
            </button>
            <button
              type="button"
              onClick={handleShare}
              className="flex min-h-[44px] min-w-[44px] items-center justify-center rounded-xl text-text-secondary transition-colors hover:bg-white/[0.04] hover:text-foreground focus-ring"
              aria-label="Copiar link"
              title="Copiar link"
            >
              <Icons.copy className="h-5 w-5" />
            </button>
            <button
              type="button"
              onClick={handlePdf}
              className="flex min-h-[44px] min-w-[44px] items-center justify-center rounded-xl text-text-secondary transition-colors hover:bg-white/[0.04] hover:text-foreground focus-ring"
              aria-label="Baixar ou imprimir"
            >
              <Icons.download className="h-5 w-5" />
            </button>
          </div>
        </div>
      </header>

      <div className="reading-progress sticky top-[76px] z-30">
        <ReadingProgress progress={scrollPercent} activeLabel={activeSectionLabel} />
      </div>

      <div className={`mx-auto grid max-w-[1180px] gap-10 px-6 py-8 md:px-10 lg:grid-cols-[minmax(0,1fr)_16rem] ${continuousEntry ? "animate-route-settle" : ""}`}>
        <div className="min-w-0">
          <section className={`${continuousEntry ? "document-origin-glow" : "animate-fade-in"} reader-surface overflow-hidden rounded-[34px] px-6 py-7 md:px-8 md:py-8`}>
            <div className="mb-5 inline-flex items-center gap-2 text-xs font-medium uppercase tracking-[0.2em] text-text-tertiary">
              <div className="h-px w-6 bg-white/10" />
              Diário Oficial da União
              <div className="h-px w-6 bg-white/10" />
            </div>

            <div className="mb-5 flex flex-wrap items-center gap-x-4 gap-y-2 text-sm">
              <SectionBadge section={doc.section} />
              <span className="text-text-secondary">{formatLongDate(doc.pub_date, doc.pub_date)}</span>
              {doc.page ? <span className="text-text-tertiary">Página {doc.page}</span> : null}
              {doc.edition ? <span className="text-text-tertiary">Ed. {doc.edition}</span> : null}
            </div>

            <h1 id={titleId} className="font-editorial max-w-4xl text-4xl leading-[0.98] text-foreground md:text-6xl">
              {doc.title}
            </h1>

            {doc.identifica && doc.identifica !== doc.title ? (
              <p className="mt-4 text-lg italic text-text-secondary">{doc.identifica}</p>
            ) : null}

            {doc.issuing_organ ? (
              <p className="mt-5 flex items-center gap-2 text-base text-text-tertiary">
                <Icons.building className="w-3.5 h-3.5" />
                {doc.issuing_organ}
              </p>
            ) : null}

            {doc.ementa ? (
              <blockquote className="mt-6 max-w-3xl border-l-2 border-primary/50 pl-5 text-lg italic leading-relaxed text-text-secondary">
                {doc.ementa}
              </blockquote>
            ) : null}

            <div className="mt-7 flex flex-wrap gap-2">
              {documentMetaItems.map((item) => (
                <span
                  key={item}
                  className="rounded-full border border-white/8 bg-white/[0.03] px-3 py-1.5 text-[11px] font-semibold uppercase tracking-[0.14em] text-text-tertiary"
                >
                  {item}
                </span>
              ))}
            </div>

            <div className="mt-8 grid gap-3 md:grid-cols-[minmax(0,1fr)_auto] md:items-end">
              <div className="rounded-[24px] border border-white/8 bg-background/28 px-4 py-4">
                <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-text-tertiary">Contexto de leitura</p>
                <p className="mt-2 text-sm leading-relaxed text-text-secondary">
                  {activeSectionLabel
                    ? `Leitura posicionada em ${activeSectionLabel}.`
                    : "Navegue pelo índice, continue do ponto salvo ou use a rede de relações para saltos contextuais."}
                </p>
              </div>
              <div className="flex flex-wrap gap-2">
                {savedPosition ? (
                  <button
                    type="button"
                    onClick={() => scrollToSaved()}
                    className="rounded-full border border-primary/18 bg-primary/12 px-4 py-2 text-sm font-medium text-primary transition-colors hover:bg-primary/16 focus-ring"
                  >
                    Continuar leitura
                  </button>
                ) : null}
                <button
                  type="button"
                  onClick={() => setShowToc(true)}
                  className="rounded-full border border-white/8 bg-white/[0.03] px-4 py-2 text-sm font-medium text-foreground transition-colors hover:bg-white/[0.06] focus-ring"
                  aria-haspopup="dialog"
                  aria-expanded={showToc}
                  aria-controls={tocSheetId}
                >
                  Abrir índice
                </button>
              </div>
            </div>
          </section>

          <article
            ref={contentRef}
            aria-labelledby={titleId}
            className={`${continuousEntry ? "animate-route-settle" : "animate-fade-in"} reader-surface mt-6 rounded-[34px] px-6 py-8 md:px-10 md:py-10`}
            style={{ animationDelay: "60ms" }}
          >
            <DocumentBody doc={doc} />

            {trailingMedia.map((media, index) => (
              <DocImage
                key={media.name || index}
                media={media}
                docId={doc.id}
                pubDate={doc.pub_date}
                section={doc.section}
                page={doc.page}
              />
            ))}

            {doc.assinatura ? (
              <div className="mt-12 border-t border-white/6 pt-10 text-center">
                <p className="whitespace-pre-line font-editorial text-2xl text-text-secondary">{doc.assinatura}</p>
              </div>
            ) : null}

            {doc.dou_url ? (
              <div className="mt-10 border-t border-white/6 pt-6">
                <a
                  href={doc.dou_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex min-h-[44px] items-center gap-2 rounded-full border border-white/8 bg-white/[0.03] px-4 py-2 text-sm text-text-accent transition-colors hover:bg-white/[0.06]"
                >
                  <Icons.externalLink className="w-4 h-4" />
                  Ver no Diário Oficial
                </a>
              </div>
            ) : null}
          </article>

          <section className="document-secondary-panels mt-8 grid gap-8 lg:grid-cols-[0.9fr_1.1fr]">
            <div className="reader-surface rounded-[30px] px-6 py-6">
              <p className="mb-5 text-xs font-semibold uppercase tracking-[0.18em] text-text-tertiary">
                Rastro editorial
              </p>
              <ol className="space-y-5">
                {activityItems.map((item, index) => (
                  <li key={`${item.label}-${index}`} className="flex gap-4">
                    <div className="flex flex-col items-center">
                      <span className="mt-1 h-3 w-3 rounded-full bg-primary" />
                      {index < activityItems.length - 1 ? <span className="mt-1 h-full w-px bg-white/8" /> : null}
                    </div>
                    <div>
                      <p className="font-editorial text-xl leading-tight text-foreground">{item.label}</p>
                      <p className="mt-1 text-sm text-text-secondary">{item.detail}</p>
                      <p className="text-sm text-text-tertiary">{item.meta}</p>
                    </div>
                  </li>
                ))}
              </ol>
            </div>

            <div>
              <DocumentGraph document={doc} />
            </div>
          </section>
        </div>

        <aside className="hidden lg:block">
          <div className="sticky top-[104px] space-y-4">
            {savedPosition ? (
              <div className="reader-surface rounded-[24px] px-4 py-4">
                <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-text-tertiary">Retomar</p>
                <p className="mt-2 text-sm text-text-secondary">
                  {savedPosition.nearestSectionId
                    ? savedPosition.nearestSectionId.replace(/-/g, " ")
                    : "Ponto salvo de leitura"}
                </p>
                <button
                  type="button"
                  onClick={() => scrollToSaved()}
                  className="mt-4 w-full rounded-[18px] border border-primary/18 bg-primary/12 px-4 py-3 text-sm font-medium text-primary transition-colors hover:bg-primary/16 focus-ring"
                >
                  Continuar daqui
                </button>
              </div>
            ) : null}
            <DocumentTOC sections={sections} activeSectionId={activeSectionId} onSelect={handleSectionSelect} />
          </div>
        </aside>
      </div>

      <BottomSheet open={showToc} onClose={() => setShowToc(false)} title="Índice do documento" contentId={tocSheetId}>
        <DocumentTOC sections={sections} activeSectionId={activeSectionId} onSelect={handleSectionSelect} />
      </BottomSheet>

      <MobileActionsBar
        onBack={() => navigate(-1)}
        onShare={handleShare}
        onPdf={handlePdf}
        onIndex={() => setShowToc(true)}
        hasSections={sections.length > 0}
      />
    </div>
  );
};

export default DocumentPage;
