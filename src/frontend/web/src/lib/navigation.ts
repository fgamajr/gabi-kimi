import type { NavigateFunction } from "react-router-dom";

export type DocumentTransitionOrigin =
  | "search-result"
  | "recent-document"
  | "document-graph"
  | "command-palette";

export function navigateToDocument(
  navigate: NavigateFunction,
  documentId: string,
  origin: DocumentTransitionOrigin
) {
  const to = `/document/${encodeURIComponent(documentId)}`;
  const state = {
    documentTransitionOrigin: origin,
    documentTransitionAt: Date.now(),
  };

  navigate(to, { state });
}
