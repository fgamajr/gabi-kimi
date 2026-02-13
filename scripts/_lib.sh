#!/bin/bash
# GABI - Scripts shared library
# Source this in other scripts. Do not execute directly.

# ─── Ensure dotnet tools are in PATH
export PATH="$PATH:$HOME/.dotnet/tools"

# ─── Load nvm if available (needed for non-interactive shells / CI)
if [ -z "$(command -v nvm 2>/dev/null)" ]; then
    export NVM_DIR="${NVM_DIR:-$HOME/.nvm}"
    [ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh" --no-use
    # Use latest installed node
    if [ -d "$NVM_DIR/versions/node" ]; then
        local_node=$(ls -1 "$NVM_DIR/versions/node" | sort -V | tail -1)
        [ -n "$local_node" ] && export PATH="$NVM_DIR/versions/node/$local_node/bin:$PATH"
    fi
fi

# ─── Repo root (must be set by caller or here)
if [ -z "${GABI_ROOT}" ]; then
    GABI_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
fi
export GABI_ROOT
cd "$GABI_ROOT" || exit 1

# ─── Paths (single source of truth)
export GABI_SCRIPTS="$GABI_ROOT/scripts"
export GABI_WEB_DIR="$GABI_ROOT/src/Gabi.Web"
export GABI_API_PROJECT="$GABI_ROOT/src/Gabi.Api"
export GABI_POSTGRES_PROJECT="$GABI_ROOT/src/Gabi.Postgres"
export GABI_LOG_DIR="${GABI_LOG_DIR:-/tmp/gabi-logs}"

# ─── Colors
export GABI_GREEN='\033[0;32m'
export GABI_YELLOW='\033[1;33m'
export GABI_RED='\033[0;31m'
export GABI_BLUE='\033[0;34m'
export GABI_NC='\033[0m'

# ─── Helpers
log_info()  { echo -e "${GABI_BLUE}$*${GABI_NC}"; }
log_ok()    { echo -e "${GABI_GREEN}$*${GABI_NC}"; }
log_warn()  { echo -e "${GABI_YELLOW}$*${GABI_NC}"; }
log_error() { echo -e "${GABI_RED}$*${GABI_NC}"; }

# ─── Check if a command exists; optional min version (e.g. 18 for node).
# Returns 0 if ok, 1 if missing, 2 if version too low.
# Usage: check_cmd "node" "https://nodejs.org/" "18"
# Sets GABI_CMD_VERSION to the version string if present.
check_cmd() {
    local name="$1"
    local install_url="${2:-}"
    local min_version="${3:-}"
    GABI_CMD_VERSION=""

    if ! command -v "$name" >/dev/null 2>&1; then
        log_error "  ❌ $name not found"
        [ -n "$install_url" ] && echo "     Install: $install_url"
        return 1
    fi

    local version=""
    case "$name" in
        dotnet) version=$(dotnet --version 2>/dev/null) ;;
        docker)  version=$(docker --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1) ;;
        node)    version=$(node -v 2>/dev/null | sed 's/^v//') ;;
        npm)     version=$(npm -v 2>/dev/null) ;;
        *)       version="ok" ;;
    esac
    GABI_CMD_VERSION="$version"

    if [ -n "$min_version" ] && [ -n "$version" ]; then
        local major
        major=$(echo "$version" | cut -d. -f1)
        if [ -n "$major" ] && [ "$major" -lt "$min_version" ] 2>/dev/null; then
            log_error "  ❌ $name $version found; $min_version+ required"
            [ -n "$install_url" ] && echo "     Install: $install_url"
            return 2
        fi
    fi

    log_ok "  ✅ $name: ${version:-ok}"
    return 0
}

# ─── Check Docker daemon is running
check_docker_running() {
    if ! docker info >/dev/null 2>&1; then
        log_error "Docker is not running. Start Docker Desktop (or the daemon) and try again."
        return 1
    fi
    return 0
}

# ─── Check if infrastructure (Postgres) is running
infra_is_running() {
    docker compose ps 2>/dev/null | grep -qi "postgres.*\(running\|healthy\|up\)"
}

# ─── Ensure dependencies for app (dotnet, node). Exit 1 if missing.
require_app_deps() {
    local err=0
    check_cmd "dotnet" "https://dotnet.microsoft.com/download" || err=$((err + 1))
    check_cmd "node"   "https://nodejs.org/ (v18+)" "18"     || err=$((err + 1))
    if [ "$err" -gt 0 ]; then
        log_error "Install missing dependencies and try again."
        exit 1
    fi
}

# ─── Ensure dependencies for setup (dotnet, docker, node 18+, npm). Exit 1 if missing.
require_setup_deps() {
    local err=0
    check_cmd "dotnet" "https://dotnet.microsoft.com/download" || err=$((err + 1))
    check_cmd "docker" "https://docs.docker.com/get-docker/"    || err=$((err + 1))
    check_cmd "node"   "https://nodejs.org/ (v18+)" "18"       || err=$((err + 1))
    check_cmd "npm"    "https://nodejs.org/"                    || err=$((err + 1))
    if [ "$err" -gt 0 ]; then
        echo ""
        log_error "Please install missing dependencies and run setup again."
        exit 1
    fi
    check_docker_running || exit 1
}
