"""Agente base para crawling.

Define a interface abstrata que todos os crawlers devem implementar.
Baseado em CRAWLER.md §3.1.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Set
from urllib.parse import urljoin, urlparse

from gabi.config import settings
from gabi.pipeline.contracts import FetchMetadata, FetchedContent


@dataclass
class CrawlResult:
    """Resultado de uma operação de crawl.
    
    Attributes:
        url: URL crawleada
        success: Se o crawl teve sucesso
        content: Conteúdo buscado (se sucesso)
        metadata: Metadados do fetch
        links: Links extraídos da página
        error: Mensagem de erro (se falha)
        duration_ms: Duração do crawl em ms
        crawled_at: Timestamp do crawl
    """
    url: str
    success: bool = False
    content: Optional[FetchedContent] = None
    metadata: Optional[FetchMetadata] = None
    links: List[str] = field(default_factory=list)
    error: Optional[str] = None
    duration_ms: int = 0
    crawled_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class AgentStats:
    """Estatísticas de um agente crawler.
    
    Attributes:
        urls_crawled: Total de URLs crawleadas
        urls_success: URLs com sucesso
        urls_failed: URLs com falha
        links_extracted: Links extraídos
        bytes_downloaded: Bytes baixados
        avg_response_time_ms: Tempo médio de resposta
        start_time: Início da operação
        end_time: Fim da operação (se concluído)
    """
    urls_crawled: int = 0
    urls_success: int = 0
    urls_failed: int = 0
    links_extracted: int = 0
    bytes_downloaded: int = 0
    avg_response_time_ms: float = 0.0
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    
    @property
    def duration_seconds(self) -> float:
        """Retorna duração em segundos."""
        if self.start_time is None:
            return 0.0
        end = self.end_time or datetime.utcnow()
        return (end - self.start_time).total_seconds()
    
    @property
    def success_rate(self) -> float:
        """Retorna taxa de sucesso (0.0 a 1.0)."""
        if self.urls_crawled == 0:
            return 0.0
        return self.urls_success / self.urls_crawled


class BaseCrawlerAgent(ABC):
    """Agente base abstrato para crawling.
    
    Todos os crawlers específicos devem herdar desta classe
    e implementar os métodos abstratos.
    
    Attributes:
        agent_id: Identificador único do agente
        source_id: ID da fonte associada
        respect_robots: Se deve respeitar robots.txt
        delay_seconds: Delay entre requests
        max_pages: Limite máximo de páginas
        max_depth: Profundidade máxima de navegação
        allowed_domains: Domínios permitidos (vazio = todos)
        excluded_patterns: Padrões de URL a excluir
        stats: Estatísticas do agente
    """
    
    def __init__(
        self,
        agent_id: str,
        source_id: str,
        respect_robots: bool = True,
        delay_seconds: Optional[float] = None,
        max_pages: Optional[int] = None,
        max_depth: Optional[int] = None,
        allowed_domains: Optional[List[str]] = None,
        excluded_patterns: Optional[List[str]] = None,
    ):
        self.agent_id = agent_id
        self.source_id = source_id
        self.respect_robots = respect_robots
        self.delay_seconds = delay_seconds or settings.crawler_delay_seconds
        self.max_pages = max_pages or settings.crawler_max_pages
        self.max_depth = max_depth or settings.crawler_max_depth
        self.allowed_domains = set(allowed_domains or [])
        self.excluded_patterns = excluded_patterns or []
        self.stats = AgentStats()
        self._crawled_urls: Set[str] = set()
        self._url_queue: List[Dict[str, Any]] = []
        
    @abstractmethod
    async def crawl(self, url: str, depth: int = 0) -> CrawlResult:
        """Executa crawl em uma URL.
        
        Args:
            url: URL para crawlear
            depth: Profundidade atual na navegação
            
        Returns:
            Resultado do crawl
        """
        pass
    
    @abstractmethod
    async def extract_links(self, page: Any) -> List[str]:
        """Extrai links de uma página.
        
        Args:
            page: Objeto da página (específico do crawler)
            
        Returns:
            Lista de URLs extraídas
        """
        pass
    
    @abstractmethod
    async def initialize(self) -> None:
        """Inicializa recursos do agente.
        
        Deve ser chamado antes de iniciar o crawling.
        """
        pass
    
    @abstractmethod
    async def shutdown(self) -> None:
        """Libera recursos do agente.
        
        Deve ser chamado ao finalizar o crawling.
        """
        pass
    
    def is_url_allowed(self, url: str) -> bool:
        """Verifica se URL é permitida para crawling.
        
        Verifica:
        - Domínio permitido (se configurado)
        - Padrões excluídos
        - URL já crawleada
        
        Args:
            url: URL a verificar
            
        Returns:
            True se URL é permitida
        """
        # Verifica se já foi crawleada
        if url in self._crawled_urls:
            return False
        
        parsed = urlparse(url)
        
        # Verifica domínios permitidos
        if self.allowed_domains:
            if parsed.netloc not in self.allowed_domains:
                return False
        
        # Verifica padrões excluídos
        for pattern in self.excluded_patterns:
            if pattern in url:
                return False
        
        return True
    
    def normalize_url(self, url: str, base_url: str) -> Optional[str]:
        """Normaliza uma URL.
        
        Converte URLs relativas em absolutas e
        remove fragmentos.
        
        Args:
            url: URL a normalizar
            base_url: URL base para resolução
            
        Returns:
            URL normalizada ou None se inválida
        """
        try:
            # Resolve URL relativa
            absolute = urljoin(base_url, url)
            parsed = urlparse(absolute)
            
            # Remove fragmento
            normalized = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
            if parsed.query:
                normalized = f"{normalized}?{parsed.query}"
            
            return normalized
        except Exception:
            return None
    
    def filter_links(self, links: List[str], base_url: str) -> List[str]:
        """Filtra e normaliza links extraídos.
        
        Args:
            links: Links brutos extraídos
            base_url: URL base da página
            
        Returns:
            Lista de URLs filtradas e normalizadas
        """
        filtered = []
        for link in links:
            normalized = self.normalize_url(link, base_url)
            if normalized and self.is_url_allowed(normalized):
                filtered.append(normalized)
        return filtered
    
    def mark_crawled(self, url: str) -> None:
        """Marca URL como crawleada.
        
        Args:
            url: URL a marcar
        """
        self._crawled_urls.add(url)
    
    def should_continue(self, current_depth: int) -> bool:
        """Verifica se deve continuar crawling.
        
        Verifica limites de páginas e profundidade.
        
        Args:
            current_depth: Profundidade atual
            
        Returns:
            True se deve continuar
        """
        if len(self._crawled_urls) >= self.max_pages:
            return False
        if current_depth >= self.max_depth:
            return False
        return True
    
    def get_stats(self) -> AgentStats:
        """Retorna estatísticas do agente.
        
        Returns:
            Cópia das estatísticas atuais
        """
        from copy import copy
        return copy(self.stats)
    
    def reset_stats(self) -> None:
        """Reseta estatísticas do agente."""
        self.stats = AgentStats()
        self._crawled_urls.clear()
        self._url_queue.clear()
