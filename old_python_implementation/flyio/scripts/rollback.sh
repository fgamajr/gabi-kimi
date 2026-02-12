#!/bin/bash
# =============================================================================
# GABI Fly.io Rollback Script
# Emergency rollback procedures
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

# Rollback application to previous version
rollback_app() {
    local app=$1
    
    log "Rolling back $app..."
    
    # Get previous release
    local previous_release
    previous_release=$(fly releases list --app "$app" | head -3 | tail -1 | awk '{print $1}')
    
    if [ -z "$previous_release" ]; then
        error "Could not find previous release for $app"
    fi
    
    log "Reverting to release: $previous_release"
    fly deploy --app "$app" --image "${app}:release-${previous_release}"
    
    success "$app rolled back to release $previous_release"
}

# Emergency: Scale to zero (stop all traffic)
emergency_stop() {
    log "EMERGENCY STOP - Scaling all apps to zero..."
    
    for app in gabi-api gabi-mcp gabi-worker; do
        fly scale count 0 --app "$app" || warn "Could not scale $app"
    done
    
    success "All apps stopped"
    log "To resume: run ./03-deploy.sh"
}

# Restore database from backup
restore_database() {
    log "Database restore from backup"
    
    local backup_file=$1
    
    if [ ! -f "$backup_file" ]; then
        error "Backup file not found: $backup_file"
    fi
    
    log "WARNING: This will overwrite the current database!"
    read -rp "Are you sure? Type 'yes' to continue: " confirm
    
    if [ "$confirm" != "yes" ]; then
        log "Restore cancelled"
        return
    fi
    
    # Connect and restore
    fly postgres connect --app gabi-db --command "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"
    fly ssh console --app gabi-api --command "psql \$DATABASE_URL < /path/to/backup" || \
        error "Restore failed"
    
    success "Database restored"
}

# Switch DNS to local (emergency failover)
emergency_failover() {
    log "EMERGENCY FAILOVER to local infrastructure"
    
    warn "Update your DNS/load balancer to point to local IP"
    warn "Local infrastructure must be running!"
    
    echo ""
    echo "Steps:"
    echo "1. Ensure local services are running: docker compose --profile infra up -d"
    echo "2. Update DNS A record: gabi.tcu.gov.br -> LOCAL_IP"
    echo "3. Verify local health: curl http://localhost:8000/health"
    echo ""
    
    read -rp "Press Enter when ready to proceed..."
    
    # Scale Fly to zero
    emergency_stop
    
    success "Failover complete - traffic now routing to local"
}

# Main menu
show_menu() {
    echo ""
    log "GABI Emergency Rollback"
    log "======================="
    echo ""
    echo "1) Rollback API to previous version"
    echo "2) Rollback MCP to previous version"
    echo "3) Rollback Worker to previous version"
    echo "4) Rollback ALL apps"
    echo "5) EMERGENCY STOP (scale all to zero)"
    echo "6) EMERGENCY FAILOVER (route to local)"
    echo "7) Restore database from backup"
    echo "q) Quit"
    echo ""
}

main() {
    while true; do
        show_menu
        read -rp "Select option: " choice
        
        case $choice in
            1)
                rollback_app "gabi-api"
                ;;
            2)
                rollback_app "gabi-mcp"
                ;;
            3)
                rollback_app "gabi-worker"
                ;;
            4)
                rollback_app "gabi-api"
                rollback_app "gabi-mcp"
                rollback_app "gabi-worker"
                ;;
            5)
                warn "This will stop all services!"
                read -rp "Type 'STOP' to confirm: " confirm
                if [ "$confirm" = "STOP" ]; then
                    emergency_stop
                fi
                ;;
            6)
                warn "This will route traffic away from Fly.io!"
                read -rp "Type 'FAILOVER' to confirm: " confirm
                if [ "$confirm" = "FAILOVER" ]; then
                    emergency_failover
                fi
                ;;
            7)
                read -rp "Enter backup file path: " backup_file
                restore_database "$backup_file"
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
