# =============================================================================
# GABI - Gerador Automático de Boletins por Inteligência Artificial
# Dockerfile Multi-Stage
# ADR-007: Container Runtime - Docker multi-stage, non-root user
# =============================================================================

# -----------------------------------------------------------------------------
# STAGE 1: Builder
# Instala dependências de build e compila pacotes Python
# -----------------------------------------------------------------------------
FROM python:3.11-slim as builder

# Evita prompts interativos durante o build
ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Instala dependências de build necessárias
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    g++ \
    libpq-dev \
    libffi-dev \
    libssl-dev \
    pkg-config \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Cria diretório de trabalho
WORKDIR /build

# Copia arquivos de dependências primeiro (cache otimizado)
COPY pyproject.toml ./

# Cria virtual environment
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Instala pip atualizado
RUN pip install --upgrade pip setuptools wheel

# Instala dependências do projeto
RUN pip install \
    fastapi>=0.109.0 \
    uvicorn[standard]>=0.27.0 \
    sqlalchemy[asyncio]>=2.0.0 \
    asyncpg>=0.29.0 \
    alembic>=1.13.0 \
    pgvector>=0.2.0 \
    celery>=5.3.0 \
    redis>=5.0.0 \
    elasticsearch>=8.11.0,<8.12.0 \
    httpx>=0.27.0 \
    pydantic>=2.6.0 \
    pydantic-settings>=2.2.0 \
    python-jose[cryptography]>=3.3.0 \
    PyJWT>=2.8.0 \
    python-multipart>=0.0.9 \
    python-dotenv>=1.0.0 \
    typer>=0.9.0 \
    rich>=13.7.0 \
    structlog>=24.1.0 \
    orjson>=3.9.0 \
    tenacity>=8.2.0 \
    prometheus-client>=0.19.0 \
    bcrypt>=4.1.0 \
    passlib[bcrypt]>=1.7.0 \
    cryptography>=42.0.0 \
    PyYAML>=6.0.0 \
    aiofiles>=23.2.0

# -----------------------------------------------------------------------------
# STAGE 2: Runtime
# Imagem final otimizada com apenas o necessário para execução
# -----------------------------------------------------------------------------
FROM python:3.11-slim as runtime

# Metadados da imagem
LABEL maintainer="TCU - Tribunal de Contas da União <ti@tcu.gov.br>" \
      description="GABI - Gerador Automático de Boletins por IA" \
      version="2.1.0"

# Evita prompts interativos
ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONFAULTHANDLER=1

# Instala dependências de runtime apenas
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    tini \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Cria non-root user para segurança
RUN groupadd --gid 1000 gabi && \
    useradd --uid 1000 --gid gabi --shell /bin/bash --create-home gabi

# Copia virtual environment do builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Define diretório de trabalho
WORKDIR /app

# Copia código da aplicação
COPY --chown=gabi:gabi src/ ./src/

# Instala aplicação em modo editable
RUN pip install -e ./src/gabi 2>/dev/null || echo "Skipping editable install"

# Muda para non-root user
USER gabi

# Expõe porta da aplicação
EXPOSE 8000

# Healthcheck
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Usa tini como init system
ENTRYPOINT ["/usr/bin/tini", "--"]

# Comando padrão
CMD ["uvicorn", "gabi.main:app", "--host", "0.0.0.0", "--port", "8000"]
