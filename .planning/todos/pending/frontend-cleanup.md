---
title: Frontend cutover cleanup (dev residues)
created: 2026-03-17
area: frontend
priority: low
blocked_by: none
status: pending
---

The Vite dev → production build cutover was completed but some files may have residual dev configuration:
- `README.md` — may reference old Vite dev topology
- `docker-compose.prod.yml` — verify frontend service reflects static build serving
- `vite.config.ts` — `allowedHosts: true` was set as quick fix, review if still needed with static build
