"use client";

import * as React from "react";
import { Suspense } from "react";
import { HomeContent } from "@/components/home/home-content";
import { SkeletonCardList } from "@/components/ui/skeleton";

// =============================================================================
// Home Page — DOU Reimagined v4.0
// =============================================================================

export default function HomePage() {
  return (
    <Suspense fallback={
      <div className="min-h-screen bg-canvas pb-24">
        <header className="h-14 bg-canvas/95 border-b border-border" />
        <main className="max-w-lg mx-auto px-4 pt-4">
          <div className="h-14 bg-raised rounded-xl mb-6 shimmer" />
          <SkeletonCardList count={3} />
        </main>
      </div>
    }>
      <HomeContent />
    </Suspense>
  );
}
