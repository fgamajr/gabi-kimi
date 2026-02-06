"""
Database layer para GABI - Gerador Automático de Boletins por IA.

Este módulo fornece a camada de acesso ao banco de dados usando SQLAlchemy async.
Suporta PostgreSQL com asyncpg driver.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator, Optional

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import declarative_base
from sqlalchemy.pool import NullPool

# Logger
logger = logging.getLogger(__name__)

# Base declarativa para modelos ORM
Base = declarative_base()


class Settings:
    """Placeholder para Settings - será substituído pelo config real."""
    
    def __init__(
        self,
        database_url: str = "postgresql+asyncpg://user:pass@localhost/gabi",
        db_pool_size: int = 10,
        db_max_overflow: int = 20,
        db_pool_pre_ping: bool = True,
        db_echo: bool = False,
    ):
        self.database_url = database_url
        self.db_pool_size = db_pool_size
        self.db_max_overflow = db_max_overflow
        self.db_pool_pre_ping = db_pool_pre_ping
        self.db_echo = db_echo


def create_engine(
    database_url: str,
    pool_size: int = 10,
    max_overflow: int = 20,
    pool_pre_ping: bool = True,
    echo: bool = False,
) -> Any:
    """
    Factory para criar async engine do SQLAlchemy.
    
    Args:
        database_url: URL do banco de dados
        pool_size: Tamanho do pool de conexões
        max_overflow: Número máximo de conexões extras além do pool_size
        pool_pre_ping: Verificar conexão antes de usar
        echo: Logar queries SQL
    
    Returns:
        AsyncEngine configurado
    """
    # Converte postgresql:// → postgresql+asyncpg://
    if database_url.startswith("postgresql://"):
        database_url = database_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    elif database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql+asyncpg://", 1)
    
    # Para SQLite em memória (usado em testes), usa NullPool
    if database_url.startswith("sqlite"):
        return create_async_engine(
            database_url,
            echo=echo,
            poolclass=NullPool,
        )
    
    engine = create_async_engine(
        database_url,
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_pre_ping=pool_pre_ping,
        echo=echo,
        future=True,
    )
    
    logger.info(f"Database engine criado: pool_size={pool_size}, max_overflow={max_overflow}")
    return engine


class DatabaseManager:
    """
    Gerenciador de conexões com o banco de dados.
    
    Responsável por:
    - Criar e gerenciar o engine async
    - Fornecer session factory
    - Gerenciar ciclo de vida (init/close)
    - Criar tabelas (dev mode)
    """
    
    def __init__(self, settings: Optional[Settings] = None):
        """
        Inicializa o DatabaseManager.
        
        Args:
            settings: Configurações do banco de dados
        """
        self.settings = settings or Settings()
        self._engine: Optional[Any] = None
        self._session_factory: Optional[async_sessionmaker[AsyncSession]] = None
    
    async def initialize(self) -> None:
        """Inicializa o engine e session factory."""
        if self._engine is not None:
            logger.warning("DatabaseManager já inicializado")
            return
        
        self._engine = create_engine(
            database_url=self.settings.database_url,
            pool_size=self.settings.db_pool_size,
            max_overflow=self.settings.db_max_overflow,
            pool_pre_ping=self.settings.db_pool_pre_ping,
            echo=self.settings.db_echo,
        )
        
        self._session_factory = async_sessionmaker(
            self._engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autocommit=False,
            autoflush=False,
        )
        
        logger.info("DatabaseManager inicializado com sucesso")
    
    async def close(self) -> None:
        """Fecha o engine e libera recursos."""
        if self._engine is None:
            return
        
        await self._engine.dispose()
        self._engine = None
        self._session_factory = None
        logger.info("DatabaseManager fechado")
    
    async def create_tables(self) -> None:
        """
        Cria todas as tabelas definidas nos modelos.
        
        ⚠️ ATENÇÃO: Apenas para desenvolvimento/testes.
        Em produção use migrations (Alembic).
        """
        if self._engine is None:
            raise RuntimeError("DatabaseManager não inicializado. Chame initialize() primeiro.")
        
        async with self._engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        
        logger.info("Tabelas criadas com sucesso")
    
    async def drop_tables(self) -> None:
        """
        Remove todas as tabelas.
        
        ⚠️ ATENÇÃO: Apenas para desenvolvimento/testes.
        """
        if self._engine is None:
            raise RuntimeError("DatabaseManager não inicializado. Chame initialize() primeiro.")
        
        async with self._engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        
        logger.info("Tabelas removidas")
    
    def get_session_factory(self) -> async_sessionmaker[AsyncSession]:
        """
        Retorna o factory de sessões.
        
        Returns:
            async_sessionmaker configurado
        
        Raises:
            RuntimeError: Se o DatabaseManager não estiver inicializado
        """
        if self._session_factory is None:
            raise RuntimeError("DatabaseManager não inicializado. Chame initialize() primeiro.")
        return self._session_factory
    
    @property
    def engine(self) -> Any:
        """Retorna o engine atual."""
        if self._engine is None:
            raise RuntimeError("DatabaseManager não inicializado. Chame initialize() primeiro.")
        return self._engine
    
    @property
    def is_initialized(self) -> bool:
        """Verifica se o manager está inicializado."""
        return self._engine is not None


# Instância global do DatabaseManager
_db_manager: Optional[DatabaseManager] = None


async def init_db(settings: Optional[Settings] = None) -> DatabaseManager:
    """
    Inicializa o banco de dados globalmente.
    
    Args:
        settings: Configurações opcionais
    
    Returns:
        DatabaseManager inicializado
    """
    global _db_manager
    
    if _db_manager is not None and _db_manager.is_initialized:
        logger.warning("Banco de dados já inicializado")
        return _db_manager
    
    _db_manager = DatabaseManager(settings)
    await _db_manager.initialize()
    return _db_manager


async def close_db() -> None:
    """Fecha a conexão com o banco de dados global."""
    global _db_manager
    
    if _db_manager is not None:
        await _db_manager.close()
        _db_manager = None
        logger.info("Conexão com banco de dados fechada")


@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Context manager para obter uma sessão do banco de dados.
    
    Gerencia automaticamente commit/rollback e fechamento da sessão.
    
    Yields:
        AsyncSession: Sessão do SQLAlchemy
    
    Example:
        >>> async with get_session() as session:
        ...     result = await session.execute(select(User))
        ...     users = result.scalars().all()
    """
    global _db_manager
    
    if _db_manager is None or not _db_manager.is_initialized:
        raise RuntimeError(
            "Database não inicializado. "
            "Chame init_db() antes de usar get_session()"
        )
    
    session_factory = _db_manager.get_session_factory()
    session = session_factory()
    
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Dependency para FastAPI - retorna uma sessão do banco de dados.
    
    Yields:
        AsyncSession: Sessão do SQLAlchemy para uso em endpoints FastAPI
    
    Example:
        >>> @app.get("/users")
        ... async def list_users(db: AsyncSession = Depends(get_db_session)):
        ...     result = await db.execute(select(User))
        ...     return result.scalars().all()
    """
    async with get_session() as session:
        yield session


# Alias para compatibilidade
get_db = get_db_session


async def check_connection() -> bool:
    """
    Verifica se a conexão com o banco está funcionando.
    
    Returns:
        True se conectado, False caso contrário
    """
    try:
        async with get_session() as session:
            result = await session.execute("SELECT 1")
            return result.scalar() == 1
    except Exception as e:
        logger.error(f"Falha na conexão com banco de dados: {e}")
        return False
