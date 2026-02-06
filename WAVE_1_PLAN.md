# WAVE 1: FOUNDATION

## Visão Geral

| Campo | Valor |
|-------|-------|
| **Wave** | 1 - Foundation |
| **Objetivo** | Projeto base funcional com config, testes e Docker |
| **Duração Estimada** | 2-3 dias |
| **Dependências** | Nenhuma (wave inicial) |
| **Próxima Wave** | Wave 2: Database & Models |

---

## Objetivo

Ter um projeto Python funcional onde:
- `make test` → pytest passa
- `docker-compose -f docker-compose.local.yml up` → sobe todos os serviços
- `make lint` → ruff passa
- `make typecheck` → mypy passa

---

## Tarefas (Ordem de Dependência)

### T1: Estrutura de Diretórios Base

**Arquivos:**
```
gabi/
├── src/gabi/
│   ├── __init__.py
│   ├── config.py          # T2
│   ├── exceptions.py      # T3
│   ├── db.py              # T4
│   ├── logging_config.py  # T3
│   └── models/
│       ├── __init__.py
│       └── base.py        # T5
├── tests/
│   ├── __init__.py
│   ├── conftest.py        # T6
│   ├── factories.py       # T6
│   └── unit/
│       ├── __init__.py
│       └── test_config.py # T6
├── docker/
│   └── Dockerfile         # T7
├── scripts/
│   └── setup-local.sh     # T7
├── pyproject.toml         # T1
├── requirements.txt       # T1
├── requirements-dev.txt   # T1
├── docker-compose.local.yml # T7
├── .env.example           # T7
├── Makefile               # T8
└── .gitignore             # T1
```

**Critério de Aceitação:**
- [ ] Diretórios criados com `__init__.py` em todos os pacotes
- [ ] `.gitignore` configurado para Python, IDEs, arquivos de ambiente

---

### T2: Configuração (config.py)

**Referência:** Seção 2.6 das especificações

**Implementação:**
```python
# src/gabi/config.py
from enum import Enum
from typing import Optional, List
from pydantic import Field, HttpUrl, field_validator, model_validator
from pydantic_settings import BaseSettings


class Environment(str, Enum):
    LOCAL = "local"
    STAGING = "staging"
    PRODUCTION = "production"


class Settings(BaseSettings):
    """Configuração centralizada do GABI.
    
    Variáveis são validadas no startup. Falha rápido em config inválida.
    """
    
    model_config = {
        "env_prefix": "GABI_",
        "env_file": ".env",
        "case_sensitive": False,
        "extra": "forbid",  # Rejeita variáveis não definidas
    }

    # === Ambiente ===
    environment: Environment = Field(default=Environment.LOCAL)
    debug: bool = Field(default=False)
    log_level: str = Field(default="info", pattern=r"^(debug|info|warning|error|critical)$")
    
    # === PostgreSQL ===
    database_url: str = Field(..., description="PostgreSQL connection URL")
    database_pool_size: int = Field(default=10, ge=1, le=100)
    database_max_overflow: int = Field(default=20, ge=0, le=100)
    database_pool_timeout: int = Field(default=30, ge=1, le=300)
    database_echo: bool = Field(default=False)
    
    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, v: str) -> str:
        if not v.startswith(("postgresql://", "postgresql+asyncpg://")):
            raise ValueError("database_url must start with 'postgresql' or 'postgresql+asyncpg'")
        return v
    
    # === Elasticsearch ===
    elasticsearch_url: HttpUrl = Field(default="http://localhost:9200")
    elasticsearch_index: str = Field(default="gabi_documents_v1")
    elasticsearch_timeout: int = Field(default=30, ge=1, le=300)
    elasticsearch_max_retries: int = Field(default=3, ge=0, le=10)
    elasticsearch_username: Optional[str] = Field(default=None)
    elasticsearch_password: Optional[str] = Field(default=None)
    
    # === Redis ===
    redis_url: HttpUrl = Field(default="redis://localhost:6379/0")
    redis_dlq_db: int = Field(default=1, ge=0, le=15)
    redis_cache_db: int = Field(default=2, ge=0, le=15)
    redis_lock_db: int = Field(default=3, ge=0, le=15)
    
    # === Embeddings (TEI) - IMUTÁVEL ===
    embeddings_url: HttpUrl = Field(default="http://localhost:8080")
    embeddings_model: str = Field(
        default="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        frozen=True
    )
    embeddings_dimensions: int = Field(default=384, frozen=True)  # IMUTÁVEL
    embeddings_batch_size: int = Field(default=32, ge=1, le=256)
    embeddings_timeout: int = Field(default=60, ge=1, le=300)
    embeddings_max_retries: int = Field(default=3, ge=0, le=10)
    
    # === Pipeline ===
    pipeline_max_memory_mb: int = Field(default=3584, ge=512, le=32768)
    pipeline_fetch_timeout: int = Field(default=60, ge=1, le=600)
    pipeline_fetch_max_size_mb: int = Field(default=100, ge=1, le=1000)
    pipeline_chunk_max_tokens: int = Field(default=512, ge=100, le=2048)
    pipeline_chunk_overlap_tokens: int = Field(default=50, ge=0, le=500)
    
    # === Auth ===
    jwt_issuer: HttpUrl = Field(default="https://auth.tcu.gov.br/realms/tcu")
    jwt_audience: str = Field(default="gabi-api")
    jwt_jwks_url: HttpUrl = Field(
        default="https://auth.tcu.gov.br/realms/tcu/protocol/openid-connect/certs"
    )
    jwt_algorithm: str = Field(default="RS256", pattern=r"^(RS256|RS384|RS512|ES256|ES384|ES512)$")
    jwt_jwks_cache_minutes: int = Field(default=5, ge=1, le=15)
    auth_enabled: bool = Field(default=True)
    auth_public_paths: List[str] = Field(default=["/health", "/metrics", "/docs", "/openapi.json"])
    
    @model_validator(mode="after")
    def validate_auth_in_production(self):
        if self.environment == Environment.PRODUCTION and not self.auth_enabled:
            raise ValueError("auth_enabled must be True in production")
        return self
    
    # === CORS ===
    cors_origins: List[str] = Field(default=["http://localhost:3000"])
    cors_allow_credentials: bool = Field(default=True)
    
    @model_validator(mode="after")
    def validate_cors_in_production(self):
        if self.environment == Environment.PRODUCTION:
            if "*" in self.cors_origins:
                raise ValueError("CORS wildcard not allowed in production")
            if "http://" in str(self.cors_origins):
                raise ValueError("HTTP origins not allowed in production (use HTTPS)")
        return self
    
    # === API ===
    api_host: str = Field(default="0.0.0.0")
    api_port: int = Field(default=8000, ge=1024, le=65535)
    api_workers: int = Field(default=1, ge=1, le=10)


# Singleton global
settings = Settings()
```

**Critério de Aceitação:**
- [ ] Config carrega de variáveis de ambiente
- [ ] Validação de URLs funciona
- [ ] Validação de auth em produção funciona
- [ ] Validação de CORS em produção funciona

---

### T3: Logging e Exceptions

**T3.1: Hierarquia de Exceções (exceptions.py)**

```python
# src/gabi/exceptions.py
"""Hierarquia de exceções do GABI.

Todas as exceções herdam de GABIException para facilitar catch global.
"""


class GABIException(Exception):
    """Exceção base do GABI."""
    
    def __init__(self, message: str, details: dict = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


# Configuração
class ConfigurationError(GABIException):
    """Erro de configuração inválida."""
    pass


# Database
class DatabaseError(GABIException):
    """Erro de banco de dados."""
    pass


class ConnectionError(DatabaseError):
    """Erro de conexão com banco."""
    pass


# Pipeline
class PipelineError(GABIException):
    """Erro no pipeline de ingestão."""
    pass


class FetchError(PipelineError):
    """Erro ao fazer download de documento."""
    pass


class ParseError(PipelineError):
    """Erro ao parsear documento."""
    pass


class DeduplicationError(PipelineError):
    """Erro na deduplicação."""
    pass


class EmbeddingError(PipelineError):
    """Erro ao gerar embeddings."""
    pass


class IndexingError(PipelineError):
    """Erro ao indexar documento."""
    pass


# Fontes
class SourceError(GABIException):
    """Erro relacionado a fonte de dados."""
    pass


class SourceNotFoundError(SourceError):
    """Fonte não encontrada."""
    pass


class SourceConfigError(SourceError):
    """Configuração de fonte inválida."""
    pass


# Auth
class AuthenticationError(GABIException):
    """Erro de autenticação."""
    pass


class AuthorizationError(GABIException):
    """Erro de autorização."""
    pass


class TokenExpiredError(AuthenticationError):
    """Token JWT expirado."""
    pass


class TokenInvalidError(AuthenticationError):
    """Token JWT inválido."""
    pass


# Search
class SearchError(GABIException):
    """Erro na busca."""
    pass


class ValidationError(GABIException):
    """Erro de validação de dados."""
    pass
```

**T3.2: Logging Estruturado (logging_config.py)**

```python
# src/gabi/logging_config.py
"""Configuração de logging estruturado para o GABI."""

import logging
import sys
from typing import Any, Dict

import structlog
from pythonjsonlogger import jsonlogger


def setup_logging(log_level: str = "info", json_format: bool = False) -> None:
    """Configura logging estruturado.
    
    Args:
        log_level: Nível de log (debug, info, warning, error, critical)
        json_format: Se True, usa formato JSON (produção)
    """
    
    # Configurar structlog
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.processors.JSONRenderer() if json_format else structlog.dev.ConsoleRenderer(),
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )
    
    # Configurar logging padrão
    level = getattr(logging, log_level.upper())
    
    if json_format:
        log_format = "%(timestamp)s %(level)s %(name)s %(message)s"
        formatter = jsonlogger.JsonFormatter(log_format)
    else:
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
    
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    handler.setLevel(level)
    
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    root_logger.addHandler(handler)
    
    # Reduzir verbosidade de libs
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("elasticsearch").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Retorna logger configurado."""
    return structlog.get_logger(name)
```

**Critério de Aceitação:**
- [ ] Exceções podem ser importadas e usadas
- [ ] Logger estruturado funciona
- [ ] Log level é respeitado

---

### T4: Database Layer (db.py)

**Implementação:**

```python
# src/gabi/db.py
"""Database layer com SQLAlchemy async."""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import declarative_base
from sqlalchemy.pool import NullPool

from gabi.config import settings
from gabi.logging_config import get_logger

logger = get_logger(__name__)

# Base declarativa para models
Base = declarative_base()


class DatabaseManager:
    """Gerenciador de conexões com PostgreSQL."""
    
    def __init__(self) -> None:
        self._engine = None
        self._session_maker = None
    
    def initialize(self) -> None:
        """Inicializa engine e session maker."""
        
        # Converter URL para asyncpg se necessário
        database_url = str(settings.database_url)
        if database_url.startswith("postgresql://"):
            database_url = database_url.replace("postgresql://", "postgresql+asyncpg://", 1)
        
        self._engine = create_async_engine(
            database_url,
            echo=settings.database_echo,
            pool_size=settings.database_pool_size,
            max_overflow=settings.database_max_overflow,
            pool_timeout=settings.database_pool_timeout,
            pool_pre_ping=True,  # Verifica conexão antes de usar
            pool_recycle=3600,  # Recicla conexões a cada 1h
        )
        
        self._session_maker = async_sessionmaker(
            self._engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
            autocommit=False,
        )
        
        logger.info(
            "Database engine initialized",
            pool_size=settings.database_pool_size,
            max_overflow=settings.database_max_overflow,
        )
    
    async def close(self) -> None:
        """Fecha conexões."""
        if self._engine:
            await self._engine.dispose()
            logger.info("Database connections closed")
    
    @asynccontextmanager
    async def session(self) -> AsyncGenerator[AsyncSession, None]:
        """Context manager para sessões."""
        if not self._session_maker:
            raise RuntimeError("Database not initialized. Call initialize() first.")
        
        async with self._session_maker() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise
            finally:
                await session.close()
    
    @asynccontextmanager
    async def session_without_commit(self) -> AsyncGenerator[AsyncSession, None]:
        """Sessão sem auto-commit (para transações manuais)."""
        if not self._session_maker:
            raise RuntimeError("Database not initialized. Call initialize() first.")
        
        async with self._session_maker() as session:
            try:
                yield session
            finally:
                await session.close()
    
    async def create_all(self) -> None:
        """Cria todas as tabelas (útil para testes)."""
        if not self._engine:
            raise RuntimeError("Database not initialized. Call initialize() first.")
        
        async with self._engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("Database tables created")
    
    async def drop_all(self) -> None:
        """Dropa todas as tabelas (útil para testes)."""
        if not self._engine:
            raise RuntimeError("Database not initialized. Call initialize() first.")
        
        async with self._engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        logger.info("Database tables dropped")


# Instância global
db = DatabaseManager()
```

**Critério de Aceitação:**
- [ ] Engine async criada corretamente
- [ ] Session manager funciona
- [ ] Connection pooling configurado
- [ ] Testes de conexão passam

---

### T5: Base Models (models/base.py)

**Implementação:**

```python
# src/gabi/models/base.py
"""Base models com mixins reutilizáveis."""

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import Boolean, Column, DateTime, Integer, String, event
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Base declarativa para todos os models."""
    
    # Gera __tablename__ automaticamente
    @classmethod
    def __tablename__(cls) -> str:
        return cls.__name__.lower()


class TimestampMixin:
    """Adiciona created_at e updated_at."""
    
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class SoftDeleteMixin:
    """Adiciona soft delete capability."""
    
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    deleted_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    
    def soft_delete(self, reason: str | None = None, deleted_by: str | None = None) -> None:
        """Marca registro como deletado."""
        self.is_deleted = True
        self.deleted_at = datetime.now(timezone.utc)
        self.deleted_reason = reason
        self.deleted_by = deleted_by
    
    def restore(self) -> None:
        """Restaura registro deletado."""
        self.is_deleted = False
        self.deleted_at = None
        self.deleted_reason = None
        self.deleted_by = None


class UUIDMixin:
    """Adiciona UUID como PK."""
    
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
    )


class VersionMixin:
    """Adiciona versionamento otimista."""
    
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    
    @staticmethod
    def increment_version(mapper: Any, connection: Any, target: Any) -> None:
        """Incrementa versão no UPDATE."""
        if target.version is not None:
            target.version += 1


def setup_version_events(model_class: type) -> None:
    """Configura eventos de versionamento para uma classe."""
    event.listen(model_class, "before_update", VersionMixin.increment_version)


# Model base completo para herança
class AuditableBase(Base, UUIDMixin, TimestampMixin, SoftDeleteMixin):
    """Base com auditoria completa (UUID, timestamps, soft delete)."""
    
    __abstract__ = True
    
    def to_dict(self) -> dict[str, Any]:
        """Converte model para dict."""
        result = {}
        for column in self.__table__.columns:
            value = getattr(self, column.name)
            if isinstance(value, datetime):
                value = value.isoformat()
            elif isinstance(value, uuid.UUID):
                value = str(value)
            result[column.name] = value
        return result
```

**Critério de Aceitação:**
- [ ] Base declarativa funciona
- [ ] Mixins aplicam campos corretamente
- [ ] to_dict() funciona

---

### T6: Testes Base

**T6.1: pyproject.toml**

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "gabi"
version = "0.1.0"
description = "Gerador Automático de Boletins por Inteligência Artificial - TCU"
requires-python = ">=3.11"
dependencies = [
    "fastapi>=0.109.2",
    "uvicorn[standard]>=0.27.1",
    "pydantic>=2.6.3",
    "pydantic-settings>=2.2.0",
    "sqlalchemy[asyncio]>=2.0.28",
    "asyncpg>=0.29.0",
    "alembic>=1.13.1",
    "celery>=5.3.6",
    "redis>=5.0.0",
    "httpx>=0.27.0",
    "elasticsearch[async]>=8.11.0",
    "structlog>=24.1.0",
    "python-json-logger>=2.0.7",
    "pyyaml>=6.0.1",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0.0",
    "pytest-asyncio>=0.23.0",
    "pytest-cov>=4.1.0",
    "factory-boy>=3.3.0",
    "faker>=23.0.0",
    "ruff>=0.3.2",
    "mypy>=1.8.0",
    "types-pyyaml>=6.0.0",
    "testcontainers>=3.7.0",
    "asgi-lifespan>=2.1.0",
    "pytest-mock>=3.12.0",
]

[tool.ruff]
target-version = "py311"
line-length = 100
select = ["E", "F", "I", "N", "W", "UP", "B", "C4", "SIM", "ARG"]
ignore = ["E501"]

[tool.ruff.isort]
known-first-party = ["gabi"]

[tool.mypy]
python_version = "3.11"
strict = true
warn_return_any = true
warn_unused_configs = true
ignore_missing_imports = true

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
python_files = ["test_*.py"]
python_classes = ["Test*"]
python_functions = ["test_*"]
addopts = "-v --tb=short --strict-markers"
markers = [
    "unit: Unit tests",
    "integration: Integration tests",
    "e2e: End-to-end tests",
]

[tool.coverage.run]
source = ["src/gabi"]
branch = true

[tool.coverage.report]
exclude_lines = [
    "pragma: no cover",
    "def __repr__",
    "raise AssertionError",
    "raise NotImplementedError",
]
```

**T6.2: conftest.py**

```python
# tests/conftest.py
"""Configuração de testes."""

import asyncio
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from gabi.models.base import Base


# Fixture para event loop
@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


# Fixture para database de teste
@pytest_asyncio.fixture(scope="function")
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """Sessão de banco de dados para testes (SQLite em memória)."""
    
    # Usar SQLite em memória para testes unitários rápidos
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=NullPool,
    )
    
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    async_session = sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )
    
    async with async_session() as session:
        yield session
    
    await engine.dispose()


# Fixture para settings de teste
@pytest.fixture
def test_settings(monkeypatch):
    """Settings para testes."""
    monkeypatch.setenv("GABI_DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    monkeypatch.setenv("GABI_ENVIRONMENT", "local")
    monkeypatch.setenv("GABI_DEBUG", "true")
    monkeypatch.setenv("GABI_LOG_LEVEL", "debug")
    
    from gabi.config import Settings
    return Settings()
```

**T6.3: factories.py**

```python
# tests/factories.py
"""Factories para testes usando factory_boy."""

import uuid
from datetime import datetime, timezone

import factory
from sqlalchemy.ext.asyncio import AsyncSession

from gabi.models.base import AuditableBase


class AsyncFactory(factory.Factory):
    """Factory base para modelos async."""
    
    class Meta:
        abstract = True
    
    @classmethod
    async def create_batch(cls, size: int, **kwargs):
        """Cria múltiplos objetos."""
        return [await cls.create(**kwargs) for _ in range(size)]


class BaseFactoryMeta:
    """Meta config para factories."""
    
    @staticmethod
    def get_session():
        # Override em conftest se necessário
        return None
```

**T6.4: test_config.py**

```python
# tests/unit/test_config.py
"""Testes de configuração."""

import pytest
from pydantic import ValidationError

from gabi.config import Environment, Settings


class TestSettings:
    """Testes das configurações."""
    
    def test_default_environment_is_local(self):
        """Ambiente padrão deve ser LOCAL."""
        settings = Settings(database_url="postgresql://user:pass@localhost/test")
        assert settings.environment == Environment.LOCAL
    
    def test_default_log_level_is_info(self):
        """Log level padrão deve ser info."""
        settings = Settings(database_url="postgresql://user:pass@localhost/test")
        assert settings.log_level == "info"
    
    def test_invalid_log_level_raises(self):
        """Log level inválido deve levantar erro."""
        with pytest.raises(ValidationError) as exc_info:
            Settings(
                database_url="postgresql://user:pass@localhost/test",
                log_level="invalid"
            )
        assert "log_level" in str(exc_info.value)
    
    def test_database_url_validation_postgresql(self):
        """URL postgresql deve ser aceita."""
        settings = Settings(database_url="postgresql://user:pass@localhost/test")
        assert "postgresql" in settings.database_url
    
    def test_database_url_validation_asyncpg(self):
        """URL postgresql+asyncpg deve ser aceita."""
        settings = Settings(database_url="postgresql+asyncpg://user:pass@localhost/test")
        assert "postgresql+asyncpg" in settings.database_url
    
    def test_database_url_validation_invalid(self):
        """URL inválida deve levantar erro."""
        with pytest.raises(ValidationError) as exc_info:
            Settings(database_url="sqlite:///test.db")
        assert "database_url" in str(exc_info.value)
    
    def test_auth_required_in_production(self):
        """Auth deve ser obrigatório em produção."""
        with pytest.raises(ValidationError) as exc_info:
            Settings(
                database_url="postgresql://user:pass@localhost/test",
                environment=Environment.PRODUCTION,
                auth_enabled=False
            )
        assert "auth_enabled" in str(exc_info.value)
    
    def test_cors_wildcard_not_allowed_in_production(self):
        """CORS wildcard não permitido em produção."""
        with pytest.raises(ValidationError) as exc_info:
            Settings(
                database_url="postgresql://user:pass@localhost/test",
                environment=Environment.PRODUCTION,
                cors_origins=["*"]
            )
        assert "CORS" in str(exc_info.value)
    
    def test_http_not_allowed_in_production_cors(self):
        """HTTP não permitido em produção."""
        with pytest.raises(ValidationError) as exc_info:
            Settings(
                database_url="postgresql://user:pass@localhost/test",
                environment=Environment.PRODUCTION,
                cors_origins=["http://localhost:3000"]
            )
        assert "HTTP" in str(exc_info.value)
    
    def test_embeddings_dimensions_immutable(self):
        """Dimensões de embedding devem ser imutáveis."""
        settings = Settings(database_url="postgresql://user:pass@localhost/test")
        assert settings.embeddings_dimensions == 384
        
        # Tentar modificar deve falhar (frozen=True)
        with pytest.raises(ValidationError):
            settings.embeddings_dimensions = 768
    
    def test_pool_size_validation(self):
        """Pool size deve estar entre 1 e 100."""
        with pytest.raises(ValidationError):
            Settings(
                database_url="postgresql://user:pass@localhost/test",
                database_pool_size=0
            )
        
        with pytest.raises(ValidationError):
            Settings(
                database_url="postgresql://user:pass@localhost/test",
                database_pool_size=101
            )
    
    def test_environment_enum_values(self):
        """Environment enum deve ter valores corretos."""
        assert Environment.LOCAL == "local"
        assert Environment.STAGING == "staging"
        assert Environment.PRODUCTION == "production"
```

**Critério de Aceitação:**
- [ ] pytest passa sem erros
- [ ] cobertura > 80% em config.py

---

### T7: Docker Local

**T7.1: docker-compose.local.yml**

```yaml
version: "3.8"

services:
  # PostgreSQL com pgvector
  postgres:
    image: ankane/pgvector:v0.5.1
    container_name: gabi-postgres
    environment:
      POSTGRES_USER: gabi
      POSTGRES_PASSWORD: gabi_local_dev
      POSTGRES_DB: gabi
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data
      - ./scripts/init-db.sql:/docker-entrypoint-initdb.d/init.sql:ro
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U gabi -d gabi"]
      interval: 5s
      timeout: 5s
      retries: 5

  # Elasticsearch
  elasticsearch:
    image: docker.elastic.co/elasticsearch/elasticsearch:8.11.0
    container_name: gabi-elasticsearch
    environment:
      - discovery.type=single-node
      - xpack.security.enabled=false
      - "ES_JAVA_OPTS=-Xms512m -Xmx512m"
    ports:
      - "9200:9200"
    volumes:
      - elasticsearch_data:/usr/share/elasticsearch/data
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:9200/_cluster/health"]
      interval: 10s
      timeout: 5s
      retries: 5

  # Redis
  redis:
    image: redis:7-alpine
    container_name: gabi-redis
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data
    command: redis-server --appendonly yes
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 3s
      retries: 5

  # TEI (Text Embeddings Inference)
  tei:
    image: ghcr.io/huggingface/text-embeddings-inference:1.4
    container_name: gabi-tei
    environment:
      - MODEL_ID=sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
    ports:
      - "8080:80"
    deploy:
      resources:
        limits:
          memory: 2G
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:80/health"]
      interval: 30s
      timeout: 10s
      retries: 3

volumes:
  postgres_data:
  elasticsearch_data:
  redis_data:
```

**T7.2: Dockerfile**

```dockerfile
# syntax=docker/dockerfile:1

# ===== Stage 1: Builder =====
FROM python:3.11-slim AS builder

WORKDIR /app

# Instalar dependências de build
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Criar virtual environment
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Instalar dependências
COPY requirements.txt requirements-dev.txt ./
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# ===== Stage 2: Production =====
FROM python:3.11-slim AS production

WORKDIR /app

# Criar usuário non-root
RUN groupadd -r gabi && useradd -r -g gabi gabi

# Copiar virtual environment
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copiar código
COPY --chown=gabi:gabi src/ ./src/
COPY --chown=gabi:gabi pyproject.toml ./

# Instalar pacote em modo produção
RUN pip install --no-deps -e .

# Mudar para usuário non-root
USER gabi

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import gabi" || exit 1

# Expor porta
EXPOSE 8000

# Comando padrão
CMD ["uvicorn", "gabi.main:app", "--host", "0.0.0.0", "--port", "8000"]

# ===== Stage 3: Development =====
FROM production AS development

USER root

# Instalar dependências de dev
COPY --from=builder /opt/venv /opt/venv
RUN pip install --no-cache-dir -r requirements-dev.txt

# Instalar ferramentas úteis
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    git \
    vim \
    && rm -rf /var/lib/apt/lists/*

USER gabi

# Instalar pacote em modo editable com deps de dev
RUN pip install -e ".[dev]"

CMD ["uvicorn", "gabi.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
```

**T7.3: .env.example**

```bash
# ============================================
# GABI - Environment Configuration
# Copie para .env e ajuste os valores
# ============================================

# === Ambiente ===
GABI_ENVIRONMENT=local
GABI_DEBUG=true
GABI_LOG_LEVEL=debug

# === PostgreSQL ===
# Formato: postgresql+asyncpg://user:pass@host:port/database
GABI_DATABASE_URL=postgresql+asyncpg://gabi:gabi_local_dev@localhost:5432/gabi
GABI_DATABASE_POOL_SIZE=10
GABI_DATABASE_MAX_OVERFLOW=20
GABI_DATABASE_ECHO=false

# === Elasticsearch ===
GABI_ELASTICSEARCH_URL=http://localhost:9200
GABI_ELASTICSEARCH_INDEX=gabi_documents_v1
GABI_ELASTICSEARCH_TIMEOUT=30
GABI_ELASTICSEARCH_MAX_RETRIES=3

# === Redis ===
GABI_REDIS_URL=redis://localhost:6379/0
GABI_REDIS_DLQ_DB=1
GABI_REDIS_CACHE_DB=2
GABI_REDIS_LOCK_DB=3

# === TEI Embeddings ===
GABI_EMBEDDINGS_URL=http://localhost:8080
GABI_EMBEDDINGS_BATCH_SIZE=32
GABI_EMBEDDINGS_TIMEOUT=60
GABI_EMBEDDINGS_MAX_RETRIES=3

# === Auth (JWT via Keycloak) ===
GABI_JWT_ISSUER=https://auth.tcu.gov.br/realms/tcu
GABI_JWT_AUDIENCE=gabi-api
GABI_JWT_JWKS_URL=https://auth.tcu.gov.br/realms/tcu/protocol/openid-connect/certs
GABI_JWT_ALGORITHM=RS256
GABI_JWT_JWKS_CACHE_MINUTES=5
GABI_AUTH_ENABLED=false

# === Rate Limiting ===
GABI_RATE_LIMIT_ENABLED=false
GABI_RATE_LIMIT_REQUESTS_PER_MINUTE=60

# === Pipeline ===
GABI_PIPELINE_MAX_MEMORY_MB=3584
GABI_PIPELINE_FETCH_TIMEOUT=60
GABI_PIPELINE_FETCH_MAX_SIZE_MB=100
GABI_PIPELINE_CHUNK_MAX_TOKENS=512
GABI_PIPELINE_CHUNK_OVERLAP_TOKENS=50

# === CORS ===
GABI_CORS_ORIGINS=["http://localhost:3000","http://localhost:8080"]

# === API ===
GABI_API_HOST=0.0.0.0
GABI_API_PORT=8000
GABI_API_WORKERS=1
```

**T7.4: scripts/setup-local.sh**

```bash
#!/bin/bash
# Setup local development environment

set -e

echo "🚀 GABI Local Setup"
echo "==================="

# Cores
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Verificar Docker
if ! command -v docker &> /dev/null; then
    echo -e "${RED}❌ Docker não encontrado. Instale o Docker primeiro.${NC}"
    exit 1
fi

if ! command -v docker-compose &> /dev/null; then
    echo -e "${RED}❌ Docker Compose não encontrado. Instale o Docker Compose primeiro.${NC}"
    exit 1
fi

# Criar .env se não existir
if [ ! -f .env ]; then
    echo -e "${YELLOW}📄 Criando .env a partir de .env.example...${NC}"
    cp .env.example .env
    echo -e "${GREEN}✅ .env criado. Edite se necessário.${NC}"
else
    echo -e "${GREEN}✅ .env já existe${NC}"
fi

# Subir serviços
echo -e "${YELLOW}🐳 Subindo serviços...${NC}"
docker-compose -f docker-compose.local.yml up -d

# Aguardar serviços
echo -e "${YELLOW}⏳ Aguardando serviços ficarem prontos...${NC}"
sleep 5

# Verificar PostgreSQL
echo "Verificando PostgreSQL..."
until docker exec gabi-postgres pg_isready -U gabi > /dev/null 2>&1; do
    echo -n "."
    sleep 2
done
echo -e "${GREEN} ✅${NC}"

# Verificar Elasticsearch
echo "Verificando Elasticsearch..."
until curl -s http://localhost:9200/_cluster/health > /dev/null 2>&1; do
    echo -n "."
    sleep 2
done
echo -e "${GREEN} ✅${NC}"

# Verificar Redis
echo "Verificando Redis..."
until docker exec gabi-redis redis-cli ping > /dev/null 2>&1; do
    echo -n "."
    sleep 2
done
echo -e "${GREEN} ✅${NC}"

# Verificar TEI
echo "Verificando TEI..."
until curl -s http://localhost:8080/health > /dev/null 2>&1; do
    echo -n "."
    sleep 2
done
echo -e "${GREEN} ✅${NC}"

echo ""
echo -e "${GREEN}✅ Ambiente local pronto!${NC}"
echo ""
echo "Serviços disponíveis:"
echo "  - PostgreSQL: localhost:5432"
echo "  - Elasticsearch: http://localhost:9200"
echo "  - Redis: localhost:6379"
echo "  - TEI: http://localhost:8080"
echo ""
echo "Próximos passos:"
echo "  1. python -m venv venv && source venv/bin/activate"
echo "  2. pip install -e '.[dev]'"
echo "  3. pytest"
echo ""
```

**Critério de Aceitação:**
- [ ] `docker-compose -f docker-compose.local.yml up -d` sobe todos os serviços
- [ ] Health checks passam
- [ ] `.env` é criado automaticamente

---

### T8: Makefile

```makefile
# Makefile para GABI
.PHONY: help install install-dev test lint typecheck format clean docker-up docker-down setup

# Python
PYTHON := python3
PIP := pip
PYTEST := pytest
RUFF := ruff
MYPY := mypy

# Docker
COMPOSE := docker-compose -f docker-compose.local.yml

help: ## Mostra ajuda
	@echo "Comandos disponíveis:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

# Setup
setup: ## Setup inicial do ambiente de desenvolvimento
	./scripts/setup-local.sh

install: ## Instala dependências de produção
	$(PIP) install -e .

install-dev: ## Instala dependências de desenvolvimento
	$(PIP) install -e ".[dev]"

# Testes
test: ## Roda testes unitários
	$(PYTEST) tests/unit -v

test-integration: ## Roda testes de integração
	$(PYTEST) tests/integration -v

test-all: ## Roda todos os testes
	$(PYTEST) -v

test-cov: ## Roda testes com cobertura
	$(PYTEST) --cov=src/gabi --cov-report=term-missing --cov-report=html

# Qualidade de código
lint: ## Roda linter (ruff)
	$(RUFF) check src tests

typecheck: ## Roda type checker (mypy)
	$(MYPY) src/gabi

format: ## Formata código (ruff format)
	$(RUFF) format src tests

format-check: ## Verifica formatação
	$(RUFF) format --check src tests

check: lint typecheck test ## Roda todas as verificações (lint, typecheck, test)

# Docker
docker-up: ## Sobe serviços Docker local
	$(COMPOSE) up -d

docker-down: ## Derruba serviços Docker
	$(COMPOSE) down

docker-logs: ## Mostra logs dos serviços
	$(COMPOSE) logs -f

docker-clean: ## Derruba e remove volumes
	$(COMPOSE) down -v

# Limpeza
clean: ## Limpa arquivos temporários
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".mypy_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "htmlcov" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name ".coverage" -delete 2>/dev/null || true

# Banco de dados
migrate: ## Roda migrações (placeholder para alembic)
	@echo "Alembic não configurado ainda"

db-reset: ## Reseta banco de dados
	$(COMPOSE) restart postgres

# API
run: ## Roda API local
	uvicorn gabi.main:app --reload --host 0.0.0.0 --port 8000

# CI
ci: install-dev lint typecheck test ## Comando para CI
```

**Critério de Aceitação:**
- [ ] `make help` mostra comandos disponíveis
- [ ] `make check` roda lint, typecheck e test
- [ ] `make docker-up` sobe serviços

---

## Checklist de Sucesso da Wave 1

| Check | Critério | Verificação |
|-------|----------|-------------|
| [ ] | `pytest` passa | Sem falhas em testes unitários |
| [ ] | `docker-compose -f docker-compose.local.yml up` sobe | Todos serviços healthy |
| [ ] | `make lint` passa | Ruff sem erros |
| [ ] | `make typecheck` passa | Mypy sem erros |
| [ ] | Config carrega corretamente | Testes de config passam |
| [ ] | Exceptions podem ser importadas | Import gabi.exceptions funciona |
| [ ] | Database layer inicializa | Engine e session funcionam |
| [ ] | Base models criam tabelas | Teste com SQLite funciona |

---

## Agentes Necessários

| Agente | Responsabilidade | Tarefas |
|--------|-----------------|---------|
| **ProjectBootstrapper** | Estrutura inicial | T1: Criar diretórios, pyproject.toml, .gitignore |
| **ConfigEngineer** | Configuração | T2: Implementar config.py com Pydantic Settings |
| **ExceptionDesigner** | Exceptions e Logging | T3: Hierarquia de exceções + logging estruturado |
| **DatabaseArchitect** | Database layer | T4: SQLAlchemy async engine + session manager |
| **ModelFoundation** | Base models | T5: Base declarativa + mixins |
| **TestEngineer** | Testes | T6: conftest.py, factories.py, testes de config |
| **DevOpsInitializer** | Docker local | T7: docker-compose, Dockerfile, .env.example |
| **BuildMaster** | Makefile | T8: Comandos make para dev workflow |

---

## Dependências entre Tarefas

```
T1 (Estrutura)
  ├── T2 (Config) ──┬── T6 (Testes)
  │                 └── T4 (Database)
  ├── T3 (Exceptions)
  ├── T5 (Models) ── T4 (Database)
  ├── T7 (Docker)
  └── T8 (Makefile)
```

---

## Notas de Implementação

1. **Python 3.11+ obrigatório** - Usar features modernas (async, typing)
2. **asyncpg** - Driver PostgreSQL async
3. **Pydantic v2** - Validação de config
4. **structlog** - Logging estruturado
5. **Não implementar models concretos** - Apenas base.py na Wave 1
6. **SQLite para testes unitários** - Performance
7. **PostgreSQL para integração** - Via docker-compose

---

## Próximas Waves

- **Wave 2**: Database & Models (implementar models reais, alembic)
- **Wave 3**: Pipeline Core (discovery, fetch, parse)
- **Wave 4**: Indexação & Busca (embeddings, ES)
- **Wave 5**: API & MCP (FastAPI, servidores)
- **Wave 6**: Observabilidade & Deploy (monitoring, K8s)
