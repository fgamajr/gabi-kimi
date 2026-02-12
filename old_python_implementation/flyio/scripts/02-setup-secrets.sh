#!/bin/bash
# =============================================================================
# GABI Fly.io Secrets Setup
# Configure all sensitive environment variables
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

# Interactive prompt for secrets
prompt_secret() {
    local name=$1
    local description=$2
    local required=${3:-true}
    
    echo ""
    log "$description"
    
    if [ "$required" = true ]; then
        read -rp "$name (required): " value
        if [ -z "$value" ]; then
            error "$name is required"
        fi
    else
        read -rp "$name (optional, press Enter to skip): " value
    fi
    
    echo "$value"
}

# Set secrets for an app
set_app_secrets() {
    local app=$1
    shift
    
    log "Setting secrets for $app..."
    
    local secrets=()
    while [[ $# -gt 0 ]]; do
        secrets+=("$1=$2")
        shift 2
    done
    
    if [ ${#secrets[@]} -eq 0 ]; then
        warn "No secrets to set for $app"
        return
    fi
    
    printf '%s\n' "${secrets[@]}" | fly secrets import --app "$app"
    success "Secrets set for $app"
}

# Main configuration
main() {
    log "GABI Fly.io Secrets Setup"
    log "========================="
    echo ""
    echo "This script will configure all sensitive environment variables."
    echo "Have your credentials ready:"
    echo "  - PostgreSQL connection string"
    echo "  - Redis connection string"
    echo "  - Elasticsearch URL and credentials"
    echo "  - OpenAI API key (for embeddings)"
    echo "  - JWT/Keycloak configuration"
    echo ""
    read -rp "Press Enter to continue..."
    
    # =========================================================================
    # Database
    # =========================================================================
    echo ""
    log "=== Database Configuration ==="
    
    DB_URL=$(prompt_secret "GABI_DATABASE_URL" \
        "PostgreSQL connection string (e.g., postgresql+asyncpg://user:pass@host:5432/gabi)")
    
    # =========================================================================
    # Redis
    # =========================================================================
    echo ""
    log "=== Redis Configuration ==="
    
    REDIS_URL=$(prompt_secret "GABI_REDIS_URL" \
        "Redis connection string (e.g., redis://default:pass@host:6379)")
    
    REDIS_PASSWORD=$(prompt_secret "GABI_REDIS_PASSWORD" \
        "Redis password (if not in URL)" false)
    
    # =========================================================================
    # Elasticsearch
    # =========================================================================
    echo ""
    log "=== Elasticsearch Configuration ==="
    
    ES_URL=$(prompt_secret "GABI_ELASTICSEARCH_URL" \
        "Elasticsearch URL (e.g., https://your-cluster.es.us-east-1.aws.found.io:9243)")
    
    ES_USERNAME=$(prompt_secret "GABI_ELASTICSEARCH_USERNAME" \
        "Elasticsearch username" false)
    
    ES_PASSWORD=$(prompt_secret "GABI_ELASTICSEARCH_PASSWORD" \
        "Elasticsearch password" false)
    
    # =========================================================================
    # OpenAI (for embeddings in production)
    # =========================================================================
    echo ""
    log "=== OpenAI Configuration ==="
    
    OPENAI_API_KEY=$(prompt_secret "OPENAI_API_KEY" \
        "OpenAI API key for embeddings" false)
    
    # =========================================================================
    # Authentication
    # =========================================================================
    echo ""
    log "=== Authentication Configuration ==="
    
    JWT_ISSUER=$(prompt_secret "GABI_JWT_ISSUER" \
        "JWT Issuer (e.g., https://auth.tcu.gov.br/realms/tcu)" false)
    
    JWT_AUDIENCE=$(prompt_secret "GABI_JWT_AUDIENCE" \
        "JWT Audience (e.g., gabi-api)" false)
    
    JWT_JWKS_URL=$(prompt_secret "GABI_JWT_JWKS_URL" \
        "JWKS URL (e.g., https://auth.tcu.gov.br/realms/tcu/protocol/openid-connect/certs)" false)
    
    # =========================================================================
    # Application Secrets (if any)
    # =========================================================================
    echo ""
    log "=== Application Secrets ==="
    
    SECRET_KEY=$(prompt_secret "GABI_SECRET_KEY" \
        "Application secret key (for session signing if needed)" false)
    
    # =========================================================================
    # Set secrets for each app
    # =========================================================================
    echo ""
    log "=== Deploying Secrets ==="
    
    # Common secrets for all apps
    declare -A common_secrets
    common_secrets[GABI_DATABASE_URL]="$DB_URL"
    common_secrets[GABI_REDIS_URL]="$REDIS_URL"
    common_secrets[GABI_ELASTICSEARCH_URL]="$ES_URL"
    
    [ -n "$REDIS_PASSWORD" ] && common_secrets[GABI_REDIS_PASSWORD]="$REDIS_PASSWORD"
    [ -n "$ES_USERNAME" ] && common_secrets[GABI_ELASTICSEARCH_USERNAME]="$ES_USERNAME"
    [ -n "$ES_PASSWORD" ] && common_secrets[GABI_ELASTICSEARCH_PASSWORD]="$ES_PASSWORD"
    [ -n "$OPENAI_API_KEY" ] && common_secrets[OPENAI_API_KEY]="$OPENAI_API_KEY"
    [ -n "$JWT_ISSUER" ] && common_secrets[GABI_JWT_ISSUER]="$JWT_ISSUER"
    [ -n "$JWT_AUDIENCE" ] && common_secrets[GABI_JWT_AUDIENCE]="$JWT_AUDIENCE"
    [ -n "$JWT_JWKS_URL" ] && common_secrets[GABI_JWT_JWKS_URL]="$JWT_JWKS_URL"
    [ -n "$SECRET_KEY" ] && common_secrets[GABI_SECRET_KEY]="$SECRET_KEY"
    
    # Convert to array for set_app_secrets
    secret_args=()
    for key in "${!common_secrets[@]}"; do
        secret_args+=("$key" "${common_secrets[$key]}")
    done
    
    # Set for each app
    for app in gabi-api gabi-mcp gabi-worker; do
        if fly apps list | grep -q "^${app}\s"; then
            set_app_secrets "$app" "${secret_args[@]}"
        else
            warn "App $app not found, skipping"
        fi
    done
    
    echo ""
    success "Secrets setup complete!"
    echo ""
    echo "Next steps:"
    echo "  1. Verify secrets: fly secrets list --app gabi-api"
    echo "  2. Run: ./03-deploy.sh"
}

main "$@"
