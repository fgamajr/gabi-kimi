# GABI Frontend-Backend Integration - Complete Summary

## Overview

This integration strategy provides a clean, type-safe approach to connect the React frontend (`user-first-view`) with the FastAPI backend (`gabi-kimi`).

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          FRONTEND (React + TypeScript)                  │
│                                                                         │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────────────────┐  │
│  │  Components  │ ←  │ React Query  │ ←  │    API Client (Axios)    │  │
│  │  (Dashboard) │    │   (Hooks)    │    │  + Auth Interceptors     │  │
│  └──────────────┘    └──────────────┘    └──────────────────────────┘  │
│         ↑                                              │                │
│         │                                              ↓                │
│  ┌──────────────┐                            ┌─────────────────────┐   │
│  │   Loading    │                            │   Error Handling    │   │
│  │  Skeletons   │                            │   (Toast + Retry)   │   │
│  └──────────────┘                            └─────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    │ HTTP + JWT Bearer Token
                                    ↓
┌─────────────────────────────────────────────────────────────────────────┐
│                          BACKEND (FastAPI)                              │
│                                                                         │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────────────────┐  │
│  │   Dashboard  │    │   Sources    │    │      Health/Auth         │  │
│  │   Routes     │    │   Routes     │    │       Middleware         │  │
│  └──────────────┘    └──────────────┘    └──────────────────────────┘  │
│         │                   │                          │                │
│         ↓                   ↓                          ↓                │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │              PostgreSQL    Redis    Elasticsearch                │  │
│  └──────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────┘
```

## Files Created

### Documentation (8 files)
1. `docs/frontend-integration-strategy.md` - Complete integration guide
2. `docs/INTEGRATION_SUMMARY.md` - This summary
3. `docs/frontend-QUICKSTART.md` - Quick start guide
4. `docs/frontend-env.d.ts` - TypeScript env types
5. `docs/frontend-dotenv.example` - Environment variables example

### Frontend Implementation Files (10 files)
6. `docs/frontend-api-types.ts` - TypeScript interfaces (4883 bytes)
7. `docs/frontend-api-client.ts` - Axios client with auth (3442 bytes)
8. `docs/frontend-api-dashboard.ts` - Dashboard API functions (5640 bytes)
9. `docs/frontend-api-sources.ts` - Sources API functions (2365 bytes)
10. `docs/frontend-api-index.ts` - Barrel exports (343 bytes)
11. `docs/frontend-hooks-useDashboard.ts` - Dashboard hooks (6393 bytes)
12. `docs/frontend-hooks-useSources.ts` - Sources hooks (3965 bytes)
13. `docs/frontend-hooks-index.ts` - Barrel exports (435 bytes)
14. `docs/frontend-Dashboard-updated.tsx` - Updated Dashboard component (10270 bytes)

## Key Integration Points

### 1. API Client Layer
- **File**: `lib/api/client.ts`
- **Features**:
  - Axios instance with interceptors
  - JWT token management (localStorage)
  - Automatic error handling with toast notifications
  - Request/response logging

### 2. Type Safety
- **File**: `lib/api/types.ts`
- **Features**:
  - Full TypeScript interfaces matching backend Pydantic schemas
  - Enums for status values
  - Frontend-mapped types for backward compatibility

### 3. Data Transformation
Backend has **9 pipeline stages**, frontend displays **4 stages**:

| Backend Stage | Frontend Stage |
|---------------|----------------|
| discovery | harvest |
| change_detection | harvest |
| fetch | harvest |
| parse | sync |
| fingerprint | sync |
| deduplication | sync |
| chunking | ingest |
| embedding | ingest |
| indexing | index |

### 4. React Query Hooks
- **File**: `hooks/useDashboard.ts`
- **Features**:
  - Automatic caching and refetching
  - Polling intervals (10s for active pipeline, 30s for stalled)
  - Error retry with exponential backoff
  - Optimistic updates for mutations

### 5. Error Handling
- Global error boundary for unhandled errors
- API error fallback for data fetching errors
- Toast notifications for user feedback
- Automatic redirect to login on 401

### 6. Loading States
- Skeleton components for each section
- Staggered animations for progressive loading
- Refresh indicator during background refetch

## Backend Configuration Required

### Environment Variables (.env)
```bash
# CORS - Must include frontend origin
GABI_CORS_ORIGINS=http://localhost:5173,http://localhost:3000,https://gabi.tcu.gov.br

# Auth - Can disable for development
GABI_AUTH_ENABLED=true  # Set to false for local dev without Keycloak
GABI_JWT_ISSUER=https://auth.tcu.gov.br/realms/tcu
GABI_JWT_AUDIENCE=gabi-api
```

### Already Configured
The backend already has:
- ✅ CORS middleware (`main.py` lines 94-100)
- ✅ JWT auth middleware (`main.py` lines 107-111)
- ✅ Public health endpoints (`config.py` lines 121-133)
- ✅ Rate limiting middleware
- ✅ Request ID middleware for tracing

## API Endpoints

### Dashboard Endpoints
| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/api/v1/dashboard/stats` | GET | Bearer | Statistics, sources, document counts |
| `/api/v1/dashboard/pipeline` | GET | Bearer | 9 pipeline stages with status |
| `/api/v1/dashboard/activity` | GET | Bearer | Audit log events (50 default) |
| `/api/v1/dashboard/health` | GET | Bearer | Component health (PG, ES, Redis, TEI) |
| `/api/v1/dashboard/trigger-ingestion` | POST | Admin | Trigger source ingestion |

### Sources Endpoints
| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/api/v1/sources` | GET | Bearer | List all sources |
| `/api/v1/sources/:id` | GET | Bearer | Source details |
| `/api/v1/sources/:id/sync` | POST | Editor+ | Trigger sync |
| `/api/v1/sources/:id/status` | GET | Bearer | Source status |

### Public Endpoints
| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/health/live` | GET | None | Liveness probe |
| `/health/ready` | GET | None | Readiness probe |
| `/health` | GET | None | Full health check |

## Minimal Changes to Existing Code

### Components - NO CHANGES NEEDED
- `PipelineOverview.tsx` - Receives same `PipelineStage[]` format
- `ActivityFeed.tsx` - Receives same `SyncJob[]` format  
- `SourcesTable.tsx` - Receives same `Source[]` format
- `SystemHealth.tsx` - Receives boolean for ES status
- `MetricCard.tsx` - No data dependencies

### Dashboard.tsx - MINIMAL CHANGES
```diff
  // OLD
- import { mockStats, mockJobs, mockPipelineStages } from '@/lib/dashboard-data';
- const [stats] = useState(mockStats);
- const [jobs] = useState(mockJobs);
- const [pipeline] = useState(mockPipelineStages);

  // NEW
+ import { useDashboardData } from '@/hooks/useDashboard';
+ const { stats, frontendPipeline, frontendJobs, isLoading } = useDashboardData();
```

## Polling Strategy

### Adaptive Polling
- **Active Pipeline** (`overall_status === 'healthy'`): Poll every 10 seconds
- **Stalled Pipeline**: Poll every 30 seconds
- **Error State**: Exponential backoff (max 60s)

### Individual Endpoint Intervals
| Endpoint | Interval | Stale Time |
|----------|----------|------------|
| /stats | 30s | 15s |
| /pipeline | 10s (adaptive) | 5s |
| /activity | 60s | 30s |
| /health | 60s | 30s |
| /sources | 30s | 15s |

## Security Considerations

1. **Token Storage**: Access tokens stored in `localStorage`
2. **Token Refresh**: Handled automatically via interceptor
3. **CORS**: Strict origin validation in production
4. **HTTPS**: Required for all origins in production
5. **Rate Limiting**: Backend enforces 60 req/min per IP
6. **Auth Fail-Closed**: Production rejects tokens when Redis unavailable

## Performance Optimizations

1. **Request Deduplication**: React Query caches identical requests
2. **Stale-While-Revalidate**: Show cached data while fetching fresh
3. **Optimistic Updates**: UI updates before API confirms
4. **Debounced Refetch**: Avoid rapid consecutive refetches
5. **Selective Refetch**: Only invalidate changed queries

## Implementation Phases

### Phase 1: Foundation (Day 1)
- [ ] Install axios
- [ ] Copy API client and types
- [ ] Configure environment variables
- [ ] Test backend connectivity

### Phase 2: Data Layer (Day 1-2)
- [ ] Copy React Query hooks
- [ ] Test data transformations
- [ ] Verify polling works
- [ ] Add error handling

### Phase 3: UI Integration (Day 2)
- [ ] Update Dashboard.tsx
- [ ] Add loading skeletons
- [ ] Add error boundaries
- [ ] Test all interactions

### Phase 4: Polish (Day 3)
- [ ] Add toast notifications
- [ ] Test auth flow
- [ ] Performance testing
- [ ] Documentation

## Testing Checklist

- [ ] All dashboard cards load data
- [ ] Pipeline stages show correct progress
- [ ] Activity feed displays recent events
- [ ] Sources table shows all sources
- [ ] Refresh button updates all data
- [ ] Error states show correctly
- [ ] Loading skeletons display during fetch
- [ ] Auth token refreshes automatically
- [ ] Logout redirects to login page

## Future Enhancements

### WebSocket Real-time Updates
```typescript
// Potential future implementation
useDashboardWebSocket({
  onPipelineUpdate: (data) => updateCache(data),
  onActivityEvent: (event) => prependToFeed(event),
});
```

### Optimistic Mutations
```typescript
// For instant UI feedback on actions
useSyncSource({
  onMutate: () => {
    // Optimistically mark source as syncing
  },
});
```

## Support

For issues:
1. Check backend logs: `make logs`
2. Verify CORS origins match
3. Test API directly: `curl http://localhost:8000/health/live`
4. Check browser Network tab for request/response details

---

**Total Documentation**: ~50KB of implementation-ready code
**Time to Integrate**: 1-2 days for experienced React developer
**Breaking Changes**: None - all existing components remain compatible
