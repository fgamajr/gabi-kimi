"use client";

import * as React from "react";
import { cn, getSectionColor, getSectionName } from "@/lib/utils";

// =============================================================================
// Badge Component — Design System v4.0
// =============================================================================

export interface BadgeProps extends React.HTMLAttributes<HTMLSpanElement> {
  variant?: "default" | "section" | "status" | "count" | "new";
  section?: 1 | 2 | 3 | "e" | string;
  status?: "vigente" | "revogado" | "retificado" | "novo";
  size?: "sm" | "md";
}

const Badge = React.forwardRef<HTMLSpanElement, BadgeProps>(
  (
    { className, variant = "default", section, status, size = "sm", children, ...props },
    ref
  ) => {
    const baseStyles = cn(
      "inline-flex items-center justify-center",
      "font-display font-semibold tracking-tight",
      "rounded-full no-select",
      size === "sm" && "px-2 py-0.5 text-2xs h-5",
      size === "md" && "px-2.5 py-1 text-xs h-6"
    );

    // Section badge (colored by DOU section)
    if (variant === "section" && section !== undefined) {
      const color = getSectionColor(section);
      return (
        <span
          ref={ref}
          className={cn(
            baseStyles,
            "text-white",
            className
          )}
          style={{ backgroundColor: color }}
          {...props}
        >
          {getSectionName(section)}
        </span>
      );
    }

    // Status badge
    if (variant === "status" && status) {
      const statusStyles = {
        vigente: "bg-success/15 text-success border border-success/20",
        revogado: "bg-error/15 text-error border border-error/20",
        retificado: "bg-warning/15 text-warning border border-warning/20",
        novo: "bg-brand/15 text-brand border border-brand/20",
      };
      
      const statusLabels = {
        vigente: "Vigente",
        revogado: "Revogado",
        retificado: "Retificado",
        novo: "Novo",
      };

      return (
        <span
          ref={ref}
          className={cn(baseStyles, statusStyles[status], className)}
          {...props}
        >
          {children || statusLabels[status]}
        </span>
      );
    }

    // Count badge (for filter chips)
    if (variant === "count") {
      return (
        <span
          ref={ref}
          className={cn(
            "ml-1.5 px-1.5 py-0 text-2xs font-mono rounded-md",
            "bg-sunken text-muted",
            className
          )}
          {...props}
        >
          {children}
        </span>
      );
    }

    // "New" indicator
    if (variant === "new") {
      return (
        <span
          ref={ref}
          className={cn(
            "relative flex h-2 w-2",
            className
          )}
          {...props}
        >
          <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-error opacity-75" />
          <span className="relative inline-flex rounded-full h-2 w-2 bg-error" />
        </span>
      );
    }

    // Default badge
    return (
      <span
        ref={ref}
        className={cn(
          baseStyles,
          "bg-sunken text-secondary border border-border",
          className
        )}
        {...props}
      >
        {children}
      </span>
    );
  }
);

Badge.displayName = "Badge";

export { Badge };
