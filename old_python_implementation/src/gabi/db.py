"""Camada de banco de dados do GABI.

Este módulo gerencia a conexão com PostgreSQL usando SQLAlchemy async.
Fornece engine, session factory e DatabaseManager para a aplicação.

Invariantes:
- Async SQLAlchemy com asyncpg
- Connection pooling com pool_pre_ping=True
- AsyncSession com expire_on_commit=False
"""

from contextlib import asynccontextmanager
from typing import AsyncGenerator, Optional

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from gabi.config import settings
from gabi.models.base import Base

# Elasticsearch client - lazy initialization
_es_client = None

# Redis client - lazy initialization
_redis_client = None


class _RedisClientProxy:
    """Proxy para redis_client que permite lazy initialization."""
    
    def __getattr__(self, name: str):
        """Proxy para atributos do cliente Redis real."""
        client = get_redis_client()
        return getattr(client, name)
    
    def __await__(self):
        """Permite await no proxy."""
        return get_redis_client().__await__()
    
    def __aenter__(self):
        return get_redis_client().__aenter__()
    
    def __aexit__(self, *args):
        return get_redis_client().__aexit__(*args)

# =============================================================================
# Engine e Session Factory
# =============================================================================

# Engine global - inicializado em init_db()
_engine: Optional[AsyncEngine] = None

# Session factory global - inicializada em init_db()
_async_session_maker: Optional[async_sessionmaker[AsyncSession]] = None


class _AsyncSessionFactoryProxy:
    """Proxy para async_session_factory que permite chamada dinâmica.
    
    Este proxy permite que dependencies.py use async_session_factory()
    mesmo quando o _async_session_maker ainda não foi inicializado.
    A verificação de inicialização é feita no momento da chamada.
    """
    
    def __call__(self, *args, **kwargs) -> AsyncSession:
        """Cria uma nova sessão usando o _async_session_maker atual."""
        if _async_session_maker is None:
            raise RuntimeError("Session factory não inicializada. Chame init_db() primeiro.")
        return _async_session_maker(*args, **kwargs)
    
    def __getattr__(self, name: str):
        """Proxy para atributos do _async_session_maker."""
        if _async_session_maker is None:
            raise RuntimeError("Session factory não inicializada. Chame init_db() primeiro.")
        return getattr(_async_session_maker, name)


# Export for dependencies
async_session_factory = _AsyncSessionFactoryProxy()


def get_es_client():
    """Retorna o cliente Elasticsearch singleton.
    
    Lazy initialization - cria o cliente na primeira chamada.
    
    Returns:
        AsyncElasticsearch: Cliente Elasticsearch async
    """
    global _es_client
    if _es_client is None:
        from elasticsearch import AsyncElasticsearch
        _es_client = AsyncElasticsearch([settings.elasticsearch_url])
    return _es_client


def get_redis_client():
    """Retorna o cliente Redis singleton.
    
    Lazy initialization - cria o cliente na primeira chamada.
    
    Returns:
        Redis: Cliente Redis async
    """
    global _redis_client
    if _redis_client is None:
        from redis.asyncio import Redis
        _redis_client = Redis.from_url(settings.redis_url, decode_responses=True)
    return _redis_client


# Export for dependencies (lazy proxy)
redis_client = _RedisClientProxy()


def _ensure_async_driver(url: str) -> str:
    """Garante que a URL use o driver asyncpg.
    
    Args:
        url: URL do banco de dados
        
    Returns:
        URL com driver asyncpg
    """
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


def create_engine() -> AsyncEngine:
    """Cria o engine async do SQLAlchemy com connection pooling.
    
    Configurações de pool:
    - pool_pre_ping=True: Verifica conexões antes de usar (evita erros de conexão morta)
    - pool_size: Número de conexões permanentes no pool
    - max_overflow: Conexões extras permitidas além do pool_size
    - pool_timeout: Tempo máximo de espera por uma conexão
    
    Returns:
        AsyncEngine configurado
        
    Raises:
        RuntimeError: Se o engine já estiver inicializado
    """
    global _engine
    
    if _engine is not None:
        raise RuntimeError("Engine já está inicializado. Use close_db() primeiro.")
    
    database_url = _ensure_async_driver(settings.database_url)
    
    _engine = create_async_engine(
        database_url,
        pool_pre_ping=True,  # Verifica conexões antes de usar
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_max_overflow,
        pool_timeout=settings.database_pool_timeout,
        echo=settings.database_echo,  # Log de SQL (debug)
        future=True,  # SQLAlchemy 2.0 style
    )
    
    return _engine


def get_engine() -> AsyncEngine:
    """Retorna o engine inicializado.
    
    Returns:
        AsyncEngine inicializado
        
    Raises:
        RuntimeError: Se o engine não estiver inicializado
    """
    if _engine is None:
        raise RuntimeError("Engine não inicializado. Chame init_db() primeiro.")
    return _engine


def create_session_maker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Cria a factory de sessões async.
    
    Configurações:
    - expire_on_commit=False: Permite acesso a atributos após commit
    - class_=AsyncSession: Garante sessão async
    
    Args:
        engine: Engine SQLAlchemy
        
    Returns:
        async_sessionmaker configurado
    """
    return async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,  # Importante: permite acesso a atributos após commit
        autocommit=False,
        autoflush=False,
    )


# =============================================================================
# Context Manager para Sessões
# =============================================================================

@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Context manager para obter uma sessão do banco de dados.
    
    Uso:
        async with get_session() as session:
            result = await session.execute(query)
            await session.commit()
    
    O context manager garante:
    - Commit automático se não houver exceções
    - Rollback automático em caso de exceção
    - Fechamento da sessão (close) sempre
    
    Yields:
        AsyncSession: Sessão do banco de dados
        
    Raises:
        RuntimeError: Se a session factory não estiver inicializada
    """
    if _async_session_maker is None:
        raise RuntimeError("Session factory não inicializada. Chame init_db() primeiro.")
    
    session: AsyncSession = _async_session_maker()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


@asynccontextmanager
async def get_session_no_commit() -> AsyncGenerator[AsyncSession, None]:
    """Context manager para sessão sem commit automático.
    
    Útil quando o caller quer controlar manualmente o commit/rollback.
    
    Uso:
        async with get_session_no_commit() as session:
            result = await session.execute(query)
            # Caller decide quando commitar
    
    Yields:
        AsyncSession: Sessão do banco de dados
    """
    if _async_session_maker is None:
        raise RuntimeError("Session factory não inicializada. Chame init_db() primeiro.")
    
    session: AsyncSession = _async_session_maker()
    try:
        yield session
    finally:
        await session.close()


# =============================================================================
# Inicialização e Finalização
# =============================================================================

async def init_db() -> None:
    """Inicializa a camada de banco de dados.
    
    Deve ser chamado no startup da aplicação.
    Cria o engine e a session factory.
    
    Raises:
        RuntimeError: Se já estiver inicializado
    """
    global _engine, _async_session_maker
    
    if _engine is not None:
        raise RuntimeError("Database layer já inicializado.")
    
    engine = create_engine()
    _async_session_maker = create_session_maker(engine)


async def init_db_with_tables() -> None:
    """Inicializa o banco de dados e cria as tabelas.
    
    ATENÇÃO: Apenas para desenvolvimento/testes.
    Em produção, use Alembic para migrations.
    
    Cria todas as tabelas definidas nos modelos.
    """
    await init_db()
    
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def close_db() -> None:
    """Fecha a camada de banco de dados.
    
    Deve ser chamado no shutdown da aplicação.
    Fecha o engine e libera recursos.
    
    Safe para chamar mesmo se não inicializado.
    """
    global _engine, _async_session_maker, _redis_client
    
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _async_session_maker = None
    
    if _redis_client is not None:
        await _redis_client.close()
        _redis_client = None


# =============================================================================
# Database Manager
# =============================================================================

class DatabaseManager:
    """Gerenciador de banco de dados para injeção de dependências.
    
    Fornece uma interface de alto nível para operações comuns.
    Pode ser usado como dependência em serviços.
    
    Exemplo:
        db_manager = DatabaseManager()
        async with db_manager.session() as session:
            # operações com session
    """
    
    def __init__(self) -> None:
        """Inicializa o DatabaseManager.
        
        Raises:
            RuntimeError: Se o banco de dados não estiver inicializado
        """
        # Valida que o banco está inicializado
        get_engine()
    
    @asynccontextmanager
    async def session(self) -> AsyncGenerator[AsyncSession, None]:
        """Fornece uma sessão transacional.
        
        Commit automático em caso de sucesso,
        rollback em caso de exceção.
        
        Yields:
            AsyncSession: Sessão do banco de dados
        """
        async with get_session() as session:
            yield session
    
    @asynccontextmanager
    async def session_no_commit(self) -> AsyncGenerator[AsyncSession, None]:
        """Fornece uma sessão sem commit automático.
        
        O caller é responsável por commit/rollback.
        
        Yields:
            AsyncSession: Sessão do banco de dados
        """
        async with get_session_no_commit() as session:
            yield session
    
    async def execute(self, statement) -> None:
        """Executa uma statement e commita.
        
        Args:
            statement: Statement SQLAlchemy para executar
        """
        async with get_session() as session:
            await session.execute(statement)
    
    async def fetch_one(self, statement):
        """Executa query e retorna primeiro resultado.
        
        Args:
            statement: Query SQLAlchemy
            
        Returns:
            Primeiro resultado ou None
        """
        async with get_session_no_commit() as session:
            result = await session.execute(statement)
            return result.scalar_one_or_none()
    
    async def fetch_all(self, statement):
        """Executa query e retorna todos os resultados.
        
        Args:
            statement: Query SQLAlchemy
            
        Returns:
            Lista de resultados
        """
        async with get_session_no_commit() as session:
            result = await session.execute(statement)
            return result.scalars().all()


# =============================================================================
# FastAPI Dependency
# =============================================================================

async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Dependency para injeção de sessão do banco em endpoints FastAPI.
    
    Uso:
        @router.get("/")
        async def endpoint(db: AsyncSession = Depends(get_db_session)):
            ...
    
    Yields:
        AsyncSession: Sessão do banco de dados
        
    Note:
        O commit deve ser feito explicitamente no endpoint.
        O rollback é automático em caso de exceção.
    """
    if _async_session_maker is None:
        raise RuntimeError("Database não inicializado. Chame init_db() primeiro.")
    
    session: AsyncSession = _async_session_maker()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    # Engine e Session
    "create_engine",
    "get_engine",
    "create_session_maker",
    "async_session_factory",
    
    # Context Managers
    "get_session",
    "get_session_no_commit",
    
    # FastAPI Dependency
    "get_db_session",
    
    # Lifecycle
    "init_db",
    "init_db_with_tables",
    "close_db",
    
    # Manager
    "DatabaseManager",
    
    # Elasticsearch
    "get_es_client",
    
    # Redis
    "get_redis_client",
    "redis_client",
]
