"""Orquestrador de múltiplos agents de crawling.

Gerencia distribuição de tarefas, coleta de resultados
e coordenação entre múltiplos agents.
Baseado em CRAWLER.md §3.3.

Integrações:
    - PolitenessManager: Rate limiting e respeito a robots.txt
    - MetadataExtractor: Extração de metadados das páginas
    - Governance: Auditoria e lineage tracking
"""

import asyncio
import hashlib
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Set, Type, Union
from collections import defaultdict

from gabi.config import settings
from gabi.pipeline.contracts import DiscoveredURL, FetchedContent, FetchMetadata
from gabi.governance.audit import AuditLogger
from gabi.governance.lineage import LineageTracker

from .base_agent import AgentStats, BaseCrawlerAgent, CrawlResult
from .metadata import MetadataExtractor, PageMetadata, LegalDocumentExtractor
from .politeness import PolitenessManager

logger = logging.getLogger(__name__)


@dataclass
class OrchestratorConfig:
    """Configuração do orquestrador.
    
    Attributes:
        max_concurrent_agents: Máximo de agents simultâneos
        max_queue_size: Tamanho máximo da fila de URLs
        batch_size: Tamanho do batch para processamento
        retry_failed: Se deve retry URLs que falharam
        max_retries: Máximo de retries por URL
        collect_stats: Se deve coletar estatísticas detalhadas
        respect_robots: Se deve respeitar robots.txt
        extract_metadata: Se deve extrair metadados das páginas
        default_delay: Delay padrão entre requests
        enable_audit: Se deve registrar auditoria
    """
    max_concurrent_agents: int = 5
    max_queue_size: int = 10000
    batch_size: int = 100
    retry_failed: bool = True
    max_retries: int = 3
    collect_stats: bool = True
    respect_robots: bool = True
    extract_metadata: bool = True
    extract_legal_metadata: bool = True
    default_delay: float = 1.0
    enable_audit: bool = True


@dataclass
class OrchestratorStats:
    """Estatísticas do orquestrador.
    
    Attributes:
        total_urls: Total de URLs no job
        processed_urls: URLs processadas
        successful_urls: URLs com sucesso
        failed_urls: URLs com falha
        retried_urls: URLs reprocessadas
        blocked_by_robots: URLs bloqueadas por robots.txt
        start_time: Início do job
        end_time: Fim do job
        agent_stats: Estatísticas por agente
        metadata_extracted: Metadados extraídos
        politeness_stats: Estatísticas de politeness
    """
    total_urls: int = 0
    processed_urls: int = 0
    successful_urls: int = 0
    failed_urls: int = 0
    retried_urls: int = 0
    blocked_by_robots: int = 0
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    agent_stats: Dict[str, AgentStats] = field(default_factory=dict)
    metadata_extracted: int = 0
    politeness_stats: Dict[str, Any] = field(default_factory=dict)
    
    @property
    def duration_seconds(self) -> float:
        """Duração em segundos."""
        if self.start_time is None:
            return 0.0
        end = self.end_time or datetime.utcnow()
        return (end - self.start_time).total_seconds()
    
    @property
    def success_rate(self) -> float:
        """Taxa de sucesso."""
        if self.processed_urls == 0:
            return 0.0
        return self.successful_urls / self.processed_urls
    
    @property
    def throughput_per_minute(self) -> float:
        """Throughput em URLs por minuto."""
        duration = self.duration_seconds
        if duration == 0:
            return 0.0
        return (self.processed_urls / duration) * 60


@dataclass
class CrawlJob:
    """Job de crawling.
    
    Attributes:
        job_id: ID único do job
        source_id: ID da fonte
        urls: URLs a crawlear
        priority: Prioridade do job
        created_at: Timestamp de criação
        started_at: Timestamp de início
        completed_at: Timestamp de conclusão
        status: Status atual
        results: Resultados coletados
        config: Configuração específica do job
    """
    job_id: str
    source_id: str
    urls: List[str] = field(default_factory=list)
    priority: int = 0
    created_at: datetime = field(default_factory=datetime.utcnow)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    status: str = "pending"  # pending, running, paused, completed, failed
    results: List[CrawlResult] = field(default_factory=list)
    config: Optional[OrchestratorConfig] = None
    metadata_results: Dict[str, PageMetadata] = field(default_factory=dict)


@dataclass
class CrawlJobResult:
    """Resultado completo de um job de crawling.
    
    Attributes:
        job: Job executado
        stats: Estatísticas
        discovered_urls: URLs descobertas durante crawling
        errors: Erros ocorridos
    """
    job: CrawlJob
    stats: OrchestratorStats
    discovered_urls: List[str] = field(default_factory=list)
    errors: List[Dict[str, Any]] = field(default_factory=list)


class Orchestrator:
    """Orquestrador de crawling multi-agente.
    
    Gerencia múltiplos agents de crawling, distribui
tarefas e coleta resultados. Integra:
    
    - PolitenessManager: Rate limiting e robots.txt
    - MetadataExtractor: Extração de metadados
    - AuditLogger: Auditoria de operações
    - LineageTracker: Rastreamento de lineage
    
    Attributes:
        config: Configuração do orquestrador
        agent_class: Classe do agente a instanciar
        agent_kwargs: Argumentos para criação de agents
        stats: Estatísticas do orquestrador
        politeness: Gerenciador de politeness
        metadata_extractor: Extrator de metadados
    """
    
    def __init__(
        self,
        config: Optional[OrchestratorConfig] = None,
        agent_class: Type[BaseCrawlerAgent] = None,
        agent_kwargs: Optional[Dict[str, Any]] = None,
        db_session = None,
    ):
        self.config = config or OrchestratorConfig()
        self.agent_class = agent_class
        self.agent_kwargs = agent_kwargs or {}
        self._db_session = db_session
        
        # Componentes
        self._agents: Dict[str, BaseCrawlerAgent] = {}
        self._url_queue: asyncio.Queue = asyncio.Queue(
            maxsize=self.config.max_queue_size
        )
        self._results: List[CrawlResult] = []
        self._failed_urls: Dict[str, int] = defaultdict(int)  # url -> retry_count
        self._processed_urls: Set[str] = set()
        self._semaphore: Optional[asyncio.Semaphore] = None
        self._shutdown_event: Optional[asyncio.Event] = None
        
        # Integrações
        self.politeness = PolitenessManager(
            respect_robots=self.config.respect_robots,
            default_delay=self.config.default_delay
        )
        self.metadata_extractor = MetadataExtractor() if self.config.extract_metadata else None
        self.legal_extractor = LegalDocumentExtractor() if self.config.extract_legal_metadata else None
        
        # Governança
        self.audit_logger: Optional[AuditLogger] = None
        self.lineage_tracker: Optional[LineageTracker] = None
        if db_session and self.config.enable_audit:
            self.audit_logger = AuditLogger(db_session)
            self.lineage_tracker = LineageTracker(db_session)
        
        self.stats = OrchestratorStats()
        self._current_job: Optional[CrawlJob] = None
        self._result_callback: Optional[Callable[[CrawlResult], None]] = None
        self._metadata_callback: Optional[Callable[[str, PageMetadata], None]] = None
    
    def register_agent(
        self,
        agent_id: str,
        agent: Optional[BaseCrawlerAgent] = None,
        **kwargs
    ) -> BaseCrawlerAgent:
        """Registra um agente no orquestrador.
        
        Args:
            agent_id: ID único do agente
            agent: Instância do agente (ou None para criar)
            **kwargs: Argumentos para criação do agente
            
        Returns:
            Agente registrado
        """
        if agent is None:
            if self.agent_class is None:
                raise ValueError("agent_class não definido e nenhum agente fornecido")
            agent = self.agent_class(agent_id=agent_id, **{**self.agent_kwargs, **kwargs})
        
        self._agents[agent_id] = agent
        logger.info(f"Agente {agent_id} registrado no orquestrador")
        return agent
    
    def unregister_agent(self, agent_id: str) -> None:
        """Remove um agente do orquestrador.
        
        Args:
            agent_id: ID do agente a remover
        """
        if agent_id in self._agents:
            del self._agents[agent_id]
            logger.info(f"Agente {agent_id} removido do orquestrador")
    
    def set_result_callback(self, callback: Callable[[CrawlResult], None]) -> None:
        """Define callback para resultados.
        
        O callback é chamado para cada resultado de crawl.
        
        Args:
            callback: Função a chamar com o resultado
        """
        self._result_callback = callback
    
    def set_metadata_callback(self, callback: Callable[[str, PageMetadata], None]) -> None:
        """Define callback para metadados.
        
        O callback é chamado para cada página com metadados extraídos.
        
        Args:
            callback: Função a chamar com (url, metadata)
        """
        self._metadata_callback = callback
    
    async def submit_urls(self, urls: List[str], priority: int = 0) -> int:
        """Submete URLs para processamento.
        
        Args:
            urls: Lista de URLs
            priority: Prioridade (maior = mais prioritário)
            
        Returns:
            Número de URLs enfileiradas
        """
        enqueued = 0
        for url in urls:
            if url not in self._processed_urls:
                try:
                    # Adiciona com timeout para não bloquear indefinidamente
                    await asyncio.wait_for(
                        self._url_queue.put((priority, url)),
                        timeout=1.0
                    )
                    enqueued += 1
                except asyncio.TimeoutError:
                    logger.warning(f"Fila cheia, URL descartada: {url}")
        
        self.stats.total_urls += enqueued
        return enqueued
    
    async def _worker(self, agent_id: str) -> None:
        """Worker que processa URLs da fila.
        
        Args:
            agent_id: ID do agente que executará os crawls
        """
        agent = self._agents.get(agent_id)
        if not agent:
            logger.error(f"Agente {agent_id} não encontrado")
            return
        
        while not self._shutdown_event.is_set():
            try:
                # Obtém URL da fila com timeout
                priority, url = await asyncio.wait_for(
                    self._url_queue.get(),
                    timeout=1.0
                )
                
                if url in self._processed_urls:
                    self._url_queue.task_done()
                    continue
                
                # Verifica robots.txt
                if not await self.politeness.can_fetch(url):
                    logger.debug(f"URL bloqueada por robots.txt: {url}")
                    self.stats.blocked_by_robots += 1
                    self._processed_urls.add(url)
                    self._url_queue.task_done()
                    continue
                
                # Aguarda rate limiting
                await self.politeness.acquire_slot(url)
                
                # Executa crawl
                start_time = datetime.utcnow()
                result = await agent.crawl(url)
                duration_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)
                
                # Registra resposta para ajuste adaptativo
                self.politeness.record_response(url, duration_ms, result.success)
                
                # Atualiza estatísticas
                self._processed_urls.add(url)
                self.stats.processed_urls += 1
                
                if result.success:
                    self.stats.successful_urls += 1
                    self._results.append(result)
                    
                    # Extrai metadados se disponível
                    await self._extract_metadata(url, result)
                    
                    # Adiciona links descobertos à fila
                    if result.links:
                        await self.submit_urls(result.links, priority=priority - 1)
                        
                    # Registra lineage se disponível
                    if self.lineage_tracker and self._current_job:
                        await self._record_lineage(url, result)
                else:
                    self.stats.failed_urls += 1
                    
                    # Retry se configurado
                    if self.config.retry_failed:
                        retry_count = self._failed_urls[url]
                        if retry_count < self.config.max_retries:
                            self._failed_urls[url] = retry_count + 1
                            self.stats.retried_urls += 1
                            # Re-enfileira com menor prioridade
                            await self._url_queue.put((priority - 10, url))
                            self.stats.total_urls += 1
                
                # Chama callback se definido
                if self._result_callback:
                    try:
                        self._result_callback(result)
                    except Exception as e:
                        logger.error(f"Erro no callback: {e}")
                
                self._url_queue.task_done()
                
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.error(f"Erro no worker {agent_id}: {e}")
    
    async def _extract_metadata(self, url: str, result: CrawlResult) -> None:
        """Extrai metadados do resultado do crawl.
        
        Args:
            url: URL crawleada
            result: Resultado do crawl
        """
        if not result.success or not result.content:
            return
        
        try:
            content = result.content.content
            if isinstance(content, bytes):
                content = content.decode('utf-8', errors='ignore')
            
            # Extrai metadados gerais
            if self.metadata_extractor:
                metadata = self.metadata_extractor.extract(content, url)
                self.stats.metadata_extracted += 1
                
                if self._current_job:
                    self._current_job.metadata_results[url] = metadata
                
                # Chama callback se definido
                if self._metadata_callback:
                    try:
                        self._metadata_callback(url, metadata)
                    except Exception as e:
                        logger.error(f"Erro no metadata callback: {e}")
            
            # Extrai metadados jurídicos
            if self.legal_extractor:
                legal_meta = self.legal_extractor.extract(content, url)
                if self._current_job and url in self._current_job.metadata_results:
                    # Merge com metadados existentes
                    self._current_job.metadata_results[url].extra['legal'] = legal_meta
                    
        except Exception as e:
            logger.warning(f"Erro ao extrair metadados de {url}: {e}")
    
    async def _record_lineage(self, url: str, result: CrawlResult) -> None:
        """Registra lineage para URL processada.
        
        Args:
            url: URL processada
            result: Resultado do crawl
        """
        if not self.lineage_tracker or not self._current_job:
            return
        
        try:
            from gabi.types import LineageNodeType, LineageEdgeType
            
            # Cria nó para a URL fonte
            source_node_id = f"crawl_source:{hashlib.md5(url.encode()).hexdigest()[:16]}"
            await self.lineage_tracker.create_node(
                node_id=source_node_id,
                node_type=LineageNodeType.SOURCE,
                name=f"Web Source: {url[:100]}",
                properties={
                    "url": url,
                    "source_id": self._current_job.source_id,
                    "job_id": self._current_job.job_id,
                }
            )
            
            # Cria nó para o documento resultante
            if result.content:
                doc_node_id = f"crawl_doc:{result.content.fingerprint[:16]}"
                await self.lineage_tracker.create_node(
                    node_id=doc_node_id,
                    node_type=LineageNodeType.DOCUMENT,
                    name=f"Document: {url[:100]}",
                    properties={
                        "url": url,
                        "content_type": result.content.metadata.content_type,
                        "size_bytes": result.content.metadata.content_length,
                    }
                )
                
                # Cria aresta source -> document
                await self.lineage_tracker.create_edge(
                    source_node=source_node_id,
                    target_node=doc_node_id,
                    edge_type=LineageEdgeType.PRODUCED,
                    properties={
                        "crawl_timestamp": datetime.utcnow().isoformat(),
                        "duration_ms": result.duration_ms,
                    }
                )
                
        except Exception as e:
            logger.warning(f"Erro ao registrar lineage para {url}: {e}")
    
    async def crawl(
        self,
        urls: List[str],
        source_id: str,
        job_id: Optional[str] = None
    ) -> CrawlJob:
        """Executa job de crawling.
        
        Args:
            urls: URLs iniciais
            source_id: ID da fonte
            job_id: ID opcional do job
            
        Returns:
            Job completado com resultados
        """
        job_id = job_id or f"job_{datetime.utcnow().timestamp()}"
        job = CrawlJob(
            job_id=job_id,
            source_id=source_id,
            urls=urls.copy(),
            config=self.config
        )
        self._current_job = job
        
        # Log de auditoria
        if self.audit_logger:
            await self.audit_logger.log_crawl_started(source_id, job_id, len(urls))
        
        # Inicializa
        self.stats.start_time = datetime.utcnow()
        self.stats.total_urls = len(urls)
        self._semaphore = asyncio.Semaphore(self.config.max_concurrent_agents)
        self._shutdown_event = asyncio.Event()
        
        # Inicializa politeness e agents
        for agent in self._agents.values():
            await agent.initialize()
        
        job.status = "running"
        job.started_at = datetime.utcnow()
        
        # Submete URLs iniciais
        await self.submit_urls(urls)
        
        # Inicia workers
        workers = [
            asyncio.create_task(self._worker(agent_id))
            for agent_id in self._agents.keys()
        ]
        
        # Aguarda conclusão
        try:
            await self._url_queue.join()
        except asyncio.CancelledError:
            logger.info("Job cancelado")
            job.status = "failed"
        
        # Finaliza
        self._shutdown_event.set()
        await asyncio.gather(*workers, return_exceptions=True)
        
        for agent in self._agents.values():
            await agent.shutdown()
            if self.config.collect_stats:
                self.stats.agent_stats[agent.agent_id] = agent.get_stats()
        
        job.status = "completed"
        job.completed_at = datetime.utcnow()
        job.results = self._results.copy()
        
        self.stats.end_time = datetime.utcnow()
        self.stats.politeness_stats = self.politeness.get_stats()
        
        # Log de auditoria
        if self.audit_logger:
            await self.audit_logger.log_crawl_completed(
                source_id, job_id, job.status, self.stats.to_dict() if hasattr(self.stats, 'to_dict') else {}
            )
        
        return job
    
    async def crawl_batch(
        self,
        discovered_urls: List[DiscoveredURL],
        agent_id: Optional[str] = None
    ) -> List[CrawlResult]:
        """Processa batch de URLs descobertas.
        
        Args:
            discovered_urls: URLs descobertas
            agent_id: ID do agente a usar (ou None para qualquer)
            
        Returns:
            Lista de resultados
        """
        if not discovered_urls:
            return []
        
        # Seleciona agente
        agent = None
        if agent_id:
            agent = self._agents.get(agent_id)
        if not agent:
            # Usa primeiro agente disponível
            agent = next(iter(self._agents.values()), None)
        
        if not agent:
            raise RuntimeError("Nenhum agente disponível")
        
        # Inicializa se necessário
        await agent.initialize()
        await self.politeness.fetch_robots_txt(discovered_urls[0].url)
        
        results = []
        for disc_url in discovered_urls:
            # Verifica robots.txt
            if not await self.politeness.can_fetch(disc_url.url):
                self.stats.blocked_by_robots += 1
                results.append(CrawlResult(
                    url=disc_url.url,
                    success=False,
                    error="Bloqueado por robots.txt"
                ))
                continue
            
            # Aguarda rate limiting
            await self.politeness.acquire_slot(disc_url.url)
            
            # Executa crawl
            start_time = datetime.utcnow()
            result = await agent.crawl(disc_url.url)
            duration_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)
            
            self.politeness.record_response(disc_url.url, duration_ms, result.success)
            results.append(result)
        
        await agent.shutdown()
        return results
    
    def get_stats(self) -> OrchestratorStats:
        """Retorna estatísticas atuais.
        
        Returns:
            Estatísticas do orquestrador
        """
        from copy import deepcopy
        stats_copy = deepcopy(self.stats)
        stats_copy.politeness_stats = self.politeness.get_stats()
        return stats_copy
    
    def reset(self) -> None:
        """Reseta estado do orquestrador."""
        self._results.clear()
        self._failed_urls.clear()
        self._processed_urls.clear()
        self._current_job = None
        
        # Limpa fila
        while not self._url_queue.empty():
            try:
                self._url_queue.get_nowait()
                self._url_queue.task_done()
            except asyncio.QueueEmpty:
                break
        
        self.stats = OrchestratorStats()
    
    async def shutdown(self) -> None:
        """Desliga orquestrador e libera recursos."""
        if self._shutdown_event:
            self._shutdown_event.set()
        
        for agent in self._agents.values():
            await agent.shutdown()
        
        await self.politeness.close()
        self._agents.clear()
        logger.info("Orquestrador desligado")


class CrawlScheduler:
    """Scheduler para jobs de crawling.
    
    Agenda e gerencia múltiplos jobs de crawling
    com controle de concorrência.
    
    Attributes:
        max_concurrent_jobs: Máximo de jobs simultâneos
        orchestrator_factory: Factory para criar orquestradores
    """
    
    def __init__(
        self,
        max_concurrent_jobs: int = 3,
        orchestrator_factory = None,
    ):
        self.max_concurrent_jobs = max_concurrent_jobs
        self.orchestrator_factory = orchestrator_factory or Orchestrator
        self._semaphore = asyncio.Semaphore(max_concurrent_jobs)
        self._jobs: Dict[str, CrawlJob] = {}
        self._results: Dict[str, CrawlJobResult] = {}
    
    async def schedule(
        self,
        urls: List[str],
        source_id: str,
        job_id: Optional[str] = None,
        config: Optional[OrchestratorConfig] = None,
    ) -> CrawlJob:
        """Agenda um job de crawling.
        
        Args:
            urls: URLs a crawlear
            source_id: ID da fonte
            job_id: ID opcional do job
            config: Configuração do orquestrador
            
        Returns:
            Job completado
        """
        async with self._semaphore:
            job_id = job_id or f"scheduled_{datetime.utcnow().timestamp()}"
            
            # Cria orquestrador
            orchestrator = self.orchestrator_factory(config=config)
            
            # Executa job
            job = await orchestrator.crawl(urls, source_id, job_id)
            
            # Armazena resultado
            self._jobs[job_id] = job
            self._results[job_id] = CrawlJobResult(
                job=job,
                stats=orchestrator.get_stats()
            )
            
            # Cleanup
            await orchestrator.shutdown()
            
            return job
    
    async def schedule_batch(
        self,
        jobs_config: List[Dict[str, Any]]
    ) -> List[CrawlJob]:
        """Agenda múltiplos jobs.
        
        Args:
            jobs_config: Lista de configurações de jobs
                Cada dict deve ter: urls, source_id, job_id (opcional)
                
        Returns:
            Lista de jobs completados
        """
        tasks = [
            self.schedule(
                urls=config["urls"],
                source_id=config["source_id"],
                job_id=config.get("job_id"),
                config=config.get("config")
            )
            for config in jobs_config
        ]
        
        return await asyncio.gather(*tasks, return_exceptions=True)
    
    def get_job_result(self, job_id: str) -> Optional[CrawlJobResult]:
        """Retorna resultado de um job.
        
        Args:
            job_id: ID do job
            
        Returns:
            Resultado do job ou None
        """
        return self._results.get(job_id)
    
    def get_all_results(self) -> Dict[str, CrawlJobResult]:
        """Retorna todos os resultados.
        
        Returns:
            Dicionário de job_id -> resultado
        """
        return self._results.copy()


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    "OrchestratorConfig",
    "OrchestratorStats",
    "CrawlJob",
    "CrawlJobResult",
    "Orchestrator",
    "CrawlScheduler",
]
