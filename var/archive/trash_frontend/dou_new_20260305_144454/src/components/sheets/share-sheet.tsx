"use client";

import * as React from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Button } from "@/components/ui/button";
import { copyToClipboard } from "@/lib/utils";
import { 
  X, 
  Check, 
  MessageSquare, 
  MapPin,
  Highlighter,
  Share2,
  Copy
} from "lucide-react";

// =============================================================================
// Share Sheet — Share-as-State v4.0
// =============================================================================

export interface ShareState {
  docId: string;
  docTitle: string;
  scrollTo?: string;
  highlights?: string[];
  note?: string;
  fromQuery?: string;
}

interface ShareSheetProps {
  isOpen: boolean;
  shareState: ShareState;
  onClose: () => void;
  currentScrollPosition?: string;
  currentHighlights?: string[];
}

export function ShareSheet({
  isOpen,
  shareState,
  onClose,
  currentScrollPosition,
  currentHighlights = [],
}: ShareSheetProps) {
  const [includePosition, setIncludePosition] = React.useState(!!currentScrollPosition);
  const [includeHighlights, setIncludeHighlights] = React.useState(currentHighlights.length > 0);
  const [includeNote, setIncludeNote] = React.useState(false);
  const [note, setNote] = React.useState("");
  const [copied, setCopied] = React.useState(false);
  const [isSharing, setIsSharing] = React.useState(false);
  const [canNativeShare, setCanNativeShare] = React.useState(false);

  // Check if native share is available (client-side only)
  React.useEffect(() => {
    setCanNativeShare(typeof navigator !== "undefined" && !!navigator.share);
  }, []);

  // Generate share URL based on options
  const shareUrl = React.useMemo(() => {
    const params = new URLSearchParams();
    
    if (includePosition && currentScrollPosition) {
      params.set("scroll", currentScrollPosition);
    }
    
    if (includeHighlights && currentHighlights.length > 0) {
      params.set("hl", currentHighlights.join(","));
    }
    
    if (includeNote && note.trim()) {
      params.set("note", encodeURIComponent(note.trim()));
    }
    
    if (shareState.fromQuery) {
      params.set("from_query", shareState.fromQuery);
    }
    
    const queryString = params.toString();
    return `${window.location.origin}/doc/${shareState.docId}${queryString ? `?${queryString}` : ""}`;
  }, [shareState, includePosition, includeHighlights, includeNote, note, currentScrollPosition, currentHighlights]);

  // Handle copy
  const handleCopy = async () => {
    const success = await copyToClipboard(shareUrl);
    if (success) {
      setCopied(true);
      setTimeout(() => setCopied(false), 3000);
    }
  };

  // Handle native share
  const handleNativeShare = async () => {
    if (navigator.share) {
      setIsSharing(true);
      try {
        await navigator.share({
          title: shareState.docTitle,
          text: includeNote && note ? `${shareState.docTitle}\n\n${note}` : shareState.docTitle,
          url: shareUrl,
        });
      } catch {
        // User cancelled or share failed
      } finally {
        setIsSharing(false);
      }
    } else {
      // Fallback to copy
      handleCopy();
    }
  };

  // Handle WhatsApp share
  const handleWhatsAppShare = () => {
    const text = encodeURIComponent(`${shareState.docTitle}\n${shareUrl}`);
    window.open(`https://wa.me/?text=${text}`, "_blank");
  };

  // Handle Telegram share
  const handleTelegramShare = () => {
    const text = encodeURIComponent(`${shareState.docTitle}\n${shareUrl}`);
    window.open(`https://t.me/share/url?url=${encodeURIComponent(shareUrl)}&text=${text}`, "_blank");
  };

  // Handle email share
  const handleEmailShare = () => {
    const subject = encodeURIComponent(shareState.docTitle);
    const body = encodeURIComponent(`${shareState.docTitle}\n\n${shareUrl}`);
    window.open(`mailto:?subject=${subject}&body=${body}`, "_blank");
  };

  return (
    <AnimatePresence>
      {isOpen && (
        <>
          {/* Backdrop */}
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-50 bg-canvas/60 backdrop-blur-sm"
            onClick={onClose}
          />

          {/* Sheet */}
          <motion.div
            initial={{ y: "100%" }}
            animate={{ y: 0 }}
            exit={{ y: "100%" }}
            transition={{ type: "spring", damping: 25, stiffness: 300 }}
            className="fixed bottom-0 left-0 right-0 z-50 bg-raised border-t border-border rounded-t-3xl max-h-[90vh] overflow-hidden"
          >
            {/* Drag handle */}
            <div className="flex justify-center pt-3 pb-2">
              <div className="w-10 h-1 rounded-full bg-border" />
            </div>

            <div className="px-4 pb-8 overflow-y-auto max-h-[calc(90vh-2rem)]">
              {/* Header */}
              <div className="flex items-center justify-between mb-6">
                <h2 className="font-display font-bold text-xl text-primary">
                  Compartilhar documento
                </h2>
                <button
                  onClick={onClose}
                  className="p-2 -mr-2 rounded-lg text-muted hover:text-primary hover:bg-sunken transition-colors touch-target"
                >
                  <X className="w-5 h-5" />
                </button>
              </div>

              {/* Document info */}
              <div className="p-4 bg-canvas rounded-xl mb-6">
                <p className="font-display font-medium text-primary line-clamp-2">
                  {shareState.docTitle}
                </p>
              </div>

              {/* Options */}
              <div className="space-y-3 mb-6">
                <p className="text-sm font-display font-medium text-secondary">
                  O que incluir no link?
                </p>

                {/* Position toggle */}
                {currentScrollPosition && (
                  <label className="flex items-center justify-between p-3 bg-canvas rounded-xl cursor-pointer">
                    <div className="flex items-center gap-3">
                      <div className="p-2 rounded-lg bg-sunken">
                        <MapPin className="w-4 h-4 text-brand" />
                      </div>
                      <div>
                        <p className="text-sm font-medium text-primary">
                          Minha posição atual
                        </p>
                        <p className="text-xs text-muted">{currentScrollPosition}</p>
                      </div>
                    </div>
                    <input
                      type="checkbox"
                      checked={includePosition}
                      onChange={(e) => setIncludePosition(e.target.checked)}
                      className="w-5 h-5 rounded border-border bg-sunken text-brand focus:ring-brand"
                    />
                  </label>
                )}

                {/* Highlights toggle */}
                {currentHighlights.length > 0 && (
                  <label className="flex items-center justify-between p-3 bg-canvas rounded-xl cursor-pointer">
                    <div className="flex items-center gap-3">
                      <div className="p-2 rounded-lg bg-sunken">
                        <Highlighter className="w-4 h-4 text-warning" />
                      </div>
                      <div>
                        <p className="text-sm font-medium text-primary">
                          Meus destaques
                        </p>
                        <p className="text-xs text-muted">{currentHighlights.length} trecho(s)</p>
                      </div>
                    </div>
                    <input
                      type="checkbox"
                      checked={includeHighlights}
                      onChange={(e) => setIncludeHighlights(e.target.checked)}
                      className="w-5 h-5 rounded border-border bg-sunken text-brand focus:ring-brand"
                    />
                  </label>
                )}

                {/* Note toggle */}
                <label className="flex items-center justify-between p-3 bg-canvas rounded-xl cursor-pointer">
                  <div className="flex items-center gap-3">
                    <div className="p-2 rounded-lg bg-sunken">
                      <MessageSquare className="w-4 h-4 text-info" />
                    </div>
                    <span className="text-sm font-medium text-primary">
                      Minha nota pessoal
                    </span>
                  </div>
                  <input
                    type="checkbox"
                    checked={includeNote}
                    onChange={(e) => setIncludeNote(e.target.checked)}
                    className="w-5 h-5 rounded border-border bg-sunken text-brand focus:ring-brand"
                  />
                </label>

                {/* Note input */}
                <AnimatePresence>
                  {includeNote && (
                    <motion.div
                      initial={{ height: 0, opacity: 0 }}
                      animate={{ height: "auto", opacity: 1 }}
                      exit={{ height: 0, opacity: 0 }}
                    >
                      <textarea
                        value={note}
                        onChange={(e) => setNote(e.target.value)}
                        placeholder="Adicione uma nota..."
                        className="w-full p-3 bg-canvas border border-border rounded-xl text-sm text-primary placeholder:text-muted focus:outline-none focus:border-brand resize-none"
                        rows={3}
                        maxLength={200}
                      />
                      <p className="text-xs text-muted text-right mt-1">
                        {note.length}/200
                      </p>
                    </motion.div>
                  )}
                </AnimatePresence>
              </div>

              {/* URL Preview */}
              <div className="mb-6">
                <p className="text-xs text-muted mb-2">Preview da URL:</p>
                <div className="p-3 bg-sunken rounded-xl">
                  <code className="text-xs text-secondary break-all font-mono">
                    {shareUrl.length > 80 ? shareUrl.slice(0, 80) + "..." : shareUrl}
                  </code>
                </div>
              </div>

              {/* Copy button */}
              <Button
                variant={copied ? "secondary" : "primary"}
                fullWidth
                onClick={handleCopy}
                leftIcon={copied ? <Check className="w-5 h-5" /> : <Copy className="w-5 h-5" />}
                className="mb-4"
              >
                {copied ? "Link copiado!" : "Copiar link"}
              </Button>

              {/* Native share button (mobile) */}
              {canNativeShare && (
                <Button
                  variant="secondary"
                  fullWidth
                  onClick={handleNativeShare}
                  isLoading={isSharing}
                  leftIcon={<Share2 className="w-5 h-5" />}
                  className="mb-6"
                >
                  Compartilhar...
                </Button>
              )}

              {/* Quick share options */}
              <div>
                <p className="text-xs text-muted mb-3">Ou compartilhe direto:</p>
                <div className="flex justify-center gap-4">
                  <button
                    onClick={handleWhatsAppShare}
                    className="flex flex-col items-center gap-2 p-3 rounded-xl hover:bg-sunken transition-colors touch-target"
                  >
                    <div className="w-12 h-12 rounded-full bg-[#25D366] flex items-center justify-center">
                      <svg className="w-6 h-6 text-white" fill="currentColor" viewBox="0 0 24 24">
                        <path d="M17.472 14.382c-.297-.149-1.758-.867-2.03-.967-.273-.099-.471-.148-.67.15-.197.297-.767.966-.94 1.164-.173.199-.347.223-.644.075-.297-.15-1.255-.463-2.39-1.475-.883-.788-1.48-1.761-1.653-2.059-.173-.297-.018-.458.13-.606.134-.133.298-.347.446-.52.149-.174.198-.298.298-.497.099-.198.05-.371-.025-.52-.075-.149-.669-1.612-.916-2.207-.242-.579-.487-.5-.669-.51-.173-.008-.371-.01-.57-.01-.198 0-.52.074-.792.372-.272.297-1.04 1.016-1.04 2.479 0 1.462 1.065 2.875 1.213 3.074.149.198 2.096 3.2 5.077 4.487.709.306 1.262.489 1.694.625.712.227 1.36.195 1.871.118.571-.085 1.758-.719 2.006-1.413.248-.694.248-1.289.173-1.413-.074-.124-.272-.198-.57-.347m-5.421 7.403h-.004a9.87 9.87 0 01-5.031-1.378l-.361-.214-3.741.982.998-3.648-.235-.374a9.86 9.86 0 01-1.51-5.26c.001-5.45 4.436-9.884 9.888-9.884 2.64 0 5.122 1.03 6.988 2.898a9.825 9.825 0 012.893 6.994c-.003 5.45-4.437 9.884-9.885 9.884m8.413-18.297A11.815 11.815 0 0012.05 0C5.495 0 .16 5.335.157 11.892c0 2.096.547 4.142 1.588 5.945L.057 24l6.305-1.654a11.882 11.882 0 005.683 1.448h.005c6.554 0 11.89-5.335 11.893-11.893a11.821 11.821 0 00-3.48-8.413z"/>
                      </svg>
                    </div>
                    <span className="text-xs text-secondary">WhatsApp</span>
                  </button>

                  <button
                    onClick={handleTelegramShare}
                    className="flex flex-col items-center gap-2 p-3 rounded-xl hover:bg-sunken transition-colors touch-target"
                  >
                    <div className="w-12 h-12 rounded-full bg-[#0088CC] flex items-center justify-center">
                      <svg className="w-6 h-6 text-white" fill="currentColor" viewBox="0 0 24 24">
                        <path d="M11.944 0A12 12 0 0 0 0 12a12 12 0 0 0 12 12 12 12 0 0 0 12-12A12 12 0 0 0 12 0a12 12 0 0 0-.056 0zm4.962 7.224c.1-.002.321.023.465.14a.506.506 0 0 1 .171.325c.016.093.036.306.02.472-.18 1.898-.962 6.502-1.36 8.627-.168.9-.499 1.201-.82 1.23-.696.065-1.225-.46-1.9-.902-1.056-.693-1.653-1.124-2.678-1.8-1.185-.78-.417-1.21.258-1.91.177-.184 3.247-2.977 3.307-3.23.007-.032.014-.15-.056-.212s-.174-.041-.249-.024c-.106.024-1.793 1.14-5.061 3.345-.48.33-.913.49-1.302.48-.428-.008-1.252-.241-1.865-.44-.752-.245-1.349-.374-1.297-.789.027-.216.325-.437.893-.663 3.498-1.524 5.83-2.529 6.998-3.014 3.332-1.386 4.025-1.627 4.476-1.635z"/>
                      </svg>
                    </div>
                    <span className="text-xs text-secondary">Telegram</span>
                  </button>

                  <button
                    onClick={handleEmailShare}
                    className="flex flex-col items-center gap-2 p-3 rounded-xl hover:bg-sunken transition-colors touch-target"
                  >
                    <div className="w-12 h-12 rounded-full bg-sunken flex items-center justify-center border border-border">
                      <svg className="w-6 h-6 text-secondary" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
                      </svg>
                    </div>
                    <span className="text-xs text-secondary">Email</span>
                  </button>
                </div>
              </div>
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
}
