"use client";

import * as React from "react";
import { motion, AnimatePresence } from "framer-motion";

import { cn, formatDate } from "@/lib/utils";
import { 
  X, 
  FileText, 
  Globe, 
  AlignLeft, 
  Code,
  Download,
  Check,
  AlertCircle
} from "lucide-react";

// =============================================================================
// Download Sheet — Download-Complete v4.0
// =============================================================================

export type DownloadFormat = "pdf" | "html" | "txt" | "json";

interface DownloadOption {
  format: DownloadFormat;
  label: string;
  description: string;
  icon: React.ReactNode;
  extension: string;
  estimatedSize?: number;
}

interface DownloadSheetProps {
  isOpen: boolean;
  docId: string;
  docTitle: string;
  docDate?: string;
  docSection?: string;
  docType?: string;
  docNumber?: string;
  pdfUrl?: string;
  onClose: () => void;
  isOffline?: boolean;
}

export function DownloadSheet({
  isOpen,
  docId,
  docTitle,
  docDate,
  docSection,
  docType,
  docNumber,
  pdfUrl,
  onClose,
  isOffline = false,
}: DownloadSheetProps) {
  const [downloading, setDownloading] = React.useState<DownloadFormat | null>(null);
  const [completed, setCompleted] = React.useState<DownloadFormat | null>(null);
  const [error, setError] = React.useState<string | null>(null);

  const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

  // Build filename
  const buildFilename = (format: DownloadFormat): string => {
    const date = docDate ? formatDate(docDate).replace(/\//g, "-") : "unknown";
    const section = docSection || "S";
    const type = docType?.replace(/\s+/g, "-") || "Documento";
    const number = docNumber || docId.slice(0, 8);
    
    return `DOU-${date}-${section}-${type}-${number}.${format === "json" ? "json" : format}`;
  };

  // Download options
  const options: DownloadOption[] = [
    {
      format: "pdf",
      label: "PDF Original",
      description: "Do arquivo oficial DOU · Formato exato da publicação",
      icon: <FileText className="w-6 h-6 text-error" />,
      extension: "pdf",
      estimatedSize: 847000, // bytes
    },
    {
      format: "html",
      label: "HTML Limpo",
      description: "Leitura otimizada · Abre em qualquer navegador",
      icon: <Globe className="w-6 h-6 text-info" />,
      extension: "html",
      estimatedSize: 42000,
    },
    {
      format: "txt",
      label: "Texto Puro",
      description: "Só o conteúdo · Ideal para análise e pesquisa",
      icon: <AlignLeft className="w-6 h-6 text-secondary" />,
      extension: "txt",
      estimatedSize: 18000,
    },
    {
      format: "json",
      label: "JSON com Metadados",
      description: "Para desenvolvedores e integrações",
      icon: <Code className="w-6 h-6 text-warning" />,
      extension: "json",
      estimatedSize: 25000,
    },
  ];

  // Format file size
  const formatSize = (bytes?: number): string => {
    if (!bytes) return "";
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  };

  // Handle download
  const handleDownload = async (format: DownloadFormat) => {
    if (isOffline && format === "pdf") {
      setError("Você está offline. O PDF estará disponível quando reconectar.");
      setTimeout(() => setError(null), 5000);
      return;
    }

    setDownloading(format);
    setError(null);

    try {
      let blob: Blob;
      const filename = buildFilename(format);

      switch (format) {
        case "pdf":
          if (pdfUrl) {
            const response = await fetch(pdfUrl);
            blob = await response.blob();
          } else {
            throw new Error("PDF não disponível");
          }
          break;

        case "html":
          // Generate clean HTML
          const htmlContent = await generateCleanHTML(docId, docTitle);
          blob = new Blob([htmlContent], { type: "text/html;charset=utf-8" });
          break;

        case "txt":
          // Fetch and extract text
          const txtContent = await fetchDocumentText(docId);
          blob = new Blob([txtContent], { type: "text/plain;charset=utf-8" });
          break;

        case "json":
          // Fetch full document as JSON
          const response = await fetch(`${API_BASE}/api/document/${docId}`);
          const data = await response.json();
          blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
          break;

        default:
          throw new Error("Formato não suportado");
      }

      // Trigger download
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      window.URL.revokeObjectURL(url);

      setCompleted(format);
      setTimeout(() => {
        setCompleted(null);
        onClose();
      }, 2000);

    } catch {
      setError("Não conseguimos baixar o arquivo. Tenta de novo?");
      setTimeout(() => setError(null), 5000);
    } finally {
      setDownloading(null);
    }
  };

  // Generate clean HTML
  const generateCleanHTML = async (docId: string, title: string): Promise<string> => {
    const response = await fetch(`${API_BASE}/api/document/${docId}`);
    const doc = await response.json();
    
    return `<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>${title}</title>
  <style>
    body { font-family: Georgia, serif; line-height: 1.75; max-width: 680px; margin: 0 auto; padding: 2rem; color: #333; }
    h1 { font-family: system-ui, sans-serif; font-size: 1.5rem; margin-bottom: 0.5rem; }
    .meta { color: #666; font-size: 0.875rem; margin-bottom: 2rem; padding-bottom: 1rem; border-bottom: 1px solid #ddd; }
    .ementa { font-style: italic; color: #555; margin-bottom: 2rem; padding: 1rem; background: #f5f5f5; border-left: 3px solid #00E5A0; }
    p { margin-bottom: 1rem; }
  </style>
</head>
<body>
  <h1>${title}</h1>
  <div class="meta">
    ${doc.issuing_organ || ""} · ${doc.publication_date ? formatDate(doc.publication_date) : ""}
  </div>
  ${doc.ementa ? `<div class="ementa">${doc.ementa}</div>` : ""}
  ${doc.body_html || doc.body_plain?.replace(/\n/g, "</p><p>") || ""}
</body>
</html>`;
  };

  // Fetch document text
  const fetchDocumentText = async (docId: string): Promise<string> => {
    const response = await fetch(`${API_BASE}/api/document/${docId}`);
    const doc = await response.json();
    
    return `${doc.identifica || `${doc.art_type} nº ${doc.document_number}`}

Órgão: ${doc.issuing_organ || "Não informado"}
Publicação: ${doc.publication_date ? formatDate(doc.publication_date) : "Não informada"}
DOU Edição: ${doc.edition_number || "Não informada"}

${doc.ementa ? `EMENTA:\n${doc.ementa}\n` : ""}
${doc.body_plain || "Conteúdo não disponível em formato texto."}

---
Baixado de DOU Reimaginado
${window.location.origin}/doc/${docId}`;
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
            className="fixed bottom-0 left-0 right-0 z-50 bg-raised border-t border-border rounded-t-3xl"
          >
            {/* Drag handle */}
            <div className="flex justify-center pt-3 pb-2">
              <div className="w-10 h-1 rounded-full bg-border" />
            </div>

            <div className="px-4 pb-8 max-h-[80vh] overflow-y-auto">
              {/* Header */}
              <div className="flex items-center justify-between mb-6">
                <h2 className="font-display font-bold text-xl text-primary">
                  Salvar documento
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
                  {docTitle}
                </p>
                <p className="text-xs text-muted mt-1">
                  {docType} · {docDate && formatDate(docDate)}
                </p>
              </div>

              {/* Error message */}
              <AnimatePresence>
                {error && (
                  <motion.div
                    initial={{ height: 0, opacity: 0 }}
                    animate={{ height: "auto", opacity: 1 }}
                    exit={{ height: 0, opacity: 0 }}
                    className="mb-4 p-3 bg-error/10 border border-error/20 rounded-xl flex items-center gap-2"
                  >
                    <AlertCircle className="w-4 h-4 text-error flex-shrink-0" />
                    <p className="text-sm text-error">{error}</p>
                  </motion.div>
                )}
              </AnimatePresence>

              {/* Offline warning */}
              {isOffline && (
                <div className="mb-4 p-3 bg-warning/10 border border-warning/20 rounded-xl flex items-center gap-2">
                  <AlertCircle className="w-4 h-4 text-warning flex-shrink-0" />
                  <p className="text-sm text-warning">
                    Você está offline. Alguns formatos podem não estar disponíveis.
                  </p>
                </div>
              )}

              {/* Download options */}
              <div className="space-y-3">
                {options.map((option) => (
                  <button
                    key={option.format}
                    onClick={() => handleDownload(option.format)}
                    disabled={downloading !== null}
                    className={cn(
                      "w-full p-4 bg-canvas rounded-xl border border-border",
                      "flex items-center gap-4",
                      "hover:border-border-strong transition-all",
                      "disabled:opacity-50 disabled:cursor-not-allowed",
                      completed === option.format && "border-success bg-success/5"
                    )}
                  >
                    <div className="p-3 rounded-xl bg-sunken">
                      {option.icon}
                    </div>
                    
                    <div className="flex-1 text-left">
                      <div className="flex items-center gap-2">
                        <p className="font-display font-semibold text-primary">
                          {option.label}
                        </p>
                        {option.estimatedSize && (
                          <span className="text-xs text-muted">
                            {formatSize(option.estimatedSize)}
                          </span>
                        )}
                      </div>
                      <p className="text-xs text-muted mt-0.5">
                        {option.description}
                      </p>
                    </div>

                    <div className="flex-shrink-0">
                      {downloading === option.format ? (
                        <div className="w-5 h-5 border-2 border-brand border-t-transparent rounded-full animate-spin" />
                      ) : completed === option.format ? (
                        <Check className="w-5 h-5 text-success" />
                      ) : (
                        <Download className="w-5 h-5 text-muted" />
                      )}
                    </div>
                  </button>
                ))}
              </div>

              {/* Filename preview */}
              <div className="mt-6 p-3 bg-sunken rounded-xl">
                <p className="text-xs text-muted mb-1">Nome do arquivo:</p>
                <code className="text-xs text-secondary font-mono break-all">
                  {buildFilename("pdf")}
                </code>
              </div>
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
}
