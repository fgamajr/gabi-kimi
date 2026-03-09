import type { NavigateFunction } from "react-router-dom";

export type DocumentTransitionOrigin =
  | "search-result"
  | "recent-document"
  | "document-graph"
  | "command-palette"
  | "chat-rag";

export interface DocumentNavigationState {
  documentTransitionAt: number;
  documentTransitionOrigin: DocumentTransitionOrigin;
}

const DOCUMENT_TRANSITION_ORIGINS = new Set<DocumentTransitionOrigin>([
  "search-result",
  "recent-document",
  "document-graph",
  "command-palette",
  "chat-rag",
]);

export function createDocumentNavigationState(origin: DocumentTransitionOrigin): DocumentNavigationState {
  return {
    documentTransitionOrigin: origin,
    documentTransitionAt: Date.now(),
  };
}

export function getDocumentNavigationState(state: unknown): DocumentNavigationState | null {
  if (!state || typeof state !== "object") return null;

  const maybeState = state as Partial<DocumentNavigationState>;
  if (!maybeState.documentTransitionOrigin || !DOCUMENT_TRANSITION_ORIGINS.has(maybeState.documentTransitionOrigin)) {
    return null;
  }

  return {
    documentTransitionOrigin: maybeState.documentTransitionOrigin,
    documentTransitionAt:
      typeof maybeState.documentTransitionAt === "number" ? maybeState.documentTransitionAt : 0,
  };
}

export function navigateToDocument(
  navigate: NavigateFunction,
  documentId: string,
  origin: DocumentTransitionOrigin
) {
  const to = `/document/${encodeURIComponent(documentId)}`;
  const state = createDocumentNavigationState(origin);

  navigate(to, { state });
}
