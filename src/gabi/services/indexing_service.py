"""Serviço de indexação de alto nível para GABI.

Coordena o pipeline completo: chunking → embedding → indexação atômica.
Integra com DLQ para falhas e suporta processamento em batch.

Baseado em GABI_SPECS_FINAL_v1.md Seção 3.2
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Coroutine, Dict, List, Optional, Protocol, TypeVar, Union
from uuid import UUID

from gabi.models.document import Document
from gabi.models.dlq import DLQMessage, DLQStatus
from gabi.models.source import SourceRegistry
from gabi.pipeline.chunker import Chunk, Chunker
from gabi.pipeline.indexer import (
    ChunkData,
    Indexer,
    IndexingDLQHandler,
    IndexingResult,
    IndexingStatus,
)

logger = logging.getLogger(__name__)

T = TypeVar("T")


# =============================================================================
# Protocols e Tipos
# =============================================================================

class EmbedderClient(Protocol):
    """Protocol para cliente de embeddings."""
    
    async def embed(
        self,
        texts: List[str],
        batch_size: int = 32,
    ) -> List[List[float]]:
        """Gera embeddings para uma lista de textos."""
        ...


class ProgressCallback(Protocol):
    """Protocol para callback de progresso."""
    
    async def __call__(
        self,
        current: int,
        total: int,
        stage: str,
        document_id: Optional[str] = None,
    ) -> None:
        """Reporta progresso do processamento."""
        ...


# =============================================================================
# Enums
# =============================================================================

class ProcessingStage(str, Enum):
    """Estágios do processamento de indexação."""
    
    CHUNKING = "chunking"
    EMBEDDING = "embedding"
    INDEXING = "indexing"
    COMPLETED = "completed"
    FAILED = "failed"


class ProcessingMode(str, Enum):
    """Modos de processamento."""
    
    SYNC = "sync"      # Síncrono, espera resultado
    ASYNC = "async"    # Async via Celery (não implementado aqui)


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class DocumentContent:
    """Conteúdo de um documento para processamento.
    
    Attributes:
        document_id: ID único do documento
        source_id: ID da fonte de origem
        title: Título do documento
        content: Conteúdo textual completo
        url: URL de origem (opcional)
        metadata: Metadados adicionais
        content_type: Tipo de conteúdo (MIME)
        language: Idioma (ISO 639-1)
    """
    
    document_id: str
    source_id: str
    title: str
    content: str
    url: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    content_type: str = "text/plain"
    language: str = "pt-BR"


@dataclass
class ProcessingResult:
    """Resultado completo do processamento de um documento.
    
    Attributes:
        document_id: ID do documento
        success: Se processamento foi bem-sucedido
        stage: Último estágio executado
        chunks_count: Quantidade de chunks gerados
        indexing_result: Resultado da indexação
        duration_ms: Duração total em ms
        errors: Lista de erros
        dlq_message_id: ID da mensagem DLQ (se falhou)
    """
    
    document_id: str
    success: bool
    stage: ProcessingStage
    chunks_count: int = 0
    indexing_result: Optional[IndexingResult] = None
    duration_ms: Optional[float] = None
    errors: List[str] = field(default_factory=list)
    dlq_message_id: Optional[UUID] = None


@dataclass
class BatchProcessingResult:
    """Resultado do processamento em batch.
    
    Attributes:
        total: Total de documentos
        successful: Quantidade de sucessos
        failed: Quantidade de falhas
        results: Lista de resultados individuais
    """
    
    total: int
    successful: int
    failed: int
    results: List[ProcessingResult] = field(default_factory=list)
    
    @property
    def success_rate(self) -> float:
        """Taxa de sucesso (0.0 - 1.0)."""
        if self.total == 0:
            return 0.0
        return self.successful / self.total


@dataclass
class IndexingServiceConfig:
    """Configuração do serviço de indexação.
    
    Attributes:
        chunk_size: Tamanho dos chunks em tokens
        chunk_overlap: Sobreposição entre chunks
        embedding_batch_size: Tamanho do batch para embeddings
        indexing_batch_size: Tamanho do batch para indexação
        enable_dlq: Habilita DLQ para falhas
        max_retries: Máximo de retries para embedder
        retry_delay_seconds: Delay entre retries
        progress_callback: Callback opcional de progresso
    """
    
    chunk_size: int = 512
    chunk_overlap: int = 50
    embedding_batch_size: int = 32
    indexing_batch_size: int = 100
    enable_dlq: bool = True
    max_retries: int = 3
    retry_delay_seconds: float = 1.0
    progress_callback: Optional[ProgressCallback] = None


# =============================================================================
# Indexing Service
# =============================================================================

class IndexingService:
    """Serviço de alto nível para indexação de documentos.
    
    Responsabilidades:
    1. Coordena chunking → embedding → indexação
    2. Gerencia batches para performance
    3. Integra com DLQ para falhas
    4. Fornece métricas e observabilidade
    
    Exemplo:
        >>> service = IndexingService(indexer, embedder)
        >>> result = await service.process_document(content)
        >>> batch_result = await service.process_batch(contents)
    """
    
    def __init__(
        self,
        indexer: Indexer,
        embedder: EmbedderClient,
        config: Optional[IndexingServiceConfig] = None,
        dlq_handler: Optional[IndexingDLQHandler] = None,
    ):
        """Inicializa o serviço.
        
        Args:
            indexer: Instância do Indexer atômico
            embedder: Cliente para geração de embeddings
            config: Configuração opcional
            dlq_handler: Handler DLQ opcional
        """
        self.indexer = indexer
        self.embedder = embedder
        self.config = config or IndexingServiceConfig()
        self.dlq_handler = dlq_handler or IndexingDLQHandler()
        
        # Inicializa chunker com config
        self.chunker = Chunker(
            max_tokens=self.config.chunk_size,
            overlap_tokens=self.config.chunk_overlap,
        )
        
    # ========================================================================
    # API Pública - Processamento Individual
    # ========================================================================
    
    async def process_document(
        self,
        content: DocumentContent,
        run_id: Optional[UUID] = None,
    ) -> ProcessingResult:
        """Processa um único documento completo.
        
        Pipeline: chunking → embedding → indexação atômica
        
        Args:
            content: Conteúdo do documento
            run_id: ID da execução atual
            
        Returns:
            ProcessingResult com resultado completo
        """
        start_time = datetime.now()
        result = ProcessingResult(
            document_id=content.document_id,
            success=False,
            stage=ProcessingStage.CHUNKING,
        )
        
        try:
            # =================================================================
            # ETAPA 1: Chunking
            # =================================================================
            await self._report_progress(1, 3, ProcessingStage.CHUNKING, content.document_id)
            
            chunks = await self._execute_chunking(content)
            result.chunks_count = len(chunks)
            
            if not chunks:
                result.success = True
                result.stage = ProcessingStage.COMPLETED
                logger.warning(f"Documento {content.document_id} sem conteúdo para indexar")
                return result
            
            # =================================================================
            # ETAPA 2: Embedding
            # =================================================================
            result.stage = ProcessingStage.EMBEDDING
            await self._report_progress(2, 3, ProcessingStage.EMBEDDING, content.document_id)
            
            chunk_data_list = await self._execute_embedding(chunks)
            
            # =================================================================
            # ETAPA 3: Indexação Atômica
            # =================================================================
            result.stage = ProcessingStage.INDEXING
            await self._report_progress(3, 3, ProcessingStage.INDEXING, content.document_id)
            
            # Cria/Atualiza documento
            document = await self._create_or_update_document(content, chunks)
            
            # Indexação atômica (PG + ES)
            indexing_result = await self.indexer.index_document(
                document=document,
                chunks=chunk_data_list,
                source_id=content.source_id,
                run_id=run_id,
            )
            
            result.indexing_result = indexing_result
            
            # Verifica resultado
            if indexing_result.status == IndexingStatus.SUCCESS:
                result.success = True
                result.stage = ProcessingStage.COMPLETED
            elif indexing_result.status == IndexingStatus.ROLLED_BACK:
                # Saga executou rollback - trata como falha
                result.success = False
                result.stage = ProcessingStage.FAILED
                result.errors.extend(indexing_result.errors)
                
                # Adiciona à DLQ
                if self.config.enable_dlq:
                    dlq_msg = await self._enqueue_to_dlq(
                        content, indexing_result.errors, run_id
                    )
                    result.dlq_message_id = dlq_msg.id
                    
            else:  # PARTIAL ou FAILED
                result.success = False
                result.stage = ProcessingStage.FAILED
                result.errors.extend(indexing_result.errors)
                
                # Adiciona à DLQ
                if self.config.enable_dlq:
                    dlq_msg = await self._enqueue_to_dlq(
                        content, indexing_result.errors, run_id
                    )
                    result.dlq_message_id = dlq_msg.id
            
        except Exception as e:
            logger.exception(f"Erro no processamento de {content.document_id}: {e}")
            result.success = False
            result.stage = ProcessingStage.FAILED
            result.errors.append(str(e))
            
            # Adiciona à DLQ
            if self.config.enable_dlq:
                try:
                    dlq_msg = await self._enqueue_to_dlq(content, [str(e)], run_id)
                    result.dlq_message_id = dlq_msg.id
                except Exception as dlq_error:
                    logger.error(f"Falha ao adicionar à DLQ: {dlq_error}")
        
        finally:
            duration = (datetime.now() - start_time).total_seconds() * 1000
            result.duration_ms = round(duration, 2)
        
        return result
    
    async def process_batch(
        self,
        contents: List[DocumentContent],
        run_id: Optional[UUID] = None,
    ) -> BatchProcessingResult:
        """Processa múltiplos documentos em batch.
        
        Args:
            contents: Lista de conteúdos para processar
            run_id: ID da execução atual
            
        Returns:
            BatchProcessingResult com resultados agregados
        """
        total = len(contents)
        results: List[ProcessingResult] = []
        successful = 0
        failed = 0
        
        logger.info(f"Iniciando batch de {total} documentos")
        
        for idx, content in enumerate(contents):
            logger.debug(f"Processando {idx + 1}/{total}: {content.document_id}")
            
            result = await self.process_document(content, run_id)
            results.append(result)
            
            if result.success:
                successful += 1
            else:
                failed += 1
        
        batch_result = BatchProcessingResult(
            total=total,
            successful=successful,
            failed=failed,
            results=results,
        )
        
        logger.info(
            f"Batch concluído: {successful}/{total} sucesso "
            f"({batch_result.success_rate:.1%})"
        )
        
        return batch_result
    
    # ========================================================================
    # API Pública - Reprocessamento
    # ========================================================================
    
    async def reprocess_from_dlq(
        self,
        dlq_message_id: UUID,
    ) -> ProcessingResult:
        """Reprocessa um documento a partir de uma mensagem DLQ.
        
        Args:
            dlq_message_id: ID da mensagem na DLQ
            
        Returns:
            ProcessingResult do reprocessamento
        """
        from gabi.db import get_session_no_commit
        from sqlalchemy import select
        
        async with get_session_no_commit() as session:
            stmt = select(DLQMessage).where(DLQMessage.id == dlq_message_id)
            result = await session.execute(stmt)
            dlq_msg = result.scalar_one_or_none()
            
            if not dlq_msg:
                raise ValueError(f"Mensagem DLQ {dlq_message_id} não encontrada")
            
            # Extrai dados do payload
            payload = dlq_msg.payload
            content = DocumentContent(
                document_id=dlq_msg.document_id or payload.get("document_id", ""),
                source_id=dlq_msg.source_id,
                title=payload.get("title", ""),
                content=payload.get("content", ""),
                url=payload.get("url"),
                metadata=payload.get("metadata", {}),
            )
            
            # Reprocessa
            processing_result = await self.process_document(
                content,
                run_id=dlq_msg.run_id,
            )
            
            # Atualiza DLQ
            if processing_result.success:
                dlq_msg.resolve(
                    resolved_by="indexing_service",
                    notes="Reprocessamento automático bem-sucedido",
                )
            else:
                dlq_msg.mark_retry_attempt()
            
            await session.commit()
            
        return processing_result
    
    async def retry_failed_documents(
        self,
        source_id: Optional[str] = None,
        limit: int = 100,
    ) -> BatchProcessingResult:
        """Retenta documentos falhos pendentes na DLQ.
        
        Args:
            source_id: Filtrar por fonte específica
            limit: Limite de documentos a processar
            
        Returns:
            BatchProcessingResult do reprocessamento
        """
        from gabi.db import get_session_no_commit
        from sqlalchemy import select, and_
        from datetime import datetime
        
        async with get_session_no_commit() as session:
            # Busca mensagens pendentes
            conditions = [
                DLQMessage.status.in_([DLQStatus.PENDING, DLQStatus.RETRYING]),
                DLQMessage.next_retry_at <= datetime.now(),
            ]
            if source_id:
                conditions.append(DLQMessage.source_id == source_id)
            
            stmt = (
                select(DLQMessage)
                .where(and_(*conditions))
                .order_by(DLQMessage.next_retry_at)
                .limit(limit)
            )
            result = await session.execute(stmt)
            messages = result.scalars().all()
        
        if not messages:
            return BatchProcessingResult(total=0, successful=0, failed=0)
        
        # Reprocessa cada um
        results: List[ProcessingResult] = []
        for msg in messages:
            try:
                result = await self.reprocess_from_dlq(msg.id)
                results.append(result)
            except Exception as e:
                logger.error(f"Falha ao reprocessar {msg.id}: {e}")
                results.append(ProcessingResult(
                    document_id=msg.document_id or "unknown",
                    success=False,
                    stage=ProcessingStage.FAILED,
                    errors=[str(e)],
                ))
        
        successful = sum(1 for r in results if r.success)
        return BatchProcessingResult(
            total=len(results),
            successful=successful,
            failed=len(results) - successful,
            results=results,
        )
    
    # ========================================================================
    # Métodos Internos
    # ========================================================================
    
    async def _execute_chunking(
        self,
        content: DocumentContent,
    ) -> List[Chunk]:
        """Executa chunking do documento."""
        result = self.chunker.chunk(
            document_text=content.content,
            metadata={
                "document_id": content.document_id,
                "source_id": content.source_id,
                "title": content.title,
            },
            document_id=content.document_id,
        )
        return result.chunks
    
    async def _execute_embedding(
        self,
        chunks: List[Chunk],
    ) -> List[ChunkData]:
        """Gera embeddings para os chunks."""
        texts = [chunk.text for chunk in chunks]
        
        # Embeddings em batch
        embeddings = await self.embedder.embed(
            texts=texts,
            batch_size=self.config.embedding_batch_size,
        )
        
        # Cria ChunkData
        chunk_data_list: List[ChunkData] = []
        for idx, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
            chunk_data = ChunkData(
                chunk_index=chunk.index,
                text=chunk.text,
                token_count=chunk.token_count,
                char_count=len(chunk.text),
                embedding=embedding,
                metadata=chunk.metadata,
                section_type=chunk.section_type,
            )
            chunk_data_list.append(chunk_data)
        
        return chunk_data_list
    
    async def _create_or_update_document(
        self,
        content: DocumentContent,
        chunks: List[Chunk],
    ) -> Document:
        """Cria ou atualiza o documento no banco."""
        from gabi.db import get_session_no_commit
        from sqlalchemy import select
        
        # Gera fingerprint
        fingerprint = hashlib.sha256(content.content.encode()).hexdigest()
        
        async with get_session_no_commit() as session:
            # Verifica se existe
            stmt = select(Document).where(
                Document.document_id == content.document_id
            )
            result = await session.execute(stmt)
            existing = result.scalar_one_or_none()
            
            if existing:
                # Atualiza
                existing.title = content.title
                existing.content_preview = content.content[:1000]
                existing.content_hash = fingerprint
                existing.content_size_bytes = len(content.content.encode())
                existing.doc_metadata = content.metadata
                existing.url = content.url
                existing.content_type = content.content_type
                existing.language = content.language
                existing.updated_at = datetime.now()
                existing.version += 1
                existing.es_indexed = False
                await session.commit()
                return existing
            else:
                # Cria novo
                document = Document(
                    document_id=content.document_id,
                    source_id=content.source_id,
                    fingerprint=fingerprint,
                    fingerprint_algorithm="sha256",
                    title=content.title,
                    content_preview=content.content[:1000],
                    content_hash=fingerprint,
                    content_size_bytes=len(content.content.encode()),
                    doc_metadata=content.metadata,
                    url=content.url,
                    content_type=content.content_type,
                    language=content.language,
                    status="active",
                    version=1,
                    is_deleted=False,
                    es_indexed=False,
                    chunks_count=len(chunks),
                )
                return document
    
    async def _enqueue_to_dlq(
        self,
        content: DocumentContent,
        errors: List[str],
        run_id: Optional[UUID],
    ) -> DLQMessage:
        """Adiciona falha à DLQ."""
        error = Exception("; ".join(errors))
        
        return await self.dlq_handler.enqueue_failure(
            document_id=content.document_id,
            source_id=content.source_id,
            error=error,
            run_id=run_id,
            payload={
                "document_id": content.document_id,
                "title": content.title,
                "content": content.content,
                "url": content.url,
                "metadata": content.metadata,
                "stage": "indexing",
                "errors": errors,
            },
        )
    
    async def _report_progress(
        self,
        current: int,
        total: int,
        stage: ProcessingStage,
        document_id: Optional[str] = None,
    ) -> None:
        """Reporta progresso via callback."""
        if self.config.progress_callback:
            try:
                await self.config.progress_callback(
                    current, total, stage.value, document_id
                )
            except Exception as e:
                logger.warning(f"Erro no progress callback: {e}")


# =============================================================================
# Factory
# =============================================================================

async def create_indexing_service(
    es_url: str = "http://localhost:9200",
    embedding_service_url: str = "http://localhost:8080",
    config: Optional[IndexingServiceConfig] = None,
) -> IndexingService:
    """Factory para criar IndexingService completo.
    
    Args:
        es_url: URL do Elasticsearch
        embedding_service_url: URL do serviço de embeddings (TEI)
        config: Configuração opcional
        
    Returns:
        IndexingService configurado
    """
    from gabi.pipeline.indexer import create_indexer
    
    # Cria indexer
    indexer = await create_indexer(es_url=es_url)
    
    # Cria embedder (simplificado - na prática usaria TEI client)
    class SimpleEmbedder:
        async def embed(self, texts: List[str], batch_size: int = 32) -> List[List[float]]:
            # Mock - na prática chama TEI
            return [[0.0] * 384 for _ in texts]
    
    embedder = SimpleEmbedder()
    dlq_handler = IndexingDLQHandler()
    
    return IndexingService(
        indexer=indexer,
        embedder=embedder,
        config=config,
        dlq_handler=dlq_handler,
    )


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    # Enums
    "ProcessingStage",
    "ProcessingMode",
    # Data classes
    "DocumentContent",
    "ProcessingResult",
    "BatchProcessingResult",
    "IndexingServiceConfig",
    # Protocols
    "EmbedderClient",
    "ProgressCallback",
    # Serviço
    "IndexingService",
    # Factory
    "create_indexing_service",
]
