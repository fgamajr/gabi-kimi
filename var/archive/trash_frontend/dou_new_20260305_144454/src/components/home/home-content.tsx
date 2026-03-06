"use client";

import * as React from "react";
import { motion, AnimatePresence } from "framer-motion";
import { SearchInput } from "@/components/search/search-input";
import { DocumentCard } from "@/components/documents/document-card";
import { DocumentViewer } from "@/components/viewer/document-viewer";
import { ShareSheet } from "@/components/sheets/share-sheet";
import { DownloadSheet } from "@/components/sheets/download-sheet";
import { BottomNav } from "@/components/layout/bottom-nav";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { OnboardingFlow } from "@/components/onboarding/onboarding-flow";
import { ToastContainer, useNUBankToast } from "@/components/feedback/nubank-toasts";
import { EmptySearch, FunLoading } from "@/components/feedback/empty-states";
import { useSearch } from "@/hooks/use-search";
import { formatDate, debounce } from "@/lib/utils";
import { 
  Search, 
  Clock, 
  X,
  Zap
} from "lucide-react";
import type { AppSection, Document } from "@/types";

// =============================================================================
// HOME CONTENT — DNA Nubank v4.0
// =============================================================================

export function HomeContent() {
  // State
  const [activeSection, setActiveSection] = React.useState<AppSection>("search");
  const [showSuggestions, setShowSuggestions] = React.useState(false);
  const [showOnboarding, setShowOnboarding] = React.useState(false);
  
  // Document viewer state
  const [selectedDoc, setSelectedDoc] = React.useState<Document | null>(null);
  const [selectedDocIndex, setSelectedDocIndex] = React.useState<number>(-1);
  const [showShare, setShowShare] = React.useState(false);
  const [showDownload, setShowDownload] = React.useState(false);
  const [favorites, setFavorites] = React.useState<Set<string>>(new Set());
  
  // Toast system
  const toast = useNUBankToast();
  
  // Search hook
  const {
    filters,
    setFilters,
    clearSearch,
    results,
    total,
    queryTime,
    isLoading,
    suggestions,
    setSuggestionQuery,
    recentSearches,
    addRecentSearch,
    removeRecentSearch,
  } = useSearch();
  
  // Check first visit
  React.useEffect(() => {
    const hasVisited = localStorage.getItem("dou_visited");
    if (!hasVisited) {
      setShowOnboarding(true);
    }
  }, []);
  
  // Debounced suggestion query
  const debouncedSetQuery = React.useMemo(
    () => debounce((q: string) => setSuggestionQuery(q), 150),
    [setSuggestionQuery]
  );
  
  // Handle search input change
  const handleSearchChange = (value: string) => {
    setFilters({ q: value });
    debouncedSetQuery(value);
    setShowSuggestions(value.length > 0);
  };
  
  // Handle search submit
  const handleSearchSubmit = (value: string) => {
    setShowSuggestions(false);
    addRecentSearch(value);
    setFilters({ q: value });
    
    // Fun feedback for first search
    if (!localStorage.getItem("dou_first_search")) {
      localStorage.setItem("dou_first_search", "true");
      setTimeout(() => {
        toast.info("Dica rápida 💡", "Deslize um card pro lado pra favoritar ou criar alerta.");
      }, 1000);
    }
  };
  
  // Handle clear
  const handleClear = () => {
    clearSearch();
    setShowSuggestions(false);
  };
  
  // Handle document open
  const handleDocumentOpen = (doc: Document, position: number) => {
    setSelectedDoc(doc);
    setSelectedDocIndex(position);
  };

  // Handle document close
  const handleDocumentClose = () => {
    setSelectedDoc(null);
    setSelectedDocIndex(-1);
  };

  // Handle navigation between docs
  const handleNavigate = (direction: "next" | "prev") => {
    const newIndex = direction === "next" 
      ? selectedDocIndex + 1 
      : selectedDocIndex - 1;
    
    if (newIndex >= 0 && newIndex < results.length) {
      setSelectedDoc(results[newIndex]);
      setSelectedDocIndex(newIndex);
    }
  };

  const handleNavigateToIndex = (index: number) => {
    if (index >= 0 && index < results.length) {
      setSelectedDoc(results[index]);
      setSelectedDocIndex(index);
    }
  };

  // Handle favorite
  const handleFavorite = (doc: Document) => {
    setFavorites(prev => {
      const next = new Set(prev);
      if (next.has(doc.id)) {
        next.delete(doc.id);
        toast.unfavorite();
      } else {
        next.add(doc.id);
        if (next.size === 1) {
          toast.firstFavorite();
        } else {
          toast.favorite();
        }
      }
      return next;
    });
  };

  // Handle alert
  const handleAlert = (doc: Document) => {
    toast.alertCreated(doc.issuing_organ);
  };

  // Handle share
  const handleShare = () => {
    setShowShare(true);
  };



  // Handle onboarding complete
  const handleOnboardingComplete = (prefs: { profession: string; organs: string[]; enableNotifications: boolean }) => {
    setShowOnboarding(false);
    localStorage.setItem("dou_visited", "true");
    localStorage.setItem("dou_preferences", JSON.stringify(prefs));
    toast.welcome();
    
    if (prefs.organs.length > 0) {
      setTimeout(() => {
        toast.success(
          `✨ ${prefs.organs.length} alerta${prefs.organs.length > 1 ? "s" : ""} criado${prefs.organs.length > 1 ? "s" : ""}!`,
          "Você vai receber notificações quando sair algo novo."
        );
      }, 500);
    }
  };

  // Check if we have search results
  const hasResults = filters.q && filters.q.length > 0 && !isLoading;
  const isEmpty = filters.q && filters.q.length > 0 && !isLoading && results.length === 0;
  
  return (
    <div className="min-h-screen bg-canvas pb-24">
      {/* Toasts */}
      <ToastContainer toasts={toast.toasts} onRemove={toast.remove} />

      {/* Header - mais clean */}
      <header className="sticky top-0 z-40 bg-canvas/80 backdrop-blur-xl safe-top">
        <div className="max-w-lg mx-auto px-5 h-16 flex items-center justify-between">
          <motion.div 
            className="flex items-center gap-3"
            whileHover={{ scale: 1.02 }}
          >
            <div className="w-8 h-8 rounded-xl bg-gradient-to-br from-brand to-brand-light flex items-center justify-center shadow-brand">
              <span className="text-white font-bold text-sm">D</span>
            </div>
            <h1 className="font-display font-bold text-xl text-primary">
              DOU
            </h1>
          </motion.div>
          
          <div className="flex items-center gap-2">
            <button 
              className="p-2.5 rounded-xl text-muted hover:text-primary hover:bg-raised/50 transition-colors"
              onClick={() => setShowOnboarding(true)}
            >
              <span className="sr-only">Ajuda</span>
              <span className="text-sm">?</span>
            </button>
            <button className="p-2.5 rounded-xl text-muted hover:text-primary hover:bg-raised/50 transition-colors relative">
              <span className="sr-only">Notificações</span>
              <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9" />
              </svg>
              <span className="absolute top-2 right-2 w-2 h-2 bg-error rounded-full" />
            </button>
          </div>
        </div>
      </header>

      <main className="max-w-lg mx-auto px-4 pt-4">
        {/* Search Section */}
        <section className="mb-6">
          <SearchInput
            value={filters.q || ""}
            onChange={handleSearchChange}
            onSubmit={handleSearchSubmit}
            onClear={handleClear}
            isLoading={isLoading}
            placeholder="O que você procura?"
            inputSize="lg"
            autoFocus={false}
          />
          
          {/* Suggestions Dropdown */}
          <AnimatePresence>
            {showSuggestions && (
              <motion.div
                initial={{ opacity: 0, y: -10 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -10 }}
                className="mt-2 bg-raised border border-border rounded-xl overflow-hidden shadow-lg"
              >
                {suggestions.length > 0 ? (
                  <div className="py-2">
                    <p className="px-4 py-2 text-xs text-muted font-display uppercase tracking-wider">
                      Sugestões
                    </p>
                    {suggestions.map((suggestion, i) => (
                      <button
                        key={i}
                        onClick={() => handleSearchSubmit(suggestion.text)}
                        className="w-full px-4 py-3 flex items-center gap-3 text-left hover:bg-sunken transition-colors"
                      >
                        <Search className="w-4 h-4 text-muted" />
                        <span className="text-sm text-primary">{suggestion.text}</span>
                      </button>
                    ))}
                  </div>
                ) : recentSearches.length > 0 ? (
                  <div className="py-2">
                    <div className="px-4 py-2 flex items-center justify-between">
                      <p className="text-xs text-muted font-display uppercase tracking-wider">
                        Buscas recentes
                      </p>
                      <button
                        onClick={() => {
                          localStorage.removeItem("dou_recent_searches");
                          window.location.reload();
                        }}
                        className="text-xs text-muted hover:text-primary"
                      >
                        Limpar
                      </button>
                    </div>
                    {recentSearches.slice(0, 5).map((search, i) => (
                      <div
                        key={i}
                        className="group flex items-center hover:bg-sunken transition-colors"
                      >
                        <button
                          onClick={() => handleSearchSubmit(search)}
                          className="flex-1 px-4 py-3 flex items-center gap-3 text-left"
                        >
                          <Clock className="w-4 h-4 text-muted" />
                          <span className="text-sm text-primary">{search}</span>
                        </button>
                        <button
                          onClick={() => removeRecentSearch(search)}
                          className="px-3 py-3 text-muted hover:text-error opacity-0 group-hover:opacity-100 transition-opacity"
                        >
                          <X className="w-4 h-4" />
                        </button>
                      </div>
                    ))}
                  </div>
                ) : null}
              </motion.div>
            )}
          </AnimatePresence>
        </section>

        {/* Results Section */}
        {isLoading ? (
          <FunLoading />
        ) : hasResults ? (
          <section className="space-y-4">
            <motion.div 
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              className="flex items-center justify-between"
            >
              <p className="text-sm text-secondary">
                <motion.span 
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  className="font-semibold text-primary"
                >
                  {total.toLocaleString("pt-BR")}
                </motion.span> resultados
                {queryTime && <span className="text-muted text-xs ml-1">(em {queryTime}ms)</span>}
              </p>
              <button className="text-sm text-brand hover:text-brand-text transition-colors flex items-center gap-1">
                <Zap className="w-4 h-4" />
                Filtros
              </button>
            </motion.div>
            
            <div className="space-y-3">
              {results.map((doc, i) => (
                <DocumentCard
                  key={doc.id}
                  doc={doc}
                  position={i}
                  totalInList={results.length}
                  isFavorited={favorites.has(doc.id)}
                  onOpen={handleDocumentOpen}
                  onFavorite={handleFavorite}
                  onAlert={handleAlert}
                  onShare={() => handleShare()}
                />
              ))}
            </div>
            
            {total > results.length && (
              <Button
                variant="secondary"
                fullWidth
                onClick={() => setFilters({ page: (filters.page || 1) + 1 })}
              >
                Carregar mais resultados
              </Button>
            )}
          </section>
        ) : isEmpty ? (
          <EmptySearch onAction={() => handleSearchSubmit("ministério da fazenda")} />
        ) : (
          /* Default Home Content */
          <>
            {/* Today Summary - mais clean */}
            <section className="mb-8">
              <div className="flex items-baseline justify-between mb-4">
                <h2 className="text-base font-display font-semibold text-primary">
                  Publicado hoje
                </h2>
                <span className="text-sm text-muted">{formatDate(new Date())}</span>
              </div>
              
              <div className="flex gap-3 overflow-x-auto scrollbar-hide -mx-5 px-5 pb-2">
                {[
                  { sec: 1 as const, count: 1847, label: "atos", color: "#5BA3FF" },
                  { sec: 2 as const, count: 312, label: "atos", color: "#FFB347" },
                  { sec: 3 as const, count: 89, label: "atos", color: "#C77DFF" },
                  { sec: "e" as const, count: 12, label: "extras", color: "#FF6B7A" },
                ].map((item) => (
                  <motion.button
                    key={item.sec}
                    whileTap={{ scale: 0.98 }}
                    onClick={() => setFilters({ section: String(item.sec) })}
                    className="flex-shrink-0 w-28 p-4 rounded-2xl bg-raised/40 border border-border/50 hover:bg-raised/70 hover:border-border transition-all text-left group"
                  >
                    <div 
                      className="w-2 h-2 rounded-full mb-3"
                      style={{ backgroundColor: item.color }}
                    />
                    <p className="text-3xl font-display font-bold text-primary group-hover:scale-105 transition-transform">
                      {item.count.toLocaleString("pt-BR")}
                    </p>
                    <p className="text-xs text-muted mt-1 capitalize">{item.label}</p>
                  </motion.button>
                ))}
              </div>
            </section>

            {/* Alerts */}
            <section className="mb-6">
              <div className="flex items-center justify-between mb-3">
                <h2 className="text-sm font-display font-medium text-secondary">
                  Seus alertas <span className="text-error ml-1">· 3 novos</span>
                </h2>
                <button className="text-xs text-brand hover:text-brand-text transition-colors">
                  Ver todos
                </button>
              </div>
              
              <div className="space-y-3">
                {[
                  {
                    id: "1",
                    tipo: "Portaria",
                    numero: "847",
                    orgao: "Ministério da Fazenda",
                    secao: 1 as const,
                    time: "Há 12 min",
                    isNew: true,
                  },
                  {
                    id: "2",
                    tipo: "Instrução Normativa",
                    numero: "93",
                    orgao: "INSS",
                    secao: 2 as const,
                    time: "Há 1h",
                    isNew: true,
                  },
                ].map((alert) => (
                  <motion.div
                    key={alert.id}
                    whileHover={{ scale: 1.01 }}
                    whileTap={{ scale: 0.99 }}
                    className="p-4 rounded-xl bg-raised border border-border hover:border-border-strong transition-colors cursor-pointer"
                  >
                    <div className="flex items-start justify-between">
                      <div className="flex items-center gap-2 mb-2">
                        <Badge variant="section" section={alert.secao} size="sm" />
                        <span className="text-xs text-muted">{alert.tipo}</span>
                      </div>
                      {alert.isNew && <Badge variant="new" />}
                    </div>
                    <p className="font-display font-medium text-primary mb-1">
                      {alert.tipo} nº {alert.numero}/2026
                    </p>
                    <p className="text-sm text-secondary mb-2">{alert.orgao}</p>
                    <div className="flex items-center justify-between">
                      <span className="text-xs text-muted">{alert.time}</span>
                      <div className="flex gap-1">
                        <button className="p-1.5 rounded-lg text-muted hover:text-brand hover:bg-brand/10 transition-colors">
                          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9" />
                          </svg>
                        </button>
                      </div>
                    </div>
                  </motion.div>
                ))}
              </div>
            </section>

            {/* Recent Reads */}
            <section>
              <h2 className="text-sm font-display font-medium text-secondary mb-3">
                Lidos recentemente
              </h2>
              
              <div className="flex gap-3 overflow-x-auto scrollbar-hide -mx-4 px-4 pb-2">
                {[
                  { tipo: "Portaria", orgao: "Banco Central", cor: "#4FA8FF" },
                  { tipo: "Resolução", orgao: "INSS", cor: "#FF9040" },
                  { tipo: "Despacho", orgao: "Min. Saúde", cor: "#B06EFF" },
                ].map((item, i) => (
                  <motion.div
                    key={i}
                    whileTap={{ scale: 0.95 }}
                    className="flex-shrink-0 w-40 p-3 rounded-xl bg-raised border border-border"
                  >
                    <div
                      className="w-8 h-1 rounded-full mb-2"
                      style={{ backgroundColor: item.cor }}
                    />
                    <p className="text-sm font-display font-medium text-primary truncate">
                      {item.tipo}
                    </p>
                    <p className="text-xs text-muted truncate">{item.orgao}</p>
                  </motion.div>
                ))}
              </div>
            </section>
          </>
        )}
      </main>

      {/* Bottom Navigation */}
      <BottomNav
        activeSection={activeSection}
        onNavigate={setActiveSection}
        alertCount={3}
      />

      {/* Onboarding */}
      <OnboardingFlow
        isOpen={showOnboarding}
        onComplete={handleOnboardingComplete}
        onSkip={() => {
          setShowOnboarding(false);
          localStorage.setItem("dou_visited", "true");
          toast.welcome();
        }}
      />

      {/* Document Viewer */}
      <AnimatePresence>
        {selectedDoc && (
          <DocumentViewer
            docId={selectedDoc.id}
            position={selectedDocIndex}
            totalInList={results.length}
            listQuery={filters.q}
            results={results}
            onNavigate={handleNavigate}
            onNavigateToIndex={handleNavigateToIndex}
            onClose={handleDocumentClose}
            onShare={() => setShowShare(true)}
            onDownload={() => setShowDownload(true)}
            onAlert={() => handleAlert(selectedDoc)}
            onFavorite={() => handleFavorite(selectedDoc)}
            isFavorited={favorites.has(selectedDoc.id)}
          />
        )}
      </AnimatePresence>

      {/* Share Sheet */}
      {selectedDoc && (
        <ShareSheet
          isOpen={showShare}
          shareState={{
            docId: selectedDoc.id,
            docTitle: selectedDoc.identifica || `${selectedDoc.art_type} nº ${selectedDoc.document_number}`,
            fromQuery: filters.q,
          }}
          onClose={() => {
            setShowShare(false);
            toast.shared();
          }}
        />
      )}

      {/* Download Sheet */}
      {selectedDoc && (
        <DownloadSheet
          isOpen={showDownload}
          docId={selectedDoc.id}
          docTitle={selectedDoc.identifica || `${selectedDoc.art_type} nº ${selectedDoc.document_number}`}
          docDate={selectedDoc.publication_date}
          docSection={String(selectedDoc.section)}
          docType={selectedDoc.art_type}
          docNumber={selectedDoc.document_number}
          onClose={() => setShowDownload(false)}
        />
      )}
    </div>
  );
}
