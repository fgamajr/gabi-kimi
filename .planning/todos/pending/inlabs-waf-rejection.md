---
title: INLABS WAF blocks Hetzner IP for daily ingestion
created: 2026-03-17
area: ingest
priority: high
blocked_by: network/institutional
status: pending
---

The INLABS server (inlabs.in.gov.br) WAF rejects requests from the Hetzner datacenter IP (204.168.173.163).
A Mac→Server relay workaround is implemented but requires manual intervention.

**Permanent solutions to evaluate:**
- Request IP whitelist from INLABS/Imprensa Nacional
- VPN with non-datacenter egress IP
- Proxy through a residential/institutional IP
- AWS Lambda or similar with rotating IPs
