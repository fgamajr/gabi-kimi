# GABI Experimental Features Implementation Plan
## Parallel Architecture for Zero-Risk Deployment

---

## 1. ARCHITECTURE PRINCIPLES

### 1.1 Zero-Breakage Guarantee
- **No modifications** to existing `/src/components/*`, `/src/pages/*`
- All new code lives in `/src/experimental/`
- Feature flags control visibility
- Route coexistence via `/beta/*` prefix

### 1.2 Instant Revert Strategy
```
REVERT METHODS (in order of speed):
1. Flag toggle:     Set window.GABI_FEATURES = {} → Instant (0ms)
2. Route ignore:    Remove /beta routes → Fast (reload)
3. Delete folder:   rm -rf src/experimental → Complete (git checkout)
```

### 1.3 File Organization
```
src/
├── experimental/                    # NEW - All new features
│   ├── features.ts                  # Feature flags registry
│   ├── routes.tsx                   # Parallel route definitions
│   ├── components/                  # New components
│   │   ├── CommandPalette/
│   │   ├── DocumentGraph/
│   │   └── charts/
│   ├── pages/                       # New page variants
│   │   ├── HomePageV2.tsx          # With sparklines
│   │   ├── DashboardPage.tsx       # Time series
│   │   └── DocumentPageV2.tsx      # With graph
│   ├── hooks/                       # New hooks
│   │   ├── useCommandPalette.ts
│   │   ├── useGraphData.ts
│   │   └── useChartData.ts
│   └── lib/                         # Utilities
│       ├── chart-utils.ts
│       └── graph-layout.ts
├── components/                      # EXISTING - Untouched
├── pages/                           # EXISTING - Untouched
└── App.tsx                          # MODIFIED - Add experimental routes
```

---

## 2. FEATURE SPECIFICATIONS

### 2.1 Feature: Command Palette (CMD+K)

**User Story:**
As a researcher, I want to press CMD+K to instantly search documents, access recent items, and navigate without mouse.

**Acceptance Criteria:**
- [ ] Global CMD+K shortcut (override existing search shortcut)
- [ ] Recent searches section (top 5)
- [ ] Recent documents section (top 5)
- [ ] Live search results (debounced 150ms)
- [ ] Keyboard navigation (↓↑ Enter Escape)
- [ ] Visual highlighting of matches
- [ ] Empty state with suggestions
- [ ] Mobile: Button in nav + full-screen modal

**Files to Create:**
```
src/experimental/components/CommandPalette/
├── index.tsx              # Main dialog component
├── useCommandPalette.ts   # Logic hook
├── types.ts               # TypeScript definitions
└── styles.css             # Animation overrides
```

**Integration Point:**
```tsx
// In AppShell - add button that triggers palette
// In App.tsx - wrap with CommandPaletteProvider
```

---

### 2.2 Feature: Document Relationship Graph

**User Story:**
As a researcher, I want to see which documents cite or are cited by the current document, forming a knowledge graph.

**Acceptance Criteria:**
- [ ] Parse `normative_refs` from API
- [ ] Visual tree/graph display
- [ ] Click to navigate to related documents
- [ ] Color coding: current (primary), cites (blue), cited-by (green)
- [ ] Expand/collapse branches
- [ ] Responsive: horizontal scroll on mobile
- [ ] Empty state when no references

**Files to Create:**
```
src/experimental/components/DocumentGraph/
├── index.tsx              # Main graph container
├── GraphNode.tsx          # Individual node component
├── GraphEdge.tsx          # Connection lines
├── useGraphData.ts        # Data transformation hook
├── layouts/
│   ├── treeLayout.ts      # Hierarchical layout
│   └── forceLayout.ts     # Force-directed (optional)
└── types.ts
```

**Integration Point:**
```tsx
// Add to DocumentPageV2 sidebar
// Below TOC or in new tab
```

---

### 2.3 Feature: Time Series Dashboard

**User Story:**
As an auditor, I want to visualize publication patterns over time to detect anomalies and seasonal trends.

**Charts Required:**
1. **Publication Volume** - Daily bars with 30-day moving average
2. **Organ Activity** - Stacked area by ministry
3. **Document Types** - Line chart with red flag highlighting
4. **Pipeline Health** - Real-time ingestion metrics
5. **Activity Heatmap** - GitHub-style calendar

**Acceptance Criteria:**
- [ ] All 5 chart types from HTML prototype
- [ ] Interactive tooltips
- [ ] Time range selector (7d, 30d, 90d, 1y, all)
- [ ] Section filter (DO1, DO2, DO3, all)
- [ ] Download chart as PNG
- [ ] Responsive: stack on mobile
- [ ] Loading skeletons
- [ ] Error states

**Files to Create:**
```
src/experimental/charts/
├── ChartContainer.tsx          # Wrapper with header, controls
├── ChartToolbar.tsx            # Time range, filters
├── PublicationVolumeChart.tsx  # Chart 1
├── OrganActivityChart.tsx      # Chart 2
├── DocumentTypesChart.tsx      # Chart 3
├── PipelineHealthChart.tsx     # Chart 4
├── ActivityHeatmap.tsx         # Chart 6
├── SparklineChart.tsx          # Chart 5 (mini)
├── useChartData.ts             # Data fetching
└── utils/
    ├── movingAverage.ts        # Math utilities
    ├── bollingerBands.ts       # Statistical functions
    └── colorScales.ts          # Heatmap colors
```

**Integration Point:**
```tsx
// New route: /beta/dashboard
// Link from HomePageV2 metric cards
```

---

### 2.4 Feature: Sparkline Cards (HomePage Enhancement)

**User Story:**
As a user, I want to see trend indicators in metric cards to understand system health at a glance.

**Acceptance Criteria:**
- [ ] 3 sparklines: Publications, Ingest Rate, Latency
- [ ] 7-day trend visualization
- [ ] Up/down indicators with percentages
- [ ] Click to expand to full dashboard
- [ ] Animate on scroll into view

**Files to Create:**
```
src/experimental/components/
├── SparklineCard.tsx
└── MetricCardV2.tsx          # Enhanced with sparkline slot
```

---

## 3. API REQUIREMENTS

### New Endpoints Needed (Backend)

```typescript
// GET /api/v2/analytics/publications?from=&to=&section=
interface PublicationsAnalytics {
  daily: Array<{
    date: string;
    count: number;
    section: string;
  }>;
  movingAverage30d: number[];
  bollingerBands: {
    upper: number[];
    lower: number[];
  };
  anomalies: Array<{
    date: string;
    severity: 'low' | 'medium' | 'high';
    deviation: number;
  }>;
}

// GET /api/v2/analytics/orgs?from=&to=
interface OrgAnalytics {
  organizations: Array<{
    name: string;
    dailyCounts: number[];
    color: string;
  }>;
  dates: string[];
}

// GET /api/v2/analytics/types?from=&to=
interface TypeAnalytics {
  types: Array<{
    name: string;
    dailyCounts: number[];
  }>;
  redFlags: Array<{
    date: string;
    type: string;
    spike: number;
  }>;
}

// GET /api/v2/analytics/health
interface HealthMetrics {
  ingestRate: Array<{ timestamp: string; docsPerHour: number }>;
  latency: Array<{ timestamp: string; p95: number }>;
  errorRate: number;
}

// GET /api/v2/analytics/heatmap?year=
interface HeatmapData {
  year: number;
  weeks: Array<{
    weekNumber: number;
    days: Array<{
      date: string;
      count: number;
      intensity: 0 | 1 | 2 | 3 | 4;
    }>;
  }>;
}

// GET /api/v2/documents/:id/related
interface RelatedDocuments {
  cites: Array<{
    id: string;
    title: string;
    date: string;
    organ: string;
  }>;
  citedBy: Array<{
    id: string;
    title: string;
    date: string;
    organ: string;
  }>;
}
```

---

## 4. IMPLEMENTATION PHASES

### Phase 0: Infrastructure (2 days)
- [ ] Create folder structure
- [ ] Implement feature flags system
- [ ] Create experimental routes
- [ ] Add "Enable Beta Features" toggle in UI

### Phase 1: Command Palette (3 days)
- [ ] Build dialog component
- [ ] Implement keyboard navigation
- [ ] Connect to search API
- [ ] Add recent items
- [ ] Mobile optimization

### Phase 2: Document Graph (4 days)
- [ ] Parse normative references
- [ ] Build tree layout algorithm
- [ ] Create node/edge components
- [ ] Add interactions (click, expand)
- [ ] Responsive design

### Phase 3: Charts Foundation (3 days)
- [ ] Select charting library (Recharts vs Visx)
- [ ] Build ChartContainer wrapper
- [ ] Create color system
- [ ] Implement loading/error states

### Phase 4: Individual Charts (5 days)
- [ ] Publication Volume + Bollinger bands
- [ ] Organ Activity (stacked area)
- [ ] Document Types with red flags
- [ ] Pipeline Health (real-time)
- [ ] Activity Heatmap

### Phase 5: Dashboard Integration (3 days)
- [ ] Create DashboardPage
- [ ] Add time range controls
- [ ] Connect all charts
- [ ] Responsive layout

### Phase 6: Sparklines & Polish (2 days)
- [ ] Sparkline component
- [ ] Integrate into HomePageV2
- [ ] Animations
- [ ] Final testing

**Total Timeline: 22 days**

---

## 5. FEATURE FLAG SYSTEM

```typescript
// src/experimental/features.ts

export interface FeatureFlags {
  commandPalette: boolean;
  documentGraph: boolean;
  timeSeriesDashboard: boolean;
  sparklineCards: boolean;
  enhancedSearch: boolean;
}

export const DEFAULT_FLAGS: FeatureFlags = {
  commandPalette: false,
  documentGraph: false,
  timeSeriesDashboard: false,
  sparklineCards: false,
  enhancedSearch: false,
};

// Load from localStorage or URL params
export function getFeatureFlags(): FeatureFlags {
  const stored = localStorage.getItem('gabi-features');
  const parsed = stored ? JSON.parse(stored) : {};
  
  // URL override: ?features=commandPalette,documentGraph
  const urlParams = new URLSearchParams(window.location.search);
  const urlFeatures = urlParams.get('features');
  if (urlFeatures) {
    const enabled = urlFeatures.split(',');
    enabled.forEach(f => parsed[f] = true);
  }
  
  return { ...DEFAULT_FLAGS, ...parsed };
}

export function setFeatureFlag(key: keyof FeatureFlags, value: boolean) {
  const current = getFeatureFlags();
  const updated = { ...current, [key]: value };
  localStorage.setItem('gabi-features', JSON.stringify(updated));
  window.location.reload();
}

// React hook
export function useFeatureFlags() {
  const [flags, setFlags] = useState(getFeatureFlags());
  
  const toggle = useCallback((key: keyof FeatureFlags) => {
    setFeatureFlag(key, !flags[key]);
    setFlags(getFeatureFlags());
  }, [flags]);
  
  return { flags, toggle };
}
```

---

## 6. TESTING STRATEGY

### Unit Tests
- Chart data transformation functions
- Graph layout algorithms
- Feature flag utilities

### Integration Tests
- Command palette flow
- Chart data fetching
- Graph navigation

### E2E Tests
- Complete user journeys
- Mobile interactions
- Revert procedures

---

## 7. ROLLBACK PROCEDURES

### Emergency Rollback (< 1 minute)
```javascript
// In browser console
localStorage.removeItem('gabi-features');
location.reload();
```

### Feature-Specific Rollback
```javascript
// Disable specific feature
const flags = JSON.parse(localStorage.getItem('gabi-features'));
flags.commandPalette = false;
localStorage.setItem('gabi-features', JSON.stringify(flags));
location.reload();
```

### Complete Removal
```bash
git checkout src/experimental  # If committed
git checkout src/App.tsx      # Restore original routes
rm -rf src/experimental        # If not committed
```

---

## 8. AGENT ASSIGNMENTS (SWARM MODE)

### Agent Pool A: Infrastructure (4 agents)
- A1: Folder structure, feature flags
- A2: Route configuration
- A3: Types and utilities
- A4: Integration with existing App.tsx

### Agent Pool B: Command Palette (6 agents)
- B1: Dialog shell and animations
- B2: Keyboard navigation logic
- B3: Recent items integration
- B4: Live search implementation
- B5: Mobile optimization
- B6: Polish and accessibility

### Agent Pool C: Document Graph (6 agents)
- C1: Data parsing and types
- C2: Tree layout algorithm
- C3: Node component
- C4: Edge/connection rendering
- C5: Interactions and navigation
- C6: Responsive design

### Agent Pool D: Charts (8 agents)
- D1: Chart container and toolbar
- D2: Publication Volume chart
- D3: Organ Activity chart
- D4: Document Types chart
- D5: Pipeline Health chart
- D6: Activity Heatmap
- D7: Sparkline component
- D8: Math utilities (Bollinger, etc.)

### Agent Pool E: Dashboard & Integration (4 agents)
- E1: Dashboard page layout
- E2: Time range controls
- E3: HomePageV2 with sparklines
- E4: Final integration and testing

**Total: 28 agents**

---

## 9. DEPENDENCIES TO INSTALL

```bash
# Charting (lightweight, React-friendly)
npm install recharts

# Or for more control (heavier)
npm install @visx/xy-chart @visx/shape @visx/scale

# Date manipulation
npm install date-fns

# Utilities
npm install lodash-es
npm install -D @types/lodash-es
```

---

## 10. SUCCESS CRITERIA

- [ ] All features work in parallel with existing code
- [ ] No modifications to `/src/components/*` or `/src/pages/*` (except App.tsx routes)
- [ ] Instant revert capability (< 5 seconds)
- [ ] Mobile-responsive
- [ ] Keyboard accessible
- [ ] No console errors
- [ ] Lighthouse score > 90

---

**PLAN APPROVED FOR EXECUTION**
**Ready to spawn 28 agents in parallel**
