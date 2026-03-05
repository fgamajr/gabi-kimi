"use client";

import * as React from "react";
import { motion, AnimatePresence } from "framer-motion";
import { useDocument } from "@/hooks/use-search";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn, formatDate, getSectionColor } from "@/lib/utils";
import { 
  ChevronLeft, 
  ChevronRight, 
  X, 
  Share2, 
  Download, 
  Bell, 
  Star,
  Menu,
  Highlighter
} from "lucide-react";
import type { Document } from "@/types";

// =============================================================================
// Document Viewer — Core do produto v4.0
// =============================================================================

export interface DocumentViewerProps {
  docId: string;
  position: number;
  totalInList: number;
  listQuery?: string;
  results?: Document[];
  initialScrollTo?: string;
  initialHighlights?: string[];
  onNavigate: (direction: "next" | "prev") => void;
  onNavigateToIndex: (index: number) => void;
  onClose: () => void;
  onShare?: () => void;
  onDownload?: () => void;
  onAlert?: () => void;
  onFavorite?: () => void;
  isFavorited?: boolean;
}

export function DocumentViewer({
  docId,
  position,
  totalInList,
  // listQuery,
  results = [],
  initialScrollTo,
  initialHighlights = [],
  onNavigate,
  onNavigateToIndex,
  onClose,
  onShare,
  onDownload,
  onAlert,
  onFavorite,
  isFavorited = false,
}: DocumentViewerProps) {
  const { data: doc, isLoading, error } = useDocument(docId);
  const contentRef = React.useRef<HTMLDivElement>(null);
  const [progress, setProgress] = React.useState(0);
  const [showMiniList, setShowMiniList] = React.useState(false);
  const [showToolbar, setShowToolbar] = React.useState(true);
  const [lastScrollY, setLastScrollY] = React.useState(0);

  // Handle scroll for progress and toolbar hide
  React.useEffect(() => {
    const handleScroll = () => {
      if (!contentRef.current) return;
      
      const { scrollTop, scrollHeight, clientHeight } = contentRef.current;
      const scrollProgress = (scrollTop / (scrollHeight - clientHeight)) * 100;
      setProgress(Math.min(100, Math.max(0, scrollProgress)));
      
      // Hide/show toolbar on scroll direction
      if (scrollTop > lastScrollY && scrollTop > 100) {
        setShowToolbar(false);
      } else {
        setShowToolbar(true);
      }
      setLastScrollY(scrollTop);
    };

    const content = contentRef.current;
    if (content) {
      content.addEventListener("scroll", handleScroll);
      return () => content.removeEventListener("scroll", handleScroll);
    }
  }, [lastScrollY]);

  // Initial scroll to section
  React.useEffect(() => {
    if (doc && initialScrollTo && contentRef.current) {
      const element = contentRef.current.querySelector(`[id="${initialScrollTo}"]`);
      if (element) {
        element.scrollIntoView({ behavior: "smooth", block: "start" });
      }
    }
  }, [doc, initialScrollTo]);

  // Apply highlights
  React.useEffect(() => {
    if (doc && initialHighlights.length > 0 && contentRef.current) {
      const textNodes = getTextNodes(contentRef.current);
      initialHighlights.forEach(term => {
        highlightText(textNodes, term);
      });
    }
  }, [doc, initialHighlights]);

  // Swipe handling for navigation
  const touchStart = React.useRef({ x: 0, y: 0 });
  
  const handleTouchStart = (e: React.TouchEvent) => {
    touchStart.current = { x: e.touches[0].clientX, y: e.touches[0].clientY };
  };

  const handleTouchEnd = (e: React.TouchEvent) => {
    const dx = e.changedTouches[0].clientX - touchStart.current.x;
    const dy = e.changedTouches[0].clientY - touchStart.current.y;
    
    // Only horizontal swipes
    if (Math.abs(dx) > Math.abs(dy) && Math.abs(dx) > 80) {
      if (dx > 0 && position > 0) {
        onNavigate("prev");
      } else if (dx < 0 && position < totalInList - 1) {
        onNavigate("next");
      }
    }
  };

  // Keyboard navigation
  React.useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "ArrowRight" && position < totalInList - 1) {
        onNavigate("next");
      } else if (e.key === "ArrowLeft" && position > 0) {
        onNavigate("prev");
      } else if (e.key === "Escape") {
        onClose();
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [position, totalInList, onNavigate, onClose]);

  if (isLoading) {
    return (
      <div className="fixed inset-0 z-50 bg-canvas">
        <div className="h-full flex flex-col">
          <div className="h-14 border-b border-border flex items-center px-4">
            <Skeleton className="h-8 w-8 rounded-lg" />
            <Skeleton className="h-4 w-32 ml-4" />
          </div>
          <div className="flex-1 p-4">
            <Skeleton variant="document" />
          </div>
        </div>
      </div>
    );
  }

  if (error || !doc) {
    console.error("DocumentViewer error:", error);
    return (
      <div className="fixed inset-0 z-50 bg-canvas flex items-center justify-center">
        <div className="text-center p-8 max-w-md">
          <div className="w-16 h-16 mx-auto mb-4 rounded-full bg-error/10 flex items-center justify-center">
            <span className="text-2xl">😕</span>
          </div>
          <h3 className="font-display font-bold text-xl text-primary mb-2">
            Não conseguimos abrir
          </h3>
          <p className="text-secondary mb-2">
            {error instanceof Error ? error.message : "Algo deu errado ao carregar este documento."}
          </p>
          <p className="text-muted text-sm mb-6">
            ID: {docId}
          </p>
          <Button onClick={onClose} fullWidth>
            Voltar para a busca
          </Button>
        </div>
      </div>
    );
  }

  const title = doc.identifica || `${doc.art_type} nº ${doc.document_number}`;
  const readTime = doc.body_word_count 
    ? `${Math.ceil(doc.body_word_count / 200)} min` 
    : null;

  return (
    <motion.div
      initial={{ opacity: 0, x: 100 }}
      animate={{ opacity: 1, x: 0 }}
      exit={{ opacity: 0, x: 100 }}
      transition={{ type: "spring", damping: 25, stiffness: 200 }}
      className="fixed inset-0 z-50 bg-canvas flex flex-col"
      onTouchStart={handleTouchStart}
      onTouchEnd={handleTouchEnd}
    >
      {/* Progress bar */}
      <div className="absolute top-0 left-0 right-0 h-0.5 bg-sunken z-50">
        <motion.div 
          className="h-full bg-brand"
          style={{ width: `${progress}%` }}
        />
      </div>

      {/* Header */}
      <header className="flex items-center justify-between px-4 h-14 border-b border-border safe-top bg-canvas/95 backdrop-blur">
        <div className="flex items-center gap-3">
          <button
            onClick={onClose}
            className="p-2 -ml-2 rounded-lg text-secondary hover:text-primary hover:bg-raised transition-colors touch-target"
            aria-label="Voltar"
          >
            <ChevronLeft className="w-6 h-6" />
          </button>
          
          {/* Navigation between docs */}
          <div className="flex items-center gap-1">
            <button
              onClick={() => onNavigate("prev")}
              disabled={position === 0}
              className="p-1.5 rounded-lg text-secondary hover:text-primary hover:bg-raised disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
              aria-label="Documento anterior"
            >
              <ChevronLeft className="w-5 h-5" />
            </button>
            
            <button
              onClick={() => setShowMiniList(true)}
              className="px-2 py-1 rounded-lg text-sm font-display font-medium text-secondary hover:text-primary hover:bg-raised transition-colors min-w-[80px] text-center"
            >
              {position + 1} de {totalInList}
            </button>
            
            <button
              onClick={() => onNavigate("next")}
              disabled={position === totalInList - 1}
              className="p-1.5 rounded-lg text-secondary hover:text-primary hover:bg-raised disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
              aria-label="Próximo documento"
            >
              <ChevronRight className="w-5 h-5" />
            </button>
          </div>
        </div>

        <div className="flex items-center gap-1">
          <button
            onClick={onShare}
            className="p-2 rounded-lg text-secondary hover:text-primary hover:bg-raised transition-colors touch-target"
            aria-label="Compartilhar"
          >
            <Share2 className="w-5 h-5" />
          </button>
          <button
            onClick={onDownload}
            className="p-2 rounded-lg text-secondary hover:text-primary hover:bg-raised transition-colors touch-target"
            aria-label="Download"
          >
            <Download className="w-5 h-5" />
          </button>
        </div>
      </header>

      {/* Content */}
      <div 
        ref={contentRef}
        className="flex-1 overflow-y-auto scroll-smooth"
      >
        <article className="max-w-2xl mx-auto px-4 py-6">
          {/* Metadata */}
          <div className="mb-6">
            <div className="flex items-center gap-2 mb-3">
              <Badge variant="section" section={doc.section} />
              <span className="text-sm text-muted">{doc.art_type}</span>
            </div>
            
            <h1 className="font-display font-bold text-2xl text-primary mb-2 leading-tight">
              {title}
            </h1>
            
            <p className="text-sm text-secondary mb-1">
              {doc.issuing_organ}
            </p>
            
            <div className="flex items-center gap-3 text-xs text-muted">
              <span>DOU Edição {doc.edition_number} · {formatDate(doc.publication_date)}</span>
              {readTime && <span>· ~{readTime} de leitura</span>}
            </div>
          </div>

          {/* Ementa */}
          {doc.ementa && (
            <div className="mb-6 p-4 bg-raised/50 border-l-2 border-brand rounded-r-lg">
              <p className="font-body text-secondary italic leading-relaxed">
                {doc.ementa}
              </p>
            </div>
          )}

          {/* Divider */}
          <div className="h-px bg-border mb-6" />

          {/* Body */}
          <div 
            className="font-body text-lg leading-[1.75] text-primary select-text"
            dangerouslySetInnerHTML={{ 
              __html: doc.body_html || `<p>${doc.body_plain?.replace(/\n/g, "</p><p>")}</p>` || "<p>Conteúdo não disponível</p>"
            }}
          />

          {/* Signatures */}
          {doc.signatures && doc.signatures.length > 0 && (
            <div className="mt-8 pt-6 border-t border-border">
              {doc.signatures.map((sig, i) => (
                <div key={i} className="mb-4">
                  <p className="font-body text-primary">{sig.person_name}</p>
                  {sig.role_title && (
                    <p className="text-sm text-muted">{sig.role_title}</p>
                  )}
                </div>
              ))}
            </div>
          )}

          {/* Normative refs */}
          {doc.normative_refs && doc.normative_refs.length > 0 && (
            <div className="mt-8 pt-6 border-t border-border">
              <h3 className="font-display font-semibold text-sm text-secondary mb-3">
                Referências normativas
              </h3>
              <ul className="space-y-2">
                {doc.normative_refs.map((ref, i) => (
                  <li key={i} className="text-sm text-muted">
                    {ref.reference_type} {ref.reference_number}
                    {ref.reference_date && ` · ${formatDate(ref.reference_date)}`}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Bottom spacing for toolbar */}
          <div className="h-24" />
        </article>
      </div>

      {/* Floating Toolbar */}
      <AnimatePresence>
        {showToolbar && (
          <motion.div
            initial={{ y: 100 }}
            animate={{ y: 0 }}
            exit={{ y: 100 }}
            className="absolute bottom-0 left-0 right-0 p-4 safe-bottom"
          >
            <div className="max-w-md mx-auto bg-overlay/95 backdrop-blur-lg border border-border rounded-2xl shadow-2xl p-2 flex items-center justify-around">
              <button
                onClick={onFavorite}
                className={cn(
                  "flex flex-col items-center gap-1 p-2 rounded-xl transition-colors touch-target min-w-[64px]",
                  isFavorited 
                    ? "text-warning" 
                    : "text-secondary hover:text-primary"
                )}
              >
                <Star className={cn("w-5 h-5", isFavorited && "fill-current")} />
                <span className="text-2xs font-medium">
                  {isFavorited ? "Salvo" : "Salvar"}
                </span>
              </button>
              
              <button
                onClick={onAlert}
                className="flex flex-col items-center gap-1 p-2 rounded-xl text-secondary hover:text-primary transition-colors touch-target min-w-[64px]"
              >
                <Bell className="w-5 h-5" />
                <span className="text-2xs font-medium">Alerta</span>
              </button>
              
              <button className="flex flex-col items-center gap-1 p-2 rounded-xl text-secondary hover:text-primary transition-colors touch-target min-w-[64px]">
                <Highlighter className="w-5 h-5" />
                <span className="text-2xs font-medium">Anotar</span>
              </button>
              
              <button className="flex flex-col items-center gap-1 p-2 rounded-xl text-secondary hover:text-primary transition-colors touch-target min-w-[64px]">
                <Menu className="w-5 h-5" />
                <span className="text-2xs font-medium">Índice</span>
              </button>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Mini List Overlay */}
      <AnimatePresence>
        {showMiniList && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="absolute inset-0 z-50 bg-canvas/80 backdrop-blur-sm"
            onClick={() => setShowMiniList(false)}
          >
            <motion.div
              initial={{ x: "100%" }}
              animate={{ x: 0 }}
              exit={{ x: "100%" }}
              transition={{ type: "spring", damping: 25 }}
              className="absolute right-0 top-0 bottom-0 w-80 bg-raised border-l border-border"
              onClick={(e) => e.stopPropagation()}
            >
              <div className="h-14 border-b border-border flex items-center justify-between px-4">
                <span className="font-display font-semibold text-primary">
                  Resultados ({totalInList})
                </span>
                <button
                  onClick={() => setShowMiniList(false)}
                  className="p-2 rounded-lg text-secondary hover:text-primary hover:bg-sunken"
                >
                  <X className="w-5 h-5" />
                </button>
              </div>
              
              <div className="overflow-y-auto h-[calc(100%-3.5rem)]">
                {results.map((result, i) => (
                  <button
                    key={result.id}
                    onClick={() => {
                      onNavigateToIndex(i);
                      setShowMiniList(false);
                    }}
                    className={cn(
                      "w-full p-4 text-left border-b border-border transition-colors",
                      i === position 
                        ? "bg-brand/10 border-l-2 border-l-brand" 
                        : "hover:bg-sunken"
                    )}
                  >
                    <div className="flex items-center gap-2 mb-1">
                      <div
                        className="w-2 h-2 rounded-full"
                        style={{ backgroundColor: getSectionColor(result.section) }}
                      />
                      <span className="text-xs text-muted">{result.art_type}</span>
                    </div>
                    <p className={cn(
                      "font-display font-medium text-sm",
                      i === position ? "text-brand" : "text-primary"
                    )}>
                      {result.identifica || `${result.art_type} nº ${result.document_number}`}
                    </p>
                  </button>
                ))}
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
}

// Helper to get all text nodes
function getTextNodes(element: HTMLElement): Text[] {
  const textNodes: Text[] = [];
  const walker = document.createTreeWalker(
    element,
    NodeFilter.SHOW_TEXT,
    null
  );
  let node;
  while ((node = walker.nextNode())) {
    textNodes.push(node as Text);
  }
  return textNodes;
}

// Helper to highlight text
function highlightText(textNodes: Text[], term: string) {
  const regex = new RegExp(`(${escapeRegex(term)})`, "gi");
  
  textNodes.forEach(node => {
    const text = node.textContent || "";
    if (regex.test(text)) {
      const span = document.createElement("span");
      span.innerHTML = text.replace(
        regex, 
        '<mark class="bg-warning/30 text-primary px-0.5 rounded">$1</mark>'
      );
      
      const parent = node.parentNode;
      if (parent) {
        while (span.firstChild) {
          parent.insertBefore(span.firstChild, node);
        }
        parent.removeChild(node);
      }
    }
  });
}

function escapeRegex(string: string): string {
  return string.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}
