#!/bin/bash
# GABI - Tail application logs
# Usage: ./scripts/app-logs.sh [api|all]

source "$(dirname "$0")/_lib.sh"
show_help() {
    echo "Usage: ./scripts/app-logs.sh api|all"
    echo "  api  - API log only"
    echo "  all  - API (default)"
}
case "${1:-all}" in
    api|API)   tail -f "$GABI_LOG_DIR/api.log" 2>/dev/null || echo "No API log." ;;
    all|ALL)   tail -f "$GABI_LOG_DIR/api.log" 2>/dev/null | sed 's/^/[API] /' ;;
    help|--help|-h) show_help ;;
    *) log_error "Unknown: $1"; show_help; exit 1 ;;
esac
