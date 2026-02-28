#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

SOURCE_ID="${1:-dou_inlabs_secao1_atos_administrativos}"
MAX_DOCS="${2:-5000}"
API_URL="${API_URL:-http://localhost:5000}"
TIMEOUT_SECONDS="${TIMEOUT_SECONDS:-5400}"
API_LOG="/tmp/gabi-api-dou-oneclick.log"
WORKER_LOG="/tmp/gabi-worker-dou-oneclick.log"

log() { printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"; }

pg_scalar() {
  local sql="$1"
  docker compose exec -T postgres psql -U gabi -d gabi -t -A -c "$sql" | tr -d '\r' | head -n1 | xargs
}

wait_http() {
  local url="$1"; local timeout="$2"; local t=0
  until curl -fsS "$url" >/dev/null 2>&1; do
    sleep 2
    t=$((t+2))
    if [ "$t" -ge "$timeout" ]; then
      echo "timeout waiting for $url" >&2
      return 1
    fi
  done
}

api_post() {
  local path="$1"
  local body="$2"
  curl -fsS -X POST "$API_URL$path" \
    -H "Authorization: Bearer $TOKEN" \
    -H 'Content-Type: application/json' \
    -d "$body"
}

log "Destroying stack and host processes"
pkill -f "dotnet.*Gabi.Api.dll" >/dev/null 2>&1 || true
pkill -f "dotnet.*Gabi.Worker.dll" >/dev/null 2>&1 || true
docker compose down -v --remove-orphans >/dev/null 2>&1 || true

log "Starting infrastructure"
docker compose up -d postgres redis elasticsearch tei >/dev/null

log "Waiting for infra health"
for i in $(seq 1 120); do
  PG_OK=false
  REDIS_OK=false
  ES_OK=false
  docker compose exec -T postgres pg_isready -U gabi -d gabi >/dev/null 2>&1 && PG_OK=true
  docker compose exec -T redis redis-cli -a devredis ping >/dev/null 2>&1 && REDIS_OK=true
  curl -fsS http://localhost:9200/_cluster/health >/dev/null 2>&1 && ES_OK=true
  if $PG_OK && $REDIS_OK && $ES_OK; then break; fi
  sleep 2
  if [ "$i" -eq 120 ]; then
    echo "infra did not become healthy" >&2
    exit 1
  fi
done

read_env_raw() {
  local key="$1"
  local value
  value="$(grep -E "^${key}=" .env 2>/dev/null | tail -n1 | cut -d= -f2- || true)"
  printf '%s' "$value"
}

if [ -f ".env" ]; then
  COOKIE_RAW="$(read_env_raw GABI_INLABS_COOKIE)"
  COOKIE_RAW="${COOKIE_RAW#\\'}"
  COOKIE_RAW="${COOKIE_RAW%\\'}"
  COOKIE_RAW="${COOKIE_RAW//\\$\\$/\\$}"
  if [ -n "$COOKIE_RAW" ] && [ -z "${GABI_INLABS_COOKIE:-}" ]; then
    export GABI_INLABS_COOKIE="$COOKIE_RAW"
  fi
fi

IN_LABS_USER_RAW="$(read_env_raw IN_LABS_USER)"
IN_LABS_PWD_RAW="$(read_env_raw IN_LABS_PWD)"
if [ -n "${IN_LABS_USER_RAW:-}" ] && [ -n "${IN_LABS_PWD_RAW:-}" ]; then
  log "Refreshing INLABS session cookie via login"
  INLABS_COOKIE_JAR="/tmp/inlabs.login.cookies"
  rm -f "$INLABS_COOKIE_JAR"
  curl -sS -c "$INLABS_COOKIE_JAR" -b "$INLABS_COOKIE_JAR" -A 'Mozilla/5.0' 'https://inlabs.in.gov.br/acessar.php' >/dev/null
  curl -sS -c "$INLABS_COOKIE_JAR" -b "$INLABS_COOKIE_JAR" -A 'Mozilla/5.0' \
    -e 'https://inlabs.in.gov.br/acessar.php' \
    --data-urlencode "email=$IN_LABS_USER_RAW" \
    --data-urlencode "password=$IN_LABS_PWD_RAW" \
    'https://inlabs.in.gov.br/logar.php' >/dev/null

  PHPSESSID="$(awk '$6=="PHPSESSID"{print $7}' "$INLABS_COOKIE_JAR" | tail -n1)"
  INLABSSESS="$(awk '$6=="inlabs_session_cookie"{print $7}' "$INLABS_COOKIE_JAR" | tail -n1)"
  TSCOOKIE="$(awk '$6=="TS016f630c"{print $7}' "$INLABS_COOKIE_JAR" | tail -n1)"
  if [ -n "${PHPSESSID:-}" ] && [ -n "${INLABSSESS:-}" ]; then
    export GABI_INLABS_COOKIE="PHPSESSID=$PHPSESSID; inlabs_session_cookie=$INLABSSESS; TS016f630c=$TSCOOKIE"
    log "INLABS cookie refreshed from credentials"
  else
    log "INLABS login did not produce session cookie; keeping existing GABI_INLABS_COOKIE"
  fi
fi

export DOTNET_ENVIRONMENT=Development
export ASPNETCORE_ENVIRONMENT=Development
export ConnectionStrings__Default="${ConnectionStrings__Default:-Host=localhost;Port=5433;Database=gabi;Username=gabi;Password=gabi_dev_password}"
export Gabi__ElasticsearchUrl="${GABI_ELASTICSEARCH_URL:-http://localhost:9200}"
export Gabi__RedisUrl="${GABI_REDIS_URL:-redis://:devredis@localhost:6380/0}"
export GABI_EMBEDDINGS_URL="${GABI_EMBEDDINGS_URL:-http://localhost:8080}"
export GABI_SOURCES_PATH="${GABI_SOURCES_PATH:-$ROOT/sources_v2.yaml}"
export GABI_AUTH_ENABLED="${GABI_AUTH_ENABLED:-false}"
export GABI_FETCH_UA_ROTATE_EVERY="${GABI_FETCH_UA_ROTATE_EVERY:-5}"
export GABI_RUN_MIGRATIONS=true
export Jwt__Key="${Jwt__Key:-dev-only-jwt-key-not-for-production-please-change-0123456789}"

log "Building host binaries"
dotnet build src/Gabi.Api/Gabi.Api.csproj -c Release >/dev/null
dotnet build src/Gabi.Worker/Gabi.Worker.csproj -c Release >/dev/null

log "Starting API"
(cd src/Gabi.Api && nohup dotnet bin/Release/net8.0/Gabi.Api.dll >"$API_LOG" 2>&1 &)

log "Waiting for API (and migrations)"
wait_http "$API_URL/health" 180

log "Starting Worker"
(cd src/Gabi.Worker && nohup dotnet bin/Release/net8.0/Gabi.Worker.dll >"$WORKER_LOG" 2>&1 &)
sleep 2

log "Authenticating operator"
TOKEN="$(curl -fsS -X POST "$API_URL/api/v1/auth/login" -H 'Content-Type: application/json' -d '{"username":"operator","password":"op123"}' | sed -n 's/.*"token":"\([^"]*\)".*/\1/p')"
if [ -z "${TOKEN:-}" ]; then
  echo "auth failed: empty token" >&2
  exit 1
fi

log "Triggering seed"
api_post "/api/v1/dashboard/seed" '{}' >/dev/null

log "Waiting for seed completion"
for i in $(seq 1 300); do
  STATUS="$(pg_scalar "SELECT COALESCE((SELECT \"Status\" FROM job_registry WHERE \"JobType\"='catalog_seed' ORDER BY \"CreatedAt\" DESC LIMIT 1),'')")"
  if [ "$STATUS" = "completed" ]; then break; fi
  if [ "$STATUS" = "failed" ] || [ "$STATUS" = "deadletter" ]; then
    echo "seed failed with status=$STATUS" >&2
    exit 1
  fi
  sleep 2
  if [ "$i" -eq 300 ]; then
    echo "seed timeout" >&2
    exit 1
  fi
done

log "Running DOU pipeline with chain_next=true max_docs_per_source=$MAX_DOCS"
api_post "/api/v1/dashboard/sources/$SOURCE_ID/run-pipeline" "{\"max_docs_per_source\":$MAX_DOCS,\"chain_next\":true,\"strict_coverage\":false}" >/dev/null

log "Waiting for pipeline to settle"
START_TS="$(date +%s)"
while true; do
  NOW="$(date +%s)"
  ELAPSED=$((NOW-START_TS))
  if [ "$ELAPSED" -ge "$TIMEOUT_SECONDS" ]; then
    echo "pipeline timeout after ${TIMEOUT_SECONDS}s" >&2
    exit 1
  fi

  ACTIVE="$(pg_scalar "SELECT COUNT(*) FROM job_registry WHERE \"SourceId\"='$SOURCE_ID' AND \"Status\" IN ('pending','processing')")"
  FAILED="$(pg_scalar "SELECT COUNT(*) FROM job_registry WHERE \"SourceId\"='$SOURCE_ID' AND \"Status\" IN ('failed','deadletter')")"
  DOCS="$(pg_scalar "SELECT COUNT(*) FROM documents WHERE \"SourceId\"='$SOURCE_ID'")"

  if [ "$ACTIVE" = "0" ] && [ "$DOCS" != "0" ] && [ "$FAILED" = "0" ]; then
    break
  fi
  sleep 5
done

DISCOVERED="$(pg_scalar "SELECT COUNT(*) FROM discovered_links WHERE \"SourceId\"='$SOURCE_ID' AND \"Status\"='active'")"
FETCHED="$(pg_scalar "SELECT COUNT(*) FROM fetch_items WHERE \"SourceId\"='$SOURCE_ID' AND \"Status\"='completed'")"
STORED="$(pg_scalar "SELECT COUNT(*) FROM documents WHERE \"SourceId\"='$SOURCE_ID'")"
NON_EMPTY="$(pg_scalar "SELECT COUNT(*) FROM documents WHERE \"SourceId\"='$SOURCE_ID' AND COALESCE(length(\"Content\"),0) > 0")"
WITH_DATE="$(pg_scalar "SELECT COUNT(*) FROM documents WHERE \"SourceId\"='$SOURCE_ID' AND \"Metadata\" ? 'data_publicacao'")"
WITH_SECTION="$(pg_scalar "SELECT COUNT(*) FROM documents WHERE \"SourceId\"='$SOURCE_ID' AND \"Metadata\" ? 'secao'")"
WITH_URL="$(pg_scalar "SELECT COUNT(*) FROM documents WHERE \"SourceId\"='$SOURCE_ID' AND (\"Metadata\" ? 'source_download_url' OR \"Metadata\" ? 'source_pdf_url')")"
WITH_PAGE="$(pg_scalar "SELECT COUNT(*) FROM documents WHERE \"SourceId\"='$SOURCE_ID' AND (\"Metadata\" ? 'pagina' OR \"Metadata\" ? 'page_start')")"
EMBEDDED="$(pg_scalar "SELECT COUNT(*) FROM documents WHERE \"SourceId\"='$SOURCE_ID' AND \"EmbeddingId\" IS NOT NULL")"
INDEXED="$(pg_scalar "SELECT COUNT(*) FROM documents WHERE \"SourceId\"='$SOURCE_ID' AND \"ElasticsearchId\" IS NOT NULL")"

ES_INDEXED="$(curl -fsS 'http://localhost:9200/gabi-docs/_count' -H 'Content-Type: application/json' -d "{\"query\":{\"term\":{\"sourceId\":\"$SOURCE_ID\"}}}" | sed -n 's/.*"count":\([0-9][0-9]*\).*/\1/p' | head -n1)"
ES_FILTER_DATE="$(curl -fsS 'http://localhost:9200/gabi-docs/_count' -H 'Content-Type: application/json' -d '{"query":{"bool":{"filter":[{"term":{"sourceId":"'"$SOURCE_ID"'"}},{"exists":{"field":"metadata.data_publicacao"}}]}}}' | sed -n 's/.*"count":\([0-9][0-9]*\).*/\1/p' | head -n1)"
ES_FILTER_SECTION="$(curl -fsS 'http://localhost:9200/gabi-docs/_count' -H 'Content-Type: application/json' -d '{"query":{"bool":{"filter":[{"term":{"sourceId":"'"$SOURCE_ID"'"}},{"exists":{"field":"metadata.secao"}}]}}}' | sed -n 's/.*"count":\([0-9][0-9]*\).*/\1/p' | head -n1)"

QUERY="ministro"
SEARCH_HITS="$(curl -fsS "$API_URL/api/v1/search?q=$QUERY&sourceId=$SOURCE_ID&page=1&pageSize=5" -H "Authorization: Bearer $TOKEN" | sed -n 's/.*"total":\([0-9][0-9]*\).*/\1/p' | head -n1)"

echo "DOU MCP STATUS"
echo "Discovered: ${DISCOVERED:-0}"
echo "Fetched: ${FETCHED:-0}"
echo "Stored: ${STORED:-0}"
echo "Indexed: ${INDEXED:-0} (es_count=${ES_INDEXED:-0})"
echo "Embedded: ${EMBEDDED:-0}"
echo "NonEmptyText: ${NON_EMPTY:-0}"
echo "Metadata date/section/url/page: ${WITH_DATE:-0}/${WITH_SECTION:-0}/${WITH_URL:-0}/${WITH_PAGE:-0}"
echo "ES metadata filters date/section: ${ES_FILTER_DATE:-0}/${ES_FILTER_SECTION:-0}"
echo "Example query: '$QUERY' Returned results: ${SEARCH_HITS:-0}"
echo "API log: $API_LOG"
echo "Worker log: $WORKER_LOG"
