"""Factories para criação de objetos de teste.

Este módulo define factories usando factory_boy para criar
instâncias de modelos de forma consistente e reutilizável.

Factories:
    SourceRegistryFactory: Factory para SourceRegistry
    DocumentFactory: Factory para Document
    DocumentChunkFactory: Factory para DocumentChunk
"""

from __future__ import annotations

import hashlib
import random
import uuid
from datetime import datetime, timezone
from typing import Any

import factory
from factory import Faker
from factory.fuzzy import FuzzyChoice, FuzzyInteger, FuzzyText

from gabi.models.source import SourceRegistry
from gabi.models.document import Document
from gabi.models.chunk import DocumentChunk
from gabi.types import (
    SourceType,
    SourceStatus,
    DocumentStatus,
    SensitivityLevel,
    SectionType,
)


# =============================================================================
# Factory Base
# =============================================================================

class AsyncSQLModelFactory(factory.Factory):
    """Factory base para modelos SQLModel assíncronos.
    
    Esta factory base configura os defaults necessários
    para trabalhar com SQLModel de forma assíncrona.
    """
    
    class Meta:
        abstract = True
    
    @classmethod
    async def create_async(cls, session, **kwargs: Any) -> Any:
        """Cria instância de forma assíncrona.
        
        Args:
            session: Sessão do SQLAlchemy
            **kwargs: Atributos do modelo
            
        Returns:
            Instância do modelo criada
        """
        instance = cls.build(**kwargs)
        session.add(instance)
        await session.flush()
        await session.refresh(instance)
        return instance
    
    @classmethod
    async def create_batch_async(
        cls, session, size: int, **kwargs: Any
    ) -> list[Any]:
        """Cria múltiplas instâncias de forma assíncrona.
        
        Args:
            session: Sessão do SQLAlchemy
            size: Quantidade de instâncias
            **kwargs: Atributos do modelo
            
        Returns:
            Lista de instâncias criadas
        """
        instances = []
        for _ in range(size):
            instance = await cls.create_async(session, **kwargs)
            instances.append(instance)
        return instances


# =============================================================================
# SourceRegistry Factory
# =============================================================================

class SourceRegistryFactory(AsyncSQLModelFactory):
    """Factory para criar instâncias de SourceRegistry.
    
    Exemplos:
        >>> # Criar fonte básica
        >>> source = SourceRegistryFactory.build()
        
        >>> # Criar fonte do tipo API
        >>> api_source = SourceRegistryFactory.build(type=SourceType.API)
        
        >>> # Criar fonte com erro
        >>> error_source = SourceRegistryFactory.build(
        ...     status=SourceStatus.ERROR,
        ...     consecutive_errors=5
        ... )
    """
    
    class Meta:
        model = SourceRegistry
        exclude = ("_faker",)
    
    # Identificação
    id = factory.Sequence(lambda n: f"test_source_{n}")
    name = factory.LazyAttribute(lambda obj: f"Fonte de Teste {obj.id}")
    description = Faker("sentence", nb_words=10)
    
    # Tipo e Status
    type = FuzzyChoice([
        SourceType.API,
        SourceType.WEB,
        SourceType.FILE,
        SourceType.CRAWLER,
    ])
    status = SourceStatus.ACTIVE
    
    # Configuração
    config_hash = factory.LazyFunction(
        lambda: hashlib.sha256(b"test_config").hexdigest()[:16]
    )
    config_json = factory.LazyAttribute(lambda _: {
        "metadata": {
            "domain": "juridico",
            "jurisdiction": "BR",
            "authority": "TCU",
            "document_type": "acordao",
        },
        "discovery": {"mode": "static_url", "url": "https://example.com/data.csv"},
        "fetch": {"protocol": "https", "method": "GET"},
        "parse": {"input_format": "csv"},
    })
    
    # Estatísticas
    document_count = FuzzyInteger(0, 10000)
    total_documents_ingested = factory.LazyAttribute(
        lambda obj: obj.document_count + FuzzyInteger(0, 1000).fuzz()
    )
    last_document_at = factory.LazyFunction(
        lambda: datetime.now(timezone.utc)
    )
    
    # Execução
    last_sync_at = factory.LazyFunction(
        lambda: datetime.now(timezone.utc)
    )
    last_success_at = factory.LazyFunction(
        lambda: datetime.now(timezone.utc)
    )
    next_scheduled_sync = factory.LazyFunction(
        lambda: datetime.now(timezone.utc)
    )
    
    # Error Tracking
    consecutive_errors = 0
    last_error_message = None
    last_error_at = None
    
    # Governança
    owner_email = Faker("email")
    sensitivity = SensitivityLevel.INTERNAL
    retention_days = 2555  # ~7 anos
    
    # Timestamps
    created_at = factory.LazyFunction(lambda: datetime.now(timezone.utc))
    updated_at = factory.LazyFunction(lambda: datetime.now(timezone.utc))
    deleted_at = None
    
    # Traits para estados específicos
    class Params:
        """Parâmetros para customização da factory."""
        
        active = factory.Trait(
            status=SourceStatus.ACTIVE,
            consecutive_errors=0,
        )
        
        paused = factory.Trait(
            status=SourceStatus.PAUSED,
        )
        
        error = factory.Trait(
            status=SourceStatus.ERROR,
            consecutive_errors=5,
            last_error_message="Erro de conexão com a fonte",
            last_error_at=factory.LazyFunction(
                lambda: datetime.now(timezone.utc)
            ),
        )
        
        disabled = factory.Trait(
            status=SourceStatus.DISABLED,
        )
        
        deleted = factory.Trait(
            deleted_at=factory.LazyFunction(
                lambda: datetime.now(timezone.utc)
            ),
        )
        
        tcu_acordaos = factory.Trait(
            id="tcu_acordaos",
            name="Acórdãos TCU",
            type=SourceType.API,
            description="Acórdãos do Tribunal de Contas da União",
        )
        
        high_volume = factory.Trait(
            document_count=FuzzyInteger(50000, 500000),
            total_documents_ingested=FuzzyInteger(100000, 1000000),
        )


# =============================================================================
# Document Factory
# =============================================================================

class DocumentFactory(factory.Factory):
    """Factory para criar instâncias de Document.
    
    Exemplos:
        >>> # Criar documento básico
        >>> doc = DocumentFactory.build()
        
        >>> # Criar documento deletado
        >>> deleted_doc = DocumentFactory.build(
        ...     is_deleted=True,
        ...     status=DocumentStatus.DELETED
        ... )
        
        >>> # Criar documento com metadados
        >>> doc_with_meta = DocumentFactory.build(
        ...     metadata={"year": 2024, "relator": "Ministro Teste"}
        ... )
    """
    
    class Meta:
        model = Document
        exclude = ("_faker",)
    
    # Identificadores
    id = factory.LazyFunction(lambda: str(uuid.uuid4()))
    document_id = factory.Sequence(lambda n: f"TCU-ACORDAO-{n:05d}-2024")
    source_id = "test_source_1"
    
    # Conteúdo
    fingerprint = factory.LazyFunction(
        lambda: hashlib.sha256(
            f"content_{uuid.uuid4()}".encode()
        ).hexdigest()
    )
    fingerprint_algorithm = "sha256"
    title = Faker("sentence", nb_words=6)
    content_preview = Faker("paragraph", nb_sentences=3)
    content_hash = factory.LazyFunction(
        lambda: hashlib.sha256(b"full content").hexdigest()
    )
    content_size_bytes = FuzzyInteger(1000, 1000000)
    
    # Metadados
    metadata = factory.LazyAttribute(lambda _: {
        "year": random.randint(1992, 2024),
        "number": str(random.randint(1, 9999)),
        "relator": Faker("name").generate(),
        "colegiado": FuzzyChoice([
            "Plenário",
            "Primeira Câmara",
            "Segunda Câmara",
        ]).fuzz(),
        "assunto": Faker("word").generate(),
        "situacao": "Aprovado",
    })
    url = factory.LazyAttribute(
        lambda obj: f"https://pesquisa.apps.tcu.gov.br/#/documento/acordao/{obj.document_id}"
    )
    content_type = "text/html"
    language = "pt-BR"
    
    # Status
    status = DocumentStatus.ACTIVE
    version = 1
    
    # Soft Delete
    is_deleted = False
    deleted_at = None
    deleted_reason = None
    deleted_by = None
    
    # Timestamps
    ingested_at = factory.LazyFunction(lambda: datetime.now(timezone.utc))
    updated_at = factory.LazyFunction(lambda: datetime.now(timezone.utc))
    reindexed_at = None
    
    # Elasticsearch Sync
    es_indexed = False
    es_indexed_at = None
    chunks_count = 0
    
    # Relacionamentos (lazy)
    source = None
    chunks = []
    
    # Traits
    class Params:
        """Parâmetros para customização da factory."""
        
        active = factory.Trait(
            status=DocumentStatus.ACTIVE,
            is_deleted=False,
        )
        
        updated = factory.Trait(
            status=DocumentStatus.UPDATED,
            version=FuzzyInteger(2, 10),
        )
        
        deleted = factory.Trait(
            status=DocumentStatus.DELETED,
            is_deleted=True,
            deleted_at=factory.LazyFunction(
                lambda: datetime.now(timezone.utc)
            ),
            deleted_reason="Removido por solicitação",
            deleted_by="admin@tcu.gov.br",
        )
        
        error = factory.Trait(
            status=DocumentStatus.ERROR,
        )
        
        indexed = factory.Trait(
            es_indexed=True,
            es_indexed_at=factory.LazyFunction(
                lambda: datetime.now(timezone.utc)
            ),
        )
        
        needs_reindex = factory.Trait(
            es_indexed=True,
            es_indexed_at=factory.LazyFunction(
                lambda: datetime(2024, 1, 1, tzinfo=timezone.utc)
            ),
            updated_at=factory.LazyFunction(
                lambda: datetime.now(timezone.utc)
            ),
        )
        
        with_chunks = factory.Trait(
            chunks_count=FuzzyInteger(1, 20),
        )
        
        large_document = factory.Trait(
            content_size_bytes=FuzzyInteger(1000000, 10000000),
            chunks_count=FuzzyInteger(50, 200),
        )


# =============================================================================
# DocumentChunk Factory
# =============================================================================

class DocumentChunkFactory(factory.Factory):
    """Factory para criar instâncias de DocumentChunk.
    
    Exemplos:
        >>> # Criar chunk básico
        >>> chunk = DocumentChunkFactory.build()
        
        >>> # Criar chunk com embedding
        >>> chunk_with_emb = DocumentChunkFactory.build(
        ...     embedding=[0.1] * 384,
        ...     embedding_model="sentence-transformers/all-MiniLM-L6-v2"
        ... )
        
        >>> # Criar chunk de ementa
        >>> ementa_chunk = DocumentChunkFactory.build(
        ...     section_type=SectionType.EMENTA
        ... )
    """
    
    class Meta:
        model = DocumentChunk
        exclude = ("_faker",)
    
    # Identificadores
    id = factory.LazyFunction(lambda: uuid.uuid4())
    document_id = factory.Sequence(lambda n: f"TCU-ACORDAO-{n:05d}-2024")
    chunk_index = factory.Sequence(lambda n: n)
    
    # Conteúdo
    chunk_text = Faker("paragraph", nb_sentences=5)
    token_count = FuzzyInteger(50, 512)
    char_count = factory.LazyAttribute(lambda obj: len(obj.chunk_text))
    
    # Embedding (384 dimensões - ADR-001)
    embedding = None
    embedding_model = None
    embedded_at = None
    
    # Metadados
    metadata = factory.LazyAttribute(lambda _: {
        "position": "start",
        "page": random.randint(1, 100),
    })
    section_type = FuzzyChoice([
        SectionType.EMENTA,
        SectionType.ACORDAO,
        SectionType.VOTO,
        SectionType.RELATORIO,
        SectionType.FUNDAMENTACAO,
        SectionType.DISPOSITIVO,
        SectionType.GENERAL,
    ])
    
    # Timestamps
    created_at = factory.LazyFunction(lambda: datetime.now(timezone.utc))
    updated_at = factory.LazyFunction(lambda: datetime.now(timezone.utc))
    
    # Relacionamentos
    document = None
    
    # Traits
    class Params:
        """Parâmetros para customização da factory."""
        
        with_embedding = factory.Trait(
            embedding=factory.LazyFunction(
                lambda: [random.uniform(-1, 1) for _ in range(384)]
            ),
            embedding_model="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
            embedded_at=factory.LazyFunction(
                lambda: datetime.now(timezone.utc)
            ),
        )
        
        ementa = factory.Trait(
            section_type=SectionType.EMENTA,
            chunk_text=Faker("paragraph", nb_sentences=2),
            token_count=FuzzyInteger(20, 100),
        )
        
        voto = factory.Trait(
            section_type=SectionType.VOTO,
            chunk_text=Faker("paragraph", nb_sentences=10),
            token_count=FuzzyInteger(200, 512),
        )
        
        relatorio = factory.Trait(
            section_type=SectionType.RELATORIO,
            chunk_text=Faker("paragraph", nb_sentences=8),
            token_count=FuzzyInteger(150, 400),
        )
        
        acordao = factory.Trait(
            section_type=SectionType.ACORDAO,
            chunk_text=Faker("paragraph", nb_sentences=5),
            token_count=FuzzyInteger(100, 300),
        )


# =============================================================================
# Funções de Utilidade
# =============================================================================

def generate_fingerprint(content: str) -> str:
    """Gera fingerprint SHA-256 para conteúdo.
    
    Args:
        content: Conteúdo para gerar o fingerprint
        
    Returns:
        str: Hash SHA-256 em hexadecimal
    """
    return hashlib.sha256(content.encode()).hexdigest()


def generate_embedding_vector(dimensions: int = 384) -> list[float]:
    """Gera vetor de embedding aleatório normalizado.
    
    Args:
        dimensions: Dimensões do vetor (padrão: 384)
        
    Returns:
        list[float]: Vetor normalizado
    """
    vector = [random.uniform(-1, 1) for _ in range(dimensions)]
    magnitude = sum(x**2 for x in vector) ** 0.5
    return [x / magnitude for x in vector]


def create_document_with_chunks(
    document_factory: DocumentFactory,
    chunk_factory: DocumentChunkFactory,
    num_chunks: int = 5,
    with_embeddings: bool = False,
) -> tuple[Document, list[DocumentChunk]]:
    """Cria um documento com chunks associados.
    
    Args:
        document_factory: Factory de documentos
        chunk_factory: Factory de chunks
        num_chunks: Número de chunks a criar
        with_embeddings: Se deve incluir embeddings nos chunks
        
    Returns:
        tuple: (Documento, Lista de chunks)
    """
    doc = document_factory.build(chunks_count=num_chunks)
    
    chunks = []
    for i in range(num_chunks):
        chunk_kwargs = {
            "document_id": doc.document_id,
            "chunk_index": i,
        }
        if with_embeddings:
            chunk_kwargs["embedding"] = generate_embedding_vector()
            chunk_kwargs["embedding_model"] = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
            chunk_kwargs["embedded_at"] = datetime.now(timezone.utc)
        
        chunk = chunk_factory.build(**chunk_kwargs)
        chunks.append(chunk)
    
    return doc, chunks


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    "AsyncSQLModelFactory",
    "SourceRegistryFactory",
    "DocumentFactory",
    "DocumentChunkFactory",
    "generate_fingerprint",
    "generate_embedding_vector",
    "create_document_with_chunks",
]
