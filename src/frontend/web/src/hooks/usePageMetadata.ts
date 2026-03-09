import { useEffect } from "react";
import { buildPageTitle, DEFAULT_APP_DESCRIPTION } from "@/lib/intl";

interface PageMetadataOptions {
  description?: string;
}

export function usePageMetadata(pageTitle: string, options: PageMetadataOptions = {}) {
  const description = options.description || DEFAULT_APP_DESCRIPTION;

  useEffect(() => {
    document.title = buildPageTitle(pageTitle);

    const descriptionMeta = document.querySelector('meta[name="description"]');
    const previousDescription = descriptionMeta?.getAttribute("content") ?? null;
    descriptionMeta?.setAttribute("content", description);

    return () => {
      if (previousDescription) {
        descriptionMeta?.setAttribute("content", previousDescription);
      }
    };
  }, [description, pageTitle]);
}
