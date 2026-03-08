# Fly Web Security Runbook

Last verified: 2026-03-07

This runbook covers the hardened public deployment of the GABI DOU web app on Fly.io.

## Scope

The current web stack already includes:

- Bearer-token authentication for protected endpoints
- signed `httpOnly` browser sessions for the document reader
- per-principal and per-IP rate limiting
- Trusted Host validation
- CSP and baseline security headers
- request body size enforcement on protected write endpoints
- path containment for `/dist/*`
- media-root containment for `/api/media/*`

In the recommended split deployment, the backend runs with `GABI_SERVE_FRONTEND=false` and the SPA moves to a separate Fly app. See [FLY_SPLIT_DEPLOY.md](/home/parallels/dev/gabi-kimi/docs/runbooks/FLY_SPLIT_DEPLOY.md).

The compact middleware pattern is not used directly because the current implementation goes further:

- [auth.py](/home/parallels/dev/gabi-kimi/src/backend/apps/auth.py)
- [security.py](/home/parallels/dev/gabi-kimi/src/backend/apps/middleware/security.py)
- [web_server.py](/home/parallels/dev/gabi-kimi/src/backend/apps/web_server.py)

## Required Fly Secrets

Set these before the first public deploy:

```bash
fly secrets set \
  PGPASSWORD='...' \
  GABI_API_TOKENS='ops:token-1,reader:token-2' \
  GABI_AUTH_SECRET='replace-with-32-bytes-or-more-random' \
  QWEN_API_KEY='...' \
  -a gabi-dou-web
```

Guidance:

- `GABI_API_TOKENS`: use distinct labeled tokens per human or service.
- `GABI_AUTH_SECRET`: use a random secret, minimum 32 bytes.
- `PGPASSWORD`: required by the `PG_DSN` user in `fly.toml`.
- `QWEN_API_KEY`: only if `/api/chat` should stay enabled.

## Required Fly Environment

The checked-in [fly.toml](/home/parallels/dev/gabi-kimi/ops/deploy/web/fly.toml) now expects:

- `GABI_ALLOWED_HOSTS=gabi-dou-web.fly.dev`
- `GABI_CORS_ORIGINS=https://gabi-dou-frontend.fly.dev`
- `REDIS_URL=redis://gabi-dou-redis.internal:6379/0`
- `GABI_SESSION_SAMESITE=none`
- `GABI_MAX_BODY_SIZE_BYTES=2097152`
- `GABI_SERVE_FRONTEND=false`
- `GABI_SECURITY_BLOCK_TIME_SEC=3600`
- `GABI_SECURITY_SCAN_THRESHOLD=6`
- `GABI_CHAT_CACHE_TTL_SEC=300`
- `GABI_CHAT_SCORE_TTL_SEC=3600`
- `GABI_CHAT_BLOCK_THRESHOLD=10`
- `GABI_CHAT_BLOCK_TIME_SEC=3600`

Adjust these if you add a custom domain:

- append the custom hostname to `GABI_ALLOWED_HOSTS`
- append the custom origin to `GABI_CORS_ORIGINS`

Example:

```toml
GABI_ALLOWED_HOSTS = 'gabi-dou-web.fly.dev,api.keygra.ph'
GABI_CORS_ORIGINS = 'https://gabi-dou-frontend.fly.dev,https://app.keygra.ph'
```

## Redis Requirement

Rate limiting should use Redis in Fly production.

Recommended topology:

- app name: `gabi-dou-redis`
- internal URL: `redis://gabi-dou-redis.internal:6379/0`

If Redis is absent, the app falls back to in-memory limits, which are weaker on multi-machine deploys.

## Media Root

`GABI_MEDIA_ROOT` is optional.

Set it only if the web app has access to a mounted or copied image cache directory. If not set, the app defaults to:

```text
/app/ops/data/dou/images
```

If the container does not ship that tree, media serving still works for images stored in `bytea`, but not for missing local cache files.

## Deploy Steps

1. Create or update secrets.
2. Confirm Redis internal DNS and hostnames in `fly.toml`.
3. Deploy:

```bash
fly deploy -c ops/deploy/web/fly.toml
```

4. Smoke-check:

```bash
fly status -a gabi-dou-web
curl -I https://gabi-dou-web.fly.dev/api/stats
curl -i https://gabi-dou-web.fly.dev/
```

Expected:

- `/api/stats` returns `200`
- `/` returns `404` on the backend app in split mode

5. Check auth behavior:

```bash
curl -i https://gabi-dou-web.fly.dev/api/document/<uuid>
curl -i -H "Authorization: Bearer token-1" \
  https://gabi-dou-web.fly.dev/api/document/<uuid>
```

Expected:

- unauthenticated protected request returns `401`
- authenticated protected request returns `200`
- suspicious traversal request still returns `403` if it reaches the app

## Access-Key Issuance Policy

Minimum policy:

- issue one token per operator, service, or environment
- never share one token across all users
- use 32+ random bytes, base64url or hex
- label every token in `GABI_API_TOKENS`
- rotate every 90 days or immediately after suspected leakage
- keep at most one overlap token during rotation windows

Example generation:

```bash
python - <<'PY'
import secrets
print(secrets.token_urlsafe(32))
PY
```

## Rotation Procedure

1. Generate a new token.
2. Add it alongside the old one in `GABI_API_TOKENS`.
3. Redeploy or restart the app.
4. Migrate readers/services to the new token.
5. Remove the old token from `GABI_API_TOKENS`.
6. Redeploy again.

## Residual Notes

- Search, analytics, suggest, and stats remain public by design.
- If you want a fully private app, attach `require_protected_access` to the remaining `/api/*` endpoints.
- `/api/chat` is now protected and rate-limited, but you should still monitor Qwen usage and Fly logs.
