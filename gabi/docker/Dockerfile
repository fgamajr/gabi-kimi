# GABI - Gerenciador de Análise de Base de Informações
# Multi-stage Dockerfile para Python 3.11
# Produção: imagem mínima com non-root user

# =============================================================================
# STAGE 1: Builder
# =============================================================================
FROM python:3.11-slim AS builder

# Build arguments
ARG PIP_NO_CACHE_DIR=1
ARG PIP_DISABLE_PIP_VERSION_CHECK=1
ARG POETRY_NO_INTERACTION=1

# Instalar dependências de build
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    libpq-dev \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# Configurar ambiente Python
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONFAULTHANDLER=1

# Criar diretório de trabalho
WORKDIR /build

# Copiar arquivos de dependências primeiro (para cache eficiente)
COPY pyproject.toml ./

# Instalar dependências em virtual environment
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Instalar pip atualizado e dependências
RUN pip install --upgrade pip setuptools wheel && \
    pip install \
    fastapi==0.109.2 \
    uvicorn[standard]==0.27.1 \
    sqlalchemy==2.0.28 \
    alembic==1.13.1 \
    asyncpg==0.29.0 \
    pgvector==0.5.1 \
    psycopg2-binary==2.9.9 \
    celery==5.3.6 \
    redis==5.0.1 \
    elasticsearch==8.11.0 \
    pydantic==2.6.3 \
    pydantic-settings==2.2.1 \
    httpx==0.27.0 \
    pdfplumber==0.11.0 \
    pypdfium2==4.27.0 \
    Pillow==10.2.0 \
    playwright==1.41.2 \
    anyio==4.3.0 \
    aiofiles==23.2.1 \
    python-dotenv==1.0.1 \
    python-multipart==0.0.9 \
    python-jose[cryptography]==3.3.0 \
    passlib[bcrypt]==1.7.4 \
    bcrypt==4.1.2 \
    PyJWT==2.8.0 \
    cryptography==42.0.5 \
    tenacity==8.2.3 \
    orjson==3.9.15 \
    ujson==5.9.0 \
    typer==0.9.0 \
    rich==13.7.1 \
    structlog==24.1.0

# =============================================================================
# STAGE 2: Runtime
# =============================================================================
FROM python:3.11-slim AS runtime

# Criar non-root user (uid 1000)
RUN groupadd --gid 1000 gabi && \
    useradd --uid 1000 --gid gabi --shell /bin/bash --create-home gabi

# Instalar dependências runtime necessárias
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Configurar ambiente Python
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONFAULTHANDLER=1 \
    PYTHONHASHSEED=random

# Copiar virtual environment do builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Criar diretório da aplicação
WORKDIR /app

# Copiar código fonte
COPY --chown=gabi:gabi gabi/src/gabi ./gabi
COPY --chown=gabi:gabi gabi/alembic ./alembic
COPY --chown=gabi:gabi gabi/alembic.ini ./
COPY --chown=gabi:gabi sources.yaml ./

# Criar diretórios necessários com permissões corretas
RUN mkdir -p /app/logs /app/tmp && chown -R gabi:gabi /app

# Mudar para non-root user
USER gabi

# Expor porta da aplicação
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Comando padrão
CMD ["uvicorn", "gabi.main:app", "--host", "0.0.0.0", "--port", "8000"]
