# Connecting Frontend (Lovable) to GABI API

## Overview
This document explains how to connect the Lovable frontend to the GABI backend API.

## API Endpoints Available

### Dashboard Endpoints
- `GET /api/v1/dashboard/stats` - Get dashboard statistics
- `GET /api/v1/dashboard/pipeline` - Get pipeline progress
- `GET /api/v1/dashboard/activity` - Get activity feed
- `GET /api/v1/dashboard/health` - Get system health
- `POST /api/v1/dashboard/trigger-ingestion` - Trigger ingestion for a source

### Pipeline Control Endpoints
- `POST /api/v1/pipeline-control/control` - Control pipeline phases (start/stop/restart)
- `GET /api/v1/pipeline-control/status` - Get pipeline status
- `POST /api/v1/pipeline-control/execute` - Execute pipeline immediately

### Search Endpoints
- `POST /api/v1/search/query` - Perform hybrid search
- `GET /api/v1/search/suggestions` - Get search suggestions

### Document Endpoints
- `GET /api/v1/documents/{id}` - Get document by ID
- `GET /api/v1/documents/list` - List documents with filters

### Source Endpoints
- `GET /api/v1/sources` - List all sources
- `GET /api/v1/sources/{id}` - Get source details

## Authentication
The API uses JWT-based authentication. Frontend needs to:
1. Obtain JWT token from authentication service
2. Include token in Authorization header: `Authorization: Bearer {token}`
3. Handle token expiration and refresh

## Example API Calls

### Get Dashboard Stats
```javascript
const response = await fetch('/api/v1/dashboard/stats', {
  headers: {
    'Authorization': `Bearer ${token}`,
    'Content-Type': 'application/json'
  }
});
const stats = await response.json();
```

### Control Pipeline
```javascript
const response = await fetch('/api/v1/pipeline-control/control', {
  method: 'POST',
  headers: {
    'Authorization': `Bearer ${token}`,
    'Content-Type': 'application/json'
  },
  body: JSON.stringify({
    source_id: 'tcu_acordaos',
    phase: 'discovery', // or null for all phases
    action: 'start' // start, stop, restart
  })
});
const result = await response.json();
```

### Get Pipeline Status
```javascript
const response = await fetch(`/api/v1/pipeline-control/status?source_id=tcu_acordaos&phase=discovery`, {
  headers: {
    'Authorization': `Bearer ${token}`,
    'Content-Type': 'application/json'
  }
});
const status = await response.json();
```

## WebSocket/SSE Connection
For real-time updates, the API supports Server-Sent Events (SSE) for pipeline progress and system events.

## Error Handling
- API follows standard HTTP status codes
- Error responses include structured error details
- Frontend should handle 401 (unauthorized) for token refresh
- Handle 5xx errors with retry mechanisms

## CORS Configuration
The API is configured to allow requests from the frontend origin. Make sure your frontend is served from an allowed origin as configured in the backend.

## Environment Variables
Configure the API base URL in your frontend:
- Development: `http://localhost:8000`
- Production: `https://gabi-api.fly.dev` (or your deployed URL)