"""Métricas Prometheus do GABI.

Expõe métricas técnicas e de negócio para monitoramento.
Baseado em GABI_SPECS_FINAL_v1.md Seção 2.12.
"""

import logging
import time
from contextlib import contextmanager
from typing import Any, Callable, Dict, List, Optional, TypeVar, Union

from prometheus_client import (
    Counter,
    Gauge,
    Histogram,
    Info,
    Summary,
    generate_latest,
    CONTENT_TYPE_LATEST,
)

from gabi.config import settings

logger = logging.getLogger(__name__)


# =============================================================================
# Métricas de Infraestrutura
# =============================================================================

# Informações da aplicação
APP_INFO = Info("gabi_app", "Informações da aplicação GABI")
APP_INFO.info({
    "version": "2.1.0",
    "environment": settings.environment.value,
})

# HTTP
HTTP_REQUESTS_TOTAL = Counter(
    "gabi_http_requests_total",
    "Total de requisições HTTP",
    ["method", "endpoint", "status"],
)

HTTP_REQUEST_DURATION = Histogram(
    "gabi_http_request_duration_seconds",
    "Duração de requisições HTTP",
    ["method", "endpoint"],
    buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
)

HTTP_REQUEST_SIZE = Histogram(
    "gabi_http_request_size_bytes",
    "Tamanho das requisições HTTP",
    ["method", "endpoint"],
    buckets=[100, 1000, 10000, 100000, 1000000],
)

HTTP_RESPONSE_SIZE = Histogram(
    "gabi_http_response_size_bytes",
    "Tamanho das respostas HTTP",
    ["method", "endpoint"],
    buckets=[100, 1000, 10000, 100000, 1000000],
)

# Conexões ativas
ACTIVE_CONNECTIONS = Gauge(
    "gabi_active_connections",
    "Conexões HTTP ativas",
)

# Rate limiting
RATE_LIMIT_HITS = Counter(
    "gabi_rate_limit_hits_total",
    "Total de hits no rate limit",
    ["client_id"],
)


# =============================================================================
# Métricas de Banco de Dados
# =============================================================================

DB_CONNECTIONS = Gauge(
    "gabi_db_connections",
    "Conexões com banco de dados",
    ["state"],  # idle, active, total
)

DB_QUERY_DURATION = Histogram(
    "gabi_db_query_duration_seconds",
    "Duração de queries",
    ["operation"],  # select, insert, update, delete
    buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0],
)

DB_QUERY_ERRORS = Counter(
    "gabi_db_query_errors_total",
    "Erros em queries",
    ["operation", "error_type"],
)


# =============================================================================
# Métricas de Elasticsearch
# =============================================================================

ES_REQUESTS_TOTAL = Counter(
    "gabi_elasticsearch_requests_total",
    "Total de requests para Elasticsearch",
    ["operation", "status"],
)

ES_REQUEST_DURATION = Histogram(
    "gabi_elasticsearch_request_duration_seconds",
    "Duração de requests ES",
    ["operation"],
    buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5],
)

ES_INDEX_SIZE = Gauge(
    "gabi_elasticsearch_index_size_bytes",
    "Tamanho do índice ES",
    ["index_name"],
)

ES_DOCUMENTS = Gauge(
    "gabi_elasticsearch_documents_total",
    "Total de documentos no índice",
    ["index_name"],
)


# =============================================================================
# Métricas de Redis
# =============================================================================

REDIS_CONNECTIONS = Gauge(
    "gabi_redis_connections",
    "Conexões Redis ativas",
)

REDIS_OPERATIONS = Counter(
    "gabi_redis_operations_total",
    "Operações Redis",
    ["operation"],  # get, set, delete, etc
)

REDIS_OPERATION_DURATION = Histogram(
    "gabi_redis_operation_duration_seconds",
    "Duração de operações Redis",
    ["operation"],
    buckets=[0.0001, 0.0005, 0.001, 0.005, 0.01],
)


# =============================================================================
# Métricas de Pipeline
# =============================================================================

PIPELINE_DOCUMENTS = Counter(
    "gabi_pipeline_documents_total",
    "Documentos processados no pipeline",
    ["source_id", "status"],  # success, failed, deduplicated
)

PIPELINE_CHUNKS = Counter(
    "gabi_pipeline_chunks_total",
    "Chunks criados",
    ["source_id"],
)

PIPELINE_EMBEDDINGS = Counter(
    "gabi_pipeline_embeddings_total",
    "Embeddings gerados",
    ["source_id", "status"],
)

PIPELINE_DURATION = Histogram(
    "gabi_pipeline_duration_seconds",
    "Duração do pipeline",
    ["source_id", "phase"],
    buckets=[1.0, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0, 600.0],
)

PIPELINE_QUEUE_SIZE = Gauge(
    "gabi_pipeline_queue_size",
    "Tamanho da fila do pipeline",
    ["source_id"],
)

PIPELINE_MEMORY = Gauge(
    "gabi_pipeline_memory_bytes",
    "Uso de memória do pipeline",
    ["source_id"],
)


# =============================================================================
# Métricas de Crawling
# =============================================================================

CRAWL_PAGES = Counter(
    "gabi_crawl_pages_total",
    "Páginas crawleadas",
    ["source_id", "status"],
)

CRAWL_LINKS = Counter(
    "gabi_crawl_links_total",
    "Links extraídos",
    ["source_id"],
)

CRAWL_DURATION = Histogram(
    "gabi_crawl_duration_seconds",
    "Duração de crawl",
    ["source_id"],
    buckets=[0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0],
)

CRAWL_ROBOTS_BLOCKED = Counter(
    "gabi_crawl_robots_blocked_total",
    "URLs bloqueadas por robots.txt",
    ["domain"],
)

CRAWL_RATE_LIMIT_DELAY = Gauge(
    "gabi_crawl_rate_limit_delay_seconds",
    "Delay atual de rate limiting",
    ["domain"],
)


# =============================================================================
# Métricas de Busca
# =============================================================================

SEARCH_REQUESTS = Counter(
    "gabi_search_requests_total",
    "Requisições de busca",
    ["search_type"],  # text, semantic, hybrid
)

SEARCH_DURATION = Histogram(
    "gabi_search_duration_seconds",
    "Duração de busca",
    ["search_type"],
    buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0],
)

SEARCH_RESULTS = Histogram(
    "gabi_search_results_count",
    "Número de resultados",
    ["search_type"],
    buckets=[0, 1, 5, 10, 20, 50, 100],
)

SEARCH_ERRORS = Counter(
    "gabi_search_errors_total",
    "Erros de busca",
    ["search_type", "error_type"],
)


# =============================================================================
# Métricas de Embeddings
# =============================================================================

EMBEDDING_REQUESTS = Counter(
    "gabi_embedding_requests_total",
    "Requisições de embedding",
    ["status"],
)

EMBEDDING_DURATION = Histogram(
    "gabi_embedding_duration_seconds",
    "Duração de geração de embeddings",
    ["batch_size"],
    buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0],
)

EMBEDDING_BATCH_SIZE = Histogram(
    "gabi_embedding_batch_size",
    "Tamanho dos batches",
    buckets=[1, 2, 4, 8, 16, 32, 64, 128],
)

EMBEDDING_DIMENSIONS = Gauge(
    "gabi_embedding_dimensions",
    "Dimensionalidade dos embeddings",
)
# Set valor fixo conforme ADR-001
EMBEDDING_DIMENSIONS.set(384)


# =============================================================================
# Métricas de MCP (Model Context Protocol)
# =============================================================================

MCP_CONNECTIONS_TOTAL = Gauge(
    "gabi_mcp_connections_total",
    "Total de conexões MCP ativas",
)

MCP_TOOL_CALLS_TOTAL = Counter(
    "gabi_mcp_tool_calls_total",
    "Total de chamadas a tools MCP",
    ["tool_name"],
)

MCP_TOOL_DURATION = Histogram(
    "gabi_mcp_tool_duration_seconds",
    "Duração de execução de tools MCP",
    ["tool_name"],
    buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0],
)

MCP_SESSION_DURATION = Histogram(
    "gabi_mcp_session_duration_seconds",
    "Duração de sessões MCP",
    buckets=[60.0, 300.0, 600.0, 1800.0, 3600.0],
)

MCP_ERRORS_TOTAL = Counter(
    "gabi_mcp_errors_total",
    "Total de erros MCP",
    ["error_type"],
)


# =============================================================================
# Métricas de DLQ
# =============================================================================

DLQ_MESSAGES = Counter(
    "gabi_dlq_messages_total",
    "Mensagens na DLQ",
    ["source_id", "action"],  # created, retried, resolved
)

DLQ_QUEUE_SIZE = Gauge(
    "gabi_dlq_queue_size",
    "Tamanho da DLQ",
    ["source_id"],
)


# =============================================================================
# Métricas de Negócio
# =============================================================================

DOCUMENTS_TOTAL = Gauge(
    "gabi_documents_total",
    "Total de documentos no sistema",
    ["source_id", "status"],
)

SOURCES_TOTAL = Gauge(
    "gabi_sources_total",
    "Total de fontes",
    ["status"],
)

SYNC_LAST_SUCCESS = Gauge(
    "gabi_sync_last_success_timestamp",
    "Timestamp da última sincronização bem-sucedida",
    ["source_id"],
)

SYNC_DURATION = Histogram(
    "gabi_sync_duration_seconds",
    "Duração de sincronizações",
    ["source_id"],
    buckets=[60.0, 300.0, 600.0, 1800.0, 3600.0],
)


# =============================================================================
# Métricas de Governança
# =============================================================================

AUDIT_EVENTS = Counter(
    "gabi_audit_events_total",
    "Eventos de auditoria",
    ["event_type", "severity"],
)

QUALITY_SCORE = Gauge(
    "gabi_quality_score",
    "Score de qualidade",
    ["source_id"],
)

LINEAGE_NODES = Gauge(
    "gabi_lineage_nodes_total",
    "Nós no grafo de lineage",
    ["node_type"],
)

LINEAGE_EDGES = Gauge(
    "gabi_lineage_edges_total",
    "Arestas no grafo de lineage",
    ["edge_type"],
)


# =============================================================================
# Context Managers para Métricas
# =============================================================================

F = TypeVar("F", bound=Callable[..., Any])


@contextmanager
def timed(metric: Histogram, *labels: str):
    """Context manager para medir duração.
    
    Args:
        metric: Métrica Histogram
        labels: Labels para a métrica
        
    Example:
        with timed(PIPELINE_DURATION, "source1", "parsing"):
            parse_document()
    """
    start = time.time()
    try:
        yield
    finally:
        duration = time.time() - start
        metric.labels(*labels).observe(duration)


@contextmanager
def db_timer(operation: str):
    """Timer para queries de banco."""
    start = time.time()
    try:
        yield
    except Exception as e:
        DB_QUERY_ERRORS.labels(operation=operation, error_type=type(e).__name__).inc()
        raise
    finally:
        duration = time.time() - start
        DB_QUERY_DURATION.labels(operation=operation).observe(duration)


class MetricsMiddleware:
    """Middleware para coleta de métricas HTTP.
    
    Integra com FastAPI para coletar métricas
    de todas as requisições.
    """
    
    def __init__(self, app=None):
        self.app = app
    
    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        
        method = scope.get("method", "GET")
        path = scope.get("path", "/")
        
        # Simplifica endpoint para métricas
        endpoint = self._simplify_endpoint(path)
        
        start = time.time()
        status_code = 200
        
        ACTIVE_CONNECTIONS.inc()
        
        async def wrapped_send(message):
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message.get("status", 200)
            await send(message)
        
        try:
            await self.app(scope, receive, wrapped_send)
        finally:
            duration = time.time() - start
            
            HTTP_REQUESTS_TOTAL.labels(
                method=method,
                endpoint=endpoint,
                status=str(status_code),
            ).inc()
            
            HTTP_REQUEST_DURATION.labels(
                method=method,
                endpoint=endpoint,
            ).observe(duration)
            
            ACTIVE_CONNECTIONS.dec()
    
    def _simplify_endpoint(self, path: str) -> str:
        """Simplifica path para métricas."""
        # Remove IDs e normaliza
        parts = path.split("/")
        simplified = []
        
        for part in parts:
            if not part:
                continue
            # Se parece UUID ou número, substitui
            if len(part) == 32 or part.replace("-", "").isalnum() and len(part) > 20:
                simplified.append("{id}")
            elif part.isdigit():
                simplified.append("{id}")
            else:
                simplified.append(part)
        
        return "/" + "/".join(simplified) if simplified else "/"


# =============================================================================
# Funções de Atualização
# =============================================================================

def update_source_metrics(source_id: str, document_count: int, last_sync: Optional[float] = None):
    """Atualiza métricas de uma fonte.
    
    Args:
        source_id: ID da fonte
        document_count: Número de documentos
        last_sync: Timestamp da última sincronização
    """
    DOCUMENTS_TOTAL.labels(source_id=source_id, status="active").set(document_count)
    
    if last_sync:
        SYNC_LAST_SUCCESS.labels(source_id=source_id).set(last_sync)


def record_pipeline_success(
    source_id: str,
    documents: int,
    chunks: int,
    embeddings: int,
    duration: float,
):
    """Registra sucesso de pipeline.
    
    Args:
        source_id: ID da fonte
        documents: Documentos processados
        chunks: Chunks criados
        embeddings: Embeddings gerados
        duration: Duração em segundos
    """
    PIPELINE_DOCUMENTS.labels(source_id=source_id, status="success").inc(documents)
    PIPELINE_CHUNKS.labels(source_id=source_id).inc(chunks)
    PIPELINE_EMBEDDINGS.labels(source_id=source_id, status="success").inc(embeddings)
    PIPELINE_DURATION.labels(source_id=source_id, phase="total").observe(duration)


def record_pipeline_failure(source_id: str, error_type: str):
    """Registra falha de pipeline.
    
    Args:
        source_id: ID da fonte
        error_type: Tipo de erro
    """
    PIPELINE_DOCUMENTS.labels(source_id=source_id, status="failed").inc()


def record_search_metrics(
    search_type: str,
    duration: float,
    result_count: int,
    error: bool = False,
    error_type: str = "",
):
    """Registra métricas de busca.
    
    Args:
        search_type: Tipo de busca
        duration: Duração em segundos
        result_count: Número de resultados
        error: Se houve erro
        error_type: Tipo de erro
    """
    SEARCH_REQUESTS.labels(search_type=search_type).inc()
    SEARCH_DURATION.labels(search_type=search_type).observe(duration)
    SEARCH_RESULTS.labels(search_type=search_type).observe(result_count)
    
    if error:
        SEARCH_ERRORS.labels(search_type=search_type, error_type=error_type).inc()


def record_crawl_metrics(
    source_id: str,
    pages: int = 0,
    links: int = 0,
    duration: float = 0,
    blocked_by_robots: int = 0,
):
    """Registra métricas de crawling.
    
    Args:
        source_id: ID da fonte
        pages: Páginas crawleadas
        links: Links extraídos
        duration: Duração em segundos
        blocked_by_robots: Bloqueados por robots.txt
    """
    CRAWL_PAGES.labels(source_id=source_id, status="success").inc(pages)
    CRAWL_LINKS.labels(source_id=source_id).inc(links)
    CRAWL_DURATION.labels(source_id=source_id).observe(duration)


def get_metrics_response() -> tuple:
    """Retorna resposta de métricas para HTTP.
    
    Returns:
        Tuple (content, content_type)
    """
    return generate_latest(), CONTENT_TYPE_LATEST


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    # HTTP
    "HTTP_REQUESTS_TOTAL",
    "HTTP_REQUEST_DURATION",
    "ACTIVE_CONNECTIONS",
    "RATE_LIMIT_HITS",
    # DB
    "DB_CONNECTIONS",
    "DB_QUERY_DURATION",
    "DB_QUERY_ERRORS",
    # ES
    "ES_REQUESTS_TOTAL",
    "ES_REQUEST_DURATION",
    "ES_INDEX_SIZE",
    "ES_DOCUMENTS",
    # Pipeline
    "PIPELINE_DOCUMENTS",
    "PIPELINE_DURATION",
    "PIPELINE_QUEUE_SIZE",
    # Crawl
    "CRAWL_PAGES",
    "CRAWL_DURATION",
    # Search
    "SEARCH_REQUESTS",
    "SEARCH_DURATION",
    "SEARCH_RESULTS",
    # Embeddings
    "EMBEDDING_REQUESTS",
    "EMBEDDING_DURATION",
    # MCP
    "MCP_CONNECTIONS_TOTAL",
    "MCP_TOOL_CALLS_TOTAL",
    "MCP_TOOL_DURATION",
    "MCP_SESSION_DURATION",
    "MCP_ERRORS_TOTAL",
    # DLQ
    "DLQ_MESSAGES",
    # Business
    "DOCUMENTS_TOTAL",
    "SOURCES_TOTAL",
    "SYNC_LAST_SUCCESS",
    # Governance
    "AUDIT_EVENTS",
    "QUALITY_SCORE",
    # Utils
    "timed",
    "db_timer",
    "MetricsMiddleware",
    "update_source_metrics",
    "record_pipeline_success",
    "record_pipeline_failure",
    "record_search_metrics",
    "record_crawl_metrics",
    "get_metrics_response",
]
