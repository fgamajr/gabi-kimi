#!/bin/bash
# GABI Pipeline Deployment Script
# ===============================
#
# This script automates the deployment of the GABI automated pipeline.
# It sets up the database schema, systemd service, and configuration files.

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
GABI_HOME="${GABI_HOME:-/opt/gabi}"
GABI_USER="${GABI_USER:-gabi}"
GABI_GROUP="${GABI_GROUP:-gabi}"
PYTHON_VENV="${PYTHON_VENV:-${GABI_HOME}/.venv}"
DSN="${DSN:-host=localhost port=5433 dbname=gabi user=gabi password=gabi}"

# Logging functions
log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if running as root
if [ "$EUID" -ne 0 ]; then 
    log_error "This script must be run as root"
    exit 1
fi

# Step 1: Create GABI user and group
log_info "Step 1: Creating GABI user and group"
if ! getent group "$GABI_GROUP" > /dev/null; then
    groupadd "$GABI_GROUP"
    log_info "Created group: $GABI_GROUP"
else
    log_info "Group already exists: $GABI_GROUP"
fi

if ! id "$GABI_USER" > /dev/null 2>&1; then
    useradd -g "$GABI_GROUP" -d "$GABI_HOME" -s /bin/bash "$GABI_USER"
    log_info "Created user: $GABI_USER"
else
    log_info "User already exists: $GABI_USER"
fi

# Step 2: Create directory structure
log_info "Step 2: Creating directory structure"
mkdir -p "$GABI_HOME"
mkdir -p "$GABI_HOME/ops/data/inlabs"
mkdir -p "$GABI_HOME/logs"
mkdir -p "$GABI_HOME/config"

chown -R "$GABI_USER:$GABI_GROUP" "$GABI_HOME"
chmod 755 "$GABI_HOME"

# Step 3: Copy application files
log_info "Step 3: Copying application files"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
mkdir -p "$GABI_HOME/src/backend"
mkdir -p "$GABI_HOME/bin"
mkdir -p "$GABI_HOME/config/sources"
cp -r "$SCRIPT_DIR/../ingest" "$GABI_HOME/"
cp -r "$SCRIPT_DIR/../dbsync" "$GABI_HOME/"
cp -r "$SCRIPT_DIR/../search" "$GABI_HOME/"
cp -r "$SCRIPT_DIR/../src/backend/ingest" "$GABI_HOME/src/backend/"
cp -r "$SCRIPT_DIR/../src/backend/dbsync" "$GABI_HOME/src/backend/"
cp -r "$SCRIPT_DIR/../src/backend/search" "$GABI_HOME/src/backend/"
cp -r "$SCRIPT_DIR/../src" "$GABI_HOME/"
cp -r "$SCRIPT_DIR/../commitment" "$GABI_HOME/"
cp -r "$SCRIPT_DIR/../config" "$GABI_HOME/config/"
cp "$SCRIPT_DIR/../ops/bin/web_server.py" "$GABI_HOME/bin/"
cp "$SCRIPT_DIR/../ops/bin/mcp_server.py" "$GABI_HOME/bin/"
cp "$SCRIPT_DIR/../ops/bin/mcp_es_server.py" "$GABI_HOME/bin/"
cp "$SCRIPT_DIR/../ops/bin/schema_sync.py" "$GABI_HOME/bin/"
cp "$SCRIPT_DIR/../ops/bin/commitment_cli.py" "$GABI_HOME/bin/"
cp "$SCRIPT_DIR/../config/sources/sources_v3.yaml" "$GABI_HOME/config/sources/"
cp "$SCRIPT_DIR/../config/sources/sources_v3.identity-test.yaml" "$GABI_HOME/config/sources/"
cp "$SCRIPT_DIR/../requirements.txt" "$GABI_HOME/"

chown -R "$GABI_USER:$GABI_GROUP" "$GABI_HOME"

# Step 4: Setup Python virtual environment
log_info "Step 4: Setting up Python virtual environment"
if [ ! -d "$PYTHON_VENV" ]; then
    sudo -u "$GABI_USER" python3 -m venv "$PYTHON_VENV"
    log_info "Created virtual environment: $PYTHON_VENV"
else
    log_info "Virtual environment already exists: $PYTHON_VENV"
fi

# Install dependencies
sudo -u "$GABI_USER" "$PYTHON_VENV/bin/pip" install -U pip
sudo -u "$GABI_USER" "$PYTHON_VENV/bin/pip" install -r "$GABI_HOME/requirements.txt"
log_info "Installed Python dependencies"

# Step 5: Setup database schema
log_info "Step 5: Setting up database schema"

# Check if PostgreSQL is running
if ! pg_isready -h localhost -p 5433 > /dev/null 2>&1; then
    log_warn "PostgreSQL is not running on port 5433"
    log_warn "Please start PostgreSQL and run this step manually:"
    log_warn "  psql '$DSN' -f $GABI_HOME/src/backend/dbsync/download_registry_schema.sql"
else
    # Create download registry schema
    sudo -u "$GABI_USER" psql "$DSN" -f "$GABI_HOME/src/backend/dbsync/download_registry_schema.sql"
    log_info "Created download registry schema"
    
    # Create discovery registry schema (via Python)
    sudo -u "$GABI_USER" "$PYTHON_VENV/bin/python" -c "
from src.backend.ingest.discovery_registry import PostgreSQLDiscoveryRegistry
registry = PostgreSQLDiscoveryRegistry('$DSN')
print('Discovery registry schema created')
"
    log_info "Created discovery registry schema"
fi

# Step 6: Setup systemd service
log_info "Step 6: Setting up systemd service"

# Copy systemd files
cp "$GABI_HOME/config/systemd/gabi-ingest.service" /etc/systemd/system/
cp "$GABI_HOME/config/systemd/gabi-ingest.timer" /etc/systemd/system/

# Update service file with correct paths
sed -i "s|/opt/gabi|$GABI_HOME|g" /etc/systemd/system/gabi-ingest.service
sed -i "s|gabi|$GABI_USER|g" /etc/systemd/system/gabi-ingest.service

systemctl daemon-reload
log_info "Systemd service and timer configured"

# Step 7: Create environment file
log_info "Step 7: Creating environment configuration"

cat > "$GABI_HOME/.env" <<EOF
# GABI Pipeline Environment Configuration
# Generated by deploy.sh on $(date)

# Database connection
GABI_DSN=$DSN

# Data directories
GABI_DATA_DIR=$GABI_HOME/ops/data/inlabs
GABI_LOG_DIR=$GABI_HOME/logs

# Pipeline configuration
GABI_CONFIG=$GABI_HOME/config/production.yaml

# Python
PATH=$PYTHON_VENV/bin:\$PATH
EOF

chown "$GABI_USER:$GABI_GROUP" "$GABI_HOME/.env"
chmod 600 "$GABI_HOME/.env"
log_info "Environment file created: $GABI_HOME/.env"

# Step 8: Create production configuration
log_info "Step 8: Creating production configuration"

cat > "$GABI_HOME/config/production.yaml" <<EOF
# GABI Production Pipeline Configuration
# Generated by deploy.sh on $(date)

data_dir: "$GABI_HOME/ops/data/inlabs"

database:
  dsn: "\${GABI_DSN}"

discovery:
  auto_discover: true
  lookback_days: 1
  sections: null

download:
  sections: null
  include_extras: true
  skip_existing: true
  max_concurrent: 1

ingestion:
  seal_commitment: true
  sources_yaml: "$GABI_HOME/config/sources/sources_v3.yaml"
  identity_yaml: "$GABI_HOME/config/sources/sources_v3.identity-test.yaml"

error_handling:
  max_retries: 3
  retry_delay_seconds: 300
  stop_on_error: false

reporting:
  generate_report: true
  report_output: "$GABI_HOME/logs/pipeline_\$(date +%%Y-%%m-%%d_%%H-%%M-%%S).json"
  log_to_stdout: true
  log_level: "INFO"
EOF

chown "$GABI_USER:$GABI_GROUP" "$GABI_HOME/config/production.yaml"
log_info "Production configuration created: $GABI_HOME/config/production.yaml"

# Step 9: Enable and start systemd timer
log_info "Step 9: Enabling systemd timer"

systemctl enable gabi-ingest.timer
systemctl start gabi-ingest.timer

log_info "Systemd timer enabled and started"

# Step 10: Test the setup
log_info "Step 10: Testing the setup"

log_info "Checking systemd timer status..."
systemctl status gabi-ingest.timer --no-pager

log_info "Checking database connection..."
if sudo -u "$GABI_USER" "$PYTHON_VENV/bin/python" -c "
import psycopg
conn = psycopg.connect('$DSN')
print('✓ Database connection successful')
conn.close()
"; then
    log_info "Database connection test passed"
else
    log_error "Database connection test failed"
    exit 1
fi

# Summary
echo ""
echo "========================================"
echo "  GABI Pipeline Deployment Complete"
echo "========================================"
echo ""
echo "Deployment directory: $GABI_HOME"
echo "User: $GABI_USER"
echo "Group: $GABI_GROUP"
echo ""
echo "Next steps:"
echo "  1. Review configuration: $GABI_HOME/config/production.yaml"
echo "  2. Check systemd timer: sudo systemctl status gabi-ingest.timer"
echo "  3. View logs: sudo journalctl -u gabi-ingest.service -f"
echo "  4. Test pipeline manually: sudo -u $GABI_USER $PYTHON_VENV/bin/python -m src.backend.ingest.orchestrator --days 1 --dry-run"
echo "  5. Enable timer (if not already): sudo systemctl enable gabi-ingest.timer"
echo ""
echo "The pipeline will run automatically every day at 2:00 AM."
echo ""
