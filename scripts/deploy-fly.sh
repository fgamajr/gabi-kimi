#!/bin/bash
# Deploy GABI to Fly.io
# Usage: ./deploy-fly.sh [environment] [--skip-build] [--skip-migrate]

set -euo pipefail

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
ENVIRONMENT="${1:-production}"
APP_NAME="gabi-api"
REGION="gru"
SKIP_BUILD=false
SKIP_MIGRATE=false

# Parse arguments
for arg in "$@"; do
    case $arg in
        --skip-build) SKIP_BUILD=true ;;
        --skip-migrate) SKIP_MIGRATE=true ;;
        --help)
            echo "Usage: ./deploy-fly.sh [environment] [options]"
            echo ""
            echo "Environments:"
            echo "  production    Deploy to production (default)"
            echo "  staging       Deploy to staging"
            echo ""
            echo "Options:"
            echo "  --skip-build   Skip Docker build"
            echo "  --skip-migrate Skip database migrations"
            echo "  --help         Show this help"
            exit 0
            ;;
    esac
done

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check prerequisites
check_prerequisites() {
    log_info "Checking prerequisites..."
    
    if ! command -v fly &> /dev/null; then
        log_error "flyctl not found. Please install: https://fly.io/docs/hands-on/install-flyctl/"
        exit 1
    fi
    
    if ! fly auth whoami &> /dev/null; then
        log_error "Not logged in to Fly.io. Run: fly auth login"
        exit 1
    fi
    
    log_success "Prerequisites OK"
}

# Load environment-specific config
load_env_config() {
    local env_file=".env.${ENVIRONMENT}"
    
    if [[ -f "$env_file" ]]; then
        log_info "Loading environment from $env_file"
        set -a
        source "$env_file"
        set +a
    fi
    
    # Override app name for staging
    if [[ "$ENVIRONMENT" == "staging" ]]; then
        APP_NAME="gabi-api-staging"
    fi
}

# Set secrets
set_secrets() {
    log_info "Setting secrets..."
    
    # Required secrets
    local secrets=(
        "SECRET_KEY"
        "OPENAI_API_KEY"
        "DATABASE_URL"
        "VECTOR_DB_PASSWORD"
        "REDIS_PASSWORD"
    )
    
    local missing=()
    for secret in "${secrets[@]}"; do
        if [[ -z "${!secret:-}" ]]; then
            missing+=("$secret")
        fi
    done
    
    if [[ ${#missing[@]} -gt 0 ]]; then
        log_error "Missing required secrets: ${missing[*]}"
        log_info "Set them with: fly secrets set SECRET_NAME=value -a $APP_NAME"
        exit 1
    fi
    
    # Set all secrets
    log_info "Uploading secrets to Fly.io..."
    fly secrets set \
        SECRET_KEY="$SECRET_KEY" \
        OPENAI_API_KEY="$OPENAI_API_KEY" \
        DATABASE_URL="$DATABASE_URL" \
        VECTOR_DB_PASSWORD="$VECTOR_DB_PASSWORD" \
        REDIS_PASSWORD="$REDIS_PASSWORD" \
        -a "$APP_NAME" --stage
    
    log_success "Secrets configured"
}

# Deploy application
deploy_app() {
    log_info "Deploying $APP_NAME to $ENVIRONMENT..."
    
    local deploy_args=""
    
    if [[ "$SKIP_BUILD" == true ]]; then
        deploy_args="$deploy_args --image-label latest"
    fi
    
    fly deploy \
        --app "$APP_NAME" \
        --config fly.toml \
        --region "$REGION" \
        $deploy_args \
        --ha
    
    log_success "Deployment complete"
}

# Run migrations
run_migrations() {
    if [[ "$SKIP_MIGRATE" == true ]]; then
        log_warn "Skipping database migrations"
        return
    fi
    
    log_info "Running database migrations..."
    
    fly ssh console -a "$APP_NAME" -C "python -m alembic upgrade head"
    
    log_success "Migrations complete"
}

# Verify deployment
verify_deployment() {
    log_info "Verifying deployment..."
    
    local health_url="https://${APP_NAME}.fly.dev/health"
    local max_attempts=10
    local attempt=1
    
    while [[ $attempt -le $max_attempts ]]; do
        log_info "Health check attempt $attempt/$max_attempts..."
        
        if curl -sf "$health_url" &> /dev/null; then
            log_success "Health check passed!"
            
            # Show deployment info
            echo ""
            echo "=========================================="
            echo "  Deployment Information"
            echo "=========================================="
            echo "  Environment: $ENVIRONMENT"
            echo "  App: $APP_NAME"
            echo "  URL: https://${APP_NAME}.fly.dev"
            echo "  Health: $health_url"
            echo "=========================================="
            
            return 0
        fi
        
        sleep 5
        ((attempt++))
    done
    
    log_error "Health check failed after $max_attempts attempts"
    log_info "Check logs: fly logs -a $APP_NAME"
    return 1
}

# Scale workers
scale_workers() {
    log_info "Scaling workers..."
    
    # Scale based on environment
    case "$ENVIRONMENT" in
        production)
            fly scale count worker=3 -a "$APP_NAME"
            ;;
        staging)
            fly scale count worker=1 -a "$APP_NAME"
            ;;
        *)
            fly scale count worker=1 -a "$APP_NAME"
            ;;
    esac
    
    log_success "Workers scaled"
}

# Main
main() {
    echo "=========================================="
    echo "  GABI Deployment Script"
    echo "  Environment: $ENVIRONMENT"
    echo "=========================================="
    echo ""
    
    check_prerequisites
    load_env_config
    
    # Confirm for production
    if [[ "$ENVIRONMENT" == "production" ]]; then
        log_warn "You are about to deploy to PRODUCTION!"
        read -p "Are you sure? (yes/no): " confirm
        if [[ "$confirm" != "yes" ]]; then
            log_info "Deployment cancelled"
            exit 0
        fi
    fi
    
    set_secrets
    deploy_app
    run_migrations
    scale_workers
    verify_deployment
    
    log_success "All done! 🚀"
}

# Handle errors
trap 'log_error "Deployment failed! Check logs above."' ERR

main "$@"
