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

# Note: Full model imports may require database initialization
# Use lazy imports for production code:
#   from gabi.models.document import Document
#   from gabi.models.chunk import DocumentChunk

__all__ = [
    # Base
    "Base",
    # Enums (safe to import)
    "DocumentStatus",
    # Note: Other models require lazy import due to DB initialization
]
