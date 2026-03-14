

# HomePage UX Refinements — Density, Motion, Featured Doc

## Current State (from screenshot)
- Data populates correctly (12.847, 2002-2026, Modo demo with yellow dot)
- Chips render but wrap to 3 rows — wasting vertical space
- Layout is `max-w-2xl` (672px) — too narrow for desktop, lots of dead lateral space
- "Mais Pesquisados" and "Experimente Buscar" compete for same purpose
- No featured document — home feels informational but not alive
- Status dot appears but SVG `<animate>` pulse may not be visually prominent enough
- Spring-in animations use CSS classes but `animate-spring-in` / `animate-float` are defined in `index.css`, not in tailwind config — they work via `@layer components` which is fine

## Plan (3 files)

### 1. `src/pages/HomePage.tsx` — Layout + density + featured doc

**Wider container**: `max-w-2xl` → `max-w-4xl` on desktop

**Two-column layout on desktop** (below metrics):
```text
┌─ search ─────────────────────────────────┐
├─ metrics (3 cards) ──────────────────────┤
├─ chips (horizontal scroll, single row) ──┤
├─ left column ──────────┬─ right column ──┤
│  Vistos recentemente   │  Documento      │
│  (history or empty     │  em destaque    │
│   state)               │  (mock card)    │
└────────────────────────┴─────────────────┘
```

**Merge search sections**: Remove "Experimente Buscar" as a standalone section entirely. The examples already feed the rotating search placeholder. Chips cover the quick-search use case. This eliminates the competing sections.

**Featured document card**: Add a "Último documento indexado" card with mock data:
- Title: "PORTARIA Nº 344, DE 12 DE MAIO DE 1998"
- Organ: "ANVISA — Agência Nacional de Vigilância Sanitária"  
- Snippet: "Aprova o Regulamento Técnico sobre substâncias e medicamentos sujeitos a controle especial."
- Section badge (DO1), date, clickable → `/document/mock-portaria-344`
- Subtle `animate-breathe` on the card

**Chips**: Force single-row horizontal scroll everywhere (remove `md:flex-wrap`). Add hover `translateY(-1px)` + lighter bg.

**Empty state**: Already says "Pesquise um documento acima..." — keep as is.

### 2. `src/components/StatusIndicator.tsx` — More prominent pulse

The SVG `<animate>` elements are there but the expanding circle is subtle. Make the pulse ring larger (r values `4;12;12` instead of `4;10;10`) and slightly more opaque initial value (0.5 instead of 0.4) for the warn state to be more visible.

### 3. `src/components/SearchBar.tsx` — No changes needed

Rotating placeholder already works from examples array. No modifications required.

## Files Changed

| File | Change |
|------|--------|
| `src/pages/HomePage.tsx` | Wider layout, two-column grid, remove "Experimente Buscar" section, add featured doc card, force single-row chips |
| `src/components/StatusIndicator.tsx` | Larger pulse radius for visibility |

## What improves
- Desktop fills horizontal space properly
- Single-row chips save ~80px vertical space  
- Featured document makes home feel alive with real content
- No more competing search sections
- Status pulse more visible

