"""Serviço de discovery para descoberta de URLs de fontes de dados.

Este módulo implementa as estratégias de discovery definidas em sources.yaml:
- url_pattern: Gera URLs a partir de templates com parâmetros
- static_url: URL única fixa
- crawler: Navegação em páginas web
- api_query: Consultas a APIs

Baseado em GABI_SPECS_FINAL_v1.md §2.1.1.
"""

from __future__ import annotations

import asyncio
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Protocol
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from gabi.pipeline.contracts import DiscoveredURL, DiscoveryResult
from gabi.types import SourceType

logger = logging.getLogger(__name__)


# =============================================================================
# Configuration Classes
# =============================================================================

@dataclass
class URLPatternConfig:
    """Configuração para modo url_pattern.
    
    Attributes:
        url_template: Template de URL com placeholders {param}
        params: Parâmetros para gerar URLs (start, end, etc.)
        change_detection: Estratégia de detecção de mudanças
    """
    url_template: str
    params: Dict[str, Any] = field(default_factory=dict)
    change_detection: Optional[Dict[str, str]] = None


@dataclass
class StaticURLConfig:
    """Configuração para modo static_url.
    
    Attributes:
        url: URL fixa única
        change_detection: Estratégia de detecção de mudanças
    """
    url: str
    change_detection: Optional[Dict[str, str]] = None


@dataclass
class CrawlerConfig:
    """Configuração para modo crawler.
    
    Attributes:
        root_url: URL inicial para crawling
        rules: Regras de navegação (selectors, depth, etc.)
        rate_limit: Intervalo mínimo entre requests (segundos)
    """
    root_url: str
    rules: Dict[str, Any] = field(default_factory=dict)
    rate_limit: float = 1.0


@dataclass
class APIQueryConfig:
    """Configuração para modo api_query.
    
    Attributes:
        driver: Driver específico da API
        params: Parâmetros para consulta
        pagination: Configuração de paginação
    """
    driver: str
    params: Dict[str, Any] = field(default_factory=dict)
    pagination: Optional[Dict[str, Any]] = None


# =============================================================================
# Rate Limiter
# =============================================================================

class RateLimiter:
    """Rate limiter simples baseado em token bucket.
    
    Controla a taxa de requisições para respeitar limites
    impostos pelas fontes de dados.
    
    Attributes:
        rate: Requisições permitidas por segundo
        burst: Máximo de requisições em burst
    """
    
    def __init__(self, rate: float = 1.0, burst: int = 1):
        """Inicializa o rate limiter.
        
        Args:
            rate: Requisições por segundo
            burst: Máximo de requisições simultâneas permitidas
        """
        self.rate = rate
        self.burst = burst
        self._tokens = float(burst)
        self._last_update = time.monotonic()
        self._lock = asyncio.Lock()
    
    async def acquire(self) -> None:
        """Adquire permissão para fazer uma requisição.
        
        Bloqueia até que um token esteja disponível.
        """
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_update
            self._tokens = min(self.burst, self._tokens + elapsed * self.rate)
            self._last_update = now
            
            if self._tokens < 1:
                wait_time = (1 - self._tokens) / self.rate
                await asyncio.sleep(wait_time)
                self._tokens = 0
                self._last_update = time.monotonic()
            else:
                self._tokens -= 1


# =============================================================================
# Discovery Strategies
# =============================================================================

class DiscoveryStrategy(ABC):
    """Interface base para estratégias de discovery.
    
    Todas as estratégias de discovery devem implementar esta interface.
    """
    
    def __init__(
        self,
        source_id: str,
        http_client: Optional[httpx.AsyncClient] = None,
        rate_limiter: Optional[RateLimiter] = None,
    ):
        """Inicializa a estratégia.
        
        Args:
            source_id: ID da fonte de dados
            http_client: Cliente HTTP opcional
            rate_limiter: Rate limiter opcional
        """
        self.source_id = source_id
        self._client = http_client
        self._rate_limiter = rate_limiter or RateLimiter(rate=1.0)
        self._own_client = http_client is None
    
    async def _get_client(self) -> httpx.AsyncClient:
        """Obtém ou cria cliente HTTP.
        
        Returns:
            Cliente HTTP ativo
        """
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(30.0),
                headers={"User-Agent": "GABI-Bot/1.0 (TCU Discovery Service)"},
            )
        return self._client
    
    @abstractmethod
    async def discover(self) -> DiscoveryResult:
        """Executa a descoberta de URLs.
        
        Returns:
            Resultado da descoberta
        """
        pass
    
    async def close(self) -> None:
        """Fecha recursos da estratégia."""
        if self._own_client and self._client and not self._client.is_closed:
            await self._client.aclose()
    
    async def __aenter__(self) -> DiscoveryStrategy:
        """Context manager entry."""
        return self
    
    async def __aexit__(self, *args: Any) -> None:
        """Context manager exit."""
        await self.close()


class URLPatternDiscovery(DiscoveryStrategy):
    """Discovery baseado em padrão de URL com parâmetros.
    
    Gera URLs a partir de um template substituindo parâmetros
    por valores gerados (ex: anos de 1992 a current).
    
    Example:
        >>> config = URLPatternConfig(
        ...     url_template="https://example.com/data/{year}.csv",
        ...     params={"year": {"start": 2020, "end": 2024}}
        ... )
        >>> strategy = URLPatternDiscovery("source_id", config)
        >>> result = await strategy.discover()
    """
    
    def __init__(
        self,
        source_id: str,
        config: URLPatternConfig,
        http_client: Optional[httpx.AsyncClient] = None,
        rate_limiter: Optional[RateLimiter] = None,
    ):
        """Inicializa a estratégia url_pattern.
        
        Args:
            source_id: ID da fonte
            config: Configuração do padrão de URL
            http_client: Cliente HTTP opcional
            rate_limiter: Rate limiter opcional
        """
        super().__init__(source_id, http_client, rate_limiter)
        self.config = config
    
    def _generate_urls(self) -> List[str]:
        """Gera URLs a partir do template e parâmetros.
        
        Returns:
            Lista de URLs geradas
        """
        urls = []
        
        # Gera combinações de parâmetros
        param_values = {}
        for param_name, param_config in self.config.params.items():
            if isinstance(param_config, dict):
                start = param_config.get("start", 0)
                end = param_config.get("end", start)
                
                # Handle "current" keyword
                if end == "current":
                    end = datetime.now().year
                
                param_values[param_name] = list(range(start, end + 1))
            else:
                param_values[param_name] = [param_config]
        
        # Gera URLs para cada combinação
        if not param_values:
            return [self.config.url_template]
        
        # Para cada combinação de parâmetros
        import itertools
        keys = list(param_values.keys())
        values = [param_values[k] for k in keys]
        
        for combo in itertools.product(*values):
            url = self.config.url_template
            for key, value in zip(keys, combo):
                url = url.replace(f"{{{key}}}", str(value))
            urls.append(url)
        
        return urls
    
    async def discover(self) -> DiscoveryResult:
        """Descobre URLs usando o padrão configurado.
        
        Returns:
            DiscoveryResult com URLs geradas
        """
        start_time = time.monotonic()
        urls = self._generate_urls()
        
        discovered = [
            DiscoveredURL(
                url=url,
                source_id=self.source_id,
                metadata={"generated": True, "template": self.config.url_template},
                priority=0,
            )
            for url in urls
        ]
        
        duration = time.monotonic() - start_time
        
        logger.info(
            f"URLPatternDiscovery: Geradas {len(discovered)} URLs "
            f"para fonte {self.source_id} em {duration:.2f}s"
        )
        
        return DiscoveryResult(
            urls=discovered,
            total_found=len(discovered),
            filtered_out=0,
            duration_seconds=duration,
        )


class StaticURLDiscovery(DiscoveryStrategy):
    """Discovery para URL única estática.
    
    Retorna uma única URL fixa configurada.
    
    Example:
        >>> config = StaticURLConfig(url="https://example.com/data.csv")
        >>> strategy = StaticURLDiscovery("source_id", config)
        >>> result = await strategy.discover()
    """
    
    def __init__(
        self,
        source_id: str,
        config: StaticURLConfig,
        http_client: Optional[httpx.AsyncClient] = None,
        rate_limiter: Optional[RateLimiter] = None,
    ):
        """Inicializa a estratégia static_url.
        
        Args:
            source_id: ID da fonte
            config: Configuração da URL estática
            http_client: Cliente HTTP opcional
            rate_limiter: Rate limiter opcional
        """
        super().__init__(source_id, http_client, rate_limiter)
        self.config = config
    
    async def discover(self) -> DiscoveryResult:
        """Retorna a URL estática configurada.
        
        Returns:
            DiscoveryResult com a URL única
        """
        start_time = time.monotonic()
        
        discovered = [
            DiscoveredURL(
                url=self.config.url,
                source_id=self.source_id,
                metadata={"static": True},
                priority=0,
            )
        ]
        
        duration = time.monotonic() - start_time
        
        logger.info(
            f"StaticURLDiscovery: URL estática descoberta para "
            f"fonte {self.source_id}"
        )
        
        return DiscoveryResult(
            urls=discovered,
            total_found=1,
            filtered_out=0,
            duration_seconds=duration,
        )


class CrawlerDiscovery(DiscoveryStrategy):
    """Discovery via crawling de páginas web.
    
    Navega recursivamente em páginas seguindo regras configuradas
    para encontrar links para documentos.
    
    Example:
        >>> config = CrawlerConfig(
        ...     root_url="https://example.com/docs",
        ...     rules={"max_depth": 2, "asset_selector": "a[href$='.pdf']"}
        ... )
        >>> strategy = CrawlerDiscovery("source_id", config)
        >>> result = await strategy.discover()
    """
    
    def __init__(
        self,
        source_id: str,
        config: CrawlerConfig,
        http_client: Optional[httpx.AsyncClient] = None,
        rate_limiter: Optional[RateLimiter] = None,
    ):
        """Inicializa a estratégia crawler.
        
        Args:
            source_id: ID da fonte
            config: Configuração do crawler
            http_client: Cliente HTTP opcional
            rate_limiter: Rate limiter opcional (padrão: 1 req/s)
        """
        super().__init__(source_id, http_client, rate_limiter)
        self.config = config
        self._visited: set[str] = set()
        self._discovered: list[DiscoveredURL] = []
    
    async def _fetch_page(self, url: str) -> Optional[str]:
        """Faz fetch de uma página.
        
        Args:
            url: URL da página
            
        Returns:
            Conteúdo HTML ou None em caso de erro
        """
        await self._rate_limiter.acquire()
        
        try:
            client = await self._get_client()
            response = await client.get(url)
            if response.status_code == 200:
                return response.text
            logger.warning(f"Crawler: HTTP {response.status_code} para {url}")
            return None
        except Exception as e:
            logger.error(f"Crawler: Erro ao fetch {url}: {e}")
            return None
    
    def _extract_links(
        self,
        html: str,
        base_url: str,
        selector: Optional[str] = None,
    ) -> List[str]:
        """Extrai links de uma página HTML.
        
        Args:
            html: Conteúdo HTML
            base_url: URL base para resolver links relativos
            selector: Seletor CSS opcional para filtrar
            
        Returns:
            Lista de URLs absolutas
        """
        soup = BeautifulSoup(html, "html.parser")
        links = []
        
        if selector:
            elements = soup.select(selector)
        else:
            elements = soup.find_all("a", href=True)
        
        for elem in elements:
            href = elem.get("href") if hasattr(elem, "get") else elem["href"]
            if href:
                absolute = urljoin(base_url, href)
                # Normaliza URL
                parsed = urlparse(absolute)
                if parsed.scheme in ("http", "https"):
                    links.append(absolute)
        
        return links
    
    async def _crawl(
        self,
        url: str,
        depth: int = 0,
    ) -> None:
        """Executa crawling recursivo.
        
        Args:
            url: URL atual
            depth: Profundidade atual
        """
        max_depth = self.config.rules.get("max_depth", 2)
        
        if depth > max_depth or url in self._visited:
            return
        
        self._visited.add(url)
        
        html = await self._fetch_page(url)
        if not html:
            return
        
        # Extrai links de documentos (assets)
        asset_selector = self.config.rules.get("asset_selector", "a[href$='.pdf']")
        assets = self._extract_links(html, url, asset_selector)
        
        for asset_url in assets:
            if asset_url not in self._visited:
                self._discovered.append(
                    DiscoveredURL(
                        url=asset_url,
                        source_id=self.source_id,
                        metadata={"depth": depth, "crawled": True},
                        priority=max_depth - depth,  # Prioriza docs menos profundos
                    )
                )
        
        # Continua navegação se necessário
        link_selector = self.config.rules.get("link_selector")
        if depth < max_depth and link_selector:
            navigation_links = self._extract_links(html, url, link_selector)
            for link in navigation_links:
                if link not in self._visited:
                    await self._crawl(link, depth + 1)
    
    async def discover(self) -> DiscoveryResult:
        """Executa crawling a partir da URL raiz.
        
        Returns:
            DiscoveryResult com URLs descobertas
        """
        start_time = time.monotonic()
        
        await self._crawl(self.config.root_url, depth=0)
        
        duration = time.monotonic() - start_time
        
        logger.info(
            f"CrawlerDiscovery: {len(self._discovered)} URLs descobertas "
            f"em {duration:.2f}s"
        )
        
        return DiscoveryResult(
            urls=self._discovered,
            total_found=len(self._discovered),
            filtered_out=len(self._visited) - len(self._discovered),
            duration_seconds=duration,
        )


class APIQueryDiscovery(DiscoveryStrategy):
    """Discovery via queries a APIs.
    
    Implementa drivers específicos para APIs diferentes.
    
    Example:
        >>> config = APIQueryConfig(driver="camara_api_v1", params={"start_year": 2020})
        >>> strategy = APIQueryDiscovery("source_id", config)
        >>> result = await strategy.discover()
    """
    
    def __init__(
        self,
        source_id: str,
        config: APIQueryConfig,
        http_client: Optional[httpx.AsyncClient] = None,
        rate_limiter: Optional[RateLimiter] = None,
    ):
        """Inicializa a estratégia api_query.
        
        Args:
            source_id: ID da fonte
            config: Configuração da API
            http_client: Cliente HTTP opcional
            rate_limiter: Rate limiter opcional
        """
        super().__init__(source_id, http_client, rate_limiter)
        self.config = config
    
    async def discover(self) -> DiscoveryResult:
        """Executa discovery via API.
        
        Returns:
            DiscoveryResult com URLs/documentos da API
        """
        start_time = time.monotonic()
        
        # Delega para driver específico
        driver = self._get_driver()
        urls = await driver.discover()
        
        duration = time.monotonic() - start_time
        
        logger.info(
            f"APIQueryDiscovery: {len(urls)} itens encontrados via "
            f"driver {self.config.driver}"
        )
        
        return DiscoveryResult(
            urls=urls,
            total_found=len(urls),
            filtered_out=0,
            duration_seconds=duration,
        )
    
    def _get_driver(self) -> "APIDriver":
        """Obtém o driver específico configurado.
        
        Returns:
            Instância do driver
        """
        drivers: Dict[str, type[APIDriver]] = {
            "camara_api_v1": CamaraAPIDriver,
            # Adicionar mais drivers conforme necessário
        }
        
        driver_class = drivers.get(self.config.driver)
        if not driver_class:
            raise ValueError(f"Driver não suportado: {self.config.driver}")
        
        return driver_class(
            self.config.params,
            self._rate_limiter,
            source_id=self.source_id,
        )


class APIDriver(ABC):
    """Interface para drivers de API."""
    
    def __init__(
        self,
        params: Dict[str, Any],
        rate_limiter: RateLimiter,
    ):
        self.params = params
        self.rate_limiter = rate_limiter
    
    @abstractmethod
    async def discover(self) -> List[DiscoveredURL]:
        """Descobre URLs/documentos via API.
        
        Returns:
            Lista de URLs descobertas
        """
        pass


class CamaraAPIDriver(APIDriver):
    """Driver para API da Câmara dos Deputados.
    
    Descobre proposições (leis ordinárias) via API de Dados Abertos.
    Endpoint: https://dadosabertos.camara.leg.br/api/v2/proposicoes
    """
    
    BASE_URL = "https://dadosabertos.camara.leg.br/api/v2"
    
    def __init__(
        self,
        params: Dict[str, Any],
        rate_limiter: RateLimiter,
        source_id: str = "camara_leis_ordinarias",
    ):
        """Inicializa o driver da Câmara.
        
        Args:
            params: Parâmetros de consulta (start_year, end_year, siglas)
            rate_limiter: Rate limiter para controle de requisições
            source_id: ID da fonte de dados
        """
        super().__init__(params, rate_limiter)
        self.source_id = source_id
    
    async def discover(self) -> List[DiscoveredURL]:
        """Descobre proposições (leis ordinárias) da Câmara.
        
        Returns:
            Lista de URLs descobertas com metadados
        """
        discovered: List[DiscoveredURL] = []
        
        # Configuração dos parâmetros
        start_year = self.params.get("start_year", 2023)
        end_year = self.params.get("end_year", 2024)
        siglas = self.params.get("siglas", ["PL"])  # Projetos de Lei por padrão
        
        # Gera lista de anos
        anos = list(range(start_year, end_year + 1))
        
        async with httpx.AsyncClient() as client:
            for ano in anos:
                for sigla in siglas:
                    try:
                        url = f"{self.BASE_URL}/proposicoes"
                        response = await client.get(
                            url,
                            params={
                                "siglaTipo": sigla,
                                "ano": ano,
                                "itens": 100,
                                "ordem": "DESC",
                                "ordenarPor": "id"
                            },
                            timeout=30.0
                        )
                        response.raise_for_status()
                        
                        data = response.json()
                        proposicoes = data.get("dados", [])
                        
                        for prop in proposicoes:
                            prop_id = prop.get("id")
                            uri = prop.get("uri")
                            
                            if uri:
                                discovered.append(DiscoveredURL(
                                    url=uri,
                                    source_id=self.source_id,
                                    metadata={
                                        "id": prop_id,
                                        "siglaTipo": prop.get("siglaTipo"),
                                        "numero": prop.get("numero"),
                                        "ano": prop.get("ano"),
                                        "ementa": prop.get("ementa", "")[:200],
                                    },
                                    discovered_at=datetime.utcnow(),
                                ))
                        
                        logger.debug(f"CamaraAPIDriver: {sigla}/{ano} - {len(proposicoes)} proposições")
                        
                        # Rate limiting
                        await self.rate_limiter.acquire()
                        
                    except Exception as e:
                        logger.warning(f"Erro ao buscar {sigla}/{ano}: {e}")
                        continue
        
        logger.info(f"CamaraAPIDriver descobriu {len(discovered)} URLs")
        return discovered


# =============================================================================
# Factory
# =============================================================================

class DiscoveryService:
    """Serviço principal de discovery.
    
    Factory e orquestrador de estratégias de discovery.
    
    Example:
        >>> service = DiscoveryService()
        >>> config = {"mode": "static_url", "url": "https://example.com/data.csv"}
        >>> result = await service.discover("source_id", config)
    """
    
    def __init__(
        self,
        http_client: Optional[httpx.AsyncClient] = None,
        default_rate_limit: float = 1.0,
    ):
        """Inicializa o serviço de discovery.
        
        Args:
            http_client: Cliente HTTP compartilhado
            default_rate_limit: Rate limit padrão (req/s)
        """
        self._client = http_client
        self._default_rate_limit = default_rate_limit
    
    def create_strategy(
        self,
        source_id: str,
        config: Dict[str, Any],
    ) -> DiscoveryStrategy:
        """Cria estratégia apropriada baseada na configuração.
        
        Args:
            source_id: ID da fonte
            config: Configuração de discovery (mode, url, etc.)
            
        Returns:
            Estratégia de discovery configurada
            
        Raises:
            ValueError: Se modo não for suportado
        """
        mode = config.get("mode", "static_url")
        rate = config.get("rate_limit", self._default_rate_limit)
        rate_limiter = RateLimiter(rate=rate)
        
        if mode == "url_pattern":
            url_config = URLPatternConfig(
                url_template=config["url_template"],
                params=config.get("params", {}),
                change_detection=config.get("change_detection"),
            )
            return URLPatternDiscovery(
                source_id, url_config, self._client, rate_limiter
            )
        
        elif mode == "static_url":
            static_config = StaticURLConfig(
                url=config["url"],
                change_detection=config.get("change_detection"),
            )
            return StaticURLDiscovery(
                source_id, static_config, self._client, rate_limiter
            )
        
        elif mode == "crawler":
            crawler_config = CrawlerConfig(
                root_url=config["root_url"],
                rules=config.get("rules", {}),
                rate_limit=rate,
            )
            return CrawlerDiscovery(
                source_id, crawler_config, self._client, rate_limiter
            )
        
        elif mode == "api_query":
            api_config = APIQueryConfig(
                driver=config["driver"],
                params=config.get("params", {}),
                pagination=config.get("pagination"),
            )
            return APIQueryDiscovery(
                source_id, api_config, self._client, rate_limiter
            )
        
        else:
            raise ValueError(f"Modo de discovery não suportado: {mode}")
    
    async def discover(
        self,
        source_id: str,
        config: Dict[str, Any],
    ) -> DiscoveryResult:
        """Executa discovery para uma fonte.
        
        Args:
            source_id: ID da fonte
            config: Configuração de discovery
            
        Returns:
            Resultado da descoberta
        """
        strategy = self.create_strategy(source_id, config)
        async with strategy:
            return await strategy.discover()


# =============================================================================
# Helper Functions
# =============================================================================

async def discover_source(
    source_id: str,
    config: Dict[str, Any],
    http_client: Optional[httpx.AsyncClient] = None,
) -> DiscoveryResult:
    """Função utilitária para executar discovery.
    
    Args:
        source_id: ID da fonte
        config: Configuração de discovery
        http_client: Cliente HTTP opcional
        
    Returns:
        Resultado da descoberta
    """
    service = DiscoveryService(http_client)
    return await service.discover(source_id, config)
