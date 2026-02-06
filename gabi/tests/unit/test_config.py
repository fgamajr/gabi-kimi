"""Unit tests for GABI configuration settings.

These tests verify that the Settings class correctly loads from environment
variables, validates inputs, and enforces production constraints.
"""

import os
from contextlib import contextmanager
from typing import Generator

import pytest
from pydantic import ValidationError

from gabi.config import Environment, Settings


# =============================================================================
# Fixtures
# =============================================================================


@contextmanager
def set_env_vars(**kwargs) -> Generator[None, None, None]:
    """Context manager to temporarily set environment variables.
    
    Args:
        **kwargs: Environment variable names and values to set.
    
    Yields:
        None
    """
    original_values = {}
    try:
        for key, value in kwargs.items():
            env_key = f"GABI_{key.upper()}"
            original_values[env_key] = os.environ.get(env_key)
            if value is not None:
                os.environ[env_key] = str(value)
            elif env_key in os.environ:
                del os.environ[env_key]
        yield
    finally:
        for key, original in original_values.items():
            if original is not None:
                os.environ[key] = original
            elif key in os.environ:
                del os.environ[key]


# =============================================================================
# Tests
# =============================================================================


@pytest.mark.asyncio
class TestSettingsLoading:
    """Tests for settings loading from environment variables."""
    
    async def test_settings_loads_from_env(self) -> None:
        """Test that settings correctly load values from environment variables.
        
        Verifies that:
        - Environment variables with GABI_ prefix are read
        - Values are correctly parsed and assigned
        - Database URL validation works
        """
        with set_env_vars(
            database_url="postgresql+asyncpg://test:test@localhost:5432/test_db",
            log_level="debug",
            api_port="9000",
            auth_enabled="false",
        ):
            settings = Settings()
            
            assert settings.database_url == "postgresql+asyncpg://test:test@localhost:5432/test_db"
            assert settings.log_level == "debug"
            assert settings.api_port == 9000
            assert settings.auth_enabled is False


@pytest.mark.asyncio
class TestEmbeddingsConfiguration:
    """Tests for embeddings configuration validation."""
    
    async def test_embeddings_dimensions_is_384(self) -> None:
        """Test that embeddings dimensions are fixed at 384.
        
        According to ADR-001, the dimensionalidade 384 é IMUTÁVEL.
        This test verifies that:
        - The default value is 384
        - The field is frozen (cannot be changed)
        - Attempting to change it raises an error
        """
        settings = Settings()
        
        assert settings.embeddings_dimensions == 384
        
        # Verify the field is frozen (cannot be modified after creation)
        with pytest.raises(ValidationError) as exc_info:
            settings.embeddings_dimensions = 768
        
        assert "frozen" in str(exc_info.value).lower()
    
    async def test_embeddings_model_is_frozen(self) -> None:
        """Test that embeddings model is immutable."""
        settings = Settings()
        
        assert settings.embeddings_model == (
            "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
        )
        
        # Verify the field is frozen (cannot be modified after creation)
        with pytest.raises(ValidationError) as exc_info:
            settings.embeddings_model = "other-model"
        
        assert "frozen" in str(exc_info.value).lower()


@pytest.mark.asyncio
class TestAuthValidation:
    """Tests for authentication configuration validation."""
    
    async def test_auth_required_in_production(self) -> None:
        """Test that auth_enabled must be True in production.
        
        Security requirement S-001: Auth não pode ser desabilitado em produção.
        This test verifies that:
        - Creating settings with auth_enabled=False in production raises an error
        - Production settings with auth_enabled=True work correctly
        """
        # Should fail in production with auth disabled
        with pytest.raises(ValidationError) as exc_info:
            Settings(
                environment=Environment.PRODUCTION,
                auth_enabled=False,
                database_url="postgresql+asyncpg://localhost/db",
                cors_origins=["https://app.example.com"],  # Valid HTTPS origin
            )
        
        assert "auth_enabled must be True in production" in str(exc_info.value)
        
        # Should succeed with auth enabled
        settings = Settings(
            environment=Environment.PRODUCTION,
            auth_enabled=True,
            database_url="postgresql+asyncpg://localhost/db",
            cors_origins=["https://app.example.com"],  # Valid HTTPS origin
        )
        assert settings.auth_enabled is True
        assert settings.environment == Environment.PRODUCTION
    
    async def test_auth_can_be_disabled_in_local(self) -> None:
        """Test that auth can be disabled in non-production environments."""
        settings = Settings(
            environment=Environment.LOCAL,
            auth_enabled=False,
            database_url="postgresql+asyncpg://localhost/db",
        )
        assert settings.auth_enabled is False
        
        settings = Settings(
            environment=Environment.STAGING,
            auth_enabled=False,
            database_url="postgresql+asyncpg://localhost/db",
        )
        assert settings.auth_enabled is False


@pytest.mark.asyncio
class TestCORSValidation:
    """Tests for CORS configuration validation in production."""
    
    async def test_cors_validation_in_production(self) -> None:
        """Test that CORS settings are validated in production.
        
        Security requirement S-003: CORS wildcard não é permitido em produção.
        This test verifies that:
        - Wildcard (*) in cors_origins raises an error in production
        - HTTP origins (non-HTTPS) raise an error in production
        - HTTPS origins work correctly
        """
        # Wildcard should fail in production
        with pytest.raises(ValidationError) as exc_info:
            Settings(
                environment=Environment.PRODUCTION,
                cors_origins=["*"],
                database_url="postgresql+asyncpg://localhost/db",
            )
        
        assert "CORS wildcard not allowed in production" in str(exc_info.value)
        
        # HTTP origins should fail in production
        with pytest.raises(ValidationError) as exc_info:
            Settings(
                environment=Environment.PRODUCTION,
                cors_origins=["http://example.com"],
                database_url="postgresql+asyncpg://localhost/db",
            )
        
        assert "HTTP origins not allowed in production" in str(exc_info.value)
        
        # HTTPS origins should succeed
        settings = Settings(
            environment=Environment.PRODUCTION,
            cors_origins=["https://chat.tcu.gov.br", "https://gabi.tcu.gov.br"],
            database_url="postgresql+asyncpg://localhost/db",
        )
        assert "https://chat.tcu.gov.br" in settings.cors_origins
    
    async def test_cors_wildcard_allowed_in_local(self) -> None:
        """Test that CORS wildcard is allowed in non-production environments."""
        settings = Settings(
            environment=Environment.LOCAL,
            cors_origins=["*"],
            database_url="postgresql+asyncpg://localhost/db",
        )
        assert "*" in settings.cors_origins
    
    async def test_cors_http_allowed_in_local(self) -> None:
        """Test that HTTP origins are allowed in non-production environments."""
        settings = Settings(
            environment=Environment.LOCAL,
            cors_origins=["http://localhost:3000"],
            database_url="postgresql+asyncpg://localhost/db",
        )
        assert "http://localhost:3000" in settings.cors_origins


@pytest.mark.asyncio
class TestDatabaseURLValidation:
    """Tests for database URL validation."""
    
    async def test_valid_database_urls(self) -> None:
        """Test that valid PostgreSQL URLs are accepted."""
        # Standard PostgreSQL URL
        settings = Settings(database_url="postgresql://user:pass@localhost/db")
        assert settings.database_url == "postgresql://user:pass@localhost/db"
        
        # Async PostgreSQL URL
        settings = Settings(
            database_url="postgresql+asyncpg://user:pass@localhost:5432/db"
        )
        assert settings.database_url == "postgresql+asyncpg://user:pass@localhost:5432/db"
    
    async def test_invalid_database_url(self) -> None:
        """Test that invalid database URLs are rejected."""
        with pytest.raises(ValidationError) as exc_info:
            Settings(database_url="mysql://localhost/db")
        
        assert "database_url must start with" in str(exc_info.value)
        
        with pytest.raises(ValidationError) as exc_info:
            Settings(database_url="not-a-url")
        
        assert "database_url must start with" in str(exc_info.value)


@pytest.mark.asyncio
class TestDefaultValues:
    """Tests for default configuration values."""
    
    async def test_default_environment_is_local(self) -> None:
        """Test that default environment is LOCAL."""
        settings = Settings()
        assert settings.environment == Environment.LOCAL
    
    async def test_default_debug_is_false(self) -> None:
        """Test that default debug mode is False."""
        settings = Settings()
        assert settings.debug is False
    
    async def test_default_log_level_is_info(self) -> None:
        """Test that default log level is 'info'."""
        settings = Settings()
        assert settings.log_level == "info"
    
    async def test_default_api_port_is_8000(self) -> None:
        """Test that default API port is 8000."""
        settings = Settings()
        assert settings.api_port == 8000
    
    async def test_default_embeddings_url(self) -> None:
        """Test that default embeddings URL points to local TEI."""
        settings = Settings()
        assert str(settings.embeddings_url) == "http://localhost:8080/"
    
    async def test_default_search_rrf_k_is_60(self) -> None:
        """Test that default RRF k parameter is 60."""
        settings = Settings()
        assert settings.search_rrf_k == 60


@pytest.mark.asyncio
class TestFieldValidation:
    """Tests for individual field validation rules."""
    
    async def test_log_level_pattern(self) -> None:
        """Test that log_level only accepts valid values."""
        # Valid values
        for level in ["debug", "info", "warning", "error", "critical"]:
            settings = Settings(log_level=level)
            assert settings.log_level == level
        
        # Invalid value
        with pytest.raises(ValidationError) as exc_info:
            Settings(log_level="invalid")
        
        assert "log_level" in str(exc_info.value)
    
    async def test_jwt_algorithm_pattern(self) -> None:
        """Test that JWT algorithm only accepts valid algorithms."""
        # Valid algorithms
        for algo in ["RS256", "RS384", "RS512", "ES256", "ES384", "ES512"]:
            settings = Settings(jwt_algorithm=algo)
            assert settings.jwt_algorithm == algo
        
        # Invalid algorithm
        with pytest.raises(ValidationError) as exc_info:
            Settings(jwt_algorithm="HS256")
        
        assert "jwt_algorithm" in str(exc_info.value)
    
    async def test_integer_bounds_validation(self) -> None:
        """Test that integer fields enforce their bounds."""
        # Test minimum bounds
        with pytest.raises(ValidationError):
            Settings(database_pool_size=0)  # min is 1
        
        with pytest.raises(ValidationError):
            Settings(search_rrf_k=0)  # min is 1
        
        # Test maximum bounds
        with pytest.raises(ValidationError):
            Settings(database_pool_size=101)  # max is 100
        
        with pytest.raises(ValidationError):
            Settings(api_port=1023)  # min is 1024
        
        with pytest.raises(ValidationError):
            Settings(api_port=65536)  # max is 65535
    
    async def test_float_bounds_validation(self) -> None:
        """Test that float fields enforce their bounds."""
        # Valid values
        settings = Settings(search_bm25_weight=0.5)
        assert settings.search_bm25_weight == 0.5
        
        settings = Settings(search_bm25_weight=10.0)
        assert settings.search_bm25_weight == 10.0
        
        # Invalid values
        with pytest.raises(ValidationError):
            Settings(search_bm25_weight=-0.1)  # min is 0.0
        
        with pytest.raises(ValidationError):
            Settings(search_bm25_weight=10.1)  # max is 10.0
