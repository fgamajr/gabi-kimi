"""Configuração global de fixtures para testes do GABI.

Este módulo define fixtures reutilizáveis para todos os testes,
seguindo as especificações de GATES.md §1.

Fixtures obrigatórias:
- event_loop: Loop de eventos asyncio
- settings: Configurações de teste
- db_session: Sessão de banco de dados
- mock_es_client: Mock do Elasticsearch
- mock_redis_client: Mock do Redis
- mock_embedder: Mock do serviço de embeddings
"""

from __future__ import annotations

import asyncio
import hashlib
import uuid
from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlmodel import SQLModel

from gabi.config import Settings, Environment
from gabi.models.base import Base
from gabi.types import (
    SourceType,
    SourceStatus,
    DocumentStatus,
    SensitivityLevel,
)


# =============================================================================
# Configuração do Event Loop
# =============================================================================
# O pytest-asyncio ≥1.0 com asyncio_mode="auto" gerencia event loops
# internamente. NÃO usar @pytest_asyncio.fixture — use @pytest.fixture normal
# que agora suporta corrotinas automaticamente.


# =============================================================================
# Fixtures de Configuração
# =============================================================================

@pytest.fixture(scope="session")
def settings() -> Settings:
    """Configurações de teste.
    
    Retorna uma instância de Settings otimizada para testes,
    com banco de dados em memória e serviços mockados.
    
    Returns:
        Settings: Configurações para ambiente de teste
    """
    return Settings(
        environment=Environment.LOCAL,
        debug=True,
        log_level="debug",
        database_url="postgresql+asyncpg://test:test@localhost:5433/gabi_test",
        database_echo=False,
        elasticsearch_url="http://localhost:9200",
        elasticsearch_index="gabi_test_documents",
        redis_url="redis://localhost:6379/15",  # DB 15 para testes
        embeddings_url="http://localhost:8080",
        embeddings_dimensions=384,
        auth_enabled=False,  # Desabilita auth em testes
        rate_limit_enabled=False,
        audit_enabled=False,
        cors_origins="*",
    )


@pytest.fixture(scope="session")
def test_db_url() -> str:
    """URL do banco de dados de teste.
    
    Returns:
        str: URL de conexão PostgreSQL para testes
    """
    return "postgresql+asyncpg://test:test@localhost:5433/gabi_test"


# =============================================================================
# Fixtures de Banco de Dados
# =============================================================================

@pytest.fixture(scope="session")
async def db_engine() -> AsyncGenerator[Any, None]:
    """Engine SQLAlchemy para testes.
    
    Cria um engine assíncrono para o banco de dados de teste.
    
    Yields:
        AsyncEngine: Engine SQLAlchemy assíncrono
    """
    engine = create_async_engine(
        "postgresql+asyncpg://test:test@localhost:5433/gabi_test",
        echo=False,
        future=True,
    )
    
    # Cria todas as tabelas
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    yield engine
    
    # Limpa tabelas após os testes
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    
    await engine.dispose()


@pytest.fixture
async def db_session(
    db_engine: Any,
) -> AsyncGenerator[AsyncSession, None]:
    """Sessão de banco de dados para testes.
    
    Fornece uma sessão assíncrona isolada para cada teste,
    com rollback automático ao final.
    
    Args:
        db_engine: Engine SQLAlchemy fixture
        
    Yields:
        AsyncSession: Sessão de banco de dados
    """
    async_session = sessionmaker(
        db_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )
    
    async with async_session() as session:
        yield session
        # Rollback para isolar testes
        await session.rollback()


@pytest.fixture
async def db_session_with_commit(
    db_engine: Any,
) -> AsyncGenerator[AsyncSession, None]:
    """Sessão de banco de dados com commit permitido.
    
    Similar ao db_session, mas permite commits para testes
    que precisam persistir dados.
    
    Args:
        db_engine: Engine SQLAlchemy fixture
        
    Yields:
        AsyncSession: Sessão de banco de dados
    """
    async_session = sessionmaker(
        db_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )
    
    async with async_session() as session:
        yield session
        # Cleanup após o teste
        await session.rollback()


# =============================================================================
# Fixtures de Mock - Elasticsearch
# =============================================================================

@pytest.fixture
def mock_es_client() -> Mock:
    """Mock do cliente Elasticsearch.
    
    Retorna um mock configurado do cliente ES async
    com métodos comuns predefinidos.
    
    Returns:
        Mock: Cliente Elasticsearch mockado
    """
    client = Mock()
    
    # Métodos async comuns
    client.index = AsyncMock(return_value={
        "_index": "gabi_documents_v1",
        "_id": "test-doc-123",
        "_version": 1,
        "result": "created",
        "_shards": {"total": 2, "successful": 1, "failed": 0},
    })
    
    client.get = AsyncMock(return_value={
        "_index": "gabi_documents_v1",
        "_id": "test-doc-123",
        "_version": 1,
        "_source": {
            "document_id": "test-doc-123",
            "title": "Test Document",
            "content": "Test content",
        },
    })
    
    client.search = AsyncMock(return_value={
        "took": 5,
        "timed_out": False,
        "hits": {
            "total": {"value": 1, "relation": "eq"},
            "hits": [
                {
                    "_index": "gabi_documents_v1",
                    "_id": "test-doc-123",
                    "_score": 1.5,
                    "_source": {
                        "document_id": "test-doc-123",
                        "title": "Test Document",
                        "content": "Test content",
                    },
                }
            ],
        },
    })
    
    client.delete = AsyncMock(return_value={
        "_index": "gabi_documents_v1",
        "_id": "test-doc-123",
        "_version": 2,
        "result": "deleted",
    })
    
    client.update = AsyncMock(return_value={
        "_index": "gabi_documents_v1",
        "_id": "test-doc-123",
        "_version": 2,
        "result": "updated",
    })
    
    client.exists = AsyncMock(return_value=True)
    client.ping = AsyncMock(return_value=True)
    client.close = AsyncMock(return_value=None)
    
    # Bulk operations
    client.bulk = AsyncMock(return_value={
        "took": 10,
        "errors": False,
        "items": [],
    })
    
    return client


@pytest.fixture
def mock_es_response() -> dict[str, Any]:
    """Resposta padrão de busca ES.
    
    Returns:
        dict: Resposta mock de search do Elasticsearch
    """
    return {
        "took": 5,
        "timed_out": False,
        "hits": {
            "total": {"value": 0, "relation": "eq"},
            "hits": [],
        },
    }


# =============================================================================
# Fixtures de Mock - Redis
# =============================================================================

@pytest.fixture
def mock_redis_client() -> Mock:
    """Mock do cliente Redis.
    
    Retorna um mock configurado do cliente Redis async
    com métodos comuns predefinidos.
    
    Returns:
        Mock: Cliente Redis mockado
    """
    client = Mock()
    
    # String operations
    client.get = AsyncMock(return_value=None)
    client.set = AsyncMock(return_value=True)
    client.setex = AsyncMock(return_value=True)
    client.delete = AsyncMock(return_value=1)
    client.exists = AsyncMock(return_value=1)
    
    # Hash operations
    client.hget = AsyncMock(return_value=None)
    client.hset = AsyncMock(return_value=1)
    client.hgetall = AsyncMock(return_value={})
    client.hdel = AsyncMock(return_value=1)
    
    # List operations
    client.lpush = AsyncMock(return_value=1)
    client.rpush = AsyncMock(return_value=1)
    client.lpop = AsyncMock(return_value=None)
    client.rpop = AsyncMock(return_value=None)
    client.lrange = AsyncMock(return_value=[])
    
    # Set operations
    client.sadd = AsyncMock(return_value=1)
    client.srem = AsyncMock(return_value=1)
    client.sismember = AsyncMock(return_value=False)
    client.smembers = AsyncMock(return_value=set())
    
    # Distributed locks
    client.lock = Mock(return_value=Mock(
        acquire=AsyncMock(return_value=True),
        release=AsyncMock(return_value=None),
        __aenter__=AsyncMock(return_value=True),
        __aexit__=AsyncMock(return_value=False),
    ))
    
    # Pub/Sub
    client.publish = AsyncMock(return_value=1)
    
    # Pipeline
    pipe = Mock()
    pipe.get = Mock(return_value=pipe)
    pipe.set = Mock(return_value=pipe)
    pipe.delete = Mock(return_value=pipe)
    pipe.execute = AsyncMock(return_value=[])
    client.pipeline = Mock(return_value=pipe)
    
    # Connection
    client.ping = AsyncMock(return_value=True)
    client.close = AsyncMock(return_value=None)
    
    return client


# =============================================================================
# Fixtures de Mock - Embedder
# =============================================================================

@pytest.fixture
def mock_embedder() -> Mock:
    """Mock do serviço de embeddings.
    
    Retorna um mock configurado do serviço de embeddings TEI
    que gera vetores aleatórios de 384 dimensões.
    
    Returns:
        Mock: Serviço de embeddings mockado
    """
    embedder = Mock()
    
    # Gera embeddings de 384 dimensões (ADR-001)
    def generate_embedding(text: str | list[str]) -> list[float] | list[list[float]]:
        """Gera embedding mock de 384 dimensões."""
        import random
        
        if isinstance(text, list):
            return [[random.uniform(-1, 1) for _ in range(384)] for _ in text]
        return [random.uniform(-1, 1) for _ in range(384)]
    
    embedder.embed = AsyncMock(side_effect=generate_embedding)
    embedder.embed_batch = AsyncMock(side_effect=generate_embedding)
    
    embedder.get_model_info = AsyncMock(return_value={
        "model_id": "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        "max_input_length": 512,
        "embedding_dimension": 384,
    })
    
    embedder.health_check = AsyncMock(return_value={
        "status": "healthy",
        "model_loaded": True,
    })
    
    return embedder


@pytest.fixture
def mock_embedding_vector() -> list[float]:
    """Vetor de embedding de 384 dimensões para testes.
    
    Returns:
        list[float]: Vetor de embedding de 384 dimensões
    """
    # Vetor normalizado para testes
    import random
    random.seed(42)  # Reprodutibilidade
    vector = [random.uniform(-1, 1) for _ in range(384)]
    # Normaliza
    magnitude = sum(x**2 for x in vector) ** 0.5
    return [x / magnitude for x in vector]


# =============================================================================
# Fixtures de Utilidade
# =============================================================================

@pytest.fixture
def test_uuid() -> str:
    """UUID fixo para testes.
    
    Returns:
        str: UUID fixo para uso em testes
    """
    return "12345678-1234-5678-1234-567812345678"


@pytest.fixture
def test_document_id() -> str:
    """ID de documento fixo para testes.
    
    Returns:
        str: ID de documento fixo
    """
    return "TCU-ACORDAO-1234-2024"


@pytest.fixture
def test_fingerprint() -> str:
    """Fingerprint SHA-256 fixo para testes.
    
    Returns:
        str: Hash SHA-256 fixo
    """
    return hashlib.sha256(b"test content").hexdigest()


@pytest.fixture
def test_timestamp() -> datetime:
    """Timestamp fixo para testes.
    
    Returns:
        datetime: Timestamp UTC fixo
    """
    return datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def sample_source_config() -> dict[str, Any]:
    """Configuração de fonte de exemplo.
    
    Returns:
        dict: Configuração completa de uma fonte
    """
    return {
        "metadata": {
            "domain": "juridico",
            "jurisdiction": "BR",
            "authority": "TCU",
            "document_type": "acordao",
            "canonical_type": "legal_decision",
            "description": "Acórdãos do TCU para testes",
        },
        "discovery": {
            "mode": "static_url",
            "url": "https://example.com/data.csv",
        },
        "fetch": {
            "protocol": "https",
            "method": "GET",
        },
        "parse": {
            "input_format": "csv",
        },
        "mapping": {
            "document_id": {"from": "KEY"},
            "title": {"from": "TITULO"},
        },
        "lifecycle": {
            "sync": {"frequency": "daily"},
        },
        "indexing": {"enabled": True},
        "embedding": {"enabled": True},
    }


@pytest.fixture
def sample_metadata() -> dict[str, Any]:
    """Metadados de documento de exemplo.
    
    Returns:
        dict: Metadados típicos de um documento jurídico
    """
    return {
        "year": 2024,
        "number": "1234",
        "relator": "Ministro Teste",
        "colegiado": "Plenário",
        "assunto": "Licitações",
        "situacao": "Aprovado",
    }


@pytest.fixture
def sample_parsed_document() -> dict[str, Any]:
    """Documento parseado de exemplo para testes de pipeline.
    
    Returns:
        dict: Dados de um documento após a fase de parsing,
              compatível com ParsedDocument do pipeline
    """
    return {
        "document_id": "TCU-ACORDAO-1234-2024",
        "source_id": "tcu_acordaos",
        "title": "Acórdão 1234/2024 - Processo de Licitação",
        "content": (
            "EMENTA: Licitação. Pregão Eletrônico. Impugnação ao edital. "
            "Irregularidade formal. Descabimento. Precedentes.\n\n"
            "RELATÓRIO: O Ministro relator apresentou os fatos pertinentes...\n\n"
            "VOTO: O Ministro vencedor opinou pelo conhecimento...\n\n"
            "ACÓRDÃO: O Tribunal, por unanimidade, decidiu..."
        ),
        "content_preview": "EMENTA: Licitação. Pregão Eletrônico. Impugnação ao edital...",
        "content_type": "text/html",
        "content_hash": hashlib.sha256(b"test content hash").hexdigest(),
        "url": "https://pesquisa.apps.tcu.gov.br/#/documento/acordao/TCU-ACORDAO-1234-2024",
        "language": "pt-BR",
        "metadata": {
            "year": 2024,
            "number": "1234",
            "numata": "1234/2024",
            "type": "AC",
            "relator": "Ministro Teste",
            "colegiado": "Plenário",
            "date": "15/01/2024",
            "process": "12345.678901/2024-00",
            "situacao": "Aprovado",
            "assunto": "Licitações",
        },
        "parsed_at": datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc),
        "parsing_duration_ms": 150,
    }


# =============================================================================
# Fixtures de Marcação
# =============================================================================

def pytest_configure(config: pytest.Config) -> None:
    """Configuração adicional do pytest.
    
    Args:
        config: Configuração do pytest
    """
    config.addinivalue_line("markers", "unit: Unit tests (fast, isolated)")
    config.addinivalue_line("markers", "integration: Integration tests")
    config.addinivalue_line("markers", "e2e: End-to-end tests")
    config.addinivalue_line("markers", "slow: Slow tests")
    config.addinivalue_line("markers", "requires_db: Requires PostgreSQL")
    config.addinivalue_line("markers", "requires_es: Requires Elasticsearch")
    config.addinivalue_line("markers", "requires_redis: Requires Redis")
