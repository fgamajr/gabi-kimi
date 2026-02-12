#!/bin/bash
# =============================================================================
# GABI Fly.io Infrastructure Setup
# Run this first to provision databases and caches
# =============================================================================

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

error() {
    echo -e "${RED}[ERROR]${NC} $1"
    exit 1
}

success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

# Check prerequisites
check_prerequisites() {
    log "Checking prerequisites..."
    
    command -v fly >/dev/null 2>&1 || error "fly CLI not found. Install: curl -L https://fly.io/install.sh | sh"
    
    fly auth whoami >/dev/null 2>&1 || error "Not authenticated with Fly.io. Run: fly auth login"
    
    success "Prerequisites OK"
}

# Create PostgreSQL database
setup_postgres() {
    log "Setting up Fly Postgres..."
    
    # Check if already exists
    if fly apps list | grep -q "gabi-db"; then
        warn "PostgreSQL app 'gabi-db' already exists. Skipping creation."
        return
    fi
    
    log "Creating PostgreSQL cluster..."
    fly postgres create \
        --name gabi-db \
        --region gru \
        --initial-cluster-size 1 \
        --vm-size shared-cpu-1x \
        --volume-size 10 \
        --auto-confirm
    
    success "PostgreSQL created: gabi-db"
}

# Create Upstash Redis
setup_redis() {
    log "Setting up Upstash Redis..."
    
    # Check if already exists
    if fly ext redis list | grep -q "gabi-redis"; then
        warn "Redis 'gabi-redis' already exists. Skipping creation."
        return
    fi
    
    log "Creating Upstash Redis..."
    fly ext redis create \
        --name gabi-redis \
        --region gru \
        --auto-confirm || warn "Redis creation may have failed or already exists"
    
    success "Redis configured: gabi-redis"
}

# Create Fly apps
setup_apps() {
    log "Creating Fly applications..."
    
    local apps=("gabi-api" "gabi-mcp" "gabi-worker")
    
    for app in "${apps[@]}"; do
        if fly apps list | grep -q "^${app}\s"; then
            warn "App '$app' already exists. Skipping."
            continue
        fi
        
        log "Creating app: $app"
        fly apps create "$app" --org personal || warn "App $app may already exist"
    done
    
    success "Applications created"
}

# Create volumes
setup_volumes() {
    log "Creating volumes..."
    
    # API uploads volume
    if ! fly volumes list --app gabi-api 2>/dev/null | grep -q "gabi_uploads"; then
        fly volumes create gabi_uploads \
            --app gabi-api \
            --region gru \
            --size 1
    else
        warn "Volume gabi_uploads already exists for gabi-api"
    fi
    
    # Worker data volume
    if ! fly volumes list --app gabi-worker 2>/dev/null | grep -q "gabi_worker_data"; then
        fly volumes create gabi_worker_data \
            --app gabi-worker \
            --region gru \
            --size 5
    else
        warn "Volume gabi_worker_data already exists for gabi-worker"
    fi
    
    success "Volumes created"
}

# Get connection strings
get_connection_strings() {
    log "Retrieving connection strings..."
    
    echo ""
    echo "=========================================="
    echo "Connection Strings (save these securely):"
    echo "=========================================="
    echo ""
    
    # PostgreSQL
    log "PostgreSQL connection:"
    fly postgres connect --app gabi-db --command "\conninfo" 2>/dev/null || \
        warn "Could not get PostgreSQL connection info. Run manually: fly postgres connect -a gabi-db"
    
    # Redis
    log "Redis connection:"
    fly ext redis status --app gabi-api 2>/dev/null || \
        warn "Could not get Redis connection info. Run manually: fly ext redis status -a gabi-api"
    
    echo ""
    echo "=========================================="
}

# Main
main() {
    log "GABI Fly.io Infrastructure Setup"
    log "================================="
    echo ""
    
    check_prerequisites
    setup_postgres
    setup_redis
    setup_apps
    setup_volumes
    get_connection_strings
    
    success "Infrastructure setup complete!"
    echo ""
    echo "Next steps:"
    echo "  1. Run: ./02-setup-secrets.sh"
    echo "  2. Configure Elasticsearch (Elastic Cloud)"
    echo "  3. Run: ./03-deploy.sh"
}

main "$@"
