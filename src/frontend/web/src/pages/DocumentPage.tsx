import React, { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
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
import type { DocumentDetail, NormativeReference } from "@/lib/api";
import { addRecentDocument } from "@/lib/history";
import { exportDocumentPdf } from "@/lib/pdfExport";
import { parseSections, type Section } from "@/lib/sectionParser";
import { generateShareUrl, useDeepLink } from "@/hooks/useDeepLink";
import { useReadingPosition } from "@/hooks/useReadingPosition";

const DocumentPage: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [doc, setDoc] = useState<DocumentDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [showActions, setShowActions] = useState(false);
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

  const activeSectionLabel = useMemo(
    () => sections.find((section) => section.id === activeSectionId)?.label,
    [activeSectionId, sections]
  );
  const normativeSummary = useMemo(() => buildNormativeSummary(doc), [doc]);
  const normativeTimeline = useMemo(() => buildNormativeTimeline(doc?.normative_refs), [doc?.normative_refs]);

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
    } finally {
      setShowActions(false);
    }
  };

  const handleCopyReference = async () => {
    if (!doc) return;
    const reference = [
      doc.title,
      doc.section ? `DOU ${doc.section.toUpperCase()}` : null,
      doc.pub_date ? new Date(doc.pub_date).toLocaleDateString("pt-BR") : null,
      doc.page ? `p. ${doc.page}` : null,
    ]
      .filter(Boolean)
      .join(" · ");
    await navigator.clipboard.writeText(reference);
    toast("Referência copiada");
    setShowActions(false);
  };

  const handlePdf = async () => {
    if (!contentRef.current || !doc) return;
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
    } finally {
      setShowActions(false);
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
    <div className="min-h-screen bg-background pb-24 md:pb-0">
      <header className="sticky top-0 z-40 bg-background/80 backdrop-blur-xl border-b border-border">
        <div className="max-w-6xl mx-auto px-4 py-3 flex items-center justify-between">
          <button
            onClick={() => navigate(-1)}
            className="p-2 rounded-lg hover:bg-muted transition-colors focus-ring min-w-[44px] min-h-[44px] flex items-center justify-center"
            aria-label="Voltar"
          >
            <Icons.back className="w-5 h-5" />
          </button>
          <div className="hidden md:flex items-center gap-3 text-sm text-text-secondary">
            <SectionBadge section={doc.section} />
            <span>{doc.page ? `Página ${doc.page}` : "Documento"}</span>
          </div>
          <button
            onClick={() => setShowActions(true)}
            className="p-2 rounded-lg hover:bg-muted transition-colors focus-ring min-w-[44px] min-h-[44px] flex items-center justify-center"
            aria-label="Ações"
          >
            <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor">
              <circle cx="12" cy="5" r="2" />
              <circle cx="12" cy="12" r="2" />
              <circle cx="12" cy="19" r="2" />
            </svg>
          </button>
        </div>
      </header>

      <ReadingProgress progress={scrollPercent} activeLabel={activeSectionLabel} />

      <div className="max-w-6xl mx-auto px-4 py-6 md:py-8 grid gap-8 lg:grid-cols-[minmax(0,1fr)_18rem]">
        <div className="min-w-0">
          <div className="border-b border-border pb-6 mb-6 animate-fade-in">
            <div className="inline-flex items-center gap-2 text-xs tracking-[0.2em] uppercase text-text-tertiary font-medium mb-5">
              <div className="w-6 h-px bg-border" />
              Diário Oficial da União
              <div className="w-6 h-px bg-border" />
            </div>

            <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-sm mb-4">
              <SectionBadge section={doc.section} />
              <span className="text-text-secondary">{formatDate(doc.pub_date)}</span>
              {doc.page ? <span className="text-text-tertiary">Página {doc.page}</span> : null}
              {doc.edition ? <span className="text-text-tertiary">Ed. {doc.edition}</span> : null}
            </div>

            {doc.art_type_name ? (
              <p className="text-xs uppercase tracking-[0.16em] text-text-accent font-semibold mb-3">
                {doc.art_type_name}
              </p>
            ) : null}

            <h1 className="text-2xl md:text-4xl font-semibold text-foreground leading-tight">
              {doc.title}
            </h1>

            {doc.identifica && doc.identifica !== doc.title ? (
              <p className="text-base text-text-secondary mt-3 italic">{doc.identifica}</p>
            ) : null}

            {doc.issuing_organ ? (
              <p className="text-sm text-text-tertiary mt-4 flex items-center gap-1.5">
                <Icons.building className="w-3.5 h-3.5" />
                {doc.issuing_organ}
              </p>
            ) : null}

            {doc.ementa ? (
              <blockquote className="mt-5 border-l-2 border-primary/40 pl-4 text-sm text-text-secondary italic leading-relaxed">
                {doc.ementa}
              </blockquote>
            ) : null}
          </div>

          <section className="grid gap-4 md:grid-cols-2 mb-6 animate-fade-in" style={{ animationDelay: "40ms" }}>
            <div className="rounded-2xl border border-border bg-card px-4 py-4">
              <p className="text-xs font-semibold uppercase tracking-[0.16em] text-text-tertiary mb-3">Situação normativa</p>
              <div className="flex items-start gap-3">
                <span
                  className={`mt-1 inline-flex h-2.5 w-2.5 rounded-full ${
                    normativeSummary.tone === "ok"
                      ? "bg-emerald-400"
                      : normativeSummary.tone === "warn"
                        ? "bg-amber-400"
                        : "bg-sky-400"
                  }`}
                />
                <div className="min-w-0">
                  <p className="text-sm font-semibold text-foreground">{normativeSummary.label}</p>
                  <p className="text-xs text-text-secondary mt-1 leading-relaxed">{normativeSummary.detail}</p>
                </div>
              </div>

              {doc.procedure_refs?.length ? (
                <div className="mt-4 pt-4 border-t border-border">
                  <p className="text-[11px] uppercase tracking-[0.16em] text-text-tertiary mb-2">Procedimentos detectados</p>
                  <div className="flex flex-wrap gap-2">
                    {doc.procedure_refs.slice(0, 4).map((procedure, index) => (
                      <span
                        key={`${procedure.procedure_type || "proc"}-${procedure.procedure_identifier || index}`}
                        className="inline-flex items-center rounded-full border border-border bg-background/70 px-2.5 py-1 text-xs text-text-secondary"
                      >
                        {[procedure.procedure_type, procedure.procedure_identifier].filter(Boolean).join(" · ")}
                      </span>
                    ))}
                  </div>
                </div>
              ) : null}
            </div>

            <div className="rounded-2xl border border-border bg-card px-4 py-4">
              <p className="text-xs font-semibold uppercase tracking-[0.16em] text-text-tertiary mb-3">Linha normativa detectada</p>
              {normativeTimeline.length ? (
                <ol className="space-y-3">
                  {normativeTimeline.map((item, index) => (
                    <li key={`${item.date || "sem-data"}-${item.label}-${index}`} className="flex gap-3">
                      <div className="flex flex-col items-center pt-0.5">
                        <span className="h-2.5 w-2.5 rounded-full bg-primary/80" />
                        {index < normativeTimeline.length - 1 ? <span className="mt-1 w-px flex-1 bg-border" /> : null}
                      </div>
                      <div className="min-w-0 pb-1">
                        <p className="text-xs text-text-tertiary">{item.dateLabel}</p>
                        <p className="text-sm text-foreground font-medium">{item.label}</p>
                        {item.detail ? <p className="text-xs text-text-secondary mt-1 leading-relaxed">{item.detail}</p> : null}
                      </div>
                    </li>
                  ))}
                </ol>
              ) : (
                <p className="text-xs text-text-secondary leading-relaxed">
                  Nenhuma cadeia de alteração foi detectada neste corpus. Isso não confirma vigência final; apenas indica ausência de referências estruturadas associadas ao documento.
                </p>
              )}
            </div>
          </section>

          <section className="mb-6 animate-fade-in" style={{ animationDelay: "60ms" }}>
            <DocumentGraph document={doc} />
          </section>

          <main ref={contentRef} className="animate-fade-in" style={{ animationDelay: "80ms" }}>
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
              <div className="mt-8 pt-6 border-t border-border text-center">
                <p className="text-sm text-text-secondary whitespace-pre-line">{doc.assinatura}</p>
              </div>
            ) : null}

            {doc.dou_url ? (
              <div className="mt-8 pt-6 border-t border-border">
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
            ) : null}
          </main>
        </div>

        <aside className="hidden lg:block">
          <div className="sticky top-[112px]">
            <DocumentTOC sections={sections} activeSectionId={activeSectionId} onSelect={handleSectionSelect} />
          </div>
        </aside>
      </div>

      <BottomSheet open={showActions} onClose={() => setShowActions(false)} title="Ações">
        <div className="space-y-1 mt-2">
          <ActionItem icon={<Icons.share className="w-5 h-5" />} label="Compartilhar posição atual" onClick={handleShare} />
          <ActionItem icon={<Icons.document className="w-5 h-5" />} label="Exportar PDF" onClick={handlePdf} />
          <ActionItem icon={<Icons.book className="w-5 h-5" />} label="Copiar referência" onClick={handleCopyReference} />
          {sections.length ? (
            <ActionItem
              icon={<Icons.chevronRight className="w-5 h-5" />}
              label="Abrir índice"
              onClick={() => {
                setShowActions(false);
                setShowToc(true);
              }}
            />
          ) : null}
          {doc.dou_url ? (
            <ActionItem
              icon={<Icons.externalLink className="w-5 h-5" />}
              label="Abrir no DOU"
              onClick={() => {
                window.open(doc.dou_url, "_blank");
                setShowActions(false);
              }}
            />
          ) : null}
        </div>
      </BottomSheet>

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

function buildNormativeSummary(doc: DocumentDetail | null) {
  if (!doc) {
    return {
      tone: "info" as const,
      label: "Sem dados normativos",
      detail: "O documento ainda não carregou referências suficientes para análise.",
    };
  }

  const refs = doc.normative_refs || [];
  const corpus = refs
    .map((ref) => [ref.reference_type, ref.reference_text, ref.reference_number].filter(Boolean).join(" "))
    .join(" ")
    .toLowerCase();

  if (/\brevog/i.test(corpus)) {
    return {
      tone: "warn" as const,
      label: "Ato com sinal de revogação ou substituição",
      detail:
        "As referências detectadas incluem linguagem de revogação. Confirme a vigência no texto consolidado ou no ato posterior correspondente.",
    };
  }

  if (/\balter|\bretific|\bprorrog|\bcomplement/i.test(corpus)) {
    return {
      tone: "warn" as const,
      label: "Ato com alterações ou complementações detectadas",
      detail:
        "Há indícios de nova versão normativa ligada a este documento. Use a linha detectada abaixo para continuar a investigação.",
    };
  }

  if (refs.length > 0 || (doc.procedure_refs || []).length > 0) {
    return {
      tone: "ok" as const,
      label: "Ato conectado a outras referências do corpus",
      detail:
        "Foram encontradas referências normativas ou procedimentais relacionadas. Isso ajuda a reconstruir contexto, mas não substitui consolidação oficial.",
    };
  }

  return {
    tone: "info" as const,
    label: "Sem alterações detectadas no corpus",
    detail:
      "Nenhuma referência estruturada de alteração, revogação ou procedimento foi detectada para este documento na base atual.",
  };
}

function buildNormativeTimeline(refs: NormativeReference[] | undefined) {
  return (refs || [])
    .map((ref) => {
      const date = ref.reference_date ? new Date(ref.reference_date) : null;
      const isValidDate = Boolean(date && !Number.isNaN(date.getTime()));
      const label = [ref.reference_type, ref.reference_number].filter(Boolean).join(" ").trim() || "Referência normativa";
      return {
        date: isValidDate ? date!.toISOString() : undefined,
        timestamp: isValidDate ? date!.getTime() : Number.MAX_SAFE_INTEGER,
        dateLabel: isValidDate
          ? date!.toLocaleDateString("pt-BR", { day: "2-digit", month: "short", year: "numeric" })
          : "Sem data",
        label,
        detail: ref.reference_text || "",
      };
    })
    .sort((left, right) => left.timestamp - right.timestamp)
    .slice(0, 6);
}

const ActionItem: React.FC<{ icon: React.ReactNode; label: string; onClick: () => void }> = ({
  icon,
  label,
  onClick,
}) => (
  <button
    onClick={onClick}
    className="w-full flex items-center gap-3 px-3 py-3 rounded-lg hover:bg-muted transition-colors text-foreground text-sm press-effect focus-ring min-h-[44px]"
  >
    <span className="text-text-secondary">{icon}</span>
    {label}
  </button>
);

export default DocumentPage;
