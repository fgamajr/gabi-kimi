"""Políticas de politeness para crawling.

Implementa rate limiting, cache de robots.txt e controle
de cortesia para crawling responsável.
Baseado em CRAWLER.md §3.4.
"""

import asyncio
import hashlib
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Set
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx

from gabi.config import settings

logger = logging.getLogger(__name__)


@dataclass
class RobotsTxtCache:
    """Cache de robots.txt.
    
    Attributes:
        url: URL do robots.txt
        content: Conteúdo bruto
        parsed: Parser RobotFileParser
        fetched_at: Timestamp de fetch
        ttl_seconds: Tempo de vida do cache
        status_code: Status HTTP do fetch
    """
    url: str
    content: str
    parsed: RobotFileParser
    fetched_at: datetime
    ttl_seconds: int = 3600  # 1 hora padrão
    status_code: int = 200
    
    @property
    def is_expired(self) -> bool:
        """Verifica se cache expirou."""
        elapsed = (datetime.utcnow() - self.fetched_at).total_seconds()
        return elapsed > self.ttl_seconds
    
    @property
    def crawl_delay(self) -> Optional[float]:
        """Retorna crawl-delay do robots.txt se definido."""
        # RobotFileParser não expõe crawl_delay diretamente
        # Precisamos parsear manualmente
        for line in self.content.split('\n'):
            line = line.strip().lower()
            if 'crawl-delay' in line:
                parts = line.split(':', 1)
                if len(parts) == 2:
                    try:
                        return float(parts[1].strip())
                    except ValueError:
                        pass
        return None


@dataclass
class RateLimitState:
    """Estado de rate limiting para um domínio.
    
    Implementa token bucket para controle de frequência.
    
    Attributes:
        domain: Domínio controlado
        min_delay_seconds: Delay mínimo entre requests
        last_request_time: Timestamp da última request
        request_count: Contador de requests no período
        window_start: Início da janela atual
        tokens: Tokens disponíveis (token bucket)
    """
    domain: str
    min_delay_seconds: float = 1.0
    last_request_time: Optional[datetime] = None
    request_count: int = 0
    window_start: datetime = field(default_factory=datetime.utcnow)
    tokens: float = 1.0  # Token bucket
    
    # Configuração do bucket
    bucket_capacity: float = 1.0
    tokens_per_second: float = 1.0
    
    async def acquire(self) -> None:
        """Adquire permissão para fazer request.
        
        Aguarda se necessário para respeitar:
        1. Delay mínimo desde última request
        2. Taxa de requests por segundo (token bucket)
        """
        now = datetime.utcnow()
        
        # Recupera tokens baseado no tempo decorrido
        if self.last_request_time:
            elapsed = (now - self.last_request_time).total_seconds()
            self.tokens = min(
                self.bucket_capacity,
                self.tokens + (elapsed * self.tokens_per_second)
            )
        
        # Verifica se precisa esperar
        if self.tokens < 1.0:
            # Calcula tempo para ter token suficiente
            tokens_needed = 1.0 - self.tokens
            wait_time = tokens_needed / self.tokens_per_second
            
            # Também respeita delay mínimo
            if self.last_request_time:
                elapsed = (now - self.last_request_time).total_seconds()
                min_delay_wait = max(0, self.min_delay_seconds - elapsed)
                wait_time = max(wait_time, min_delay_wait)
            
            if wait_time > 0:
                logger.debug(f"Rate limit: aguardando {wait_time:.2f}s para {self.domain}")
                await asyncio.sleep(wait_time)
                
            # Recalcula tokens após espera
            elapsed = (datetime.utcnow() - self.last_request_time).total_seconds() if self.last_request_time else 0
            self.tokens = min(
                self.bucket_capacity,
                self.tokens + (elapsed * self.tokens_per_second)
            )
        
        # Consome token
        self.tokens -= 1.0
        self.last_request_time = datetime.utcnow()
        self.request_count += 1
    
    def record_success(self, response_time_ms: float) -> None:
        """Registra request bem-sucedida.
        
        Ajusta dinamicamente o rate limit baseado
        no tempo de resposta do servidor.
        
        Args:
            response_time_ms: Tempo de resposta em ms
        """
        # Se servidor está lento, aumenta delay
        if response_time_ms > 5000:  # 5 segundos
            self.min_delay_seconds = min(self.min_delay_seconds * 1.2, 10.0)
            logger.debug(f"Servidor lento, aumentando delay para {self.min_delay_seconds:.2f}s")
        # Se servidor está rápido, pode diminuir delay levemente
        elif response_time_ms < 500 and self.min_delay_seconds > 0.5:
            self.min_delay_seconds = max(self.min_delay_seconds * 0.95, 0.5)


@dataclass
class DomainPoliteness:
    """Configuração de politeness para um domínio.
    
    Attributes:
        domain: Domínio
        robots_cache: Cache do robots.txt
        rate_limit: Estado do rate limiter
        user_agents_allowed: User agents permitidos
        disallowed_paths: Paths bloqueados
        sitemap_urls: URLs de sitemap
    """
    domain: str
    robots_cache: Optional[RobotsTxtCache] = None
    rate_limit: RateLimitState = field(init=False)
    user_agents_allowed: Set[str] = field(default_factory=set)
    disallowed_paths: List[str] = field(default_factory=list)
    sitemap_urls: List[str] = field(default_factory=list)
    
    def __post_init__(self):
        self.rate_limit = RateLimitState(
            domain=self.domain,
            min_delay_seconds=settings.crawler_delay_seconds
        )
    
    def is_allowed(self, url: str, user_agent: str) -> bool:
        """Verifica se URL é permitida para o user agent.
        
        Args:
            url: URL a verificar
            user_agent: User agent string
            
        Returns:
            True se permitido
        """
        # Verifica robots.txt primeiro
        if self.robots_cache and self.robots_cache.parsed:
            if not self.robots_cache.parsed.can_fetch(user_agent, url):
                return False
        
        # Verifica paths bloqueados
        parsed = urlparse(url)
        path = parsed.path
        for disallowed in self.disallowed_paths:
            if path.startswith(disallowed):
                return False
        
        return True
    
    def get_crawl_delay(self) -> float:
        """Retorna crawl-delay em segundos."""
        if self.robots_cache:
            delay = self.robots_cache.crawl_delay
            if delay is not None:
                return delay
        return settings.crawler_delay_seconds


class PolitenessManager:
    """Gerenciador de politeness para crawling.
    
    Centraliza controle de:
    - robots.txt fetching e caching
    - Rate limiting por domínio
    - Respeito a diretrizes de crawling
    
    Attributes:
        respect_robots: Se deve respeitar robots.txt
        default_delay: Delay padrão entre requests
        robots_cache_ttl: TTL do cache de robots.txt
        max_robots_size: Tamanho máximo de robots.txt em bytes
    """
    
    def __init__(
        self,
        respect_robots: bool = True,
        default_delay: Optional[float] = None,
        robots_cache_ttl: int = 3600,
        max_robots_size: int = 1024 * 1024,  # 1MB
        http_client: Optional[httpx.AsyncClient] = None,
    ):
        self.respect_robots = respect_robots
        self.default_delay = default_delay or settings.crawler_delay_seconds
        self.robots_cache_ttl = robots_cache_ttl
        self.max_robots_size = max_robots_size
        
        self._http_client = http_client
        self._domains: Dict[str, DomainPoliteness] = {}
        self._robots_cache: Dict[str, RobotsTxtCache] = {}
        self._semaphore = asyncio.Semaphore(5)  # Limita requests simultâneos
        
        logger.info(f"PolitenessManager iniciado (respect_robots={respect_robots})")
    
    def _get_domain(self, url: str) -> str:
        """Extrai domínio de URL."""
        parsed = urlparse(url)
        return parsed.netloc.lower()
    
    def _get_robots_url(self, url: str) -> str:
        """Constrói URL do robots.txt."""
        parsed = urlparse(url)
        return f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    
    async def _get_http_client(self) -> httpx.AsyncClient:
        """Obtém ou cria cliente HTTP."""
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(
                timeout=30.0,
                follow_redirects=True,
                headers={
                    "User-Agent": "GABI-Bot/1.0 (+https://gabi.tcu.gov.br/bot)"
                }
            )
        return self._http_client
    
    async def fetch_robots_txt(
        self,
        url: str,
        force_refresh: bool = False
    ) -> Optional[RobotsTxtCache]:
        """Busca e cacheia robots.txt.
        
        Args:
            url: URL qualquer do domínio
            force_refresh: Força re-fetch mesmo se cache válido
            
        Returns:
            Cache do robots.txt ou None se não encontrado
        """
        if not self.respect_robots:
            return None
        
        robots_url = self._get_robots_url(url)
        domain = self._get_domain(url)
        
        # Verifica cache
        if not force_refresh and robots_url in self._robots_cache:
            cache = self._robots_cache[robots_url]
            if not cache.is_expired:
                logger.debug(f"robots.txt cache hit para {domain}")
                return cache
        
        # Fetch robots.txt
        async with self._semaphore:
            try:
                client = await self._get_http_client()
                response = await client.get(robots_url)
                
                if response.status_code == 200:
                    content = response.text
                    
                    # Limita tamanho
                    if len(content.encode('utf-8')) > self.max_robots_size:
                        logger.warning(f"robots.txt muito grande para {domain}, truncando")
                        content = content[:self.max_robots_size]
                    
                    # Parseia
                    rp = RobotFileParser()
                    rp.parse(content.split('\n'))
                    
                    cache = RobotsTxtCache(
                        url=robots_url,
                        content=content,
                        parsed=rp,
                        fetched_at=datetime.utcnow(),
                        ttl_seconds=self.robots_cache_ttl,
                        status_code=200
                    )
                    
                    self._robots_cache[robots_url] = cache
                    logger.info(f"robots.txt carregado para {domain}")
                    return cache
                    
                elif response.status_code == 404:
                    # Sem robots.txt = permite tudo
                    logger.debug(f"robots.txt não encontrado para {domain}")
                    cache = RobotsTxtCache(
                        url=robots_url,
                        content="",
                        parsed=RobotFileParser(),
                        fetched_at=datetime.utcnow(),
                        status_code=404
                    )
                    self._robots_cache[robots_url] = cache
                    return cache
                    
                else:
                    logger.warning(f"robots.txt retornou {response.status_code} para {domain}")
                    return None
                    
            except Exception as e:
                logger.error(f"Erro ao fetch robots.txt para {domain}: {e}")
                return None
    
    async def can_fetch(
        self,
        url: str,
        user_agent: str = "*"
    ) -> bool:
        """Verifica se pode fazer fetch de URL.
        
        Args:
            url: URL a verificar
            user_agent: User agent string
            
        Returns:
            True se fetch é permitido
        """
        if not self.respect_robots:
            return True
        
        robots_cache = await self.fetch_robots_txt(url)
        if robots_cache is None:
            # Sem info de robots = permite
            return True
        
        if robots_cache.status_code == 404:
            return True
        
        return robots_cache.parsed.can_fetch(user_agent, url)
    
    async def get_crawl_delay(self, url: str) -> float:
        """Retorna crawl-delay para o domínio.
        
        Args:
            url: URL do domínio
            
        Returns:
            Delay em segundos
        """
        robots_cache = await self.fetch_robots_txt(url)
        if robots_cache:
            delay = robots_cache.crawl_delay
            if delay is not None:
                return delay
        return self.default_delay
    
    async def acquire_slot(self, url: str) -> None:
        """Adquire slot de rate limiting para URL.
        
        Aguarda se necessário para respeitar politeness.
        
        Args:
            url: URL a ser requisitada
        """
        domain = self._get_domain(url)
        
        # Obtém ou cria estado do domínio
        if domain not in self._domains:
            self._domains[domain] = DomainPoliteness(domain=domain)
            
            # Busca delay do robots.txt
            delay = await self.get_crawl_delay(url)
            self._domains[domain].rate_limit.min_delay_seconds = delay
        
        domain_state = self._domains[domain]
        
        # Atualiza delay se mudou no robots.txt
        robots_cache = await self.fetch_robots_txt(url)
        if robots_cache and robots_cache.crawl_delay:
            domain_state.rate_limit.min_delay_seconds = robots_cache.crawl_delay
        
        # Adquire slot
        await domain_state.rate_limit.acquire()
    
    def record_response(self, url: str, response_time_ms: float, success: bool) -> None:
        """Registra resposta para ajuste dinâmico.
        
        Args:
            url: URL requisitada
            response_time_ms: Tempo de resposta em ms
            success: Se request foi bem-sucedida
        """
        domain = self._get_domain(url)
        if domain in self._domains:
            self._domains[domain].rate_limit.record_success(response_time_ms)
    
    def get_sitemaps(self, url: str) -> List[str]:
        """Retorna sitemaps listados no robots.txt.
        
        Args:
            url: URL do domínio
            
        Returns:
            Lista de URLs de sitemap
        """
        robots_url = self._get_robots_url(url)
        if robots_url in self._robots_cache:
            cache = self._robots_cache[robots_url]
            if cache.status_code == 200:
                # Parse sitemap entries
                sitemaps = []
                for line in cache.content.split('\n'):
                    line = line.strip().lower()
                    if line.startswith('sitemap:'):
                        parts = line.split(':', 1)
                        if len(parts) == 2:
                            sitemaps.append(parts[1].strip())
                return sitemaps
        return []
    
    def get_stats(self) -> Dict[str, Any]:
        """Retorna estatísticas do manager.
        
        Returns:
            Dicionário com estatísticas
        """
        total_requests = sum(
            d.rate_limit.request_count 
            for d in self._domains.values()
        )
        
        domain_stats = {}
        for domain, state in self._domains.items():
            domain_stats[domain] = {
                "requests": state.rate_limit.request_count,
                "current_delay": state.rate_limit.min_delay_seconds,
                "has_robots": state.robots_cache is not None
            }
        
        return {
            "domains_count": len(self._domains),
            "robots_cached": len(self._robots_cache),
            "total_requests": total_requests,
            "domains": domain_stats
        }
    
    async def close(self) -> None:
        """Fecha recursos do manager."""
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None
        
        self._domains.clear()
        self._robots_cache.clear()
        logger.info("PolitenessManager fechado")


class AdaptiveRateLimiter:
    """Rate limiter adaptativo baseado em feedback.
    
    Ajusta taxa de requests baseado em:
    - Taxa de erro do servidor (5xx)
    - Tempo de resposta
    - Rejeições (429 Too Many Requests)
    
    Attributes:
        initial_rate: Taxa inicial (requests/segundo)
        min_rate: Taxa mínima
        max_rate: Taxa máxima
        adaptation_factor: Fator de adaptação
    """
    
    def __init__(
        self,
        initial_rate: float = 1.0,
        min_rate: float = 0.1,
        max_rate: float = 10.0,
        adaptation_factor: float = 0.5,
    ):
        self.current_rate = initial_rate
        self.min_rate = min_rate
        self.max_rate = max_rate
        self.adaptation_factor = adaptation_factor
        
        self._last_adjustment = time.time()
        self._error_count = 0
        self._success_count = 0
        self._lock = asyncio.Lock()
    
    async def record_success(self, response_time_ms: float) -> None:
        """Registra request bem-sucedida.
        
        Args:
            response_time_ms: Tempo de resposta
        """
        async with self._lock:
            self._success_count += 1
            
            # Se resposta rápida e sucessos consecutivos, aumenta taxa
            if response_time_ms < 1000 and self._success_count >= 5:
                self.current_rate = min(
                    self.max_rate,
                    self.current_rate * (1 + self.adaptation_factor)
                )
                self._success_count = 0
                logger.debug(f"Rate aumentado para {self.current_rate:.2f} req/s")
    
    async def record_error(self, status_code: int) -> None:
        """Registra erro.
        
        Args:
            status_code: Código HTTP de erro
        """
        async with self._lock:
            self._error_count += 1
            self._success_count = 0
            
            # 429 Too Many Requests -> reduz drasticamente
            if status_code == 429:
                self.current_rate = max(
                    self.min_rate,
                    self.current_rate * 0.5
                )
                logger.warning(f"Rate limit hit (429), reduzindo para {self.current_rate:.2f} req/s")
            
            # 5xx errors -> reduz gradualmente
            elif 500 <= status_code < 600:
                self.current_rate = max(
                    self.min_rate,
                    self.current_rate * (1 - self.adaptation_factor)
                )
                logger.debug(f"Server error ({status_code}), rate reduzido para {self.current_rate:.2f} req/s")
    
    async def get_delay(self) -> float:
        """Retorna delay atual em segundos."""
        async with self._lock:
            return 1.0 / self.current_rate


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    "RobotsTxtCache",
    "RateLimitState",
    "DomainPoliteness",
    "PolitenessManager",
    "AdaptiveRateLimiter",
]
