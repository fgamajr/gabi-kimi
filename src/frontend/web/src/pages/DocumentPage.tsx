import React, { useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import { toast } from "sonner";
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
import { getDocument } from "@/lib/api";
import type { DocumentDetail } from "@/lib/api";
import { addRecentDocument } from "@/lib/history";
import { downloadServerPdf, exportDocumentPdf, prefersPrintPdfFallback } from "@/lib/pdfExport";
import { parseSections, type Section } from "@/lib/sectionParser";
import { generateShareUrl, useDeepLink } from "@/hooks/useDeepLink";
import { useReadingPosition } from "@/hooks/useReadingPosition";

const DocumentPage: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const location = useLocation();
  const navigate = useNavigate();
  const [doc, setDoc] = useState<DocumentDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [showToc, setShowToc] = useState(false);
  const [sections, setSections] = useState<Section[]>([]);
  const [activeSectionId, setActiveSectionId] = useState<string | null>(null);
  const contentRef = useRef<HTMLDivElement>(null);
  const resumeToastShownRef = useRef<string | null>(null);

  useEffect(() => {
    if (!id) return;
    setLoading(true);
    setError(false);
    getDocument(id)
      .then(setDoc)
      .catch(() => setError(true))
      .finally(() => setLoading(false));
  }, [id]);

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

  useEffect(() => {
    if (!doc || !contentRef.current) return;
    const frame = window.requestAnimationFrame(() => {
      const parsedSections = parseSections(contentRef.current!);
      setSections(parsedSections);
      setActiveSectionId(parsedSections[0]?.id || null);
    });
    return () => window.cancelAnimationFrame(frame);
  }, [doc]);

  useEffect(() => {
    if (!sections.length) return;
    const observers = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((entry) => entry.isIntersecting)
          .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top);
        if (visible[0]?.target?.id) {
          setActiveSectionId(visible[0].target.id);
        }
      },
      { rootMargin: "-20% 0px -65% 0px", threshold: [0.1, 0.4, 0.8] }
    );

    sections.forEach((section) => observers.observe(section.element));
    return () => observers.disconnect();
  }, [sections]);

  const { savedPosition, scrollPercent, scrollToSaved } = useReadingPosition(
    doc?.id,
    contentRef,
    sections.map((section) => section.id)
  );

  useDeepLink(contentRef, Boolean(doc && contentRef.current));

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
  const transitionOrigin = (location.state as { documentTransitionOrigin?: string } | null)?.documentTransitionOrigin;
  const continuousEntry = Boolean(transitionOrigin);

  const activeSectionLabel = useMemo(
    () => sections.find((section) => section.id === activeSectionId)?.label,
    [activeSectionId, sections]
  );

  const formatDate = (value: string) => {
    try {
      return new Date(value).toLocaleDateString("pt-BR", {
        weekday: "long",
        day: "2-digit",
        month: "long",
        year: "numeric",
      });
    } catch {
      return value;
    }
  };

  const activityItems = useMemo(
    () => [
      {
        label: "Publicação no DOU",
        detail: formatDate(doc?.pub_date || ""),
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
        meta: new Date().toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" }),
      },
    ],
    [doc?.pub_date]
  );

  const handleSectionSelect = (section: Section) => {
    setShowToc(false);
    section.element.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  const handleShare = async () => {
    if (!doc) return;
    const shareUrl = generateShareUrl(activeSectionId || undefined, activeSectionId ? undefined : scrollPercent);
    try {
      if (navigator.share) {
        await navigator.share({ title: doc.title, url: shareUrl });
      } else {
        await navigator.clipboard.writeText(shareUrl);
        toast("Link copiado", { description: "O link do documento foi copiado com a posição atual." });
      }
    } catch {
      toast("Não foi possível compartilhar agora.");
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
    } catch {
      // Fall back to client-side rendering below.
    }
    try {
      await exportDocumentPdf(contentRef.current, {
        title: doc.title,
        section: doc.section,
        pubDate: doc.pub_date,
      });
      toast("PDF exportado", { description: "O documento foi preparado para download." });
    } catch {
      window.print();
      toast("Abrindo impressão", { description: "Use Salvar como PDF no navegador se necessário." });
    }
  };

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
          </div>
          <div className="flex items-center gap-1">
            <button
              onClick={handleShare}
              className="flex min-h-[44px] min-w-[44px] items-center justify-center rounded-xl text-text-secondary transition-colors hover:bg-white/[0.04] hover:text-foreground focus-ring"
              aria-label="Compartilhar"
            >
              <Icons.share className="h-5 w-5" />
            </button>
            <button
              onClick={handlePdf}
              className="flex min-h-[44px] min-w-[44px] items-center justify-center rounded-xl text-text-secondary transition-colors hover:bg-white/[0.04] hover:text-foreground focus-ring"
              aria-label="Baixar ou imprimir"
            >
              <Icons.download className="h-5 w-5" />
            </button>
          </div>
        </div>
      </header>

      <div className="reading-progress">
        <ReadingProgress progress={scrollPercent} activeLabel={activeSectionLabel} />
      </div>

      <div className={`mx-auto grid max-w-[1180px] gap-10 px-6 py-8 md:px-10 lg:grid-cols-[minmax(0,1fr)_16rem] ${continuousEntry ? "animate-route-settle" : ""}`}>
        <div className="min-w-0">
          <section className={`${continuousEntry ? "document-origin-glow" : "animate-fade-in"} border-b border-white/6 pb-8`}>
            <div className="mb-5 inline-flex items-center gap-2 text-xs font-medium uppercase tracking-[0.2em] text-text-tertiary">
              <div className="h-px w-6 bg-white/10" />
              Diário Oficial da União
              <div className="h-px w-6 bg-white/10" />
            </div>

            <div className="mb-5 flex flex-wrap items-center gap-x-4 gap-y-2 text-sm">
              <SectionBadge section={doc.section} />
              <span className="text-text-secondary">{formatDate(doc.pub_date)}</span>
              {doc.page ? <span className="text-text-tertiary">Página {doc.page}</span> : null}
              {doc.edition ? <span className="text-text-tertiary">Ed. {doc.edition}</span> : null}
            </div>

            <h1 className="max-w-4xl text-3xl font-semibold leading-tight text-foreground md:text-5xl">
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
          </section>

          <main
            ref={contentRef}
            className={`${continuousEntry ? "animate-route-settle" : "animate-fade-in"} pt-8`}
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
                <p className="whitespace-pre-line text-2xl text-text-secondary">{doc.assinatura}</p>
              </div>
            ) : null}

            {doc.dou_url ? (
              <div className="mt-10 border-t border-white/6 pt-6">
                <a
                  href={doc.dou_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex min-h-[44px] items-center gap-2 text-sm text-text-accent hover:underline"
                >
                  <Icons.externalLink className="w-4 h-4" />
                  Ver no Diário Oficial
                </a>
              </div>
            ) : null}
          </main>

          <section className="document-secondary-panels mt-12 grid gap-8 border-t border-white/6 pt-8 lg:grid-cols-[0.9fr_1.1fr]">
            <div>
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
                      <p className="text-lg text-foreground">{item.label}</p>
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
          <div className="sticky top-[104px]">
            <DocumentTOC sections={sections} activeSectionId={activeSectionId} onSelect={handleSectionSelect} />
          </div>
        </aside>
      </div>

      <BottomSheet open={showToc} onClose={() => setShowToc(false)} title="Índice do documento">
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
