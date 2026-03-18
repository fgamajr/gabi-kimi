---
created: 2026-03-18T00:38:33.191Z
status: partial
title: Cut over frontend to production build
area: general
files:
  - src/frontend/app/vite.config.ts
  - docker-compose.prod.yml
  - ops/nginx/prod.conf
  - README.md
---

## Problem

The public domain `https://gabidou.top` is currently fronted by host nginx and valid TLS, but it still proxies to the Vite development server running on port `8081`. This keeps the site usable, but it leaks dev-only behavior into production, including HMR websocket errors, React dev warnings, and a runtime dependency on the Vite dev process.

## Solution

Replace the Vite dev server in production with a built frontend artifact. Build the React app, serve the static output from nginx or a minimal web container, remove HMR/websocket expectations from the public path, and update the documented production topology to match the final deployment.

## Current State

The production domain `https://gabidou.top` is already serving a built frontend artifact. Public validation no longer shows `@vite/client` or `/src/main.tsx`, and the HTML references hashed assets under `/assets/`.

## Remaining Work

- `README.md` still documents the old host-nginx-to-`127.0.0.1:8081` Vite-dev topology and explicitly says the final static-build cutover is still pending.
- `docker-compose.prod.yml` still publishes `8081:8080` for `frontend` and `8001:8000` for `backend`, so the local production definition does not match the hardened host-only ingress model described by the completed rollout.
- `ops/nginx/prod.conf` is still a container-nginx proxy config (`proxy_pass http://frontend:8080`) instead of a finalized static-asset-serving production path.
