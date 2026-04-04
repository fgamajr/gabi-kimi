from typing import Optional
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    MONGO_STRING: str = "mongodb://mongo:27017/gabi_dou"
    DB_NAME: str = "gabi_dou"
    POSTGRES_URL: str = "postgresql://gabi:gabi@postgres:5432/gabi"
    POSTGRES_DB: str = "gabi"
    POSTGRES_USER: str = "gabi"
    DOU_DATA_PATH: Optional[str] = "/data/gabi_dou"
    ICLOUD_DATA_PATH: Optional[str] = "/data/gabi_dou"
    PIPELINE_TMP: str = "/data/gabi_dou/pipeline"
    RAW_CACHE_PATH: str = "/workspace/ops/data/raw_cache"
    DOU_INGEST_PARALLELISM: int = 3
    ES_URL: str = "http://elasticsearch:9200"
    ES_INDEX: str = "gabi_documents_v3"
    ES_ALIAS: Optional[str] = "gabi_documents"
    ES_CHUNKS_INDEX: str = "gabi_document_chunks_v1"
    TCU_ES_INDEX: str = "gabi_tcu_acordaos_v1"
    TCU_NORMAS_INDEX: str = "gabi_tcu_normas_v1"
    TCU_PUBLICACOES_INDEX: str = "gabi_tcu_publicacoes_v1"
    GABI_ALLOWED_HOSTS: str = "frontend,backend,localhost,127.0.0.1"
    GABI_CORS_ORIGINS: str = "http://localhost:8081,http://127.0.0.1:8081"
    GABI_CORS_ALLOW_CREDENTIALS: bool = False
    GABI_EXPOSE_API_DOCS: bool = True
    GABI_PUBLIC_HEALTH_DETAILS: bool = False
    GABI_ENABLE_SECURITY_HEADERS: bool = True
    GABI_HSTS_MAX_AGE: int = 31536000
    GABI_HSTS_INCLUDE_SUBDOMAINS: bool = True
    GABI_HSTS_PRELOAD: bool = False
    GABI_FRAME_OPTIONS: str = "DENY"
    GABI_REFERRER_POLICY: str = "strict-origin-when-cross-origin"
    GABI_PERMISSIONS_POLICY: str = (
        "accelerometer=(), autoplay=(), camera=(), display-capture=(), geolocation=(), "
        "gyroscope=(), magnetometer=(), microphone=(), payment=(), publickey-credentials-get=(), usb=()"
    )
    GABI_COOP: str = "same-origin"
    GABI_CORP: str = "same-origin"
    GABI_CSP: str = (
        "default-src 'self'; "
        "base-uri 'self'; "
        "object-src 'none'; "
        "frame-ancestors 'none'; "
        "img-src 'self' data: https:; "
        "style-src 'self'; "
        "script-src 'self' 'unsafe-inline'; "
        "connect-src 'self'; "
        "form-action 'self'; "
        "upgrade-insecure-requests"
    )

    # Auth
    GABI_API_TOKENS: str = ""

    @property
    def api_tokens(self) -> dict[str, str]:
        """Parse GABI_API_TOKENS='mcp:abc123,cli:xyz' → {token: label}."""
        tokens: dict[str, str] = {}
        for entry in self.GABI_API_TOKENS.split(","):
            entry = entry.strip()
            if not entry:
                continue
            if ":" in entry:
                label, token = entry.split(":", 1)
                tokens[token.strip()] = label.strip()
            else:
                tokens[entry] = "anonymous"
        return tokens

    # Hybrid search / reranker
    VECTOR_SEARCH_ENABLED: bool = False
    EMBED_SERVER_URL: str = "http://host.docker.internal:8900"
    RERANKER_ENABLED: bool = False
    RERANKER_PROVIDER: str = "http"
    RERANKER_URL: str = "http://host.docker.internal:8902"
    RERANKER_COHERE_URL: str = "https://api.cohere.com/v2/rerank"
    RERANKER_COHERE_MODEL: str = "rerank-v3.5"
    RERANKER_TOP_K: int = 50
    RERANKER_TIMEOUT: float = 5.0
    RERANKER_MAX_DOCS: int = 50
    RERANKER_MAX_DOC_CHARS: int = 2200
    QUERY_REWRITE_ENABLED: bool = True
    QUERY_REWRITE_MODEL: str = ""
    QUERY_REWRITE_TIMEOUT: float = 12.0
    QUERY_REWRITE_VARIANTS: int = 3
    RETRIEVAL_AUDIT_LOG_PATH: str = "/data/gabi_dou/audit/retrieval.jsonl"

    # Editorial highlights
    COHERE_API_KEY: str = ""
    ANTHROPIC_API_KEY: str = ""
    EDITORIAL_LLM_MODEL: str = "claude-sonnet-4-20250514"
    EDITORIAL_LOOKBACK_DAYS: int = 7

    # RAG answer pipeline
    RAG_ENABLED: bool = False
    RAG_MODEL: str = "claude-sonnet-4-20250514"
    RAG_MAX_CONTEXT_CHARS: int = 80000
    RAG_TIMEOUT: float = 30.0
    RAG_MAX_EVIDENCE_CHUNKS: int = 15

    # SEO
    SPA_DIST_DIR: str = "/shared/dist"
    SITE_URL: str = "https://gabidou.top"

    @property
    def es_target_index(self) -> str:
        return (self.ES_ALIAS or self.ES_INDEX).strip()

    @property
    def cors_origins(self) -> list[str]:
        return [
            origin.strip()
            for origin in self.GABI_CORS_ORIGINS.split(",")
            if origin.strip()
        ]

    @property
    def allowed_hosts(self) -> list[str]:
        from urllib.parse import urlparse

        hosts = [
            host.strip() for host in self.GABI_ALLOWED_HOSTS.split(",") if host.strip()
        ]
        site_hostname = urlparse(self.SITE_URL).hostname
        if site_hostname and site_hostname not in hosts:
            hosts.append(site_hostname)
        return hosts

    @property
    def hsts_header(self) -> str | None:
        if self.GABI_HSTS_MAX_AGE <= 0:
            return None

        parts = [f"max-age={self.GABI_HSTS_MAX_AGE}"]
        if self.GABI_HSTS_INCLUDE_SUBDOMAINS:
            parts.append("includeSubDomains")
        if self.GABI_HSTS_PRELOAD:
            parts.append("preload")
        return "; ".join(parts)

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
