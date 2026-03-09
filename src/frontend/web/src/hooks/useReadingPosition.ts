import { useEffect, useCallback, useRef, useState } from "react";
import { getScrollBehavior } from "@/lib/motion";

interface ReadingPosition {
  scrollPercent: number;
  nearestSectionId?: string;
  timestamp: number;
}

const STORAGE_PREFIX = 'gabi-reading-pos-';
const EXPIRY_MS = 7 * 24 * 60 * 60 * 1000; // 7 days
const DEBOUNCE_MS = 1000;

export function getContentScrollMetrics(el: HTMLElement | null) {
  const contentTop = el ? el.getBoundingClientRect().top + window.scrollY : 0;
  const contentHeight = el?.scrollHeight || 0;
  const scrollableHeight = Math.max(contentHeight - window.innerHeight, 1);
  return { contentTop, scrollableHeight };
}

function getStoredPosition(docId: string): ReadingPosition | null {
  try {
    const raw = localStorage.getItem(`${STORAGE_PREFIX}${docId}`);
    if (!raw) return null;
    const pos: ReadingPosition = JSON.parse(raw);
    if (Date.now() - pos.timestamp > EXPIRY_MS) {
      localStorage.removeItem(`${STORAGE_PREFIX}${docId}`);
      return null;
    }
    return pos;
  } catch {
    return null;
  }
}

function savePosition(docId: string, pos: ReadingPosition) {
  try {
    localStorage.setItem(`${STORAGE_PREFIX}${docId}`, JSON.stringify(pos));
  } catch { /* quota exceeded, ignore */ }
}

export function clearReadingPosition(docId: string) {
  localStorage.removeItem(`${STORAGE_PREFIX}${docId}`);
}

export function useReadingPosition(
  docId: string | undefined,
  contentRef: React.RefObject<HTMLElement>,
  sectionIds?: string[]
) {
  const [savedPosition, setSavedPosition] = useState<ReadingPosition | null>(null);
  const [scrollPercent, setScrollPercent] = useState(0);
  const timerRef = useRef<ReturnType<typeof setTimeout>>();

  // Load saved position on mount
  useEffect(() => {
    if (!docId) return;
    const pos = getStoredPosition(docId);
    setSavedPosition(pos);
  }, [docId]);

  // Track scroll and save position
  useEffect(() => {
    if (!docId) return;

    const handleScroll = () => {
      const { contentTop, scrollableHeight } = getContentScrollMetrics(contentRef.current);
      const relativeOffset = Math.max(0, window.scrollY - contentTop);
      const percent = Math.min(1, Math.max(0, relativeOffset / scrollableHeight));
      setScrollPercent(Math.min(1, Math.max(0, percent)));

      if (timerRef.current) clearTimeout(timerRef.current);
      timerRef.current = setTimeout(() => {
        // Find nearest visible section
        let nearestSectionId: string | undefined;
        if (sectionIds?.length && contentRef.current) {
          for (const id of sectionIds) {
            const el = document.getElementById(id);
            if (el && el.getBoundingClientRect().top <= window.innerHeight * 0.5) {
              nearestSectionId = id;
            }
          }
        }

        savePosition(docId, {
          scrollPercent: percent,
          nearestSectionId,
          timestamp: Date.now(),
        });
      }, DEBOUNCE_MS);
    };

    window.addEventListener('scroll', handleScroll, { passive: true });
    return () => {
      window.removeEventListener('scroll', handleScroll);
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, [docId, sectionIds, contentRef]);

  const scrollToSaved = useCallback(() => {
    if (!savedPosition) return;
    if (savedPosition.nearestSectionId) {
      const el = document.getElementById(savedPosition.nearestSectionId);
      if (el) {
        el.scrollIntoView({ behavior: getScrollBehavior(), block: "start" });
        return;
      }
    }
    const { contentTop, scrollableHeight } = getContentScrollMetrics(contentRef.current);
    window.scrollTo({
      top: contentTop + scrollableHeight * savedPosition.scrollPercent,
      behavior: getScrollBehavior(),
    });
  }, [contentRef, savedPosition]);

  return { savedPosition, scrollPercent, scrollToSaved };
}
