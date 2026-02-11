# =============================================================================
# GABI MCP Hybrid Search Server - Dockerfile
# =============================================================================
# 
# This Dockerfile builds the MCP Hybrid Search Server with:
# - Hybrid search capabilities (exact + semantic + RRF)
# - SSE transport for ChatTCU integration
# - JWT authentication via Keycloak
# - Rate limiting via Redis
#
# Build:
#   docker build -f docker/mcp-hybrid.Dockerfile -t gabi-mcp-hybrid:latest .
#
# Run:
#   docker run -p 8001:8001 gabi-mcp-hybrid:latest
#
# =============================================================================

FROM python:3.12-slim as builder

# Build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install uv for fast package management
RUN pip install uv

WORKDIR /build

# Copy dependency files
COPY pyproject.toml ./
COPY src/ ./src/

# Create virtual environment and install dependencies
RUN uv venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
RUN uv pip install -e ".[mcp]"

# =============================================================================
# Production Stage
# =============================================================================

FROM python:3.12-slim as production

# Security: Run as non-root user
RUN groupadd -r gabi && useradd -r -g gabi gabi

# Runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy virtual environment from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Set working directory
WORKDIR /app

# Copy application code
COPY --from=builder /build/src ./src

# Copy configuration files
COPY sources.yaml ./
COPY alembic.ini ./
COPY alembic/ ./alembic/

# Environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONFAULTHANDLER=1 \
    GABI_ENVIRONMENT=production \
    GABI_MCP_ENABLED=true \
    GABI_MCP_PORT=8001 \
    GABI_MCP_AUTH_REQUIRED=true

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8001/health || exit 1

# Switch to non-root user
USER gabi

# Expose port
EXPOSE 8001

# Start MCP Hybrid Search Server
CMD ["python", "-m", "gabi.mcp.server_hybrid"]
