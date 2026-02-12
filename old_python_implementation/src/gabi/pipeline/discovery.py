"""Engine de descoberta de URLs.

Implementa três modos de discovery:
1. url_pattern: Padrão com range (ex: https://example.com/data-{year}.csv)
2. static_url: URL única estática
3. api_pagination: Paginação via API

Respeita rate limits configurados entre requisições.
"""

import asyncio
import itertools
import logging
import re
import time
from typing import Any, Dict, List, Optional, Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx

from gabi.pipeline.contracts import DiscoveredURL, DiscoveryResult
from gabi.config import settings


logger = logging.getLogger(__name__)


@dataclass
class DiscoveryConfig:
    """Configuração para descoberta de URLs.
    
    Attributes:
        mode: Modo de discovery (url_pattern, static_url, api_pagination, crawler, api_query)
        url: URL base (para static_url ou api_pagination)
        url_pattern: Padrão de URL com placeholders (para url_pattern)
        range_config: Configuração de range para url_pattern
        pagination_config: Configuração de paginação para api_pagination
        rate_limit_delay: Delay entre requisições em segundos
        priority: Prioridade padrão para URLs descobertas
        headers: Headers HTTP adicionais
        crawler_rules: Regras de crawling (link_selector, asset_selector, etc.)
        api_query_config: Configuração completa para api_query (driver, params, etc.)
    """
    mode: str  # url_pattern, static_url, api_pagination, crawler, api_query
    url: Optional[str] = None
    url_pattern: Optional[str] = None
    range_config: Optional[Dict[str, Any]] = None
    pagination_config: Optional[Dict[str, Any]] = None
    rate_limit_delay: float = 1.0
    priority: int = 0
    headers: Optional[Dict[str, str]] = None
    timeout: int = 30
    max_retries: int = 3
    max_urls: Optional[int] = None
    # Crawler mode fields
    crawler_rules: Optional[Dict[str, Any]] = None
    # api_query mode fields
    api_query_config: Optional[Dict[str, Any]] = None


class RateLimiter:
    """Rate limiter simples baseado em token bucket."""
    
    def __init__(self, requests_per_second: float = 1.0):
        self.min_interval = 1.0 / requests_per_second
        self.last_request_time: Optional[float] = None
        self._lock = asyncio.Lock()
    
    async def acquire(self):
        """Adquire permissão para fazer uma requisição."""
        async with self._lock:
            if self.last_request_time is not None:
                elapsed = time.monotonic() - self.last_request_time
                if elapsed < self.min_interval:
                    wait_time = self.min_interval - elapsed
                    await asyncio.sleep(wait_time)
            self.last_request_time = time.monotonic()


class DiscoveryEngine:
    """Engine de descoberta de URLs.
    
    Suporta múltiplos modos de discovery com rate limiting.
    """
    
    def __init__(self):
        self.rate_limiter = RateLimiter(
            requests_per_second=settings.crawler_delay_seconds
        )
        self._handlers: Dict[str, Callable] = {
            "static_url": self._handle_static_url,
            "url_pattern": self._handle_url_pattern,
            "api_pagination": self._handle_api_pagination,
            "crawler": self._handle_crawler,
            "api_query": self._handle_api_query,
        }
    
    async def discover(
        self,
        source_id: str,
        config: DiscoveryConfig
    ) -> DiscoveryResult:
        """Executa discovery baseado na configuração.
        
        Args:
            source_id: ID da fonte
            config: Configuração de discovery
            
        Returns:
            DiscoveryResult com URLs descobertas
        """
        start_time = time.monotonic()
        
        handler = self._handlers.get(config.mode)
        if not handler:
            logger.error(f"Modo de discovery desconhecido: {config.mode}")
            return DiscoveryResult(
                urls=[],
                total_found=0,
                filtered_out=0,
                duration_seconds=time.monotonic() - start_time
            )
        
        try:
            urls = await handler(source_id, config)
            duration = time.monotonic() - start_time
            
            # Remove duplicatas mantendo ordem
            seen = set()
            unique_urls = []
            for url in urls:
                if url.url not in seen:
                    seen.add(url.url)
                    unique_urls.append(url)
            
            filtered_out = len(urls) - len(unique_urls)
            
            logger.info(
                f"Discovery completado para {source_id}: "
                f"{len(unique_urls)} URLs únicas, "
                f"{filtered_out} duplicatas filtradas, "
                f"{duration:.2f}s"
            )
            
            return DiscoveryResult(
                urls=unique_urls,
                total_found=len(unique_urls),
                filtered_out=filtered_out,
                duration_seconds=duration
            )
            
        except Exception as e:
            logger.error(f"Erro no discovery para {source_id}: {e}")
            return DiscoveryResult(
                urls=[],
                total_found=0,
                filtered_out=0,
                duration_seconds=time.monotonic() - start_time
            )
    
    async def _handle_static_url(
        self,
        source_id: str,
        config: DiscoveryConfig
    ) -> List[DiscoveredURL]:
        """Handler para URL estática única.
        
        Args:
            source_id: ID da fonte
            config: Configuração de discovery
            
        Returns:
            Lista com uma única URL
        """
        if not config.url:
            logger.error("URL não configurada para modo static_url")
            return []
        
        await self.rate_limiter.acquire()
        
        return [
            DiscoveredURL(
                url=config.url,
                source_id=source_id,
                priority=config.priority,
                metadata={"discovery_mode": "static_url"}
            )
        ]
    
    def _validate_url(self, url: str) -> bool:
        """Valida formato de URL.
        
        Args:
            url: URL a ser validada
            
        Returns:
            True se URL é válida, False caso contrário
        """
        if not url or not isinstance(url, str):
            return False
        
        try:
            parsed = urlparse(url)
            
            # Check scheme
            if parsed.scheme not in ("http", "https"):
                logger.warning(f"URL com scheme inválido: {url}")
                return False
            
            # Check netloc (domain)
            if not parsed.netloc:
                logger.warning(f"URL sem domínio: {url}")
                return False
            
            # Basic URL format validation
            if not re.match(r"^[a-zA-Z0-9\-\.]+\.[a-zA-Z]{2,}", parsed.netloc):
                logger.warning(f"Domínio inválido: {parsed.netloc}")
                return False
            
            return True
            
        except Exception as e:
            logger.warning(f"Erro ao validar URL {url}: {e}")
            return False
    
    async def _handle_url_pattern(
        self,
        source_id: str,
        config: DiscoveryConfig
    ) -> List[DiscoveredURL]:
        """Handler para padrão de URL com range.
        
        Exemplo: "https://example.com/data-{year}-{month}.csv" com 
        range_config={"year": {"start": 2020, "end": 2024}, "month": {"start": 1, "end": 12}}
        
        Supports multiple variables and generates cartesian product.
        
        Args:
            source_id: ID da fonte
            config: Configuração de discovery
            
        Returns:
            Lista de URLs geradas a partir do padrão
        """
        if not config.url_pattern:
            logger.error("url_pattern não configurado")
            return []
        
        if not config.range_config:
            logger.error("range_config não configurado para url_pattern")
            return []
        
        # Validate base URL pattern format
        if not self._validate_url(config.url_pattern.replace("{", "").replace("}", "")):
            # Try to construct a sample URL for validation
            sample_url = config.url_pattern
            for var_name, range_spec in config.range_config.items():
                start = range_spec.get("start", 0)
                sample_url = sample_url.replace(f"{{{var_name}}}", str(start))
            
            if not self._validate_url(sample_url):
                logger.error(f"URL pattern inválido: {config.url_pattern}")
                return []
        
        urls = []
        
        # Build list of value lists for each variable
        var_names = []
        value_lists = []
        
        for var_name, range_spec in config.range_config.items():
            start = self._resolve_range_value(range_spec.get("start", 0))
            end = self._resolve_range_value(range_spec.get("end", start))
            step = self._resolve_range_value(range_spec.get("step", 1))
            if step == 0:
                logger.warning("Step 0 inválido para %s; usando 1", var_name)
                step = 1
            if end < start and step > 0:
                step = -step
            
            placeholder = f"{{{var_name}}}"
            
            if placeholder not in config.url_pattern:
                logger.warning(f"Placeholder {placeholder} não encontrado no padrão")
                continue
            
            range_stop = end + 1 if step > 0 else end - 1
            var_names.append(var_name)
            value_lists.append(list(range(start, range_stop, step)))
        
        if not var_names:
            logger.error("Nenhuma variável válida encontrada no padrão")
            return []
        
        # Generate cartesian product of all variable combinations
        for combination in itertools.product(*value_lists):
            if config.max_urls is not None and len(urls) >= config.max_urls:
                break
            await self.rate_limiter.acquire()
            
            url = config.url_pattern
            metadata = {
                "discovery_mode": "url_pattern",
                "pattern": config.url_pattern,
            }
            
            for var_name, value in zip(var_names, combination):
                url = url.replace(f"{{{var_name}}}", str(value))
                metadata[var_name] = value
            
            # Validate generated URL
            if not self._validate_url(url):
                logger.warning(f"URL gerada inválida, ignorando: {url}")
                continue
            
            urls.append(
                DiscoveredURL(
                    url=url,
                    source_id=source_id,
                    priority=config.priority,
                    metadata=metadata
                )
            )
        
        return urls

    @staticmethod
    def _resolve_range_value(raw_value: Any) -> int:
        """Converte valor de range para inteiro.
        
        Suporta tokens simbólicos como ``current`` para ano corrente.
        """
        if isinstance(raw_value, int):
            return raw_value
        if isinstance(raw_value, str):
            value = raw_value.strip().lower()
            if value in {"current", "current_year", "this_year", "now"}:
                return datetime.now(timezone.utc).year
            if re.fullmatch(r"-?\d+", value):
                return int(value)
        raise ValueError(f"Valor de range inválido: {raw_value!r}")
    
    async def _handle_api_pagination(
        self,
        source_id: str,
        config: DiscoveryConfig
    ) -> List[DiscoveredURL]:
        """Handler para paginação via API.
        
        Navega por páginas de uma API extraindo URLs.
        
        Args:
            source_id: ID da fonte
            config: Configuração de discovery
            
        Returns:
            Lista de URLs extraídas da API
        """
        if not config.url:
            logger.error("URL não configurada para modo api_pagination")
            return []
        
        pagination = config.pagination_config or {}
        page_param = pagination.get("page_param", "page")
        page_size_param = pagination.get("page_size_param", "per_page")
        page_size = pagination.get("page_size", 100)
        max_pages = pagination.get("max_pages", 100)
        url_field = pagination.get("url_field", "url")
        results_path = pagination.get("results_path", "results")
        has_more_path = pagination.get("has_more_path", "has_more")
        
        urls = []
        page = pagination.get("start_page", 1)
        headers = config.headers or {}
        
        async with httpx.AsyncClient(timeout=config.timeout) as client:
            while page <= max_pages:
                await self.rate_limiter.acquire()
                
                # Constrói URL com parâmetros de paginação
                params = {
                    page_param: page,
                    page_size_param: page_size
                }
                
                try:
                    response = await client.get(
                        config.url,
                        params=params,
                        headers=headers
                    )
                    response.raise_for_status()
                    data = response.json()
                    
                    # Extrai resultados
                    results = data
                    if results_path:
                        for key in results_path.split("."):
                            results = results.get(key, [])
                            if not isinstance(results, (list, dict)):
                                break
                    
                    if not isinstance(results, list):
                        logger.warning(f"Resultados não são uma lista: {type(results)}")
                        break
                    
                    # Extrai URLs dos resultados
                    for item in results:
                        if isinstance(item, dict) and url_field in item:
                            urls.append(
                                DiscoveredURL(
                                    url=item[url_field],
                                    source_id=source_id,
                                    priority=config.priority,
                                    metadata={
                                        "discovery_mode": "api_pagination",
                                        "page": page,
                                        "api_data": {k: v for k, v in item.items() if k != url_field}
                                    }
                                )
                            )
                        elif isinstance(item, str):
                            urls.append(
                                DiscoveredURL(
                                    url=item,
                                    source_id=source_id,
                                    priority=config.priority,
                                    metadata={
                                        "discovery_mode": "api_pagination",
                                        "page": page
                                    }
                                )
                            )
                    
                    logger.debug(f"Página {page}: {len(results)} resultados, {len(urls)} URLs acumuladas")
                    
                    # Verifica se há mais páginas
                    has_more = True
                    if has_more_path:
                        has_more = data
                        for key in has_more_path.split("."):
                            has_more = has_more.get(key, False) if isinstance(has_more, dict) else False
                    
                    if not has_more or len(results) < page_size:
                        break
                    
                    page += 1
                    
                except httpx.HTTPStatusError as e:
                    logger.error(f"Erro HTTP na página {page}: {e.response.status_code}")
                    break
                except httpx.RequestError as e:
                    logger.error(f"Erro de requisição na página {page}: {e}")
                    break
                except Exception as e:
                    logger.error(f"Erro inesperado na página {page}: {e}")
                    break
        
        logger.info(f"API pagination: {len(urls)} URLs extraídas em {page - pagination.get('start_page', 1) + 1} páginas")
        return urls
    
    async def _handle_crawler(
        self,
        source_id: str,
        config: DiscoveryConfig,
    ) -> List[DiscoveredURL]:
        """Handler para discovery via crawling de páginas HTML.

        Crawlea uma root_url, extrai links de subpáginas e/ou links de assets
        (PDFs, etc.) seguindo as regras configuradas.

        Suporta:
        - Paginação via query param (pagination_param)
        - Extração de links de detalhe (link_selector regex)
        - Extração de assets diretos (asset_selector regex)
        - Profundidade configurável (max_depth)
        """
        root_url = config.url
        if not root_url:
            logger.error("root_url não configurada para modo crawler")
            return []

        rules = config.crawler_rules or {}
        asset_pattern = rules.get("asset_selector", r'href="([^"]+\.pdf)"')
        link_pattern = rules.get("link_selector", "")
        pagination_param = rules.get("pagination_param")
        max_depth = int(rules.get("max_depth", 1))
        rate_limit = float(rules.get("rate_limit", 1.0))
        max_pages = int(rules.get("max_pages", 50))

        # Convert CSS-like selectors to regex patterns
        asset_regex = self._selector_to_regex(asset_pattern)
        link_regex = self._selector_to_regex(link_pattern) if link_pattern else None

        urls: List[DiscoveredURL] = []
        visited: set[str] = set()

        parsed_root = urlparse(root_url)
        base_url = f"{parsed_root.scheme}://{parsed_root.netloc}"

        async with httpx.AsyncClient(
            timeout=config.timeout,
            follow_redirects=True,
            headers={"User-Agent": "GABI-Crawler/1.0"},
        ) as client:
            # Phase 1: Collect listing pages (with pagination)
            listing_pages = [root_url]
            if pagination_param:
                for page_num in range(2, max_pages + 1):
                    sep = "&" if "?" in root_url else "?"
                    listing_pages.append(f"{root_url}{sep}{pagination_param}={page_num}")

            # Phase 2: Crawl listing pages to find detail links and/or assets
            detail_links: List[str] = []

            for page_url in listing_pages:
                if config.max_urls and len(urls) + len(detail_links) >= config.max_urls:
                    break
                await asyncio.sleep(rate_limit)
                try:
                    resp = await client.get(page_url)
                    if resp.status_code != 200:
                        logger.debug("Crawler page %s returned %s, stopping pagination", page_url, resp.status_code)
                        break
                    html = resp.text
                    visited.add(page_url)

                    # Extract direct asset links (e.g. PDFs)
                    for match in re.finditer(asset_regex, html, re.IGNORECASE):
                        asset_url = self._resolve_url(match.group(1), base_url)
                        if asset_url and asset_url not in visited:
                            visited.add(asset_url)
                            urls.append(DiscoveredURL(
                                url=asset_url,
                                source_id=source_id,
                                priority=config.priority,
                                metadata={"discovery_mode": "crawler", "depth": 0},
                            ))

                    # Extract detail page links for deeper crawling
                    if link_regex and max_depth >= 2:
                        for match in re.finditer(link_regex, html, re.IGNORECASE):
                            link_url = self._resolve_url(match.group(1), base_url)
                            if link_url and link_url not in visited:
                                detail_links.append(link_url)

                    # If no new detail links found on this page, stop pagination
                    if pagination_param and not re.search(link_regex or asset_regex, html, re.IGNORECASE):
                        break

                except Exception as exc:
                    logger.warning("Crawler error on %s: %s", page_url, exc)
                    break

            # Phase 3: Crawl detail pages for assets (depth 2)
            if detail_links and max_depth >= 2:
                for detail_url in detail_links:
                    if config.max_urls and len(urls) >= config.max_urls:
                        break
                    if detail_url in visited:
                        continue
                    visited.add(detail_url)
                    await asyncio.sleep(rate_limit)
                    try:
                        resp = await client.get(detail_url)
                        if resp.status_code != 200:
                            continue
                        html = resp.text
                        for match in re.finditer(asset_regex, html, re.IGNORECASE):
                            asset_url = self._resolve_url(match.group(1), base_url)
                            if asset_url and asset_url not in visited:
                                visited.add(asset_url)
                                urls.append(DiscoveredURL(
                                    url=asset_url,
                                    source_id=source_id,
                                    priority=config.priority,
                                    metadata={"discovery_mode": "crawler", "depth": 1, "parent": detail_url},
                                ))
                    except Exception as exc:
                        logger.warning("Crawler error on detail %s: %s", detail_url, exc)

        logger.info("Crawler discovery for %s: %d asset URLs found", source_id, len(urls))
        return urls

    @staticmethod
    def _selector_to_regex(selector: str) -> str:
        """Convert a CSS-like selector hint to a regex for href extraction.

        Supports patterns like:
        - ``a[href$='.pdf']`` → ``href="([^"]+\\.pdf)"``
        - ``a[href*='/publicacoes/']`` → ``href="([^"]*\\/publicacoes\\/[^"]*?)"``
        - ``a[href$='.pdf']:not([href$='todas'])`` → regex with negative lookahead
        - Raw regex (passed through if it contains a capture group)
        """
        # Already a real regex (has capture group AND does not look like CSS)
        if "(" in selector and not re.search(r':not\(|:has\(|a\[', selector):
            return selector

        # Strip :not(...) clause and handle it separately
        not_pattern = None
        base_selector = selector
        not_match = re.search(r":not\(\[href[^\]]*=['\"](.+?)['\"]\]\)", selector)
        if not_match:
            not_pattern = re.escape(not_match.group(1))
            base_selector = selector[:not_match.start()]

        # a[href$='.pdf']
        m = re.match(r"a\[href\$=['\"](.+?)['\"]\]", base_selector)
        if m:
            suffix = re.escape(m.group(1))
            if not_pattern:
                return r'href="((?![^"]*' + not_pattern + r')[^"]+' + suffix + r')"'
            return r'href="([^"]+' + suffix + r')"'

        # a[href*='...']
        m = re.match(r"a\[href\*=['\"](.+?)['\"]\]", base_selector)
        if m:
            contains = re.escape(m.group(1))
            if not_pattern:
                return r'href="((?![^"]*' + not_pattern + r')[^"]*' + contains + r'[^"]*?)"'
            return r'href="([^"]*' + contains + r'[^"]*?)"'

        # Fallback: treat as literal substring match
        escaped = re.escape(selector)
        return r'href="([^"]*' + escaped + r'[^"]*?)"'

    @staticmethod
    def _resolve_url(url: str, base_url: str) -> Optional[str]:
        """Resolve a possibly relative URL against a base URL."""
        if not url:
            return None
        url = url.strip()
        if url.startswith(("http://", "https://")):
            return url
        if url.startswith("/"):
            return base_url.rstrip("/") + url
        return None

    async def _handle_api_query(
        self,
        source_id: str,
        config: DiscoveryConfig,
    ) -> List[DiscoveredURL]:
        """Handler para discovery via API REST paginada.

        Suporta drivers específicos:
        - camara_api_v1: API Dados Abertos da Câmara dos Deputados
        - generic: API genérica com paginação offset/limit
        """
        api_config = config.api_query_config or {}
        driver = api_config.get("driver", "generic")
        params = api_config.get("params", {})

        if driver == "camara_api_v1":
            return await self._discover_camara_api(source_id, config, params)

        # Generic API query: needs an explicit URL
        url = api_config.get("url") or api_config.get("endpoint") or config.url
        if not url:
            logger.error("URL não configurada para modo api_query")
            return []
        return [DiscoveredURL(
            url=url,
            source_id=source_id,
            priority=config.priority,
            metadata={"discovery_mode": "api_query", "driver": driver},
        )]

    async def _discover_camara_api(
        self,
        source_id: str,
        config: DiscoveryConfig,
        params: Dict[str, Any],
    ) -> List[DiscoveredURL]:
        """Discovery via API Dados Abertos da Câmara dos Deputados.

        Pagina pela API v2 de proposições (leis ordinárias) extraindo
        URLs de detalhamento de cada proposição.
        """
        start_year = int(params.get("start_year", 2020))
        end_year = int(params.get("end_year", datetime.now(timezone.utc).year))
        items_per_page = 100
        max_per_year = config.max_urls or 200

        urls: List[DiscoveredURL] = []
        total_limit = config.max_urls

        async with httpx.AsyncClient(
            timeout=config.timeout,
            follow_redirects=True,
            headers={"Accept": "application/json"},
        ) as client:
            for year in range(end_year, start_year - 1, -1):  # newest first
                if total_limit and len(urls) >= total_limit:
                    break
                page = 1
                year_count = 0
                while year_count < max_per_year:
                    if total_limit and len(urls) >= total_limit:
                        break
                    await asyncio.sleep(config.rate_limit_delay)
                    api_url = (
                        f"https://dadosabertos.camara.leg.br/api/v2/proposicoes"
                        f"?siglaTipo=PL&ano={year}&itens={items_per_page}"
                        f"&pagina={page}&ordem=ASC&ordenarPor=id"
                    )
                    try:
                        resp = await client.get(api_url)
                        if resp.status_code != 200:
                            logger.warning("Camara API %s returned %s", api_url, resp.status_code)
                            break
                        data = resp.json()
                        dados = data.get("dados", [])
                        if not dados:
                            break

                        for item in dados:
                            if total_limit and len(urls) >= total_limit:
                                break
                            prop_url = item.get("uri", "")
                            prop_id = item.get("id", "")
                            ementa = item.get("ementa", "")
                            if prop_url:
                                urls.append(DiscoveredURL(
                                    url=prop_url,
                                    source_id=source_id,
                                    priority=config.priority,
                                    metadata={
                                        "discovery_mode": "api_query",
                                        "driver": "camara_api_v1",
                                        "prop_id": prop_id,
                                        "year": year,
                                        "ementa": ementa[:200] if ementa else "",
                                    },
                                ))
                                year_count += 1

                        # Check if there are more pages
                        links = data.get("links", [])
                        has_next = any(l.get("rel") == "next" for l in links)
                        if not has_next or len(dados) < items_per_page:
                            break
                        page += 1

                    except Exception as exc:
                        logger.warning("Camara API error year=%s page=%s: %s", year, page, exc)
                        break

        logger.info("Camara API discovery for %s: %d proposições found", source_id, len(urls))
        return urls

    def register_handler(self, mode: str, handler: Callable) -> None:
        """Registra um handler customizado para um modo de discovery.
        
        Args:
            mode: Nome do modo
            handler: Função handler async
        """
        self._handlers[mode] = handler
        logger.info(f"Handler registrado para modo: {mode}")


# Singleton global
discovery_engine = DiscoveryEngine()
