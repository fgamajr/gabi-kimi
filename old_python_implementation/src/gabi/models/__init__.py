"""Models - Camada de dados do GABI.

Define modelos SQLAlchemy para persistência de documentos, chunks,
fontes, execuções e mensagens DLQ.

Example:
    >>> from gabi.models.base import Base
    >>> from gabi.models.document import Document
    >>> from gabi.models.chunk import DocumentChunk
"""

# Import base first (no side effects)
from gabi.models.base import Base

# Import enums and simple models that don't have side effects
from gabi.models.document import DocumentStatus

# Import all models - lazy loading to avoid DB initialization issues
try:
    from gabi.models.audit import AuditLog
    from gabi.models.lineage import LineageNode, LineageEdge
    from gabi.models.dlq import DLQMessage, DLQStatus
    from gabi.models.execution import ExecutionManifest, ExecutionStatus
    from gabi.models.cache import ChangeDetectionCache
    from gabi.models.pipeline_action import PipelineAction
    from gabi.models.source import SourceRegistry
    from gabi.models.document import Document
    from gabi.models.chunk import DocumentChunk
except ImportError:
    # Models may not be available without DB initialization
    pass

# Note: Full model imports may require database initialization
# Use lazy imports for production code:
#   from gabi.models.document import Document
#   from gabi.models.chunk import DocumentChunk

__all__ = [
    # Base
    "Base",
    # Enums (safe to import)
    "DocumentStatus",
    # Models (may require DB initialization)
    "AuditLog",
    "LineageNode",
    "LineageEdge",
    "DLQMessage",
    "DLQStatus",
    "ExecutionManifest",
    "ExecutionStatus",
    "ChangeDetectionCache",
    "PipelineAction",
    "SourceRegistry",
    "Document",
    "DocumentChunk",
]
