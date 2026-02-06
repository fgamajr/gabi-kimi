"""Pytest fixtures and configuration for GABI tests.

This module provides all necessary fixtures for testing the GABI application,
including database setup, async session management, and HTTP client fixtures.
"""

import asyncio
from typing import AsyncGenerator, Generator

import httpx
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from gabi.config import Environment, Settings
from gabi.models.base import Base


# =============================================================================
# Session-scoped fixtures
# =============================================================================


@pytest.fixture(scope="session")
def event_loop() -> Generator[asyncio.AbstractEventLoop, None, None]:
    """Create an instance of the default event loop for the test session.
    
    This fixture ensures that all async tests share the same event loop,
    preventing issues with resources that are bound to a specific loop.
    """
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
def settings() -> Settings:
    """Provide test-specific settings.
    
    Returns a Settings instance configured for testing with:
    - Local environment
    - Test database URL
    - Disabled auth for unit tests (override in integration tests)
    - Debug mode enabled
    """
    return Settings(
        environment=Environment.LOCAL,
        debug=True,
        log_level="debug",
        database_url="postgresql+asyncpg://postgres:postgres@localhost:5432/gabi_test",
        database_echo=False,
        auth_enabled=False,  # Disabled for unit tests
        elasticsearch_url="http://localhost:9200",
        redis_url="redis://localhost:6379/15",  # Use DB 15 for tests
        audit_enabled=False,  # Reduce noise in tests
        rate_limit_enabled=False,  # Disable rate limiting for tests
    )


@pytest.fixture(scope="session")
async def db_engine(settings: Settings) -> AsyncGenerator[AsyncEngine, None]:
    """Create an async database engine for the test session.
    
    This engine is used to create all tables before tests run and
    drop them after all tests complete.
    
    Yields:
        AsyncEngine: SQLAlchemy async engine configured for tests.
    """
    engine = create_async_engine(
        settings.database_url,
        echo=settings.database_echo,
        pool_size=5,
        max_overflow=10,
        pool_pre_ping=True,
    )
    
    # Create all tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    yield engine
    
    # Drop all tables after tests
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    
    await engine.dispose()


# =============================================================================
# Function-scoped fixtures
# =============================================================================


@pytest_asyncio.fixture
async def db_session(db_engine: AsyncEngine) -> AsyncGenerator[AsyncSession, None]:
    """Provide an async database session for each test function.
    
    This fixture creates a new session for each test and handles
    rollback after each test to ensure test isolation.
    
    Args:
        db_engine: The session-scoped database engine fixture.
    
    Yields:
        AsyncSession: A database session with active transaction.
    """
    async_session = sessionmaker(
        db_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )
    
    async with async_session() as session:
        async with session.begin():
            yield session
        # Transaction is automatically rolled back after test


@pytest_asyncio.fixture
async def client(settings: Settings) -> AsyncGenerator[httpx.AsyncClient, None]:
    """Provide an async HTTP client for testing the API.
    
    This fixture creates an httpx AsyncClient configured to communicate
    with the GABI API during tests.
    
    Args:
        settings: The test settings fixture.
    
    Yields:
        AsyncClient: HTTP client configured for API testing.
    """
    from gabi.main import create_application
    
    app = create_application(settings)
    
    async with httpx.AsyncClient(
        app=app,
        base_url="http://test",
        follow_redirects=True,
    ) as client:
        yield client


# =============================================================================
# Helper fixtures for specific test scenarios
# =============================================================================


@pytest.fixture
def auth_settings() -> Settings:
    """Provide settings with authentication enabled.
    
    Use this fixture in integration tests that require authentication.
    """
    return Settings(
        environment=Environment.LOCAL,
        debug=True,
        database_url="postgresql+asyncpg://postgres:postgres@localhost:5432/gabi_test",
        auth_enabled=True,
        jwt_issuer="https://auth.tcu.gov.br/realms/tcu",
        jwt_audience="gabi-api",
        jwt_jwks_url="https://auth.tcu.gov.br/realms/tcu/protocol/openid-connect/certs",
    )


@pytest.fixture
def production_settings() -> Settings:
    """Provide production-like settings for validation tests.
    
    Use this fixture to test production-specific validations.
    """
    return Settings(
        environment=Environment.PRODUCTION,
        debug=False,
        log_level="info",
        database_url="postgresql+asyncpg://postgres:postgres@localhost:5432/gabi_prod",
        auth_enabled=True,
        cors_origins=["https://chat.tcu.gov.br", "https://gabi.tcu.gov.br"],
    )
