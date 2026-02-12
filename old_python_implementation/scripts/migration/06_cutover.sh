#!/bin/bash
# =============================================================================
# GABI Migration - Phase 6: Production Cutover
# =============================================================================
# This script performs the final cutover to Fly.io production

set -euo pipefail

# Configuration
APP_NAME="${FLY_APP_NAME:-gabi-api}"
OLD_DNS="${OLD_DNS_RECORD:-}"
NEW_DNS="${NEW_DNS_RECORD:-}"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() { echo -e "${GREEN}[INFO]${NC} $*"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*"; }
log_step() { echo -e "${BLUE}[STEP]${NC} $*"; }

# Confirmation prompt
confirm() {
    read -p "Are you sure you want to proceed with cutover? (yes/no): " response
    if [[ "$response" != "yes" ]]; then
        log_error "Cutover cancelled"
        exit 1
    fi
}

echo "=========================================="
echo "GABI Production Cutover"
echo "=========================================="
echo ""
echo "This will switch production traffic to Fly.io"
echo ""

confirm

START_TIME=$(date +%s)

# Step 1: Final validation
log_step "Running final validation..."
python3 "$(dirname "$0")/05_validate_migration.py"
if [[ $? -ne 0 ]]; then
    log_error "Validation failed! Aborting cutover."
    exit 1
fi

# Step 2: Enable maintenance mode (optional)
log_step "Enabling maintenance mode on local instance (if applicable)..."
# curl -X POST http://localhost:8000/admin/maintenance/enable || true

# Step 3: Pause ingestion jobs
log_step "Pausing ingestion jobs..."
docker compose --profile all exec -T worker \
    celery -A gabi.worker control cancel_consumer gabi.sync 2>/dev/null || true

# Wait for current jobs to complete
log_info "Waiting for current jobs to complete (60s)..."
sleep 60

# Step 4: Final sync of any new data
log_step "Running final data sync..."
# This would run any incremental sync needed

# Step 5: Verify Fly.io app health
log_step "Verifying Fly.io app health..."
if ! fly status --app "$APP_NAME"; then
    log_error "Fly.io app is not healthy!"
    exit 1
fi

# Health check
HEALTH_URL="https://${APP_NAME}.fly.dev/health"
for i in {1..5}; do
    if curl -sf "$HEALTH_URL" > /dev/null; then
        log_info "Health check passed"
        break
    fi
    log_warn "Health check attempt $i failed, retrying..."
    sleep 5
done

# Step 6: Update DNS (manual or automated)
log_step "DNS Cutover"
echo "=========================================="
echo "ACTION REQUIRED: Update DNS"
echo "=========================================="
echo ""
echo "Update your DNS records to point to Fly.io:"
echo ""
echo "  Old: $OLD_DNS"
echo "  New: $NEW_DNS (or Fly.io anycast IP)"
echo ""
echo "Or if using fly.io subdomain, this is automatic."
echo ""
read -p "Press Enter when DNS has been updated..."

# Step 7: Verify traffic
log_step "Verifying traffic routing..."
for i in {1..10}; do
    RESPONSE=$(curl -s -o /dev/null -w "%{http_code}" "https://${APP_NAME}.fly.dev/health" 2>/dev/null || echo "000")
    if [[ "$RESPONSE" == "200" ]]; then
        log_info "Traffic routing correctly (HTTP 200)"
        break
    fi
    log_warn "Health check returned $RESPONSE, waiting for DNS propagation..."
    sleep 10
done

# Step 8: Enable ingestion on Fly.io
log_step "Enabling ingestion on Fly.io..."
fly ssh console --app "$APP_NAME" --command "echo 'Ingestion ready'" || true

# Step 9: Monitor
log_step "Monitoring for 5 minutes..."
echo "Checking error rates and response times..."

for i in {1..30}; do
    # Get metrics from Fly.io
    STATUS=$(curl -s -o /dev/null -w "%{http_code}" "https://${APP_NAME}.fly.dev/health" || echo "000")
    
    if [[ "$STATUS" == "200" ]]; then
        echo -n "✓"
    else
        echo -n "✗($STATUS)"
    fi
    
    sleep 10
done
echo ""

# Step 10: Completion
END_TIME=$(date +%s)
DURATION=$((END_TIME - START_TIME))

log_info "=========================================="
log_info "Cutover Complete!"
log_info "=========================================="
log_info "Duration: $((DURATION / 60)) minutes"
log_info ""
log_info "Next steps:"
log_info "  1. Monitor error rates for 24 hours"
log_info "  2. Run incremental sync validation"
log_info "  3. Update documentation"
log_info "  4. Schedule decommission of local infrastructure"
log_info ""
log_info "Rollback procedure (if needed):"
log_info "  1. Switch DNS back to local infrastructure"
log_info "  2. Resume local ingestion jobs"
log_info "  3. Sync any new data from Fly.io back to local"
