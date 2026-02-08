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
from urllib.parse import urlparse

import httpx

from gabi.pipeline.contracts import DiscoveredURL, DiscoveryResult
from gabi.config import settings


logger = logging.getLogger(__name__)


@dataclass
class DiscoveryConfig:
    """Configuração para descoberta de URLs.
    
    Attributes:
        mode: Modo de discovery (url_pattern, static_url, api_pagination)
        url: URL base (para static_url ou api_pagination)
        url_pattern: Padrão de URL com placeholders (para url_pattern)
        range_config: Configuração de range para url_pattern (ex: {"year": {"start": 2020, "end": 2024}})
        pagination_config: Configuração de paginação para api_pagination
        rate_limit_delay: Delay entre requisições em segundos
        priority: Prioridade padrão para URLs descobertas
        headers: Headers HTTP adicionais
    """
    mode: str  # url_pattern, static_url, api_pagination
    url: Optional[str] = None
    url_pattern: Optional[str] = None
    range_config: Optional[Dict[str, Any]] = None
    pagination_config: Optional[Dict[str, Any]] = None
    rate_limit_delay: float = 1.0
    priority: int = 0
    headers: Optional[Dict[str, str]] = None
    timeout: int = 30
    max_retries: int = 3


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
            start = range_spec.get("start", 0)
            end = range_spec.get("end", start)
            step = range_spec.get("step", 1)
            
            placeholder = f"{{{var_name}}}"
            
            if placeholder not in config.url_pattern:
                logger.warning(f"Placeholder {placeholder} não encontrado no padrão")
                continue
            
            var_names.append(var_name)
            value_lists.append(list(range(start, end + 1, step)))
        
        if not var_names:
            logger.error("Nenhuma variável válida encontrada no padrão")
            return []
        
        # Generate cartesian product of all variable combinations
        for combination in itertools.product(*value_lists):
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
