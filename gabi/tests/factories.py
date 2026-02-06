"""Factory Boy factories for GABI test data generation.

This module provides async factories for creating test data using factory_boy
with async support. All factories are designed to work with SQLAlchemy async
sessions and can be used in pytest-asyncio tests.

Example:
    async def test_document_creation(db_session):
        source = await SourceRegistryFactory.create_async(session=db_session)
        document = await DocumentFactory.create_async(
            session=db_session,
            source_id=source.id
        )
"""

import uuid
from datetime import datetime, timezone
from typing import Any

import factory
from factory import Faker, LazyAttribute, Sequence

# =============================================================================
# Base Factory Configuration
# =============================================================================


class AsyncSQLAlchemyFactory(factory.Factory):
    """Base factory for async SQLAlchemy models.
    
    Provides common configuration and utilities for all async factories.
    """
    
    class Meta:
        abstract = True
    
    @classmethod
    async def create_async(cls, session, **kwargs) -> Any:
        """Create and persist an instance asynchronously.
        
        Args:
            session: The async SQLAlchemy session to use.
            **kwargs: Factory attributes to override.
        
        Returns:
            The created and persisted model instance.
        """
        instance = cls.build(**kwargs)
        session.add(instance)
        await session.flush()
        await session.refresh(instance)
        return instance
    
    @classmethod
    async def create_batch_async(cls, session, size: int, **kwargs) -> list[Any]:
        """Create multiple instances asynchronously.
        
        Args:
            session: The async SQLAlchemy session to use.
            size: Number of instances to create.
            **kwargs: Factory attributes to override (applied to all).
        
        Returns:
            List of created and persisted model instances.
        """
        instances = []
        for _ in range(size):
            instance = await cls.create_async(session=session, **kwargs)
            instances.append(instance)
        return instances


# =============================================================================
# SourceRegistry Factory
# =============================================================================


class SourceRegistryFactory(AsyncSQLAlchemyFactory):
    """Factory for creating SourceRegistry test data.
    
    Generates realistic source registry entries with all required fields
    and sensible defaults for testing.
    
    Attributes:
        id: Unique identifier for the source (e.g., 'tcu_acordaos').
        name: Human-readable name for the source.
        type: Source type (api, web, file, crawler).
        status: Current status of the source.
        config_hash: SHA256 hash of the source configuration.
        config_json: Configuration as JSON object.
        owner_email: Email of the source owner.
    """
    
    class Meta:
        model = dict  # Placeholder - replace with actual model when available
        # model = "gabi.models.source.SourceRegistry"
    
    id = Sequence(lambda n: f"test_source_{n}")
    name = LazyAttribute(lambda obj: f"Test Source {obj.id}")
    description = Faker("sentence", nb_words=10)
    type = factory.Iterator(["api", "web", "file", "crawler"])
    status = "active"
    config_hash = Faker("sha256")
    config_json = factory.Dict({
        "url": factory.Faker("url").generate(),
        "method": "GET",
        "timeout": 30,
    })
    
    # Statistics
    document_count = 0
    total_documents_ingested = 0
    last_document_at = None
    
    # Execution
    last_sync_at = None
    last_success_at = None
    next_scheduled_sync = None
    
    # Error tracking
    consecutive_errors = 0
    last_error_message = None
    last_error_at = None
    
    # Governance
    owner_email = Faker("email")
    sensitivity = "internal"
    retention_days = 2555
    
    # Timestamps
    created_at = factory.LazyFunction(lambda: datetime.now(timezone.utc))
    updated_at = factory.LazyFunction(lambda: datetime.now(timezone.utc))


# =============================================================================
# Document Factory
# =============================================================================


class DocumentFactory(AsyncSQLAlchemyFactory):
    """Factory for creating Document test data.
    
    Generates realistic document entries with all required fields.
    
    Attributes:
        id: UUID primary key.
        document_id: Unique document identifier (e.g., 'ACORDAO-1234/2024').
        source_id: Reference to the source registry.
        fingerprint: Content fingerprint (SHA256).
        title: Document title.
        status: Document status.
    """
    
    class Meta:
        model = dict  # Placeholder - replace with actual model when available
        # model = "gabi.models.document.Document"
    
    id = factory.LazyFunction(uuid.uuid4)
    document_id = Sequence(lambda n: f"DOC-{n:08d}/2024")
    source_id = "test_source"
    
    # Content
    fingerprint = Faker("sha256")
    fingerprint_algorithm = "sha256"
    title = Faker("sentence", nb_words=6)
    content_preview = Faker("text", max_nb_chars=500)
    content_hash = Faker("sha256")
    content_size_bytes = factory.Faker("random_int", min=100, max=1000000)
    
    # Metadata
    metadata = factory.Dict({
        "author": factory.Faker("name").generate(),
        "department": factory.Faker("company").generate(),
        "year": 2024,
    })
    url = Faker("url")
    content_type = factory.Iterator(["text/html", "application/pdf", "text/plain"])
    language = "pt-BR"
    
    # Status
    status = "active"
    version = 1
    
    # Soft delete
    is_deleted = False
    deleted_at = None
    deleted_reason = None
    deleted_by = None
    
    # Timestamps
    ingested_at = factory.LazyFunction(lambda: datetime.now(timezone.utc))
    updated_at = factory.LazyFunction(lambda: datetime.now(timezone.utc))
    reindexed_at = None
    
    # Cross-store consistency
    es_indexed = False
    es_indexed_at = None
    chunks_count = 0
    
    # Factory traits for different states
    class Params:
        """Factory traits for creating documents in specific states."""
        
        deleted = factory.Trait(
            is_deleted=True,
            deleted_at=factory.LazyFunction(lambda: datetime.now(timezone.utc)),
            deleted_reason="Test deletion",
            deleted_by="test_user",
            status="deleted",
        )
        
        indexed = factory.Trait(
            es_indexed=True,
            es_indexed_at=factory.LazyFunction(lambda: datetime.now(timezone.utc)),
        )
        
        with_chunks = factory.Trait(
            chunks_count=factory.Faker("random_int", min=1, max=10),
        )


# =============================================================================
# DocumentChunk Factory
# =============================================================================


class DocumentChunkFactory(AsyncSQLAlchemyFactory):
    """Factory for creating DocumentChunk test data.
    
    Generates document chunks with embeddings for testing vector search
    and chunking functionality.
    
    Attributes:
        id: UUID primary key.
        document_id: Reference to the parent document.
        chunk_index: Position within the document chunks.
        chunk_text: The actual text content of the chunk.
        embedding: Vector embedding (384 dimensions).
    """
    
    class Meta:
        model = dict  # Placeholder - replace with actual model when available
        # model = "gabi.models.chunk.DocumentChunk"
    
    id = factory.LazyFunction(uuid.uuid4)
    document_id = "DOC-00000001/2024"
    chunk_index = Sequence(lambda n: n)
    
    # Content
    chunk_text = Faker("paragraph", nb_sentences=5)
    token_count = factory.Faker("random_int", min=10, max=512)
    char_count = LazyAttribute(lambda obj: len(obj.chunk_text))
    
    # Embedding (384 dimensions for MiniLM-L12-v2)
    embedding = factory.LazyAttribute(
        lambda _: [0.0] * 384  # Zero vector for testing
    )
    embedding_model = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    embedded_at = factory.LazyFunction(lambda: datetime.now(timezone.utc))
    
    # Metadata
    metadata = factory.Dict({
        "section": factory.Iterator([
            "relatorio", "voto", "acordao", "ementa", "decisao"
        ]),
    })
    section_type = factory.Iterator([
        "relatorio", "voto", "acordao", "ementa", "decisao"
    ])
    
    # Timestamps
    created_at = factory.LazyFunction(lambda: datetime.now(timezone.utc))
    updated_at = factory.LazyFunction(lambda: datetime.now(timezone.utc))
    
    # Factory traits
    class Params:
        """Factory traits for creating chunks in specific states."""
        
        without_embedding = factory.Trait(
            embedding=None,
            embedded_at=None,
            embedding_model=None,
        )
        
        artigo_section = factory.Trait(
            section_type="artigo",
            metadata=factory.Dict({"section": "artigo", "numero": "1º"}),
        )


# =============================================================================
# Utility functions for complex test scenarios
# =============================================================================


async def create_document_with_chunks(
    session,
    chunk_count: int = 3,
    with_embeddings: bool = True,
    **document_kwargs
) -> tuple[Any, list[Any]]:
    """Create a document with associated chunks.
    
    This is a convenience function for creating a complete document
    with chunks in a single call.
    
    Args:
        session: The async SQLAlchemy session.
        chunk_count: Number of chunks to create.
        with_embeddings: Whether to include embeddings in chunks.
        **document_kwargs: Additional attributes for the document.
    
    Returns:
        Tuple of (document, chunks).
    """
    # Create source first if not provided
    if "source_id" not in document_kwargs:
        source = await SourceRegistryFactory.create_async(session=session)
        document_kwargs["source_id"] = source.id
    
    # Create document
    document = await DocumentFactory.create_async(
        session=session,
        with_chunks=True,
        **document_kwargs
    )
    
    # Create chunks
    chunks = []
    for i in range(chunk_count):
        chunk_kwargs = {
            "session": session,
            "document_id": document.document_id,
            "chunk_index": i,
        }
        if not with_embeddings:
            chunk_kwargs["without_embedding"] = True
        
        chunk = await DocumentChunkFactory.create_async(**chunk_kwargs)
        chunks.append(chunk)
    
    # Update document chunk count
    document.chunks_count = len(chunks)
    await session.flush()
    
    return document, chunks


async def create_source_with_documents(
    session,
    document_count: int = 5,
    **source_kwargs
) -> tuple[Any, list[Any]]:
    """Create a source with multiple documents.
    
    Args:
        session: The async SQLAlchemy session.
        document_count: Number of documents to create.
        **source_kwargs: Additional attributes for the source.
    
    Returns:
        Tuple of (source, documents).
    """
    source = await SourceRegistryFactory.create_async(
        session=session,
        **source_kwargs
    )
    
    documents = await DocumentFactory.create_batch_async(
        session=session,
        size=document_count,
        source_id=source.id,
    )
    
    # Update source statistics
    source.document_count = len(documents)
    await session.flush()
    
    return source, documents
