# Fly Split Deploy

Last verified: 2026-03-07

This deployment mode separates the public GABI web surface into two Fly apps:

- `gabi-dou-web`: API/backend only
- `gabi-dou-frontend`: static SPA

## Why this split exists

It removes the SPA and static asset surface from the backend in production:

- no `/`, `/search`, `/document`, `/analytics` frontend serving on the API app
- no `/dist/*` static asset serving on the API app
- cleaner CORS boundary
- lower backend CPU usage

## Backend app

Use:

- [ops/deploy/web/fly.toml](/home/parallels/dev/gabi-kimi/ops/deploy/web/fly.toml)
- [ops/deploy/web/Dockerfile](/home/parallels/dev/gabi-kimi/ops/deploy/web/Dockerfile)

Production behavior:

- `GABI_SERVE_FRONTEND=false`
- `GABI_CORS_ORIGINS=https://gabi-dou-frontend.fly.dev`
- `GABI_SESSION_SAMESITE=none`
- protected endpoints still require Bearer/session auth

## Frontend app

Use:

- [ops/deploy/frontend-static/fly.toml](/home/parallels/dev/gabi-kimi/ops/deploy/frontend-static/fly.toml)
- [ops/deploy/frontend-static/Dockerfile](/home/parallels/dev/gabi-kimi/ops/deploy/frontend-static/Dockerfile)
- [ops/deploy/frontend-static/nginx.conf](/home/parallels/dev/gabi-kimi/ops/deploy/frontend-static/nginx.conf)

The frontend build consumes:

- `VITE_API_BASE_URL`

Default checked-in value:

```text
https://gabi-dou-web.fly.dev/api
```

## Deploy order

1. Deploy or update Redis.
2. Deploy backend API.
3. Deploy frontend static app.
4. Smoke-test cross-origin auth and document media.

Important:

- cross-origin document sessions rely on `SameSite=None` cookies
- frontend requests must continue using `credentials: "include"`

## Commands

Backend:

```bash
fly deploy -c ops/deploy/web/fly.toml
```

Frontend:

```bash
fly deploy -c ops/deploy/frontend-static/fly.toml
```

## Smoke checks

Backend:

```bash
curl -I https://gabi-dou-web.fly.dev/api/stats
curl -i https://gabi-dou-web.fly.dev/
```

Expected:

- `/api/stats` returns `200`
- `/` on the backend returns `404`

Frontend:

```bash
curl -I https://gabi-dou-frontend.fly.dev/
curl -I https://gabi-dou-frontend.fly.dev/dist/index.html
```

Expected:

- `/` returns `200`
- `/dist/index.html` returns `200`

Protected document flow:

1. Open the frontend app.
2. Navigate to a document.
3. Submit a valid access key.
4. Confirm document JSON, media URLs, and PDF download all hit the API origin successfully.

## Custom domains

If you move off `*.fly.dev`, update both apps:

- backend `GABI_ALLOWED_HOSTS`
- backend `GABI_CORS_ORIGINS`
- frontend `VITE_API_BASE_URL`

The safest pattern is:

- `api.example.com` for backend
- `app.example.com` for frontend
