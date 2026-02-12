"""Navegador baseado em Playwright.

Gerencia navegação de páginas, extração de links e
respeito a robots.txt.
Baseado em CRAWLER.md §3.2.
"""

import asyncio
import hashlib
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Set
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

from playwright.async_api import Browser, BrowserContext, Page, async_playwright

from gabi.config import settings
from gabi.pipeline.contracts import FetchMetadata

from .base_agent import BaseCrawlerAgent, CrawlResult


@dataclass
class RobotsCache:
    """Cache de robots.txt.
    
    Attributes:
        content: Conteúdo do robots.txt
        fetched_at: Timestamp de fetch
        ttl_seconds: Tempo de vida do cache
    """
    content: str
    fetched_at: datetime
    ttl_seconds: int = 3600  # 1 hora
    
    @property
    def is_expired(self) -> bool:
        """Verifica se cache expirou."""
        elapsed = (datetime.utcnow() - self.fetched_at).total_seconds()
        return elapsed > self.ttl_seconds


@dataclass
class RateLimiter:
    """Rate limiter por domínio.
    
    Implementa token bucket para controlar
    frequência de requests.
    
    Attributes:
        domain: Domínio controlado
        min_delay_seconds: Delay mínimo entre requests
        last_request_time: Timestamp da última request
    """
    domain: str
    min_delay_seconds: float = 1.0
    last_request_time: Optional[datetime] = None
    
    async def acquire(self) -> None:
        """Adquire permissão para fazer request.
        
        Aguarda se necessário para respeitar
        o rate limit configurado.
        """
        if self.last_request_time is not None:
            elapsed = (datetime.utcnow() - self.last_request_time).total_seconds()
            if elapsed < self.min_delay_seconds:
                wait_time = self.min_delay_seconds - elapsed
                await asyncio.sleep(wait_time)
        
        self.last_request_time = datetime.utcnow()


class Navigator:
    """Navegador Playwright com políteness.
    
    Gerencia instância do Playwright, respeita
    robots.txt e implementa rate limiting.
    
    Attributes:
        headless: Modo headless
        timeout_seconds: Timeout de navegação
        respect_robots: Se deve respeitar robots.txt
        user_agent: User-Agent string
    """
    
    def __init__(
        self,
        headless: bool = True,
        timeout_seconds: Optional[int] = None,
        respect_robots: bool = True,
        user_agent: Optional[str] = None,
    ):
        self.headless = headless
        self.timeout_seconds = timeout_seconds or settings.crawler_timeout_seconds
        self.respect_robots = respect_robots
        self.user_agent = user_agent or self._default_user_agent()
        
        self._playwright: Optional[Any] = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._robots_cache: Dict[str, RobotsCache] = {}
        self._rate_limiters: Dict[str, RateLimiter] = {}
        
    def _default_user_agent(self) -> str:
        """Retorna User-Agent padrão."""
        return (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.0 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.0 "
            "GABI-Bot/1.0 (+https://gabi.tcu.gov.br/bot)"
        )
    
    async def initialize(self) -> None:
        """Inicializa o navegador."""
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=self.headless,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
            ]
        )
        self._context = await self._browser.new_context(
            user_agent=self.user_agent,
            viewport={"width": 1920, "height": 1080},
            accept_downloads=False,
        )
        
        # Bloqueia recursos desnecessários
        await self._context.route(
            "**/*.{png,jpg,jpeg,gif,svg,css,woff,woff2,ttf,otf}",
            lambda route: route.abort()
        )
    
    async def shutdown(self) -> None:
        """Encerra o navegador."""
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
    
    async def fetch_robots_txt(self, base_url: str) -> Optional[RobotFileParser]:
        """Busca e parseia robots.txt.
        
        Args:
            base_url: URL base para construir path do robots.txt
            
        Returns:
            Parser do robots.txt ou None
        """
        if not self.respect_robots:
            return None
        
        parsed = urlparse(base_url)
        robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
        
        # Verifica cache
        cache = self._robots_cache.get(parsed.netloc)
        if cache and not cache.is_expired:
            rp = RobotFileParser()
            rp.parse(cache.content.split('\n'))
            return rp
        
        try:
            page = await self._context.new_page()
            response = await page.goto(
                robots_url,
                timeout=self.timeout_seconds * 1000,
                wait_until="networkidle"
            )
            
            if response and response.status == 200:
                content = await page.content()
                # Extrai texto do body
                text = await page.evaluate("() => document.body.innerText")
                
                # Salva no cache
                self._robots_cache[parsed.netloc] = RobotsCache(
                    content=text,
                    fetched_at=datetime.utcnow()
                )
                
                # Parseia
                rp = RobotFileParser()
                rp.parse(text.split('\n'))
                return rp
                
        except Exception:
            pass
        finally:
            await page.close()
        
        return None
    
    def can_fetch(self, url: str, robots_parser: Optional[RobotFileParser]) -> bool:
        """Verifica se pode fazer fetch de URL.
        
        Args:
            url: URL a verificar
            robots_parser: Parser do robots.txt
            
        Returns:
            True se fetch é permitido
        """
        if not self.respect_robots or robots_parser is None:
            return True
        
        return robots_parser.can_fetch(self.user_agent, url)
    
    def _get_rate_limiter(self, domain: str) -> RateLimiter:
        """Obtém ou cria rate limiter para domínio."""
        if domain not in self._rate_limiters:
            self._rate_limiters[domain] = RateLimiter(
                domain=domain,
                min_delay_seconds=settings.crawler_delay_seconds
            )
        return self._rate_limiters[domain]
    
    async def navigate(
        self,
        url: str,
        wait_for: Optional[str] = None,
        wait_until: str = "networkidle"
    ) -> CrawlResult:
        """Navega para uma URL.
        
        Args:
            url: URL para navegar
            wait_for: Seletor CSS para aguardar
            wait_until: Condição de espera
            
        Returns:
            Resultado da navegação
        """
        start_time = time.time()
        parsed = urlparse(url)
        
        # Rate limiting
        rate_limiter = self._get_rate_limiter(parsed.netloc)
        await rate_limiter.acquire()
        
        # Verifica robots.txt
        robots_parser = await self.fetch_robots_txt(url)
        if not self.can_fetch(url, robots_parser):
            duration_ms = int((time.time() - start_time) * 1000)
            return CrawlResult(
                url=url,
                success=False,
                error="URL bloqueada por robots.txt",
                duration_ms=duration_ms
            )
        
        page: Optional[Page] = None
        try:
            page = await self._context.new_page()
            
            # Navega
            response = await page.goto(
                url,
                timeout=self.timeout_seconds * 1000,
                wait_until=wait_until
            )
            
            if wait_for:
                await page.wait_for_selector(wait_for, timeout=5000)
            
            # Extrai metadados
            status_code = response.status if response else 0
            headers = dict(response.headers) if response else {}
            content_type = headers.get("content-type", "")
            
            # Extrai conteúdo
            content = await page.content()
            content_bytes = content.encode('utf-8')
            
            # Calcula hash
            content_hash = hashlib.sha256(content_bytes).hexdigest()
            
            duration_ms = int((time.time() - start_time) * 1000)
            
            metadata = FetchMetadata(
                url=url,
                method="GET",
                status_code=status_code,
                content_type=content_type,
                content_length=len(content_bytes),
                headers=headers,
                fetch_duration_ms=duration_ms
            )
            
            from gabi.pipeline.contracts import FetchedContent
            fetched = FetchedContent(
                url=url,
                content=content_bytes,
                metadata=metadata,
                fingerprint=content_hash
            )
            
            return CrawlResult(
                url=url,
                success=200 <= status_code < 300,
                content=fetched,
                metadata=metadata,
                duration_ms=duration_ms
            )
            
        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            return CrawlResult(
                url=url,
                success=False,
                error=str(e),
                duration_ms=duration_ms
            )
        finally:
            if page:
                await page.close()
    
    async def extract_links(self, page: Page) -> List[str]:
        """Extrai links de uma página.
        
        Args:
            page: Página do Playwright
            
        Returns:
            Lista de URLs absolutas
        """
        links = await page.eval_on_selector_all(
            "a[href]",
            "elements => elements.map(e => e.href)"
        )
        return [link for link in links if link.startswith("http")]
    
    async def get_page(self) -> Page:
        """Obtém nova página do contexto.
        
        Returns:
            Nova página
        """
        return await self._context.new_page()


class PlaywrightCrawlerAgent(BaseCrawlerAgent):
    """Agente crawler usando Playwright.
    
    Implementação concreta do BaseCrawlerAgent
    usando Playwright para navegação.
    """
    
    def __init__(self, *args, headless: bool = True, **kwargs):
        super().__init__(*args, **kwargs)
        self.headless = headless
        self._navigator: Optional[Navigator] = None
    
    async def initialize(self) -> None:
        """Inicializa navigator."""
        self._navigator = Navigator(
            headless=self.headless,
            respect_robots=self.respect_robots
        )
        await self._navigator.initialize()
        self.stats.start_time = datetime.utcnow()
    
    async def shutdown(self) -> None:
        """Encerra navigator."""
        if self._navigator:
            await self._navigator.shutdown()
        self.stats.end_time = datetime.utcnow()
    
    async def crawl(self, url: str, depth: int = 0) -> CrawlResult:
        """Executa crawl em URL.
        
        Args:
            url: URL para crawlear
            depth: Profundidade atual
            
        Returns:
            Resultado do crawl
        """
        if not self._navigator:
            raise RuntimeError("Agente não inicializado. Chame initialize() primeiro.")
        
        if not self.should_continue(depth):
            return CrawlResult(
                url=url,
                success=False,
                error="Limite de páginas ou profundidade atingido"
            )
        
        self.stats.urls_crawled += 1
        
        result = await self._navigator.navigate(url)
        
        if result.success:
            self.stats.urls_success += 1
            self.stats.bytes_downloaded += result.metadata.content_length or 0
            
            # Extrai links se dentro do limite de profundidade
            if depth < self.max_depth:
                page = await self._navigator.get_page()
                try:
                    await page.goto(url, timeout=10000, wait_until="domcontentloaded")
                    links = await self.extract_links(page)
                    result.links = self.filter_links(links, url)
                    self.stats.links_extracted += len(result.links)
                finally:
                    await page.close()
        else:
            self.stats.urls_failed += 1
        
        self.mark_crawled(url)
        return result
    
    async def extract_links(self, page: Page) -> List[str]:
        """Extrai links da página.
        
        Args:
            page: Página do Playwright
            
        Returns:
            Lista de URLs
        """
        if not self._navigator:
            raise RuntimeError("Agente não inicializado.")
        
        return await self._navigator.extract_links(page)
