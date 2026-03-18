---
created: 2026-03-18T00:38:33.191Z
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
