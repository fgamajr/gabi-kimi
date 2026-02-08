"""Funções de dependência FastAPI para injeção de dependência.

Este módulo fornece funções de dependência para uso com FastAPI's Depends(),
permitindo injeção de dependência para testes e facilitando mocking.

Invariants:
    - Todas as dependências são funções async generators ou funções síncronas
    - Injeção de dependência permite substituição em testes unitários
    - Recursos são gerenciados via context managers para garantir cleanup
"""

from typing import AsyncGenerator, Generator

from elasticsearch import AsyncElasticsearch
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from gabi.config import Settings, settings


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Fornece uma sessão de banco de dados para injeção de dependência.
    
    Yields:
        AsyncSession: Sessão SQLAlchemy async para operações no PostgreSQL.
        
    Example:
        >>> @app.get("/items")
        ... async def list_items(db: AsyncSession = Depends(get_db)):
        ...     result = await db.execute(select(Item))
        ...     return result.scalars().all()
    
    Invariant:
        - Sessão é sempre fechada após o request, mesmo em caso de exceção
        - Rollback automático em caso de exceção não tratada
    """
    # Import local para evitar circular imports
    from gabi.db import async_session_factory
    
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def get_es_client() -> AsyncGenerator[AsyncElasticsearch, None]:
    """Fornece um cliente Elasticsearch para injeção de dependência.
    
    Yields:
        AsyncElasticsearch: Cliente async para Elasticsearch.
        
    Example:
        >>> @app.get("/search")
        ... async def search(q: str, es: AsyncElasticsearch = Depends(get_es_client)):
        ...     return await es.search(index="docs", query={"match": {"title": q}})
    
    Invariant:
        - Cliente é reutilizado (singleton) via gerenciamento em db.py
        - Não fecha o cliente aqui pois é gerenciado globalmente
    """
    from gabi.db import get_es_client as _get_es_client
    yield _get_es_client()


def get_settings() -> Settings:
    """Fornece as configurações da aplicação para injeção de dependência.
    
    Returns:
        Settings: Instância singleton das configurações do GABI.
        
    Example:
        >>> @app.get("/config")
        ... async def config(settings: Settings = Depends(get_settings)):
        ...     return {"debug": settings.debug}
    
    Invariant:
        - Sempre retorna o mesmo objeto singleton (settings global)
        - Thread-safe para leitura (settings é imutável após criação)
    """
    return settings


async def get_redis() -> AsyncGenerator[Redis, None]:
    """Fornece uma conexão Redis para injeção de dependência.
    
    Yields:
        Redis: Conexão async para Redis (db padrão 0).
        
    Example:
        >>> @app.post("/cache")
        ... async def cache_item(key: str, value: str, redis: Redis = Depends(get_redis)):
        ...     await redis.set(key, value, ex=3600)
        ...     return {"ok": True}
    
    Invariant:
        - Conexão é obtida do pool gerenciado em db.py
        - Não fecha a conexão aqui pois é gerenciada pelo pool
    """
    from gabi.db import redis_client
    yield redis_client
