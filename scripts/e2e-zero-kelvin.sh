#!/usr/bin/env bash
# GABI - E2E Zero Kelvin: sobe infra, API e Worker; roda seed → discovery; confere DB;
# repete; depois dispara discovery SEM seed (fail-safe). No final mostra só resultados 1ª e 2ª rodada.
#
# Uso: ./scripts/e2e-zero-kelvin.sh
# Requer: docker, dotnet, curl, jq, psql (client libpq) no PATH. Opcional: .env no root.

set -e
GABI_ROOT="${GABI_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
cd "$GABI_ROOT"

for cmd in docker dotnet curl jq psql; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "Erro: $cmd não encontrado. Instale e coloque no PATH."
    exit 1
  fi
done

# Cores
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'
log_info()  { echo -e "${BLUE}$*${NC}"; }
log_ok()    { echo -e "${GREEN}$*${NC}"; }
log_warn()  { echo -e "${YELLOW}$*${NC}"; }
log_error() { echo -e "${RED}$*${NC}"; }

# Config (host)
API_URL="${GABI_API_URL:-http://localhost:5100}"
SOURCE_ID="${GABI_E2E_SOURCE:-tcu_acordaos}"
PG_HOST="${PGHOST:-localhost}"
PG_PORT="${GABI_POSTGRES_PORT:-5433}"
PG_USER="${PGUSER:-gabi}"
PG_PASS="${PGPASSWORD:-gabi_dev_password}"
PG_DB="${PGDATABASE:-gabi}"
export PGPASSWORD="$PG_PASS"

# Credenciais API (Operator para seed e refresh)
USERNAME="${GABI_E2E_USER:-operator}"
PASSWORD="${GABI_E2E_PASS:-op123}"

# Timeouts (segundos) - seed pode demorar com muitas fontes e retry; Worker pode demorar a iniciar
WAIT_SEED_MAX=240
WAIT_DISCOVERY_MAX=120
WAIT_FETCH_MAX=90
WAIT_INGEST_MAX=90
WAIT_API_MAX=30
POLL_INTERVAL=3

# Arquivos de resultado (só 1ª e 2ª rodada no final)
RESULTS_FILE="$GABI_ROOT/e2e-zero-kelvin-results.txt"
mkdir -p "$(dirname "$RESULTS_FILE")"

# ─── Helpers ─────────────────────────────────────────────────────────────────
pg_query() {
  psql -h "$PG_HOST" -p "$PG_PORT" -U "$PG_USER" -d "$PG_DB" -t -A -c "$1" 2>/dev/null || echo "0"
}

api_get() {
  local path="$1"
  if [ -n "$TOKEN" ]; then
    curl -sf -H "Authorization: Bearer $TOKEN" "$API_URL$path"
  else
    curl -sf "$API_URL$path"
  fi
}

# GET sem falhar em 4xx/5xx (para polling seed/last, discovery/last que retornam 404 até existir run)
api_get_soft() {
  local path="$1"
  if [ -n "$TOKEN" ]; then
    curl -s -H "Authorization: Bearer $TOKEN" "$API_URL$path"
  else
    curl -s "$API_URL$path"
  fi
}

api_post() {
  local path="$1"
  local body="${2:-{}}"
  if [ -n "$TOKEN" ]; then
    curl -sf -X POST -H "Content-Type: application/json" -H "Authorization: Bearer $TOKEN" -d "$body" "$API_URL$path"
  else
    curl -sf -X POST -H "Content-Type: application/json" -d "$body" "$API_URL$path"
  fi
}

wait_for_api() {
  log_info "Aguardando API em $API_URL (até ${WAIT_API_MAX}s)..."
  local i=0
  while [ "$i" -lt "$WAIT_API_MAX" ]; do
    if curl -sf "$API_URL/health" >/dev/null 2>&1; then
      log_ok "API pronta."
      log_info "Aguardando 5s para migrações concluírem..."
      sleep 5
      return 0
    fi
    sleep 1
    i=$((i + 1))
  done
  log_error "API não respondeu a tempo."
  return 1
}

login() {
  local res
  res=$(curl -sf -X POST -H "Content-Type: application/json" \
    -d "{\"username\":\"$USERNAME\",\"password\":\"$PASSWORD\"}" \
    "$API_URL/api/v1/auth/login") || true
  if [ -z "$res" ]; then
    log_error "Login falhou (sem resposta)."
    return 1
  fi
  TOKEN=$(echo "$res" | jq -r '.token // empty')
  if [ -z "$TOKEN" ] || [ "$TOKEN" = "null" ]; then
    log_error "Login falhou (token vazio). Resposta: $res"
    return 1
  fi
  log_ok "Login OK (Operator)."
  return 0
}

api_post_soft() {
  local path="$1"
  local body="${2:-{}}"
  if [ -n "$TOKEN" ]; then
    curl -s -X POST -H "Content-Type: application/json" -H "Authorization: Bearer $TOKEN" -d "$body" "$API_URL$path"
  else
    curl -s -X POST -H "Content-Type: application/json" -d "$body" "$API_URL$path"
  fi
}

trigger_seed() {
  api_post_soft "/api/v1/dashboard/seed"
}

trigger_discovery() {
  api_post_soft "/api/v1/dashboard/sources/$SOURCE_ID/phases/discovery" '{}'
}

trigger_fetch() {
  api_post_soft "/api/v1/dashboard/sources/$SOURCE_ID/phases/fetch" '{}'
}

trigger_ingest() {
  api_post_soft "/api/v1/dashboard/sources/$SOURCE_ID/phases/ingest" '{}'
}

wait_seed_completed() {
  local i=0
  while [ "$i" -lt "$WAIT_SEED_MAX" ]; do
    local last
    last=$(api_get_soft "/api/v1/dashboard/seed/last")
    if [ -n "$last" ]; then
      local status
      status=$(echo "$last" | jq -r '.status // empty')
      if [ "$status" = "completed" ] || [ "$status" = "partial" ]; then
        echo "$last"
        return 0
      fi
    fi
    sleep "$POLL_INTERVAL"
    i=$((i + POLL_INTERVAL))
  done
  return 1
}

wait_discovery_completed() {
  local i=0
  while [ "$i" -lt "$WAIT_DISCOVERY_MAX" ]; do
    local last
    last=$(api_get_soft "/api/v1/dashboard/sources/$SOURCE_ID/discovery/last")
    if [ -n "$last" ]; then
      local status
      status=$(echo "$last" | jq -r '.status // empty')
      if [ "$status" = "completed" ] || [ "$status" = "partial" ] || [ "$status" = "failed" ]; then
        echo "$last"
        return 0
      fi
    fi
    sleep "$POLL_INTERVAL"
    i=$((i + POLL_INTERVAL))
  done
  return 1
}

wait_fetch_completed() {
  local i=0
  while [ "$i" -lt "$WAIT_FETCH_MAX" ]; do
    local last
    last=$(api_get_soft "/api/v1/dashboard/sources/$SOURCE_ID/fetch/last")
    if [ -n "$last" ]; then
      local status
      status=$(echo "$last" | jq -r '.status // empty')
      if [ "$status" = "completed" ] || [ "$status" = "partial" ] || [ "$status" = "failed" ]; then
        echo "$last"
        return 0
      fi
    fi
    sleep "$POLL_INTERVAL"
    i=$((i + POLL_INTERVAL))
  done
  return 1
}

wait_ingest_completed() {
  local i=0
  while [ "$i" -lt "$WAIT_INGEST_MAX" ]; do
    local pending
    pending=$(pg_query "SELECT COUNT(*) FROM documents WHERE \"SourceId\" = '$SOURCE_ID' AND \"Status\" = 'pending';")
    if [ "${pending:-0}" = "0" ]; then
      echo "{\"status\":\"completed\",\"pending_docs\":0}"
      return 0
    fi
    sleep "$POLL_INTERVAL"
    i=$((i + POLL_INTERVAL))
  done
  return 1
}

# ─── Infra ───────────────────────────────────────────────────────────────────
wait_postgres() {
  log_info "Aguardando Postgres em $PG_HOST:$PG_PORT..."
  local i=0
  until psql -h "$PG_HOST" -p "$PG_PORT" -U "$PG_USER" -d "$PG_DB" -t -c "SELECT 1;" >/dev/null 2>&1; do
    sleep 1
    i=$((i + 1))
    if [ "$i" -ge 60 ]; then
      log_error "Postgres não respondeu em 60s."
      return 1
    fi
    echo -n "."
  done
  echo " OK"
  log_ok "Postgres pronto."
}

start_infra() {
  log_info "Subindo infra (Postgres, Redis, Elasticsearch)..."
  if [ -f "$GABI_ROOT/scripts/infra-up.sh" ]; then
    bash "$GABI_ROOT/scripts/infra-up.sh" || true
  else
    docker compose up -d
  fi
  wait_postgres || return 1
  log_ok "Infra pronta."
}

# ─── Apps (API + Worker) em background ─────────────────────────────────────────
start_apps() {
  log_info "Iniciando API e Worker (background)..."
  export GABI_RUN_MIGRATIONS=true
  [ -f "$GABI_ROOT/.env" ] && set -a && . "$GABI_ROOT/.env" && set +a
  export ConnectionStrings__Default="Host=localhost;Port=$PG_PORT;Database=gabi;Username=$PG_USER;Password=$PG_PASS"
  unset GABI_SOURCES_PATH  # limpa valor anterior que pode estar relativo
  export GABI_SOURCES_PATH="$GABI_ROOT/sources_v2.yaml"

  dotnet run --project "$GABI_ROOT/src/Gabi.Api/Gabi.Api.csproj" --no-build --urls "http://localhost:5100" > "$GABI_ROOT/e2e-api.log" 2>&1 &
  API_PID=$!
  sleep 2
  dotnet run --project "$GABI_ROOT/src/Gabi.Worker/Gabi.Worker.csproj" --no-build > "$GABI_ROOT/e2e-worker.log" 2>&1 &
  WORKER_PID=$!
  log_ok "API PID=$API_PID  Worker PID=$WORKER_PID"
}

stop_apps() {
  [ -n "$API_PID" ] && kill "$API_PID" 2>/dev/null || true
  [ -n "$WORKER_PID" ] && kill "$WORKER_PID" 2>/dev/null || true
  log_info "API e Worker encerrados."
}

# ─── Coleta resultados no banco (para exibir no final) ────────────────────────
snapshot_db() {
  local seed_runs
  local sources
  local discovery_runs
  local links
  local fetch_runs
  local fetch_items
  local docs_pending
  local docs_completed
  seed_runs=$(pg_query "SELECT COUNT(*) FROM seed_runs;")
  sources=$(pg_query "SELECT COUNT(*) FROM source_registry;")
  discovery_runs=$(pg_query "SELECT COUNT(*) FROM discovery_runs;")
  links=$(pg_query "SELECT COUNT(*) FROM discovered_links;")
  fetch_runs=$(pg_query "SELECT COUNT(*) FROM fetch_runs;")
  fetch_items=$(pg_query "SELECT COUNT(*) FROM fetch_items;")
  docs_pending=$(pg_query "SELECT COUNT(*) FROM documents WHERE \"Status\"='pending';")
  docs_completed=$(pg_query "SELECT COUNT(*) FROM documents WHERE \"Status\"='completed';")
  echo "seed_runs=$seed_runs source_registry=$sources discovery_runs=$discovery_runs discovered_links=$links fetch_runs=$fetch_runs fetch_items=$fetch_items docs_pending=$docs_pending docs_completed=$docs_completed"
}

# ─── Main ───────────────────────────────────────────────────────────────────
main() {
  log_info "═══════════════════════════════════════════════════════════════"
  log_info "  E2E Zero Kelvin: infra → seed → discovery → conferir DB"
  log_info "  Segunda rodada; depois discovery SEM seed (fail-safe)."
  log_info "═══════════════════════════════════════════════════════════════"
  echo ""

  docker compose down -v --remove-orphans >/dev/null 2>&1 || true
  start_infra
  dotnet build "$GABI_ROOT/src/Gabi.Api/Gabi.Api.csproj" -q
  dotnet build "$GABI_ROOT/src/Gabi.Worker/Gabi.Worker.csproj" -q
  start_apps
  wait_for_api || { log_error "API não subiu."; stop_apps; exit 1; }
  login || { log_error "Login falhou. Verifique Users em appsettings (operator/op123)."; stop_apps; exit 1; }

  # Resultados a exibir no final
  R1_SEED=""
  R1_DISCOVERY=""
  R1_FETCH=""
  R1_INGEST=""
  R1_DB=""
  R2_SEED=""
  R2_DISCOVERY=""
  R2_FETCH=""
  R2_INGEST=""
  R2_DB=""
  R3_DISCOVERY=""
  R3_DB=""

  # ─── 1ª RODADA: Seed → conferir DB → Discovery → conferir DB ─────────────────
  log_info "─── 1ª RODADA ───"
  trigger_seed >/dev/null
  log_info "Seed disparado; aguardando conclusão (até ${WAIT_SEED_MAX}s)..."
  R1_SEED=$(wait_seed_completed) || { log_warn "Seed não concluiu a tempo."; R1_SEED="timeout"; }
  R1_DB=$(snapshot_db)
  log_ok "DB após seed: $R1_DB"

  log_info "Discovery disparado para $SOURCE_ID; aguardando (até ${WAIT_DISCOVERY_MAX}s)..."
  trigger_discovery >/dev/null
  R1_DISCOVERY=$(wait_discovery_completed) || { log_warn "Discovery não concluiu a tempo."; R1_DISCOVERY="timeout"; }

  log_info "Fetch disparado para $SOURCE_ID; aguardando (até ${WAIT_FETCH_MAX}s)..."
  trigger_fetch >/dev/null
  R1_FETCH=$(wait_fetch_completed) || { log_warn "Fetch não concluiu a tempo."; R1_FETCH="timeout"; }

  log_info "Ingest disparado para $SOURCE_ID; aguardando (até ${WAIT_INGEST_MAX}s)..."
  trigger_ingest >/dev/null
  R1_INGEST=$(wait_ingest_completed) || { log_warn "Ingest não concluiu a tempo."; R1_INGEST="timeout"; }

  R1_DB=$(snapshot_db)
  log_ok "DB após discovery/fetch/ingest: $R1_DB"
  echo ""

  # ─── 2ª RODADA: Seed de novo → Discovery de novo ───────────────────────────
  log_info "─── 2ª RODADA (seed + discovery de novo) ───"
  trigger_seed >/dev/null
  R2_SEED=$(wait_seed_completed) || { log_warn "Seed não concluiu a tempo."; R2_SEED="timeout"; }
  R2_DB=$(snapshot_db)
  trigger_discovery >/dev/null
  R2_DISCOVERY=$(wait_discovery_completed) || { log_warn "Discovery não concluiu a tempo."; R2_DISCOVERY="timeout"; }
  trigger_fetch >/dev/null
  R2_FETCH=$(wait_fetch_completed) || { log_warn "Fetch não concluiu a tempo."; R2_FETCH="timeout"; }
  trigger_ingest >/dev/null
  R2_INGEST=$(wait_ingest_completed) || { log_warn "Ingest não concluiu a tempo."; R2_INGEST="timeout"; }
  R2_DB=$(snapshot_db)
  log_ok "DB após 2ª rodada: $R2_DB"
  echo ""

  # ─── FAIL-SAFE: Discovery SEM ter clicado em Seed antes ───────────────────
  log_info "─── FAIL-SAFE: Discovery SEM seed antes ───"
  stop_apps
  docker compose down -v --remove-orphans >/dev/null 2>&1 || true
  start_infra
  dotnet build "$GABI_ROOT/src/Gabi.Api/Gabi.Api.csproj" -q
  dotnet build "$GABI_ROOT/src/Gabi.Worker/Gabi.Worker.csproj" -q
  start_apps
  wait_for_api || { log_error "API não subiu para fail-safe."; stop_apps; exit 1; }
  login || { log_error "Login falhou para fail-safe."; stop_apps; exit 1; }

  R3_HTTP=$(curl -s -o /tmp/e2e-r3-body.txt -w "%{http_code}" \
    -X POST -H "Content-Type: application/json" -H "Authorization: Bearer $TOKEN" \
    -d '{}' "$API_URL/api/v1/dashboard/sources/$SOURCE_ID/phases/discovery")
  if [ "$R3_HTTP" -ge 400 ]; then
    R3_DISCOVERY="{\"status\":\"api_error\",\"http\":$R3_HTTP,\"body\":$(jq -Rs . < /tmp/e2e-r3-body.txt)}"
  else
    R3_DISCOVERY=$(wait_discovery_completed) || { log_warn "Discovery (sem seed) não concluiu a tempo."; R3_DISCOVERY="timeout"; }
  fi
  R3_DB=$(snapshot_db)
  log_ok "DB após discovery sem seed: $R3_DB"
  echo ""

  stop_apps

  # ─── Saída: só resultados 1ª e 2ª rodada (+ fail-safe) ─────────────────────
  summary_seed() { echo "$1" | jq -r 'if . == "timeout" then "timeout"; else "sources_seeded=\(.sources_seeded // "?"), status=\(.status // "?")"; end' 2>/dev/null || echo "$1"; }
  summary_disc() { echo "$1" | jq -r 'if . == "timeout" then "timeout"; else "links_total=\(.links_total // "?"), status=\(.status // "?")"; end' 2>/dev/null || echo "$1"; }
  summary_fetch() { echo "$1" | jq -r 'if . == "timeout" then "timeout"; else "items_total=\(.items_total // "?"), completed=\(.items_completed // "?"), failed=\(.items_failed // "?"), status=\(.status // "?")"; end' 2>/dev/null || echo "$1"; }
  summary_ingest() { echo "$1" | jq -r 'if . == "timeout" then "timeout"; else "status=\(.status // "?"), pending_docs=\(.pending_docs // "?")"; end' 2>/dev/null || echo "$1"; }
  {
    echo "═══════════════════════════════════════════════════════════════"
    echo "  E2E ZERO KELVIN - RESULTADOS"
    echo "═══════════════════════════════════════════════════════════════"
    echo ""
    echo "─── 1ª RODADA ───"
    echo "  Seed:     $(summary_seed "$R1_SEED")"
    echo "  Discovery: $(summary_disc "$R1_DISCOVERY")"
    echo "  Fetch:    $(summary_fetch "$R1_FETCH")"
    echo "  Ingest:   $(summary_ingest "$R1_INGEST")"
    echo "  DB:       $R1_DB"
    echo ""
    echo "─── 2ª RODADA ───"
    echo "  Seed:     $(summary_seed "$R2_SEED")"
    echo "  Discovery: $(summary_disc "$R2_DISCOVERY")"
    echo "  Fetch:    $(summary_fetch "$R2_FETCH")"
    echo "  Ingest:   $(summary_ingest "$R2_INGEST")"
    echo "  DB:       $R2_DB"
    echo ""
    echo "─── FAIL-SAFE (discovery sem seed antes) ───"
    echo "  Discovery: $(summary_disc "$R3_DISCOVERY")"
    echo "  DB:       $R3_DB"
    echo ""
    echo "─── Raw (1ª rodada) ───"
    echo "  Seed last:    $R1_SEED"
    echo "  Discovery last: $R1_DISCOVERY"
    echo "  Fetch last:   $R1_FETCH"
    echo "  Ingest:       $R1_INGEST"
    echo ""
    echo "─── Raw (2ª rodada) ───"
    echo "  Seed last:    $R2_SEED"
    echo "  Discovery last: $R2_DISCOVERY"
    echo "  Fetch last:   $R2_FETCH"
    echo "  Ingest:       $R2_INGEST"
    echo ""
  } | tee "$RESULTS_FILE"

  if [ -x "$GABI_ROOT/scripts/cardinality-report.sh" ]; then
    echo "" >> "$RESULTS_FILE"
    echo "─── Tabelas por estágio (contagens reais do banco) ───" >> "$RESULTS_FILE"
    "$GABI_ROOT/scripts/cardinality-report.sh" >> "$RESULTS_FILE"
  fi
  log_ok "Resultados gravados em $RESULTS_FILE"
}

trap 'stop_apps 2>/dev/null; exit 130' INT TERM
main "$@"
