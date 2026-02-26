#!/usr/bin/env bash
# ╔═══════════════════════════════════════════════════════════════╗
# ║ DEPRECATED: Este script esta sendo migrado para o            ║
# ║ ReliabilityLab C# (tests/ReliabilityLab/).                  ║
# ║ Ver: tests/ReliabilityLab/README.md para a versao moderna.   ║
# ╚═══════════════════════════════════════════════════════════════╝
# ═══════════════════════════════════════════════════════════════════════════════
# GABI - Smoke Test (non-destructive)
# ═══════════════════════════════════════════════════════════════════════════════
# Verifica que a API está viva e responde a health, auth e search.
# NÃO inicia nem para serviços; NÃO destrói dados.
# Uso: ./tests/smoke-test.sh
#      API_URL=http://localhost:5100 ./tests/smoke-test.sh
# ═══════════════════════════════════════════════════════════════════════════════

set -euo pipefail

API_URL="${API_URL:-http://localhost:5100}"
PASSED=0
FAILED=0

log() { echo "[smoke] $*"; }
ok()  { log "PASS: $*"; ((PASSED++)) || true; }
fail() { log "FAIL: $*"; ((FAILED++)) || true; }

# 1. Health (liveness)
if curl -sf --max-time 5 "$API_URL/health" >/dev/null 2>&1; then
  ok "GET /health"
else
  fail "GET /health — API not responding at $API_URL"
  exit 1
fi

# 2. Readiness (PostgreSQL)
if curl -sf --max-time 5 "$API_URL/health/ready" >/dev/null 2>&1; then
  ok "GET /health/ready"
else
  fail "GET /health/ready — readiness check failed"
fi

# 3. Auth (viewer credentials from AGENTS.md)
login_body="$(curl -sf -w '\n%{http_code}' -X POST "$API_URL/api/v1/auth/login" \
  -H 'Content-Type: application/json' \
  -d '{"username":"viewer","password":"view123"}' 2>/dev/null)" || true
status_code="$(echo "$login_body" | tail -n1)"
body="$(echo "$login_body" | sed '$d')"

if [[ "$status_code" == "200" ]]; then
  TOKEN=""
  if command -v python3 >/dev/null 2>&1; then
    TOKEN="$(python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("token",""))' <<<"$body" 2>/dev/null)" || true
  fi
  [[ -z "$TOKEN" ]] && TOKEN="$(echo "$body" | grep -o '"token":"[^"]*"' | head -1 | cut -d'"' -f4)" || true
  if [[ -n "$TOKEN" ]]; then
    ok "POST /api/v1/auth/login (viewer)"
  else
    fail "POST /api/v1/auth/login — 200 but no token in body"
  fi
else
  fail "POST /api/v1/auth/login — HTTP $status_code"
fi

# 4. Search (authenticated) — 200 or 503 (ES not configured) both acceptable
if [[ -n "${TOKEN:-}" ]]; then
  search_status="$(curl -sf -o /dev/null -w '%{http_code}' --max-time 10 \
    -H "Authorization: Bearer $TOKEN" \
    "$API_URL/api/v1/search?q=test&limit=1" 2>/dev/null)" || search_status="000"
  if [[ "$search_status" == "200" ]]; then
    ok "GET /api/v1/search (auth) — 200"
  elif [[ "$search_status" == "503" ]]; then
    ok "GET /api/v1/search (auth) — 503 (Elasticsearch not configured, acceptable)"
  else
    fail "GET /api/v1/search (auth) — HTTP $search_status"
  fi
fi

log "---"
log "Result: $PASSED passed, $FAILED failed"
if [[ "$FAILED" -gt 0 ]]; then
  exit 1
fi
exit 0
