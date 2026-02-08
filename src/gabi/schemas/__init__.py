"""Schemas - Validação e serialização de dados."""

from gabi.schemas.search import (
    SearchFilters,
    SearchRequest,
    SearchResult,
    SearchResponse,
    RRFConfig,
    SearchMetrics,
)

from gabi.schemas.health import (
    HealthStatus,
    ComponentStatus,
    HealthResponse,
    LivenessResponse,
    ReadinessCheck,
    ReadinessResponse,
)

from gabi.schemas.documents import (
    DocumentStatus,
    DocumentListItem,
    DocumentDetail,
    DocumentChunkInfo,
    DocumentListResponse,
    DocumentDetailResponse,
    DocumentReindexRequest,
    DocumentReindexResponse,
    DocumentDeleteResponse,
    DocumentFilterParams,
)

from gabi.schemas.sources import (
    SourceType,
    SourceStatus,
    SensitivityLevel,
    SourceListItem,
    SourceDetail,
    SourceSyncRequest,
    SourceSyncResponse,
    SourceStatusResponse,
    SourceStats,
    SourceListResponse,
    SourceStatsResponse,
)

from gabi.schemas.admin import (
    ExecutionStatus,
    DLQStatus,
    ExecutionStats,
    ExecutionListItem,
    ExecutionDetail,
    ExecutionListResponse,
    DLQMessageItem,
    DLQListResponse,
    DLQRetryRequest,
    DLQRetryResponse,
    DLQResolveRequest,
    DLQResolveResponse,
    SystemStats,
    SystemStatsResponse,
)

__all__ = [
    # Search
    "SearchFilters",
    "SearchRequest",
    "SearchResult",
    "SearchResponse",
    "RRFConfig",
    "SearchMetrics",
    # Health
    "HealthStatus",
    "ComponentStatus",
    "HealthResponse",
    "LivenessResponse",
    "ReadinessCheck",
    "ReadinessResponse",
    # Documents
    "DocumentStatus",
    "DocumentListItem",
    "DocumentDetail",
    "DocumentChunkInfo",
    "DocumentListResponse",
    "DocumentDetailResponse",
    "DocumentReindexRequest",
    "DocumentReindexResponse",
    "DocumentDeleteResponse",
    "DocumentFilterParams",
    # Sources
    "SourceType",
    "SourceStatus",
    "SensitivityLevel",
    "SourceListItem",
    "SourceDetail",
    "SourceSyncRequest",
    "SourceSyncResponse",
    "SourceStatusResponse",
    "SourceStats",
    "SourceListResponse",
    "SourceStatsResponse",
    # Admin
    "ExecutionStatus",
    "DLQStatus",
    "ExecutionStats",
    "ExecutionListItem",
    "ExecutionDetail",
    "ExecutionListResponse",
    "DLQMessageItem",
    "DLQListResponse",
    "DLQRetryRequest",
    "DLQRetryResponse",
    "DLQResolveRequest",
    "DLQResolveResponse",
    "SystemStats",
    "SystemStatsResponse",
]
