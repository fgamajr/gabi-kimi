import { useEffect } from "react";
import { toast } from "sonner";
import { getScrollBehavior } from "@/lib/motion";
import { getContentScrollMetrics } from "./useReadingPosition";

/**
 * Parse #pos= fragment from URL and scroll to position.
 * Supports: #pos=art-12 (anchor) or #pos=0.34 (percentage)
 */
export function useDeepLink(
  contentRef: React.RefObject<HTMLElement>,
  ready: boolean // true when content is rendered and sections are parsed
) {
  useEffect(() => {
    if (!ready || !contentRef.current) return;

    const hash = window.location.hash;
    if (!hash.startsWith('#pos=')) return;

    const pos = hash.slice(5); // remove '#pos='
    const numericValue = parseFloat(pos);

    // Delay to ensure DOM is fully laid out
    const timer = setTimeout(() => {
      if (!isNaN(numericValue) && numericValue >= 0 && numericValue <= 1) {
        const { contentTop, scrollableHeight } = getContentScrollMetrics(contentRef.current);
        window.scrollTo({ top: contentTop + scrollableHeight * numericValue, behavior: getScrollBehavior() });
      } else {
        // Anchor-based
        const el = document.getElementById(pos);
        if (el) {
          el.scrollIntoView({ behavior: getScrollBehavior(), block: "start" });
          el.classList.add('deep-link-highlight');
          setTimeout(() => el.classList.remove('deep-link-highlight'), 2000);
        } else {
          toast('Posição compartilhada não encontrada — exibindo do início', {
            duration: 4000,
          });
        }
      }
    }, 300);

    return () => clearTimeout(timer);
  }, [ready, contentRef]);
}

/**
 * Generate a shareable URL with the current reading position.
 */
export function generateShareUrl(
  sectionId?: string,
  scrollPercent?: number
): string {
  const base = `${window.location.origin}${window.location.pathname}`;
  if (sectionId) return `${base}#pos=${sectionId}`;
  if (scrollPercent != null) return `${base}#pos=${scrollPercent.toFixed(2)}`;
  return base;
}
