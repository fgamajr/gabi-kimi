"use client";

import { cn } from "@/lib/utils";

// =============================================================================
// Skeleton Component — Design System v4.0
// =============================================================================

interface SkeletonProps extends React.HTMLAttributes<HTMLDivElement> {
  variant?: "default" | "card" | "text" | "circle" | "document";
  lines?: number;
}

function Skeleton({
  className,
  variant = "default",
  lines = 3,
  ...props
}: SkeletonProps) {
  // Text lines skeleton
  if (variant === "text") {
    return (
      <div className={cn("space-y-2", className)} {...props}>
        {Array.from({ length: lines }).map((_, i) => (
          <div
            key={i}
            className={cn(
              "h-4 rounded",
              "bg-sunken shimmer",
              i === lines - 1 && "w-3/4"
            )}
          />
        ))}
      </div>
    );
  }

  // Circle/Avatar skeleton
  if (variant === "circle") {
    return (
      <div
        className={cn(
          "rounded-full bg-sunken shimmer",
          className
        )}
        {...props}
      />
    );
  }

  // Document card skeleton
  if (variant === "card") {
    return (
      <div
        className={cn(
          "p-4 rounded-xl bg-raised border border-border",
          "space-y-3",
          className
        )}
        {...props}
      >
        {/* Header: badge + date */}
        <div className="flex items-center justify-between">
          <div className="h-5 w-16 rounded-full bg-sunken shimmer" />
          <div className="h-4 w-20 rounded bg-sunken shimmer" />
        </div>
        
        {/* Title */}
        <div className="space-y-2">
          <div className="h-5 w-3/4 rounded bg-sunken shimmer" />
          <div className="h-4 w-1/2 rounded bg-sunken shimmer" />
        </div>
        
        {/* Snippet lines */}
        <div className="space-y-1.5 pt-1">
          <div className="h-3.5 w-full rounded bg-sunken shimmer" />
          <div className="h-3.5 w-5/6 rounded bg-sunken shimmer" />
        </div>
        
        {/* Footer: org + actions */}
        <div className="flex items-center justify-between pt-1">
          <div className="h-4 w-32 rounded bg-sunken shimmer" />
          <div className="flex gap-2">
            <div className="h-8 w-8 rounded-lg bg-sunken shimmer" />
            <div className="h-8 w-8 rounded-lg bg-sunken shimmer" />
          </div>
        </div>
      </div>
    );
  }

  // Document viewer skeleton
  if (variant === "document") {
    return (
      <div className={cn("space-y-4", className)} {...props}>
        {/* Header */}
        <div className="flex items-center justify-between">
          <div className="h-4 w-20 rounded bg-sunken shimmer" />
          <div className="h-4 w-16 rounded bg-sunken shimmer" />
        </div>
        
        {/* Title */}
        <div className="space-y-2">
          <div className="h-8 w-3/4 rounded bg-sunken shimmer" />
          <div className="h-6 w-1/2 rounded bg-sunken shimmer" />
        </div>
        
        {/* Metadata */}
        <div className="h-4 w-48 rounded bg-sunken shimmer" />
        
        {/* Divider */}
        <div className="h-px bg-border" />
        
        {/* Body */}
        <Skeleton variant="text" lines={12} />
      </div>
    );
  }

  // Default skeleton
  return (
    <div
      className={cn(
        "rounded bg-sunken shimmer",
        className
      )}
      {...props}
    />
  );
}

// Card skeleton list for loading states
function SkeletonCardList({ count = 3 }: { count?: number }) {
  return (
    <div className="space-y-3">
      {Array.from({ length: count }).map((_, i) => (
        <Skeleton key={i} variant="card" />
      ))}
    </div>
  );
}

export { Skeleton, SkeletonCardList };
