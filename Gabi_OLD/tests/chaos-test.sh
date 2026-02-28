#!/usr/bin/env bash
# ╔═══════════════════════════════════════════════════════════════╗
# ║ DEPRECATED: Este script esta sendo migrado para o            ║
# ║ ReliabilityLab C# (tests/ReliabilityLab/).                  ║
# ║ Ver: tests/ReliabilityLab/README.md para a versao moderna.   ║
# ╚═══════════════════════════════════════════════════════════════╝
# ═══════════════════════════════════════════════════════════════════════════════
# GABI - Chaos Test Runner (Staging Validation Playbook)
# ═══════════════════════════════════════════════════════════════════════════════
# Executa experimentos de chaos definidos em docs/reliability/CHAOS_PLAYBOOK.md.
# Só pode rodar em ambiente NÃO-Production (DOTNET_ENVIRONMENT != Production).
# Timeout global: 15 minutos. Rollback é executado ao sair (trap) ou ao final.
#
# Uso:
#   ./tests/chaos-test.sh list              # Lista experimentos disponíveis
#   ./tests/chaos-test.sh 1                  # Experimento 1 (DB Hiccup)
#   ./tests/chaos-test.sh db-hiccup         # Idem por nome
#
# Para limite rígido de 15 min, rode: timeout 900 ./tests/chaos-test.sh 1
#
# Em caso de falha persistente (ex.: job zumbi após Exp 5), use:
#   ./tests/zero-kelvin-test.sh docker-only
#
# ═══════════════════════════════════════════════════════════════════════════════

set -euo pipefail

GABI_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$GABI_ROOT"
LOG_FILE="${LOG_FILE:-/tmp/gabi-chaos-test.log}"
CHAOS_TIMEOUT=900

# Rollback state (so trap can run the right cleanup)
ROLLBACK_EXP=""

log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"
}

err() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: $*" | tee -a "$LOG_FILE" >&2
}

# ═══════════════════════════════════════════════════════════════════════════════
# Safety: refuse to run in Production
# ═══════════════════════════════════════════════════════════════════════════════
check_environment() {
  local env="${DOTNET_ENVIRONMENT:-}"
  if [[ "$env" == "Production" ]]; then
    err "Chaos tests MUST NOT run when DOTNET_ENVIRONMENT=Production. Current: Production"
    err "Set DOTNET_ENVIRONMENT=Staging or Development, or unset it for local runs."
    exit 1
  fi
  log "Environment check OK (DOTNET_ENVIRONMENT=${env:-<unset>})"
}

# ═══════════════════════════════════════════════════════════════════════════════
# Rollback (run on exit or after experiment)
# ═══════════════════════════════════════════════════════════════════════════════
run_rollback() {
  case "$ROLLBACK_EXP" in
    1|db-hiccup)
      log "Rollback Exp 1: unpause postgres"
      docker compose unpause postgres 2>/dev/null || true
      ;;
    4|es-split)
      log "Rollback Exp 4: flush iptables OUTPUT (requires capability or root)"
      iptables -D OUTPUT -p tcp --dport 9200 -j DROP 2>/dev/null || iptables -F OUTPUT 2>/dev/null || true
      ;;
    *)
      if [[ -n "$ROLLBACK_EXP" ]]; then
        log "Rollback for experiment $ROLLBACK_EXP: see CHAOS_PLAYBOOK.md for manual steps"
      fi
      ;;
  esac
  ROLLBACK_EXP=""
}

trap run_rollback EXIT

# ═══════════════════════════════════════════════════════════════════════════════
# Experiment list (for list command and dispatch)
# ═══════════════════════════════════════════════════════════════════════════════
list_experiments() {
  cat << 'EOF'
Experiments:
  1 | db-hiccup         The Transient Database Hiccup (PostgreSQL stall 15s)
  2 | tarpit            The Indestructible Tarpit (slow HTTP) - manual/stub
  3 | poison-pill       The Poison Pill Bomb - manual/stub
  4 | es-split          Network Split-Brain (ES outage) - manual/stub
  5 | ghost-deploy      The Ghost Deploy (SIGTERM) - manual/stub
  6 | replay-surge      The Replay Amplification Surge - manual/stub
  7 | duplicate-delivery The Duplicate Delivery Test - manual/stub
  8 | clock-skew        Clock Skew Anomaly - manual/stub

Use: ./tests/chaos-test.sh <number|name>
EOF
}

# ═══════════════════════════════════════════════════════════════════════════════
# Experiment 1: PostgreSQL stall (docker pause 15s, then unpause)
# ═══════════════════════════════════════════════════════════════════════════════
run_exp1() {
  log "Experiment 1: Transient Database Hiccup - pausing postgres for 15s"
  ROLLBACK_EXP="1"
  if ! docker compose ps postgres -q 2>/dev/null | head -1 | grep -q .; then
    err "Postgres service not running. Start infra with: docker compose up -d postgres"
    return 1
  fi
  docker compose pause postgres
  log "Postgres paused; waiting 15s..."
  sleep 15
  docker compose unpause postgres
  ROLLBACK_EXP=""
  log "Experiment 1 complete: postgres unpaused. Check worker logs and DLQ for Transient retries."
  return 0
}

# ═══════════════════════════════════════════════════════════════════════════════
# Stub runners for experiments not yet implemented
# ═══════════════════════════════════════════════════════════════════════════════
run_stub() {
  local name="$1"
  log "Experiment $name: not automated. See docs/reliability/CHAOS_PLAYBOOK.md for fault injection and rollback."
  return 0
}

# ═══════════════════════════════════════════════════════════════════════════════
# Dispatch by argument
# ═══════════════════════════════════════════════════════════════════════════════
run_experiment() {
  local arg="${1:-}"
  case "$arg" in
    1|db-hiccup)        run_exp1 ;;
    2|tarpit)           run_stub "2 (Tarpit)" ;;
    3|poison-pill)       run_stub "3 (Poison Pill)" ;;
    4|es-split)          run_stub "4 (ES Split-Brain)" ;;
    5|ghost-deploy)      run_stub "5 (Ghost Deploy)" ;;
    6|replay-surge)      run_stub "6 (Replay Surge)" ;;
    7|duplicate-delivery) run_stub "7 (Duplicate Delivery)" ;;
    8|clock-skew)        run_stub "8 (Clock Skew)" ;;
    *)
      err "Unknown experiment: $arg"
      list_experiments
      return 1
      ;;
  esac
}

# ═══════════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════════
main() {
  check_environment

  if [[ "${1:-}" == "list" ]]; then
    list_experiments
    exit 0
  fi

  if [[ -z "${1:-}" ]]; then
    err "Usage: $0 list | <experiment_number_or_name>"
    list_experiments
    exit 1
  fi

  case "$1" in
    1|db-hiccup) ROLLBACK_EXP="1" ;;
    4|es-split)  ROLLBACK_EXP="4" ;;
  esac

  log "Chaos test started: $1 (max ${CHAOS_TIMEOUT}s; use: timeout 900 $0 $1)"
  if run_experiment "$1"; then
    log "Chaos test finished: $1 PASS"
    exit 0
  else
    err "Chaos test finished: $1 FAIL"
    exit 1
  fi
}

main "$@"
