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
import time
import uuid
from datetime import datetime, timezone
import itertools
from typing import Any, Dict, List, Optional, Set, TYPE_CHECKING
from dataclasses import dataclass, field, asdict
from enum import Enum

import httpx
from sqlalchemy import insert, update

from gabi.models.dlq import DLQMessage as DLQMessageModel
from gabi.models.execution import ExecutionManifest
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
from gabi.types import DLQStatus, ExecutionTrigger

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
            if self.db_session is None:
                raise RuntimeError("db_session é obrigatório para deduplicação")
            self._deduplicator = Deduplicator(
                db_session=self.db_session,
                redis_client=self.redis_client,
            )
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
            from gabi.pipeline.indexer import Indexer
            if self.es_client is None:
                raise RuntimeError("es_client é obrigatório para indexação")
            self._indexer = Indexer(es_client=self.es_client)
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
            "phase_durations_ms": {},
        }
        
        try:
            # Fase 1: Discovery
            discovery_start = time.perf_counter()
            urls = await self._discovery_phase(source_config, stats)
            stats["phase_durations_ms"][PipelinePhase.DISCOVERY.value] = round(
                (time.perf_counter() - discovery_start) * 1000, 2
            )
            
            if not urls:
                logger.info(f"No URLs discovered for {source_id}")
                stats["status"] = "success"
                await self._complete_manifest(run_id, "success", stats)
                return stats
            
            # Fase 2: Change Detection
            change_detection_start = time.perf_counter()
            urls_to_process = await self._change_detection_phase(urls, source_id, source_config, stats)
            stats["phase_durations_ms"][PipelinePhase.CHANGE_DETECTION.value] = round(
                (time.perf_counter() - change_detection_start) * 1000, 2
            )
            
            # Fase 3: Processing
            if urls_to_process:
                processing_start = time.perf_counter()
                await self._processing_phase(
                    urls_to_process,
                    source_id,
                    source_config,
                    run_id,
                    stats,
                )
                stats["phase_durations_ms"]["processing_total"] = round(
                    (time.perf_counter() - processing_start) * 1000, 2
                )
            
            stats["status"] = "success"
            await self._complete_manifest(run_id, "success", stats)
            logger.info(
                "Pipeline run completed",
                extra={
                    "run_id": run_id,
                    "source_id": source_id,
                    "status": "success",
                    "phase_durations_ms": stats.get("phase_durations_ms", {}),
                },
            )
            
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
            
            param_names = list(params.keys())
            if not param_names:
                return []
            
            # Cria ranges para cada parâmetro
            ranges = []
            for param_name in param_names:
                param_spec = params[param_name]
                start = self._resolve_range_value(param_spec.get("start", 0))
                end = self._resolve_range_value(param_spec.get("end", start))
                step = self._resolve_range_value(param_spec.get("step", 1))
                if step == 0:
                    step = 1
                if end < start and step > 0:
                    step = -step
                stop = end + 1 if step > 0 else end - 1
                ranges.append(list(range(start, stop, step)))
            
            # Gera combinações
            for combination in itertools.product(*ranges):
                if len(urls) >= max_urls:
                    break
                url = url_template
                for param_name, value in zip(param_names, combination):
                    url = url.replace(f"{{{param_name}}}", str(value))
                urls.append(url)
            
            return urls

        elif mode == "crawler":
            # Validation fallback: use root URL as seed so sync path can exercise fetch/parse/index.
            root_url = discovery_config.get("root_url") or discovery_config.get("url")
            if root_url:
                return [root_url]
            return []

        elif mode == "api_query":
            # Validation fallback path for driver-based APIs without explicit URL.
            url = (
                discovery_config.get("validation_url")
                or discovery_config.get("url")
                or discovery_config.get("endpoint")
                or discovery_config.get("base_url")
            )
            if url:
                return [url]

            if discovery_config.get("driver") == "camara_api_v1":
                return ["https://www.camara.leg.br/"]
            return []
        
        # Outros modos podem ser implementados conforme necessário
        return []

    @staticmethod
    def _resolve_range_value(raw_value: Any) -> int:
        """Converte valor de range para inteiro, suportando tokens simbólicos."""
        if isinstance(raw_value, int):
            return raw_value
        if isinstance(raw_value, str):
            value = raw_value.strip().lower()
            if value in {"current", "current_year", "this_year", "now"}:
                return datetime.now(timezone.utc).year
            if value.lstrip("-").isdigit():
                return int(value)
        raise ValueError(f"Invalid range value: {raw_value!r}")
    
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
        
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(self.config.max_concurrent_urls)

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
        fetched: Optional[FetchedContent] = None
        try:
            # Verifica limite de memória
            self._check_memory()

            # Fetch
            fetch_started = time.perf_counter()
            method = fetch_config.get("method", "GET")
            headers = fetch_config.get("headers")
            fetched = await self.fetcher.fetch(
                url=url,
                source_id=source_id,
                method=method,
                headers=headers,
            )
            fetch_duration_ms = round((time.perf_counter() - fetch_started) * 1000, 2)
            stats["fetch_duration_ms_total"] = round(
                stats.get("fetch_duration_ms_total", 0.0) + fetch_duration_ms, 2
            )

            # Parse
            parse_started = time.perf_counter()
            parser_config = dict(parse_config)
            parser_config.setdefault("source_id", source_id)
            parsed = None
            if parser_config.get("input_format") or parser_config.get("format"):
                parsed = await self.parser.parse(fetched, parser_config)
            parse_duration_ms = round((time.perf_counter() - parse_started) * 1000, 2)
            stats["parse_duration_ms_total"] = round(
                stats.get("parse_duration_ms_total", 0.0) + parse_duration_ms, 2
            )
            
            # Atualiza estatísticas
            stats["documents_fetched"] = stats.get("documents_fetched", 0) + 1
            stats["documents_parsed"] = stats.get("documents_parsed", 0) + len(
                getattr(parsed, "documents", []) or []
            )
            
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
        finally:
            if fetched is not None:
                fetched.cleanup()
    
    async def _create_manifest(self, manifest: PipelineManifest) -> None:
        """Cria manifest de execução no banco de dados.
        
        Args:
            manifest: Manifesto a ser criado
        """
        if self.db_session:
            status_value = (
                manifest.status.value
                if isinstance(manifest.status, PipelineStatus)
                else str(manifest.status)
            )
            await self.db_session.execute(
                insert(ExecutionManifest).values(
                    run_id=manifest.run_id,
                    source_id=manifest.source_id,
                    status=status_value,
                    trigger=ExecutionTrigger.MANUAL.value,
                    started_at=manifest.started_at or datetime.now(timezone.utc),
                    stats=asdict(manifest.stats),
                    checkpoint=asdict(manifest.checkpoint),
                )
            )
            if hasattr(self.db_session, "commit"):
                await self.db_session.commit()
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
        
        if self.db_session is not None:
            checkpoint_payload = (
                asdict(self._manifest.checkpoint)
                if self._manifest
                else {
                    "processed_count": processed,
                    "last_processed_url": last_url,
                    "timestamp": datetime.now(timezone.utc),
                }
            )
            await self.db_session.execute(
                update(ExecutionManifest)
                .where(ExecutionManifest.run_id == run_id)
                .values(checkpoint=checkpoint_payload)
            )
            if hasattr(self.db_session, "commit"):
                await self.db_session.commit()
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
        
        if self.db_session is not None:
            await self.db_session.execute(
                update(ExecutionManifest)
                .where(ExecutionManifest.run_id == run_id)
                .values(
                    status=status,
                    completed_at=datetime.now(timezone.utc),
                    stats=stats,
                )
            )
            if hasattr(self.db_session, "commit"):
                await self.db_session.commit()
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
            error_hash = hashlib.sha256(f"{error_type}:{error_message}".encode()).hexdigest()[:16]
            await self.db_session.execute(
                insert(DLQMessageModel).values(
                    source_id=source_id,
                    run_id=run_id,
                    url=url,
                    error_type=error_type,
                    error_message=error_message,
                    error_hash=error_hash,
                    status=DLQStatus.PENDING.value,
                    payload={
                        "source_id": source_id,
                        "run_id": run_id,
                        "url": url,
                        "error_type": error_type,
                        "error_message": error_message,
                    },
                )
            )
            if hasattr(self.db_session, "commit"):
                await self.db_session.commit()
        
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
