"use client";

import * as React from "react";
import { motion } from "framer-motion";
import { cn, formatRelativeTime, truncate, getSectionColor } from "@/lib/utils";
import { Bell, Share2, Star, ChevronRight } from "lucide-react";
import type { Document } from "@/types";

// =============================================================================
// Document Card v4.1 — Clean Nubank Style
// Menos peso visual, mais espaçamento, mais ar
// =============================================================================

export interface DocumentCardProps {
  doc: Document;
  variant?: "default" | "compact" | "alert" | "featured";
  position?: number;
  totalInList?: number;
  isRead?: boolean;
  isFavorited?: boolean;
  onOpen?: (doc: Document, position: number) => void;
  onFavorite?: (doc: Document) => void;
  onAlert?: (doc: Document) => void;
  onShare?: (doc: Document) => void;
  className?: string;
}

const DocumentCard = React.forwardRef<HTMLDivElement, DocumentCardProps>(
  (
    {
      doc,
      variant = "default",
      position = 0,
      // eslint-disable-next-line @typescript-eslint/no-unused-vars
      totalInList: _totalInList,
      isRead = false,
      isFavorited = false,
      onOpen,
      onFavorite,
      onAlert,
      onShare,
      className,
    },
    ref
  ) => {
    const cardRef = React.useRef<HTMLDivElement>(null);

    React.useImperativeHandle(ref, () => cardRef.current!);

    const handleClick = () => {
      onOpen?.(doc, position);
    };

    // Format title
    const title = doc.identifica || `${doc.art_type} nº ${doc.document_number}`;
    const orgName = doc.issuing_organ || "Órgão não informado";
    const dateLabel = doc.publication_date
      ? formatRelativeTime(doc.publication_date)
      : "";

    // Compact variant
    if (variant === "compact") {
      return (
        <motion.div
          ref={cardRef}
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.2, delay: position * 0.04 }}
          onClick={handleClick}
          className={cn(
            "group flex items-center gap-4 p-4 rounded-2xl",
            "bg-raised/50 border border-border/50",
            "cursor-pointer",
            "transition-all duration-200",
            "hover:bg-raised hover:border-border",
            "active:scale-[0.99]",
            isRead && "opacity-60",
            className
          )}
        >
          {/* Section indicator - linha fina vertical */}
          <div
            className="w-0.5 h-10 rounded-full flex-shrink-0"
            style={{ backgroundColor: getSectionColor(doc.section) }}
          />
          
          {/* Content */}
          <div className="flex-1 min-w-0">
            <p className="text-sm font-display font-medium text-primary truncate">
              {title}
            </p>
            <p className="text-xs text-muted mt-0.5 truncate">
              {orgName} · {dateLabel}
            </p>
          </div>
          
          <ChevronRight className="w-5 h-5 text-muted opacity-0 group-hover:opacity-100 transition-opacity" />
        </motion.div>
      );
    }

    // Default variant - mais espaçamento, menos peso
    return (
      <motion.div
        ref={cardRef}
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.2, delay: position * 0.04 }}
        onClick={handleClick}
        className={cn(
          "group p-5 rounded-2xl",
          "bg-raised/30 border border-border/50",
          "cursor-pointer",
          "transition-all duration-200",
          "hover:bg-raised/60 hover:border-border",
          "hover:shadow-elevated",
          isRead && "opacity-50",
          className
        )}
        role="article"
      >
        {/* Header: Section badge + Date - layout mais leve */}
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2">
            {/* Badge mais sutil */}
            <span
              className="px-2 py-0.5 rounded-md text-2xs font-display font-semibold text-white"
              style={{ backgroundColor: getSectionColor(doc.section) }}
            >
              {doc.section === "e" ? "Extra" : `Seção ${doc.section}`}
            </span>
            <span className="text-xs text-muted">
              {doc.art_type}
            </span>
          </div>
          <span className="text-xs text-muted">{dateLabel}</span>
        </div>

        {/* Title - mais espaçamento */}
        <h3 className={cn(
          "font-display font-semibold text-base mb-2 leading-snug",
          isRead ? "text-secondary" : "text-primary"
        )}>
          {title}
        </h3>

        {/* Org - cor mais suave */}
        <p className="text-sm text-secondary mb-3">
          {orgName}
        </p>

        {/* Snippet ou Ementa - mais ar */}
        {doc.snippet ? (
          <p 
            className="text-sm text-muted line-clamp-2 mb-4 leading-relaxed"
            dangerouslySetInnerHTML={{ 
              __html: doc.snippet.replace(/<em>/g, '<span class="text-brand-light font-medium">').replace(/<\/em>/g, '</span>')
            }}
          />
        ) : doc.ementa ? (
          <p className="text-sm text-muted line-clamp-2 mb-4 leading-relaxed italic">
            {truncate(doc.ementa, 120)}
          </p>
        ) : null}

        {/* Footer: Actions - mais espaçado e sutil */}
        <div className="flex items-center justify-between pt-3 border-t border-border/30">
          <span className="text-xs text-muted">
            {doc.body_word_count ? `~${Math.round(doc.body_word_count / 200)} min` : ""}
          </span>
          
          <div className="flex items-center gap-1">
            {/* Favorite - mais sutil */}
            <button
              onClick={(e) => {
                e.stopPropagation();
                onFavorite?.(doc);
              }}
              className={cn(
                "p-2 rounded-xl transition-all duration-150",
                isFavorited 
                  ? "text-warning bg-warning/10" 
                  : "text-muted hover:text-primary hover:bg-sunken/50"
              )}
            >
              <Star className={cn("w-4 h-4", isFavorited && "fill-current")} />
            </button>
            
            {/* Alert */}
            <button
              onClick={(e) => {
                e.stopPropagation();
                onAlert?.(doc);
              }}
              className="p-2 rounded-xl text-muted hover:text-brand hover:bg-brand/10 transition-all duration-150"
            >
              <Bell className="w-4 h-4" />
            </button>
            
            {/* Share */}
            <button
              onClick={(e) => {
                e.stopPropagation();
                onShare?.(doc);
              }}
              className="p-2 rounded-xl text-muted hover:text-primary hover:bg-sunken/50 transition-all duration-150"
            >
              <Share2 className="w-4 h-4" />
            </button>
          </div>
        </div>
      </motion.div>
    );
  }
);

DocumentCard.displayName = "DocumentCard";

export { DocumentCard };
