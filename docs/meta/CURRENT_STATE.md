# Current State

Last verified: 2026-03-06

This document describes the current shipped state of the GABI DOU frontend and related product capabilities. It is intentionally grounded in code that exists in the repository now, not aspirational roadmap items.

## Frontend Stack

- React 18 + TypeScript + Vite
- Tailwind CSS + shadcn/ui primitives
- TanStack Query at app root
- Local state still used in most pages for page-level fetching and UI state

## Routing and Layout

Current routes are defined in [App.tsx](/home/parallels/dev/gabi-kimi/src/frontend/web/src/App.tsx).

Implemented:
- Shared route shell via [AppShell.tsx](/home/parallels/dev/gabi-kimi/src/frontend/web/src/components/AppShell.tsx)
- Desktop left rail with Home and Search
- Mobile bottom navigation with Home and Search
- Document routes stay inside the shell on desktop and hide the mobile nav

Not implemented:
- Multi-section enterprise navigation
- Separate analytics/dashboard route
- Collections/favorites/config screens

## Home

Current implementation: [HomePage.tsx](/home/parallels/dev/gabi-kimi/src/frontend/web/src/pages/HomePage.tsx)

Implemented:
- Operational dashboard-style home
- Search bar with rotating placeholder
- Publications / period / status cards
- Popular search chips in horizontal scroll
- Recent documents from localStorage
- Featured document card

Not implemented:
- Time-series analytics widgets
- Sparkline cards
- Live operational telemetry

## Search

Current implementation: [SearchPage.tsx](/home/parallels/dev/gabi-kimi/src/frontend/web/src/pages/SearchPage.tsx)

Implemented:
- Search bar with autocomplete and recent searches
- Structured legal filters:
  - section
  - act type
  - issuing organ
  - date range
- Query interpretation feedback from backend:
  - `interpreted_query`
  - `inferred_filters`
  - `applied_filters`
- Active filter chips
- Pagination

Not implemented:
- Boolean/power-user syntax UI
- Saved searches
- Faceted exploration beyond current filters
- Command-palette-first search flow across the whole app

## Command Palette

Implemented:
- Global `Cmd/Ctrl+K` command palette in [CommandPalette.tsx](/home/parallels/dev/gabi-kimi/src/frontend/web/src/components/CommandPalette.tsx)
- Quick navigation to Home / Search
- Recent searches
- Recent documents
- Inline top results from search API

This is a lightweight navigation/search palette, not yet a full workspace command system.

## Document Reader

Current implementation: [DocumentPage.tsx](/home/parallels/dev/gabi-kimi/src/frontend/web/src/pages/DocumentPage.tsx)

Implemented:
- Sticky header
- Reading progress bar
- Section parsing + TOC
- Saved reading position + resume prompt
- Deep-link restore
- Share current position
- Copy formal reference
- Client-side PDF export fallback + print fallback
- Mobile actions bar
- Secure HTML rendering and image fallback path

## Validity / Version Awareness

Implemented:
- Frontend API types expose:
  - `normative_refs`
  - `procedure_refs`
- Reader shows:
  - `Situação normativa`
  - compact normative timeline
  - procedure badges

Important limitation:
- This is heuristic product guidance, not authoritative legal consolidation
- The current UI intentionally uses cautious wording and should not be treated as a definitive vigência engine

## Relationship Exploration

Implemented:
- First-step relationship view in [DocumentGraph.tsx](/home/parallels/dev/gabi-kimi/src/frontend/web/src/components/DocumentGraph.tsx)
- Uses real `normative_refs` and `procedure_refs`
- Supports navigation to related searches/documents

Not implemented:
- True graph visualization
- Multi-hop exploration
- Canonical amendment chains
- Timeline-of-validity engine

## Images and Media

Implemented:
- Media metadata from backend
- Blob/local media serving
- Image fallback behavior in the reader

Not implemented:
- Advanced media gallery treatment
- Reconstruction of original publication layout fidelity

## What Is Not Shipped

The following are not currently part of the real frontend, even if discussed in planning conversations:

- Time-series dashboard from concept HTML
- Publication volume / organ activity / heatmap charts
- Full Palantir-style graph exploration
- Automated amendment detection engine
- Canonical PDF generation from authoritative source
- Offline-first reading mode

## Recommended Next Steps

Highest product-value gaps after the current state:

1. Strengthen legal validity/version modeling beyond heuristics
2. Expand relationship exploration from list/tree to real graph workflows
3. Add analytics/time-series views backed by real API endpoints
4. Deepen command palette into a primary interaction surface
