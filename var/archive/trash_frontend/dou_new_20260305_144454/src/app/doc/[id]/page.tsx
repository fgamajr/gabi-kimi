import { Suspense } from "react";
import { DocContent } from "./doc-content";
import { Skeleton } from "@/components/ui/skeleton";

// =============================================================================
// Document Page — Share-as-State + Deep Linking v4.0
// =============================================================================

// Generate static params for build (required for output: export)
export function generateStaticParams() {
  return [{ id: "placeholder" }];
}

interface DocPageProps {
  params: { id: string };
}

export default function DocumentPage({ params }: DocPageProps) {
  return (
    <Suspense fallback={
      <div className="fixed inset-0 bg-canvas flex items-center justify-center">
        <Skeleton variant="document" className="w-full max-w-2xl mx-4" />
      </div>
    }>
      <DocContent docId={params.id} />
    </Suspense>
  );
}
