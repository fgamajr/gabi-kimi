"use client";

import * as React from "react";
import { useSearchParams, useRouter } from "next/navigation";
import { DocumentViewer } from "@/components/viewer/document-viewer";
import { ShareSheet } from "@/components/sheets/share-sheet";
import { DownloadSheet } from "@/components/sheets/download-sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { useDocument } from "@/hooks/use-search";
import { toast } from "sonner";
import type { Document } from "@/types";

// =============================================================================
// Document Content — Share-as-State + Deep Linking v4.0
// =============================================================================

interface DocContentProps {
  docId: string;
}

export function DocContent({ docId }: DocContentProps) {
  const searchParams = useSearchParams();
  const router = useRouter();
  
  // Parse share state from URL
  const scrollTo = searchParams.get("scroll") || undefined;
  const highlights = searchParams.get("hl")?.split(",").filter(Boolean) || [];
  const note = searchParams.get("note") ? decodeURIComponent(searchParams.get("note")!) : undefined;
  const fromQuery = searchParams.get("from_query") || undefined;
  
  // State for sheets
  const [showShare, setShowShare] = React.useState(false);
  const [showDownload, setShowDownload] = React.useState(false);
  
  // Current scroll position (updated by viewer)
  const [currentScrollPosition /*, setCurrentScrollPosition */] = React.useState<string | undefined>(scrollTo);
  const [currentHighlights /*, setCurrentHighlights */] = React.useState<string[]>(highlights);
  
  // Fetch document
  const { data: doc, isLoading } = useDocument(docId);
  
  // Mock state for navigation (in real app, this would come from context or URL)
  const [navigationState /*, setNavigationState */] = React.useState({
    position: 0,
    total: 1,
    results: [] as Document[],
    query: fromQuery,
  });

  // Handle navigation
  const handleNavigate = (direction: "next" | "prev") => {
    const newPosition = direction === "next" 
      ? navigationState.position + 1 
      : navigationState.position - 1;
    
    if (newPosition >= 0 && newPosition < navigationState.results.length) {
      const nextDoc = navigationState.results[newPosition];
      router.push(`/doc/${nextDoc.id}?from_query=${encodeURIComponent(fromQuery || "")}`);
    }
  };

  const handleNavigateToIndex = (index: number) => {
    if (index >= 0 && index < navigationState.results.length) {
      const nextDoc = navigationState.results[index];
      router.push(`/doc/${nextDoc.id}?from_query=${encodeURIComponent(fromQuery || "")}`);
    }
  };

  // Handle close (go back or to home)
  const handleClose = () => {
    if (fromQuery) {
      router.push(`/?q=${encodeURIComponent(fromQuery)}`);
    } else {
      router.push("/");
    }
  };

  // Handle share
  const handleShare = () => {
    setShowShare(true);
  };

  // Handle download
  const handleDownload = () => {
    setShowDownload(true);
  };

  // Handle favorite
  const handleFavorite = () => {
    toast.success("Salvo nos favoritos! ⭐", {
      description: "Você pode ver todos os seus favoritos no seu perfil.",
    });
  };

  // Handle alert
  const handleAlert = () => {
    toast.success("Alerta criado! 🔔", {
      description: "Você vai receber uma notificação quando sair algo novo deste órgão.",
    });
  };

  // Show shared banner if coming from share link
  const isSharedLink = scrollTo || highlights.length > 0 || note;

  if (isLoading) {
    return (
      <div className="fixed inset-0 bg-canvas">
        <div className="h-full flex flex-col">
          <div className="h-14 border-b border-border flex items-center px-4">
            <Skeleton className="h-8 w-8 rounded-lg" />
          </div>
          <div className="flex-1 p-4">
            <Skeleton variant="document" />
          </div>
        </div>
      </div>
    );
  }

  if (!doc) {
    return (
      <div className="fixed inset-0 bg-canvas flex items-center justify-center">
        <div className="text-center p-8">
          <p className="text-error mb-4">Documento não encontrado</p>
          <button 
            onClick={() => router.push("/")}
            className="px-4 py-2 bg-brand text-canvas rounded-lg font-medium"
          >
            Voltar para home
          </button>
        </div>
      </div>
    );
  }

  return (
    <>
      {/* Shared link banner */}
      {isSharedLink && (
        <div className="fixed top-0 left-0 right-0 z-[60] bg-brand/90 backdrop-blur text-canvas px-4 py-2 safe-top">
          <div className="max-w-lg mx-auto flex items-center justify-between">
            <p className="text-sm font-medium">
              📌 Alguém compartilhou este trecho com você
            </p>
            <button 
              onClick={() => router.replace(`/doc/${docId}`)}
              className="text-xs underline opacity-80 hover:opacity-100"
            >
              Fechar
            </button>
          </div>
        </div>
      )}

      {/* Note banner if shared with note */}
      {note && (
        <div className="fixed top-12 left-0 right-0 z-[60] bg-info/10 border-b border-info/20 px-4 py-3">
          <div className="max-w-lg mx-auto">
            <p className="text-sm text-info font-medium mb-1">Nota do remetente:</p>
            <p className="text-sm text-primary">{note}</p>
          </div>
        </div>
      )}

      <DocumentViewer
        docId={docId}
        position={navigationState.position}
        totalInList={navigationState.total}
        listQuery={fromQuery}
        results={navigationState.results}
        initialScrollTo={scrollTo}
        initialHighlights={highlights}
        onNavigate={handleNavigate}
        onNavigateToIndex={handleNavigateToIndex}
        onClose={handleClose}
        onShare={handleShare}
        onDownload={handleDownload}
        onAlert={handleAlert}
        onFavorite={handleFavorite}
        isFavorited={false}
      />

      <ShareSheet
        isOpen={showShare}
        shareState={{
          docId,
          docTitle: doc.identifica || `${doc.art_type} nº ${doc.document_number}`,
          scrollTo: currentScrollPosition,
          highlights: currentHighlights,
          fromQuery,
        }}
        onClose={() => setShowShare(false)}
        currentScrollPosition={currentScrollPosition}
        currentHighlights={currentHighlights}
      />

      <DownloadSheet
        isOpen={showDownload}
        docId={docId}
        docTitle={doc.identifica || `${doc.art_type} nº ${doc.document_number}`}
        docDate={doc.publication_date}
        docSection={String(doc.section)}
        docType={doc.art_type}
        docNumber={doc.document_number}
        pdfUrl={undefined} // Would come from API
        onClose={() => setShowDownload(false)}
      />
    </>
  );
}
