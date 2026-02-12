"""Search schemas for GABI API.

Este módulo contém todos os schemas Pydantic para a API de busca híbrida,
consolidando modelos de request/response e health check.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator


class SearchFilters(BaseModel):
    """Filters for search queries."""
    
    source_id: Optional[str] = None
    source_type: Optional[str] = None
    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None
    tags: Optional[List[str]] = None
    metadata: Optional[Dict[str, Any]] = None
    
    @field_validator('date_from', 'date_to', mode='before')
    @classmethod
    def parse_dates(cls, v):
        """Parse date strings to datetime objects."""
        if isinstance(v, str):
            return datetime.fromisoformat(v.replace('Z', '+00:00'))
        return v


class SearchRequest(BaseModel):
    """Request para busca híbrida.
    
    Attributes:
        query: Termo de busca (texto livre)
        sources: Lista de sources para filtrar (opcional)
        filters: Filtros adicionais (opcional)
        limit: Número máximo de resultados
        offset: Offset para paginação
        hybrid_weights: Pesos para fusão (bm25, vector)
    """
    
    query: str = Field(
        ...,  # required
        min_length=1,
        max_length=1000,
        description="Termo de busca em texto livre",
        examples=["licitação pregão eletrônico"],
    )
    sources: Optional[List[str]] = Field(
        default=None,
        description="Filtrar por sources específicas",
        examples=[["tcu_acordaos", "tcu_normas"]],
    )
    filters: Optional[dict[str, Any]] = Field(
        default=None,
        description="Filtros adicionais (metadata)",
        examples=[{"metadata.year": 2024}],
    )
    limit: int = Field(
        default=10,
        ge=1,
        le=100,
        description="Número máximo de resultados",
    )
    offset: int = Field(
        default=0,
        ge=0,
        le=10000,
        description="Offset para paginação",
    )
    hybrid_weights: Optional[dict[str, float]] = Field(
        default=None,
        description="Pesos para fusão híbrida (bm25, vector)",
        examples=[{"bm25": 1.0, "vector": 1.2}],
    )
    
    @field_validator("hybrid_weights")
    @classmethod
    def validate_weights(cls, v: Optional[dict[str, float]]) -> Optional[dict[str, float]]:
        """Valida pesos da busca híbrida."""
        if v is None:
            return None
        allowed_keys = {"bm25", "vector"}
        for key in v.keys():
            if key not in allowed_keys:
                raise ValueError(f"Peso inválido: {key}. Use: {allowed_keys}")
        return v


class SearchHit(BaseModel):
    """Um resultado de busca.
    
    Attributes:
        document_id: ID único do documento
        title: Título do documento
        content_preview: Preview do conteúdo
        source_id: Source de origem
        source_type: Tipo da source (opcional)
        score: Score de relevância combinado
        bm25_score: Score BM25 (opcional)
        vector_score: Score vetorial (opcional)
        rank_bm25: Rank na busca BM25 (opcional)
        rank_vector: Rank na busca vetorial (opcional)
        metadata: Metadados do documento
        url: URL de origem (se disponível)
    """
    
    document_id: str = Field(..., description="ID único do documento")
    title: Optional[str] = Field(default=None, description="Título do documento")
    content_preview: Optional[str] = Field(default=None, description="Preview do conteúdo")
    source_id: str = Field(..., description="Source de origem")
    source_type: Optional[str] = Field(default=None, description="Tipo da source")
    score: float = Field(..., description="Score de relevância combinado (RRF)")
    bm25_score: Optional[float] = Field(default=None, description="Score BM25")
    vector_score: Optional[float] = Field(default=None, description="Score vetorial (cosine)")
    rank_bm25: Optional[int] = Field(default=None, description="Rank na busca BM25")
    rank_vector: Optional[int] = Field(default=None, description="Rank na busca vetorial")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Metadados")
    url: Optional[str] = Field(default=None, description="URL de origem")


class SearchResponse(BaseModel):
    """Resposta da busca híbrida.
    
    Attributes:
        query: Query original
        total: Total de resultados encontrados
        took_ms: Tempo de execução em ms
        hits: Lista de resultados
        aggregations: Agregações (se solicitado)
    """
    
    query: str = Field(..., description="Query original")
    total: int = Field(..., description="Total de resultados encontrados")
    took_ms: float = Field(..., description="Tempo de execução em ms")
    hits: List[SearchHit] = Field(default_factory=list, description="Resultados")
    aggregations: Optional[dict[str, Any]] = Field(
        default=None, description="Agregações"
    )


class IndexHealth(BaseModel):
    """Health de um índice.
    
    Attributes:
        index: Nome do índice
        status: Status (green, yellow, red)
        docs_count: Número de documentos
        size_mb: Tamanho em MB
    """
    
    index: str = Field(..., description="Nome do índice")
    status: str = Field(..., description="Status (green, yellow, red)")
    docs_count: int = Field(..., description="Número de documentos")
    size_mb: float = Field(..., description="Tamanho em MB")


class HealthResponse(BaseModel):
    """Resposta do health check.
    
    Attributes:
        status: Status geral (healthy, degraded, unhealthy)
        indices: Lista de índices e seus status
        took_ms: Tempo de execução
    """
    
    status: str = Field(..., description="Status geral")
    indices: List[IndexHealth] = Field(default_factory=list)
    took_ms: float = Field(..., description="Tempo de execução em ms")


# Legacy alias for backwards compatibility
SearchResult = SearchHit


class RRFConfig(BaseModel):
    """Configuration for Reciprocal Rank Fusion (legacy).
    
    Kept for backwards compatibility.
    """
    
    k: int = Field(default=60, ge=1, description="RRF ranking constant")
    weight_bm25: float = Field(default=1.0, ge=0, description="Weight for BM25 scores")
    weight_vector: float = Field(default=1.0, ge=0, description="Weight for vector scores")


class SearchMetrics(BaseModel):
    """Metrics for search performance tracking (legacy).
    
    Kept for backwards compatibility.
    """
    
    query: str
    search_type: str
    results_count: int
    took_ms: float
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    cache_hit: bool = False
    error: Optional[str] = None


__all__ = [
    "SearchRequest",
    "SearchHit",
    "SearchResult",
    "SearchResponse",
    "IndexHealth",
    "HealthResponse",
    "SearchFilters",
    "RRFConfig",
    "SearchMetrics",
]
