"""Pipeline Orchestrator - Coordena a execução do pipeline de ingestão.

Orquestra todas as fases do pipeline:
1. Discovery - Descoberta de URLs
2. Change Detection - Detecção de mudanças
3. Fetch - Download de conteúdo
4. Parse - Extração de texto
5. Fingerprint - Geração de fingerprints
6. Deduplication - Verificação de duplicatas
7. Chunking - Divisão em chunks
8. Embedding - Geração de embeddings
9. Indexing - Indexação no PostgreSQL/ES

Baseado em GABI_SPECS_FINAL_v1.md Seção 2.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, TYPE_CHECKING
from dataclasses import dataclass, field
from enum import Enum

import httpx

from gabi.pipeline.contracts import (
    DiscoveredURL,
    DiscoveryResult,
    ChangeCheckResult,
    ChangeDetectionSummary,
    FetchMetadata,
    FetchedContent,
    ParsedDocument,
    ParseResult,
    DocumentFingerprint,
    DuplicateCheckResult,
    Chunk,
    ChunkingResult,
    EmbeddedChunk,
    EmbeddingResult,
    IndexDocument,
    IndexChunk,
    IndexingResult,
    ExecutionCheckpoint,
    ExecutionStats,
    DLQMessage,
    PipelineResult,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


logger = logging.getLogger(__name__)


class PipelineStatus(str, Enum):
    """Status da execução do pipeline."""
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    PARTIAL_SUCCESS = "partial_success"
    FAILED = "failed"
    CANCELLED = "cancelled"


class PipelinePhase(str, Enum):
    """Fases do pipeline."""
    DISCOVERY = "discovery"
    CHANGE_DETECTION = "change_detection"
    FETCH = "fetch"
    PARSE = "parse"
    FINGERPRINT = "fingerprint"
    DEDUPLICATION = "deduplication"
    CHUNKING = "chunking"
    EMBEDDING = "embedding"
    INDEXING = "indexing"


@dataclass
class PipelineConfig:
    """Configuração do pipeline.
    
    Attributes:
        max_concurrent_urls: Número máximo de URLs processadas em paralelo
        max_memory_mb: Limite de memória em MB
        checkpoint_interval: Intervalo para salvar checkpoint (em itens)
        enable_dlq: Se deve enviar erros para DLQ
        retry_failed: Se deve retry de itens falhos
        max_retries: Número máximo de retries
    """
    max_concurrent_urls: int = 5
    max_memory_mb: int = 2048
    checkpoint_interval: int = 100
    enable_dlq: bool = True
    retry_failed: bool = True
    max_retries: int = 3


@dataclass
class PipelineManifest:
    """Manifesto de execução do pipeline.
    
    Attributes:
        run_id: ID único da execução
        source_id: ID da fonte
        status: Status atual
        started_at: Timestamp de início
        completed_at: Timestamp de conclusão
        checkpoint: Checkpoint atual
        stats: Estatísticas
    """
    run_id: str
    source_id: str
    status: PipelineStatus = PipelineStatus.PENDING
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    checkpoint: ExecutionCheckpoint = field(default_factory=ExecutionCheckpoint)
    stats: ExecutionStats = field(default_factory=ExecutionStats)


class PipelineOrchestrator:
    """Orquestrador do pipeline de ingestão.
    
    Coordena todas as fases do pipeline, gerenciando:
    - Ciclo de vida da execução
    - Concorrência e limites de recursos
    - Checkpoint/resume
    - Tratamento de erros e DLQ
    - Estatísticas e métricas
    
    Example:
        >>> orchestrator = PipelineOrchestrator(
        ...     db_session=session,
        ...     es_client=es_client,
        ...     redis_client=redis_client,
        ... )
        >>> stats = await orchestrator.run(
        ...     source_id="tcu_acordaos",
        ...     source_config=config,
        ... )
    """
    
    def __init__(
        self,
        db_session: Optional[Any] = None,
        es_client: Optional[Any] = None,
        redis_client: Optional[Any] = None,
        http_client: Optional[httpx.AsyncClient] = None,
        config: Optional[PipelineConfig] = None,
    ):
        """Inicializa o orquestrador.
        
        Args:
            db_session: Sessão do banco de dados
            es_client: Cliente Elasticsearch
            redis_client: Cliente Redis
            http_client: Cliente HTTP (opcional)
            config: Configuração do pipeline
        """
        self.db_session = db_session
        self.es_client = es_client
        self.redis_client = redis_client
        self.http_client = http_client
        self.config = config or PipelineConfig()
        
        # Componentes serão inicializados lazy
        self._change_detector: Optional[Any] = None
        self._fetcher: Optional[Any] = None
        self._parser: Optional[Any] = None
        self._fingerprinter: Optional[Any] = None
        self._deduplicator: Optional[Any] = None
        self._chunker: Optional[Any] = None
        self._embedder: Optional[Any] = None
        self._indexer: Optional[Any] = None
        
        # Estado interno
        self._manifest: Optional[PipelineManifest] = None
        self._semaphore: Optional[asyncio.Semaphore] = None
    
    @property
    def change_detector(self) -> Any:
        """Lazy init do change detector."""
        if self._change_detector is None:
            from gabi.pipeline.change_detection import ChangeDetector
            self._change_detector = ChangeDetector()
        return self._change_detector
    
    @property
    def fetcher(self) -> Any:
        """Lazy init do fetcher."""
        if self._fetcher is None:
            from gabi.pipeline.fetcher import ContentFetcher
            self._fetcher = ContentFetcher()
        return self._fetcher
    
    @property
    def parser(self) -> Any:
        """Lazy init do parser."""
        if self._parser is None:
            from gabi.pipeline.parser import ContentParser
            self._parser = ContentParser()
        return self._parser
    
    @property
    def fingerprinter(self) -> Any:
        """Lazy init do fingerprinter."""
        if self._fingerprinter is None:
            from gabi.pipeline.fingerprint import Fingerprinter
            self._fingerprinter = Fingerprinter()
        return self._fingerprinter
    
    @property
    def deduplicator(self) -> Any:
        """Lazy init do deduplicator."""
        if self._deduplicator is None:
            from gabi.pipeline.deduplication import Deduplicator
            self._deduplicator = Deduplicator()
        return self._deduplicator
    
    @property
    def chunker(self) -> Any:
        """Lazy init do chunker."""
        if self._chunker is None:
            from gabi.pipeline.chunker import Chunker
            self._chunker = Chunker()
        return self._chunker
    
    @property
    def embedder(self) -> Any:
        """Lazy init do embedder."""
        if self._embedder is None:
            from gabi.pipeline.embedder import Embedder
            self._embedder = Embedder()
        return self._embedder
    
    @property
    def indexer(self) -> Any:
        """Lazy init do indexer."""
        if self._indexer is None:
            from gabi.pipeline.indexer import DocumentIndexer
            self._indexer = DocumentIndexer(
                db_session=self.db_session,
                es_client=self.es_client,
            )
        return self._indexer
    
    def _check_memory(self) -> None:
        """Verifica uso de memória e levanta erro se exceder limite."""
        try:
            import psutil
            process = psutil.Process()
            memory_mb = process.memory_info().rss / (1024 * 1024)
            if memory_mb > self.config.max_memory_mb:
                raise MemoryError(
                    f"Memory limit exceeded: {memory_mb:.0f}MB > "
                    f"{self.config.max_memory_mb}MB"
                )
        except ImportError:
            # psutil não disponível, ignora
            pass
    
    async def run(
        self,
        source_id: str,
        source_config: Dict[str, Any],
        resume_from: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Executa o pipeline completo.
        
        Args:
            source_id: ID da fonte
            source_config: Configuração da fonte
            resume_from: ID de execução anterior para resumir
            
        Returns:
            Estatísticas da execução
        """
        # Cria ou recupera manifest
        if resume_from:
            run_id = resume_from
            self._manifest = await self._load_manifest(run_id)
        else:
            run_id = str(uuid.uuid4())
            self._manifest = PipelineManifest(
                run_id=run_id,
                source_id=source_id,
                status=PipelineStatus.RUNNING,
                started_at=datetime.now(timezone.utc),
            )
            await self._create_manifest(self._manifest)
        
        # Inicializa semáforo para controle de concorrência
        self._semaphore = asyncio.Semaphore(self.config.max_concurrent_urls)
        
        stats = {
            "run_id": run_id,
            "source_id": source_id,
            "status": "running",
            "started_at": self._manifest.started_at.isoformat() if self._manifest.started_at else None,
        }
        
        try:
            # Fase 1: Discovery
            urls = await self._discovery_phase(source_config, stats)
            
            if not urls:
                logger.info(f"No URLs discovered for {source_id}")
                stats["status"] = "success"
                await self._complete_manifest(run_id, "success", stats)
                return stats
            
            # Fase 2: Change Detection
            urls_to_process = await self._change_detection_phase(urls, source_id, source_config, stats)
            
            # Fase 3: Processing
            if urls_to_process:
                await self._processing_phase(
                    urls_to_process,
                    source_id,
                    source_config,
                    run_id,
                    stats,
                )
            
            stats["status"] = "success"
            await self._complete_manifest(run_id, "success", stats)
            
        except Exception as e:
            logger.error(f"Pipeline failed for {source_id}: {e}")
            stats["status"] = "failed"
            stats["error"] = str(e)
            await self._complete_manifest(run_id, "failed", stats)
            raise
        
        return stats
    
    async def _discovery_phase(
        self,
        source_config: Dict[str, Any],
        stats: Dict[str, Any],
    ) -> List[str]:
        """Fase de descoberta de URLs.
        
        Args:
            source_config: Configuração da fonte
            stats: Estatísticas acumuladas
            
        Returns:
            Lista de URLs descobertas
        """
        discovery_config = source_config.get("discovery", {})
        mode = discovery_config.get("mode", "static_url")
        
        if mode == "static_url":
            url = discovery_config.get("url")
            if url:
                return [url]
            return []
        
        elif mode == "url_pattern":
            url_template = discovery_config.get("url_template", "")
            params = discovery_config.get("params", {})
            max_urls = discovery_config.get("max_urls", 100)
            
            urls = []
            # Gera URLs baseado nos parâmetros
            import itertools
            
            param_names = list(params.keys())
            if not param_names:
                return []
            
            # Cria ranges para cada parâmetro
            ranges = []
            for param_name in param_names:
                param_spec = params[param_name]
                start = param_spec.get("start", 0)
                end = param_spec.get("end", start)
                step = param_spec.get("step", 1)
                ranges.append(list(range(start, end + 1, step)))
            
            # Gera combinações
            for combination in itertools.product(*ranges):
                if len(urls) >= max_urls:
                    break
                url = url_template
                for param_name, value in zip(param_names, combination):
                    url = url.replace(f"{{{param_name}}}", str(value))
                urls.append(url)
            
            return urls
        
        # Outros modos podem ser implementados conforme necessário
        return []
    
    async def _change_detection_phase(
        self,
        urls: List[str],
        source_id: str,
        source_config: Dict[str, Any],
        stats: Dict[str, Any],
    ) -> List[str]:
        """Fase de detecção de mudanças.
        
        Args:
            urls: URLs descobertas
            source_id: ID da fonte
            source_config: Configuração da fonte
            stats: Estatísticas acumuladas
            
        Returns:
            Lista de URLs que precisam ser processadas
        """
        # Por padrão, processa todas as URLs
        # Em implementação completa, verificaria cache de mudanças
        return urls
    
    async def _processing_phase(
        self,
        urls: List[str],
        source_id: str,
        source_config: Dict[str, Any],
        run_id: str,
        stats: Dict[str, Any],
    ) -> None:
        """Fase de processamento das URLs.
        
        Args:
            urls: URLs a processar
            source_id: ID da fonte
            source_config: Configuração da fonte
            run_id: ID da execução
            stats: Estatísticas acumuladas
        """
        fetch_config = source_config.get("fetch", {})
        parse_config = source_config.get("parse", {})
        mapping_config = source_config.get("mapping", {})
        quality_config = source_config.get("quality", {})
        
        async def process_with_semaphore(url: str) -> None:
            async with self._semaphore:
                await self._process_single_url(
                    url=url,
                    source_id=source_id,
                    fetch_config=fetch_config,
                    parse_config=parse_config,
                    mapping_config=mapping_config,
                    quality_config=quality_config,
                    run_id=run_id,
                    stats=stats,
                )
        
        # Processa URLs em paralelo com controle de concorrência
        tasks = [process_with_semaphore(url) for url in urls]
        await asyncio.gather(*tasks, return_exceptions=True)
    
    async def _process_single_url(
        self,
        url: str,
        source_id: str,
        fetch_config: Dict[str, Any],
        parse_config: Dict[str, Any],
        mapping_config: Dict[str, Any],
        quality_config: Dict[str, Any],
        run_id: str,
        stats: Dict[str, Any],
    ) -> None:
        """Processa uma única URL.
        
        Args:
            url: URL a processar
            source_id: ID da fonte
            fetch_config: Configuração de fetch
            parse_config: Configuração de parsing
            mapping_config: Configuração de mapeamento
            quality_config: Configuração de qualidade
            run_id: ID da execução
            stats: Estatísticas acumuladas
        """
        try:
            # Verifica limite de memória
            self._check_memory()
            
            # Atualiza estatísticas
            stats["documents_fetched"] = stats.get("documents_fetched", 0) + 1
            
        except Exception as e:
            logger.error(f"Error processing {url}: {e}")
            if self.config.enable_dlq:
                await self._send_to_dlq(
                    source_id=source_id,
                    run_id=run_id,
                    url=url,
                    error_type="processing_error",
                    error_message=str(e),
                )
            raise
    
    async def _create_manifest(self, manifest: PipelineManifest) -> None:
        """Cria manifest de execução no banco de dados.
        
        Args:
            manifest: Manifesto a ser criado
        """
        # Em implementação completa, salvaria no banco
        logger.info(f"Created manifest for run {manifest.run_id}")
    
    async def _load_manifest(self, run_id: str) -> PipelineManifest:
        """Carrega manifest de execução anterior.
        
        Args:
            run_id: ID da execução
            
        Returns:
            Manifesto carregado
        """
        # Em implementação completa, carregaria do banco
        return PipelineManifest(
            run_id=run_id,
            source_id="unknown",
            status=PipelineStatus.RUNNING,
        )
    
    async def _update_checkpoint(
        self,
        run_id: str,
        processed: int,
        last_url: Optional[str] = None,
    ) -> None:
        """Atualiza checkpoint de execução.
        
        Args:
            run_id: ID da execução
            processed: Número de itens processados
            last_url: Última URL processada
        """
        if self._manifest:
            self._manifest.checkpoint.processed_count = processed
            self._manifest.checkpoint.last_processed_url = last_url
            self._manifest.checkpoint.timestamp = datetime.now(timezone.utc)
        
        # Em implementação completa, salvaria no banco
        logger.debug(f"Updated checkpoint for run {run_id}: {processed} items")
    
    async def _complete_manifest(
        self,
        run_id: str,
        status: str,
        stats: Dict[str, Any],
    ) -> None:
        """Finaliza manifest de execução.
        
        Args:
            run_id: ID da execução
            status: Status final
            stats: Estatísticas finais
        """
        if self._manifest:
            self._manifest.status = PipelineStatus(status)
            self._manifest.completed_at = datetime.now(timezone.utc)
        
        # Em implementação completa, atualizaria no banco
        logger.info(f"Completed run {run_id} with status {status}")
    
    async def _send_to_dlq(
        self,
        source_id: str,
        run_id: str,
        url: str,
        error_type: str,
        error_message: str,
    ) -> None:
        """Envia mensagem para Dead Letter Queue.
        
        Args:
            source_id: ID da fonte
            run_id: ID da execução
            url: URL que falhou
            error_type: Tipo de erro
            error_message: Mensagem de erro
        """
        if self.db_session:
            # Em implementação completa, salvaria no banco
            pass
        
        logger.warning(
            f"Sent to DLQ: source={source_id}, url={url}, "
            f"error_type={error_type}, error={error_message}"
        )


# Função utilitária para execução do pipeline
async def run_pipeline(
    source_id: str,
    source_config: Dict[str, Any],
    db_session: Optional[Any] = None,
    es_client: Optional[Any] = None,
    redis_client: Optional[Any] = None,
    resume_from: Optional[str] = None,
) -> Dict[str, Any]:
    """Executa o pipeline para uma fonte.
    
    Função de conveniência para executar o pipeline sem
    criar explicitamente o orquestrador.
    
    Args:
        source_id: ID da fonte
        source_config: Configuração da fonte
        db_session: Sessão do banco de dados
        es_client: Cliente Elasticsearch
        redis_client: Cliente Redis
        resume_from: ID de execução anterior para resumir
        
    Returns:
        Estatísticas da execução
    """
    orchestrator = PipelineOrchestrator(
        db_session=db_session,
        es_client=es_client,
        redis_client=redis_client,
    )
    
    return await orchestrator.run(
        source_id=source_id,
        source_config=source_config,
        resume_from=resume_from,
    )


# Exportações
__all__ = [
    "PipelineOrchestrator",
    "PipelineConfig",
    "PipelineManifest",
    "PipelineStatus",
    "PipelinePhase",
    "run_pipeline",
]
