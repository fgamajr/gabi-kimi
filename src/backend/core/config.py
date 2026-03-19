from typing import Optional
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    MONGO_STRING: str = "mongodb://mongo:27017/gabi_dou"
    DB_NAME: str = "gabi_dou"
    DOU_DATA_PATH: Optional[str] = "/data/gabi_dou"
    ICLOUD_DATA_PATH: Optional[str] = "/data/gabi_dou"
    PIPELINE_TMP: str = "/data/gabi_dou/pipeline"
    RAW_CACHE_PATH: str = "/workspace/ops/data/raw_cache"
    DOU_INGEST_PARALLELISM: int = 3
    ES_URL: str = "http://elasticsearch:9200"
    ES_INDEX: str = "gabi_documents_v3"
    ES_ALIAS: Optional[str] = "gabi_documents"
    GABI_CORS_ORIGINS: str = "http://localhost:8081,http://127.0.0.1:8081"

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
    RERANKER_URL: str = "http://host.docker.internal:8902"
    RERANKER_TOP_K: int = 50
    RERANKER_TIMEOUT: float = 5.0
    RERANKER_MAX_DOCS: int = 50
    RERANKER_MAX_DOC_CHARS: int = 2200

    # Editorial highlights
    ANTHROPIC_API_KEY: str = ""
    EDITORIAL_LLM_MODEL: str = "claude-sonnet-4-20250514"
    EDITORIAL_LOOKBACK_DAYS: int = 7

    # SEO
    SPA_DIST_DIR: str = "/shared/dist"
    SITE_URL: str = "https://gabidou.top"

    @property
    def es_target_index(self) -> str:
        return (self.ES_ALIAS or self.ES_INDEX).strip()

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.GABI_CORS_ORIGINS.split(",") if origin.strip()]
    
    class Config:
        env_file = ".env"
        extra = "ignore"

settings = Settings()
