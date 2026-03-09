import { useCallback, useEffect, useMemo, useState, type RefObject } from "react";
import { getScrollBehavior } from "@/lib/motion";
import { parseSections, type Section } from "@/lib/sectionParser";

interface DocumentSectionSource {
  id: string;
}

export function useDocumentSectionNavigation(
  document: DocumentSectionSource | null,
  contentRef: RefObject<HTMLElement>
) {
  const [sections, setSections] = useState<Section[]>([]);
  const [sectionsReady, setSectionsReady] = useState(false);
  const [activeSectionId, setActiveSectionId] = useState<string | null>(null);

  useEffect(() => {
    if (!document || !contentRef.current) {
      setSections([]);
      setSectionsReady(false);
      setActiveSectionId(null);
      return;
    }

    setSectionsReady(false);

    const frame = window.requestAnimationFrame(() => {
      if (!contentRef.current) return;

      const parsedSections = parseSections(contentRef.current);
      setSections(parsedSections);
      setActiveSectionId(parsedSections[0]?.id || null);
      setSectionsReady(true);
    });

    return () => window.cancelAnimationFrame(frame);
  }, [contentRef, document]);

  useEffect(() => {
    if (!sections.length) {
      setActiveSectionId(null);
      return;
    }

    const observer = new IntersectionObserver(
      (entries) => {
        const visibleSections = entries
          .filter((entry) => entry.isIntersecting)
          .sort((left, right) => left.boundingClientRect.top - right.boundingClientRect.top);

        if (visibleSections[0]?.target?.id) {
          setActiveSectionId(visibleSections[0].target.id);
        }
      },
      { rootMargin: "-20% 0px -65% 0px", threshold: [0.1, 0.4, 0.8] }
    );

    sections.forEach((section) => observer.observe(section.element));
    return () => observer.disconnect();
  }, [sections]);

  const activeSectionLabel = useMemo(
    () => sections.find((section) => section.id === activeSectionId)?.label,
    [activeSectionId, sections]
  );

  const scrollToSection = useCallback((section: Section) => {
    section.element.scrollIntoView({ behavior: getScrollBehavior(), block: "start" });
  }, []);

  return {
    activeSectionId,
    activeSectionLabel,
    scrollToSection,
    sections,
    sectionsReady,
  };
}
