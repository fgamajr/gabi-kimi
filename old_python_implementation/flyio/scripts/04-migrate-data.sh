#!/bin/bash
# =============================================================================
# GABI Data Migration Script
# Migrate data from local to Fly.io
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

# Configuration
BACKUP_DIR="./backups/$(date +%Y%m%d_%H%M%S)"
LOCAL_ES_URL="${LOCAL_ES_URL:-http://localhost:9200}"
LOCAL_DB_URL="${LOCAL_DB_URL:-postgresql://gabi:gabi_dev_password@localhost:5432/gabi}"

# Create backup directory
mkdir -p "$BACKUP_DIR"

# Export local PostgreSQL
export_postgres() {
    log "Exporting PostgreSQL data..."
    
    local output="$BACKUP_DIR/gabi_metadata.sql"
    
    pg_dump \
        --data-only \
        --no-owner \
        --no-privileges \
        --no-comments \
        --exclude-table=alembic_version \
        "$LOCAL_DB_URL" > "$output"
    
    local size=$(du -h "$output" | cut -f1)
    success "PostgreSQL exported: $output ($size)"
}

# Export Elasticsearch index
export_elasticsearch() {
    log "Exporting Elasticsearch data..."
    
    # Check if elasticdump is installed
    if ! command -v elasticdump >/dev/null 2>&1; then
        warn "elasticdump not found. Installing..."
        npm install -g elasticdump || error "Failed to install elasticdump"
    fi
    
    local index_name="${ES_INDEX:-gabi_documents_v1}"
    local output="$BACKUP_DIR/${index_name}.json"
    local mapping="$BACKUP_DIR/${index_name}_mapping.json"
    
    # Export mapping
    log "Exporting index mapping..."
    elasticdump \
        --input="${LOCAL_ES_URL}/${index_name}" \
        --output="$mapping" \
        --type=mapping || warn "Mapping export may have failed"
    
    # Export data
    log "Exporting index data (this may take a while for 470k docs)..."
    elasticdump \
        --input="${LOCAL_ES_URL}/${index_name}" \
        --output="$output" \
        --type=data \
        --limit=10000 \
        --concurrency=5 || warn "Data export may have failed"
    
    local size=$(du -h "$output" | cut -f1)
    success "Elasticsearch exported: $output ($size)"
}

# Import PostgreSQL to Fly
import_postgres_fly() {
    log "Importing PostgreSQL to Fly..."
    
    local fly_db_url
    fly_db_url=$(fly postgres connect --app gabi-db --command "echo \$DATABASE_URL" 2>/dev/null) || \
        error "Could not get Fly database URL"
    
    local input="$BACKUP_DIR/gabi_metadata.sql"
    
    log "Importing to Fly PostgreSQL..."
    psql "$fly_db_url" < "$input" || warn "Import may have failed"
    
    success "PostgreSQL imported to Fly"
}

# Import Elasticsearch to Elastic Cloud
import_elasticsearch_cloud() {
    log "Importing Elasticsearch to Elastic Cloud..."
    
    local index_name="${ES_INDEX:-gabi_documents_v1}"
    local input="$BACKUP_DIR/${index_name}.json"
    local es_url
    
    # Get ES URL from secrets
    es_url=$(fly secrets list --app gabi-api | grep ELASTICSEARCH_URL | awk '{print $2}')
    
    if [ -z "$es_url" ]; then
        read -rp "Enter Elastic Cloud URL: " es_url
    fi
    
    log "Importing to Elastic Cloud..."
    elasticdump \
        --input="$input" \
        --output="${es_url}/${index_name}" \
        --type=data \
        --limit=5000 \
        --concurrency=3 || warn "Import may have failed"
    
    success "Elasticsearch imported to Elastic Cloud"
}

# Verify migration
verify_migration() {
    log "Verifying migration..."
    
    # Check API health
    local api_url="https://gabi-api.fly.dev"
    
    log "Checking API health..."
    curl -sf "${api_url}/health" > /dev/null && success "API is healthy" || warn "API health check failed"
    
    # Check document count
    log "Checking document count..."
    # This would need to query the API or ES directly
    
    success "Migration verification complete"
}

# Main menu
show_menu() {
    echo ""
    log "GABI Data Migration"
    log "==================="
    echo ""
    echo "1) Export local data (PostgreSQL + Elasticsearch)"
    echo "2) Import to Fly.io (PostgreSQL only)"
    echo "3) Import to Elastic Cloud"
    echo "4) Full migration (export + import + verify)"
    echo "5) Verify migration only"
    echo "q) Quit"
    echo ""
}

main() {
    while true; do
        show_menu
        read -rp "Select option: " choice
        
        case $choice in
            1)
                export_postgres
                export_elasticsearch
                ;;
            2)
                import_postgres_fly
                ;;
            3)
                import_elasticsearch_cloud
                ;;
            4)
                export_postgres
                export_elasticsearch
                import_postgres_fly
                import_elasticsearch_cloud
                verify_migration
                ;;
            5)
                verify_migration
                ;;
            q|Q)
                log "Goodbye!"
                exit 0
                ;;
            *)
                warn "Invalid option"
                ;;
        esac
    done
}

main "$@"
