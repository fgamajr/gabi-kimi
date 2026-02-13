#!/bin/bash
# GABI - Start infrastructure (PostgreSQL, Elasticsearch, Redis)
# Usage: ./scripts/infra-up.sh

set -e
# shellcheck source=scripts/_lib.sh
source "$(dirname "$0")/_lib.sh"

log_info "🐳 GABI - Starting infrastructure"
echo ""

check_docker_running || exit 1

if infra_is_running; then
    log_warn "Infrastructure is already running."
    echo "  Run ./scripts/infra-down.sh first if you need to restart."
    exit 0
fi

log_warn "Starting Docker containers..."
docker compose up -d

echo ""
log_warn "Waiting for services..."

echo -n "  🐘 PostgreSQL   "
until docker compose exec -T postgres pg_isready -U gabi >/dev/null 2>&1; do sleep 1; echo -n "."; done
echo -e " ${GABI_GREEN}✅${GABI_NC}"

echo -n "  🔍 Elasticsearch "
until curl -sf http://localhost:9200/_cluster/health >/dev/null 2>&1; do sleep 1; echo -n "."; done
echo -e " ${GABI_GREEN}✅${GABI_NC}"

echo -n "  🔄 Redis        "
until docker compose exec -T redis redis-cli ping >/dev/null 2>&1; do sleep 1; echo -n "."; done
echo -e " ${GABI_GREEN}✅${GABI_NC}"

echo ""
log_ok "Infrastructure ready."
echo ""
echo "Services:"
echo "  • PostgreSQL:  localhost:5433"
echo "  • Elastic:     http://localhost:9200"
echo "  • Redis:       localhost:6379"
echo ""
echo "Next: ./scripts/app-up.sh   or   ./scripts/dev app up"
echo "Stop: ./scripts/infra-down.sh"
echo ""
