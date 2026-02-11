# GABI Frontend Integration - Quick Start

## 1. Install Dependencies

```bash
cd /home/fgamajr/dev/user-first-view
npm install axios
```

## 2. Copy Files

Copy these files to your frontend project:

```
frontend/src/
├── lib/
│   ├── api/
│   │   ├── client.ts      ← from docs/frontend-api-client.ts
│   │   ├── types.ts       ← from docs/frontend-api-types.ts
│   │   ├── dashboard.ts   ← from docs/frontend-api-dashboard.ts
│   │   ├── sources.ts     ← from docs/frontend-api-sources.ts
│   │   └── index.ts       ← from docs/frontend-api-index.ts
│   └── dashboard-data.ts  ← Keep formatters, remove mock exports
├── hooks/
│   ├── useDashboard.ts    ← from docs/frontend-hooks-useDashboard.ts
│   ├── useSources.ts      ← from docs/frontend-hooks-useSources.ts
│   └── index.ts           ← from docs/frontend-hooks-index.ts
└── components/
    ├── loading/
    │   └── DashboardSkeleton.tsx  ← create simple skeleton
    └── error/
        ├── ErrorBoundary.tsx      ← create error boundary
        └── ApiErrorFallback.tsx   ← create error fallback
```

## 3. Environment Variables

Create `.env.local` in your frontend root:

```bash
VITE_API_URL=http://localhost:8000/api/v1
```

## 4. Update App.tsx

Update QueryClient configuration:

```tsx
import { QueryClient } from '@tanstack/react-query';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 3,
      staleTime: 10000,
      refetchOnWindowFocus: true,
    },
  },
});
```

## 5. Update Dashboard.tsx

Replace mock data with hooks (see docs/frontend-Dashboard-updated.tsx for full example):

```tsx
// OLD
import { mockStats, mockJobs, mockPipelineStages } from '@/lib/dashboard-data';
const [stats] = useState(mockStats);

// NEW
import { useDashboardData } from '@/hooks/useDashboard';
const { stats, frontendPipeline, frontendJobs, isLoading } = useDashboardData();
```

## 6. Start Backend

```bash
cd /home/fgamajr/dev/gabi-kimi
# Start PostgreSQL, Elasticsearch, Redis
docker-compose up -d

# Run migrations
make migrate

# Start API
make dev
```

## 7. Test Integration

```bash
cd /home/fgamajr/dev/user-first-view
npm run dev
```

## Backend CORS Configuration

The backend is already configured. Just update `.env` in backend:

```bash
GABI_CORS_ORIGINS=http://localhost:5173,http://localhost:3000
```

## API Endpoints Available

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/api/v1/dashboard/stats` | GET | Yes | Dashboard statistics |
| `/api/v1/dashboard/pipeline` | GET | Yes | Pipeline stages |
| `/api/v1/dashboard/activity` | GET | Yes | Activity feed |
| `/api/v1/dashboard/health` | GET | Yes | System health |
| `/api/v1/dashboard/trigger-ingestion` | POST | Admin | Trigger ingestion |
| `/api/v1/sources` | GET | Yes | List sources |
| `/api/v1/sources/:id/sync` | POST | Editor+ | Sync source |
| `/api/v1/sources/:id/status` | GET | Yes | Source status |
| `/health/live` | GET | No | Liveness probe |

## Troubleshooting

### CORS Errors
- Check `GABI_CORS_ORIGINS` includes your frontend URL
- Verify backend is running on expected port

### Auth Errors
- Backend requires JWT token from Keycloak
- For development, you can disable auth: `GABI_AUTH_ENABLED=false`

### Connection Errors
- Verify all services are running: `docker-compose ps`
- Check backend logs: `make logs`

## Architecture Overview

```
Frontend (React) → React Query → API Client → FastAPI Backend
     ↓                    ↓              ↓
Components ← Hooks ← Axios ← JWT Auth
```

## Key Decisions

1. **Polling over WebSocket**: Simpler, works with existing infrastructure
2. **React Query**: Built-in caching, refetching, error handling
3. **Data Transformers**: Backend has 9 pipeline stages → Frontend shows 4
4. **Minimal Changes**: Existing components receive same data shape
