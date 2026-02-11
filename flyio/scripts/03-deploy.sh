#!/bin/bash
# =============================================================================
# GABI Fly.io Deployment Script
# Deploy all applications
# =============================================================================

set -euo pipefail

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log() { echo -e "${BLUE}[INFO]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }
success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }

# Deploy an app
deploy_app() {
    local app=$1
    local config_path=$2
    
    log "Deploying $app..."
    
    if [ ! -f "$config_path/fly.toml" ]; then
        error "Configuration not found: $config_path/fly.toml"
    fi
    
    cd "$config_path"
    
    # Deploy
    fly deploy --app "$app" --config fly.toml --remote-only
    
    cd - >/dev/null
    
    success "$app deployed successfully"
}

# Wait for app to be healthy
wait_for_health() {
    local app=$1
    local path=${2:-/health}
    local max_attempts=30
    local attempt=1
    
    log "Waiting for $app to be healthy..."
    
    while [ $attempt -le $max_attempts ]; do
        if fly status --app "$app" | grep -q "healthy"; then
            success "$app is healthy"
            return 0
        fi
        
        log "Attempt $attempt/$max_attempts - waiting..."
        sleep 10
        attempt=$((attempt + 1))
    done
    
    warn "$app health check timed out. Check: fly logs --app $app"
    return 1
}

# Run migrations
run_migrations() {
    log "Running database migrations..."
    
    # Run migration in API container
    fly ssh console --app gabi-api --command "cd /app && alembic upgrade head" || \
        warn "Migration may have failed or already applied"
    
    success "Migrations complete"
}

# Main
main() {
    log "GABI Fly.io Deployment"
    log "======================"
    echo ""
    
    # Get script directory
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    FLYIO_DIR="$(dirname "$SCRIPT_DIR")"
    PROJECT_ROOT="$(dirname "$FLYIO_DIR")"
    
    cd "$PROJECT_ROOT"
    
    # Check apps exist
    for app in gabi-api gabi-mcp gabi-worker; do
        if ! fly apps list | grep -q "^${app}\s"; then
            error "App $app not found. Run ./01-setup-infrastructure.sh first"
        fi
    done
    
    # Deploy in order
    log "Step 1/4: Deploying gabi-api..."
    deploy_app "gabi-api" "$FLYIO_DIR/api"
    wait_for_health "gabi-api"
    
    log "Step 2/4: Running database migrations..."
    run_migrations
    
    log "Step 3/4: Deploying gabi-mcp..."
    deploy_app "gabi-mcp" "$FLYIO_DIR/mcp"
    wait_for_health "gabi-mcp"
    
    log "Step 4/4: Deploying gabi-worker..."
    deploy_app "gabi-worker" "$FLYIO_DIR/worker"
    
    echo ""
    success "All applications deployed!"
    echo ""
    echo "Services:"
    echo "  API:  https://gabi-api.fly.dev"
    echo "  MCP:  https://gabi-mcp.fly.dev"
    echo ""
    echo "Useful commands:"
    echo "  fly logs --app gabi-api       # View API logs"
    echo "  fly status --app gabi-api     # Check API status"
    echo "  fly ssh console --app gabi-api  # SSH into API"
}

main "$@"
