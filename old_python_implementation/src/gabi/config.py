"""Configuração centralizada do GABI.

Pydantic Settings para validação e carregamento de configurações.
Variáveis são validadas no startup. Falha rápido em config inválida.

Example:
    >>> from gabi.config import settings
    >>> db_url = settings.database_url
    >>> es_password = settings.elasticsearch_password.get_secret_value()
"""

from typing import List, Optional
from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings

from gabi.types import Environment


class Settings(BaseSettings):
    """Configuração centralizada do GABI.
    
    Variáveis são validadas no startup. Falha rápido em config inválida.
    
    Environment Variables:
        Todas as configurações podem ser definidas via variáveis de ambiente
        com prefixo GABI_. Exemplo: GABI_DATABASE_URL, GAPI_API_PORT.
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
    database_url: str = Field(default="postgresql://localhost:5432/gabi", description="PostgreSQL connection URL")
    database_pool_size: int = Field(default=10, ge=1, le=100)
    database_max_overflow: int = Field(default=20, ge=0, le=100)
    database_pool_timeout: int = Field(default=30, ge=1, le=300)
    database_echo: bool = Field(default=False)  # SQL logging
    
    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, v: str) -> str:
        if not v.startswith(("postgresql://", "postgresql+asyncpg://")):
            raise ValueError("database_url must start with 'postgresql' or 'postgresql+asyncpg'")
        return v
    
    # === Elasticsearch ===
    elasticsearch_url: str = Field(default="http://localhost:9200")
    elasticsearch_index: str = Field(default="gabi_documents_v1")
    elasticsearch_timeout: int = Field(default=30, ge=1, le=300)
    elasticsearch_max_retries: int = Field(default=3, ge=0, le=10)
    elasticsearch_username: Optional[str] = Field(default=None)
    elasticsearch_password: Optional[SecretStr] = Field(default=None)
    
    # === Redis ===
    redis_url: str = Field(default="redis://localhost:6379/0")
    redis_password: Optional[SecretStr] = Field(default=None)
    redis_dlq_db: int = Field(default=1, ge=0, le=15)
    redis_cache_db: int = Field(default=2, ge=0, le=15)
    redis_lock_db: int = Field(default=3, ge=0, le=15)
    
    # === Embeddings (TEI) - IMUTÁVEL ===
    embeddings_url: str = Field(default="http://localhost:8080")
    embeddings_model: str = Field(
        default="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        frozen=True
    )
    embeddings_dimensions: int = Field(default=384, frozen=True)  # IMUTÁVEL - ADR-001
    embeddings_batch_size: int = Field(default=32, ge=1, le=256)
    embeddings_timeout: int = Field(default=60, ge=1, le=300)
    embeddings_max_retries: int = Field(default=3, ge=0, le=10)
    embeddings_circuit_breaker_threshold: int = Field(default=5, ge=1, le=20)
    embeddings_circuit_breaker_timeout: int = Field(default=60, ge=10, le=300)
    
    # === Pipeline ===
    pipeline_max_memory_mb: int = Field(default=3584, ge=512, le=32768)
    pipeline_fetch_timeout: int = Field(default=60, ge=1, le=600)
    pipeline_fetch_max_retries: int = Field(default=3, ge=0, le=10)
    pipeline_fetch_max_size_mb: int = Field(default=100, ge=1, le=1000)
    
    # === Fetcher Security (SSRF Protection) ===
    fetcher_ssrf_enabled: bool = Field(default=True, description="Enable SSRF protection")
    fetcher_ssrf_block_internal_ips: bool = Field(default=True, description="Block private IP ranges")
    fetcher_ssrf_allowed_hosts: List[str] = Field(
        default=[],
        description="List of allowed hosts/domains (empty = allow all except blocked)"
    )
    fetcher_circuit_breaker_enabled: bool = Field(default=True, description="Enable circuit breaker")
    fetcher_circuit_breaker_threshold: int = Field(default=5, ge=1, le=20, description="Failures before opening circuit")
    fetcher_circuit_breaker_timeout: int = Field(default=60, ge=10, le=300, description="Seconds before retry in half-open state")
    pipeline_chunk_max_tokens: int = Field(default=512, ge=100, le=2048)
    pipeline_chunk_overlap_tokens: int = Field(default=50, ge=0, le=500)
    pipeline_concurrency: int = Field(default=3, ge=1, le=20)
    pipeline_checkpoint_interval: int = Field(default=100, ge=10, le=1000)
    
    # === Busca ===
    search_rrf_k: int = Field(default=60, ge=1, le=1000)
    search_default_limit: int = Field(default=10, ge=1, le=100)
    search_max_limit: int = Field(default=100, ge=1, le=1000)
    search_bm25_weight: float = Field(default=1.0, ge=0.0, le=10.0)
    search_vector_weight: float = Field(default=1.0, ge=0.0, le=10.0)
    search_timeout_ms: int = Field(default=5000, ge=100, le=30000)
    
    # === Auth ===
    jwt_issuer: str = Field(default="https://auth.tcu.gov.br/realms/tcu")
    jwt_audience: str = Field(default="gabi-api")
    jwt_jwks_url: str = Field(
        default="https://auth.tcu.gov.br/realms/tcu/protocol/openid-connect/certs"
    )
    jwt_algorithm: str = Field(default="RS256", pattern=r"^(RS256|RS384|RS512|ES256|ES384|ES512)$")
    jwt_jwks_cache_minutes: int = Field(default=5, ge=1, le=15)
    auth_enabled: bool = Field(default=True)
    auth_public_paths: List[str] = Field(
        default=[
            "/health",
            "/health/live",
            "/health/ready",
            "/api/v1/health",
            "/api/v1/health/live",
            "/api/v1/health/ready",
            "/metrics",
            "/docs",
            "/openapi.json",
        ]
    )
    auth_fail_closed: bool = Field(
        default=False,
        description="Fail-closed authentication: reject tokens when Redis is unavailable (recommended for production)"
    )
    
    @model_validator(mode="after")
    def validate_auth_in_production(self):
        """Valida que auth está habilitado em produção."""
        if self.environment == Environment.PRODUCTION and not self.auth_enabled:
            raise ValueError("auth_enabled must be True in production")
        return self
    
    # === Rate Limiting ===
    rate_limit_enabled: bool = Field(default=True)
    rate_limit_requests_per_minute: int = Field(default=60, ge=1, le=10000)
    rate_limit_burst: int = Field(default=10, ge=1, le=1000)
    rate_limit_window_seconds: int = Field(default=60, ge=1, le=3600)
    rate_limit_fail_closed: bool = Field(default=True, description="Block requests when Redis is unavailable")
    
    # === Security ===
    trusted_proxies: List[str] = Field(
        default=[],
        description="List of trusted proxy IP addresses that can provide X-Forwarded-For headers"
    )
    
    # === MCP ===
    mcp_enabled: bool = Field(default=True)
    mcp_port: int = Field(default=8001, ge=1024, le=65535)
    mcp_auth_required: bool = Field(default=True)
    mcp_cors_origins: str = Field(default="http://localhost:3000")
    
    # === Crawler ===
    crawler_headless: bool = Field(default=True)
    crawler_delay_seconds: float = Field(default=1.0, ge=0.1, le=60.0)
    crawler_respect_robots: bool = Field(default=True)
    crawler_max_pages: int = Field(default=1000, ge=1, le=100000)
    crawler_max_depth: int = Field(default=3, ge=1, le=10)
    crawler_timeout_seconds: int = Field(default=30, ge=1, le=300)
    
    # === Governança ===
    audit_enabled: bool = Field(default=True)
    audit_retention_days: int = Field(default=2555, ge=30, le=36500)  # ~7 anos
    quality_enabled: bool = Field(default=True)
    lineage_enabled: bool = Field(default=True)
    
    # === Sources ===
    sources_path: str = Field(default="sources.yaml")
    sources_validation_strict: bool = Field(default=True)
    
    # === API ===
    api_host: str = Field(default="0.0.0.0")
    api_port: int = Field(default=8000, ge=1024, le=65535)
    api_workers: int = Field(default=1, ge=1, le=10)
    api_reload: bool = Field(default=False)
    
    # === CORS ===
    cors_origins: str = Field(default="http://localhost:3000")
    cors_allow_credentials: bool = Field(default=True)
    cors_allow_methods: str = Field(default="GET,POST,PUT,DELETE")
    cors_allow_headers: str = Field(default="Authorization,Content-Type,X-Request-ID")
    
    @property
    def cors_origins_list(self) -> List[str]:
        """Retorna CORS origins como lista."""
        return [o.strip() for o in self.cors_origins.split(",")]
    
    @property
    def cors_allow_methods_list(self) -> List[str]:
        """Retorna métodos permitidos como lista."""
        return [m.strip() for m in self.cors_allow_methods.split(",")]
    
    @property
    def cors_allow_headers_list(self) -> List[str]:
        """Retorna headers permitidos como lista."""
        return [h.strip() for h in self.cors_allow_headers.split(",")]

    @property
    def mcp_cors_origins_list(self) -> List[str]:
        """Retorna MCP CORS origins como lista."""
        return [o.strip() for o in self.mcp_cors_origins.split(",")]
    
    @model_validator(mode="after")
    def validate_cors_in_production(self):
        """Valida configurações CORS em produção."""
        if self.environment == Environment.PRODUCTION:
            origins = self.cors_origins_list
            if "*" in origins:
                raise ValueError("CORS wildcard not allowed in production")
            if any("http://" in origin for origin in origins):
                raise ValueError("HTTP origins not allowed in production (use HTTPS)")
        return self


# Singleton global
settings = Settings()
