# Coding Conventions

**Analysis Date:** 2026-03-08

## Naming Patterns

**Files (Frontend):**
- React components: PascalCase — `ResultCard.tsx`, `AppShell.tsx`, `DocumentRenderer.tsx`
- Pages: PascalCase with `Page` suffix — `SearchPage.tsx`, `HomePage.tsx`, `AnalyticsPage.tsx`
- Hooks: camelCase with `use` prefix — `useReadingPosition.ts`, `useDeepLink.ts`, `use-mobile.tsx`
- Utility modules: camelCase — `api.ts`, `utils.ts`, `sectionParser.ts`, `pdfExport.ts`
- UI primitives (shadcn/ui): kebab-case — `alert-dialog.tsx`, `scroll-area.tsx`, `toggle-group.tsx`

**Files (Backend):**
- Python modules: snake_case — `xml_parser.py`, `bulk_pipeline.py`, `web_server.py`
- Test files: `test_` prefix — `test_bulk_pipeline.py`, `test_commitment.py`

**Functions (Frontend):**
- camelCase for all functions — `fetchJSON()`, `normalizeSection()`, `buildDouUrl()`
- React components as arrow functions assigned to const — `const ResultCard: React.FC<Props> = ({ ... }) => { ... }`
- Event handlers: inline or named with descriptive prefix — `onClick={() => ...}`, `onKeyDown={(e) => ...}`

**Functions (Backend):**
- snake_case for public functions — `normalize_pub_date()`, `article_to_ingest_record()`, `build_zip_url()`
- Leading underscore for internal/private helpers — `_norm()`, `_sha()`, `_canonicalize_content()`, `_nfc()`
- Type annotations on all function signatures using Python 3.10+ union syntax (`str | None`)

**Variables (Frontend):**
- camelCase — `queryClient`, `searchParams`, `localSection`
- Constants: UPPER_SNAKE for navigation data — `NAV_ITEMS`, `SECTIONS`

**Variables (Backend):**
- snake_case for local variables — `pub_name`, `art_type`, `edition_number`
- UPPER_SNAKE for module-level constants — `CRSS_VERSION`, `FIELD_ORDER`, `SORT_KEY_FIELDS`, `ALL_SECTIONS`
- Dataclass fields: snake_case — `SearchConfig(backend=..., es_url=..., es_index=...)`

**Types (Frontend):**
- TypeScript interfaces with PascalCase — `SearchResult`, `DocumentDetail`, `ChatResponse`
- Use `interface` for object shapes, not `type` aliases (except for union types)
- All API response types defined centrally in `src/frontend/web/src/lib/api.ts`

**Types (Backend):**
- Python dataclasses with `@dataclass(frozen=True)` for config/value objects — `SearchConfig`, `DOUArticle`, `ZIPTarget`
- NamedTuples for lightweight data — `MergedArticle`, `Signature`, `ImageRef`, `NormRef`
- Protocol classes for adapter interfaces — `SearchAdapter(Protocol)`

## Code Style

**Formatting (Frontend):**
- No dedicated Prettier config detected — relies on editor defaults
- 2-space indentation in TSX/TS files
- Double quotes for JSX attribute strings
- Single quotes for JS string imports (inconsistent — both used)
- Semicolons at end of statements

**Formatting (Backend):**
- No dedicated formatter config (no ruff.toml, .flake8, .pylintrc)
- 4-space indentation (PEP 8 standard)
- Double quotes for docstrings and strings
- `from __future__ import annotations` at top of every module (for PEP 604 union syntax)
- Section dividers using `# ---...---` comment blocks to group related functions

**Linting (Frontend):**
- ESLint 9 with flat config at `src/frontend/web/eslint.config.js`
- Extends: `@eslint/js` recommended + `typescript-eslint` recommended
- Plugins: `react-hooks` (recommended rules), `react-refresh` (only-export-components warn)
- `@typescript-eslint/no-unused-vars` is **off** (relaxed unused variable checking)

**Linting (Backend):**
- No linter configuration detected — no ruff, flake8, pylint, or mypy config

**TypeScript Configuration:**
- `strict: false` in `src/frontend/web/tsconfig.app.json` — relaxed type checking
- `noImplicitAny: false` — any types allowed implicitly
- `strictNullChecks: false` — null/undefined not strictly checked
- `noUnusedLocals: false`, `noUnusedParameters: false` — unused code allowed
- Path alias: `@/*` maps to `./src/*`

## Import Organization

**Frontend (TypeScript):**
1. React and core libraries — `import React from "react"`, `import { useState } from "react"`
2. Third-party libraries — `import { useNavigate } from "react-router-dom"`, `import { QueryClient } from "@tanstack/react-query"`
3. Internal components/modules via `@/` alias — `import { Icons } from "@/components/Icons"`, `import { searchDocuments } from "@/lib/api"`
4. Relative imports for siblings — `import { SectionBadge } from "./Badges"`

**Path Aliases:**
- `@/` resolves to `src/frontend/web/src/` (configured in `vite.config.ts`, `vitest.config.ts`, and `tsconfig.json`)

**Backend (Python):**
1. `from __future__ import annotations` (always first)
2. Standard library imports — `import hashlib`, `import re`, `from datetime import date`
3. Third-party imports — `import httpx`, `import psycopg2`, `from fastapi import ...`
4. Local project imports using full path — `from src.backend.ingest.xml_parser import DOUArticle`

## Error Handling

**Frontend Patterns:**
- API errors thrown as `new Error(`API error: ${res.status}`)` in `fetchJSON()` at `src/frontend/web/src/lib/api.ts`
- Try/catch in formatting helpers with fallback returns:
  ```typescript
  try {
    return new Date(d).toLocaleDateString('pt-BR', { ... });
  } catch { return d; }
  ```
- Defensive null coercion throughout API normalization layer — `String(result.field || "").trim() || undefined`
- SSE streaming errors dispatched via callback — `handlers.onError?.(detail)`

**Backend Patterns:**
- Functions return `None` on invalid input rather than raising — `normalize_pub_date("invalid")` returns `None`
- HTTP errors raised as `HTTPException` in FastAPI endpoints at `src/backend/apps/web_server.py`
- `IndexError` for out-of-range Merkle tree indices at `src/backend/commitment/tree.py`
- Custom exception classes: `XMLParseError` at `src/backend/ingest/xml_parser.py`, `IngestionUnsealedError` at `src/backend/dbsync/registry_ingest.py`

## Logging

**Backend Framework:** loguru (declared in `requirements.txt`)

**Frontend:** No logging framework — uses browser console implicitly

## Comments

**When to Comment (Backend):**
- Module-level docstrings on every Python file explaining purpose, usage, and key endpoints
- Docstrings on public functions with parameter/return descriptions
- Section dividers with `# ---` comment blocks to organize code regions
- Inline comments for non-obvious invariant enforcement (e.g., CRSS-1 spec references like "MECH-1 rule 1")

**When to Comment (Frontend):**
- Minimal comments in React components — code is self-documenting
- Type comments via JSDoc/TSDoc not used

## Function Design

**Backend:**
- Small, focused pure functions for transformations — `_norm()`, `_sha()`, `strip_html()`
- Factory pattern for adapters — `create_search_adapter(cfg)` returns correct implementation
- Protocol-based interface contracts — `SearchAdapter(Protocol)` in `src/backend/search/adapters.py`
- Configuration via `@dataclass(frozen=True)` with `load_*()` factory functions

**Frontend:**
- Arrow function components exclusively — `const Component: React.FC<Props> = () => { ... }`
- Lazy loading for page-level routes — `const HomePage = lazy(() => import("./pages/HomePage"))`
- API functions as standalone exports, not class methods — `export function searchDocuments(params): Promise<SearchResponse>`
- Heavy normalization layer between raw API responses and typed frontend models in `src/frontend/web/src/lib/api.ts`

## Module Design

**Frontend Exports:**
- Pages use `export default` (required for `React.lazy()`) — `export default SearchPage`
- Components use named exports — `export const AppShell: React.FC = ...`
- Utility modules use named exports — `export function cn(...)`, `export function searchDocuments(...)`
- Types co-located with their API functions in `src/frontend/web/src/lib/api.ts`

**Backend Exports:**
- No `__all__` declarations — all public functions importable directly
- Internal functions prefixed with `_` are still imported in tests (e.g., `_compute_natural_key_hash`, `_extract_doc_number`)

**Barrel Files:**
- Not used in backend — direct imports from specific modules
- shadcn/ui components each in their own file under `src/frontend/web/src/components/ui/`

## UI/Styling Conventions

**Component Styling:**
- Tailwind CSS utility classes directly in JSX — no CSS modules or styled-components
- `cn()` utility from `src/frontend/web/src/lib/utils.ts` for conditional class merging (clsx + tailwind-merge)
- CSS custom properties (HSL values) for theming defined in CSS, consumed via `hsl(var(--token))` in Tailwind config at `src/frontend/web/tailwind.config.ts`
- shadcn/ui primitives in `src/frontend/web/src/components/ui/` with Radix UI underneath
- Custom design tokens: `text-primary`, `text-secondary`, `text-tertiary`, `surface-elevated`, `surface-sunken`, `gold`, `gold-dim`

**Design System:**
- Dark theme only (`darkMode: ["class"]` in Tailwind config)
- Font families via CSS variables: `--font-sans` (Manrope), `--font-serif` (Source Serif 4), `--font-mono` (JetBrains Mono)
- Rounded corners: large radii (`rounded-[26px]`, `rounded-[1.35rem]`, `rounded-2xl`)
- Subtle borders using `border-white/5`, `border-white/8`, `border-white/10`
- Gradient backgrounds using `bg-[linear-gradient(...)]` with low-opacity rgba values

**Accessibility:**
- `aria-label` on icon-only buttons and nav links
- `role="link"` + `tabIndex={0}` + `onKeyDown` for clickable cards
- `focus-ring` utility class for keyboard focus indicators

---

*Convention analysis: 2026-03-08*
