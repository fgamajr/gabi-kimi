# Phase 16: Tear Down & Industrial Dashboard - Context

**Gathered:** 2026-03-10
**Status:** Ready for planning
**Source:** PRD Express Path (industrial.md - inline)

<domain>
## Phase Boundary

This phase tears down all Fly.io apps (stop paying for prototypes), establishes local-first development, bypasses the embedding pipeline to focus on BM25/Elasticsearch only, and redesigns the pipeline dashboard as an industrial SCADA-style control panel.

Three deliverables:
1. Fly.io teardown — destroy all gabi-dou-* apps and volumes
2. Pipeline simplification — disable/bypass embedding stage, BM25+ES only
3. Industrial control panel — SCADA-style pipeline dashboard replacing current PipelineOverview

</domain>

<decisions>
## Implementation Decisions

### Fly.io Teardown
- Destroy ALL gabi-dou-* apps: frontend, web, worker, es, redis
- Destroy Postgres (data is expendable at this stage)
- Save secrets locally before destroying (NOT committed to git)
- All development runs locally after teardown
- Re-deploy to Fly only when the system is perfected

### Local Development Stack
- ES: localhost:9200 (Docker single-node)
- Worker: localhost:8081
- Web API: localhost:8080
- Frontend: localhost:5173 (Vite dev server)
- Postgres: localhost:5432 (Docker)
- Redis: skip entirely, use in-memory fallback

### Pipeline Simplification
- Temporarily bypass embedding stage (save time, disk space, API costs)
- Focus on BM25 + Elasticsearch only for search
- Enrichment stage also paused/skipped
- Pipeline stages: Discovery → Download → Extract → BM25 Index → Verify
- Embedding and enrichment can be re-enabled later

### Industrial Control Panel Dashboard
- SCADA-style industrial control panel (NOT SaaS dashboard)
- Dark theme only (#0A0E17 background, glowing pipes/borders)
- Left-to-right pipeline flow as spatial information architecture
- Parallel tracks after Extract: BM25 (active), Embedding (disabled), Enrichment (disabled)
- Each stage is a "machine" with: name, flow indicator, queue depth, throughput, valve state
- Pipes between stages: active (green), blocked (red), empty (gray dashed)
- Fonts: JetBrains Mono (monospace/industrial), Inter (labels)
- Color palette: green (#22C55E) active, red (#EF4444) error, amber (#F59E0B) warning, purple (#A78BFA) cost

### Backend API
- Single endpoint: GET /registry/plant-status (all dashboard data)
- Stage control: POST /pipeline/stage/{name}/pause|resume|trigger
- Master control: POST /pipeline/pause-all, POST /pipeline/resume-all
- Response includes: stages, sources, storage, totals

### Interactions
- Click machine → expand inline (queue contents, last error, toggle buttons)
- Hover machine → tooltip (last run, avg time, success rate)
- Keyboard: 1-7 focus stages, P pause, R resume, T trigger, Space master valve
- Responsive: horizontal flow desktop, 2-row tablet, vertical stack mobile

### Claude's Discretion
- React component architecture (how to decompose the SCADA layout)
- State management approach (React Query vs custom hooks)
- Animation implementation (CSS vs JS for pipe flow)
- SVG vs CSS for pipe connections
- Mobile breakpoints and layout transitions
- How to structure the plant-status aggregation on the backend
- Whether to use WebSocket for real-time updates or polling

</decisions>

<specifics>
## Specific Ideas

### Design References
- Oil refinery SCADA screens (dark background, glowing pipes)
- SpaceX mission control (clean, data-dense, dark theme)
- Factorio game UI (pipes, machines, throughput indicators)
- NOT Grafana, NOT Jira, NOT admin panels

### Visual States for Machines
- AUTO: Green border, animated flow, normal brightness
- PAUSED: Yellow border, static flow, dimmed
- ERROR: Red border, pulsing glow, error count
- IDLE: Gray border, no flow, minimal

### Storage Tanks Section
- ES Index usage (%, bar)
- SQLite size
- Disk usage (%, free GB)

### Summary Bar
- System health indicator (top right)
- Alerts count
- Cost today (USD)
- Last edition date

### Acceptance Tests
- Plant-status endpoint responds in < 200ms
- Dashboard renders all stages with correct states
- Pause/resume works per stage
- Mobile responsive preserving flow metaphor
- Dark theme passes WCAG AA contrast
- Fernando can answer "is pipeline healthy?" in < 3 seconds
- Fernando can pause a stage in < 2 clicks
- Fernando can identify bottleneck in < 5 seconds

</specifics>

<deferred>
## Deferred Ideas

- Animated particle flow in pipes (keep simple, maybe v2)
- Sparkline throughput history on pipe click
- WebSocket real-time updates (polling is fine for now)
- Re-deployment to Fly.io (separate phase when ready)
- Re-enabling embedding and enrichment stages

</deferred>

---

*Phase: 16-tear-down*
*Context gathered: 2026-03-10 via PRD Express Path*
