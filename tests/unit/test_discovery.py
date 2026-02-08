"""Testes unitários para o serviço de discovery.

Este módulo testa as estratégias de discovery de forma isolada,
com mocks para todas as dependências externas.

Testes:
    - test_discover_url_pattern: Geração de URLs a partir de template
    - test_discover_static_url: Retorno de URL estática única
    - test_rate_limiting: Controle de taxa de requisições
    - test_crawler_discovery: Crawling com mocks HTTP
    - test_api_query_discovery: Discovery via API
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import httpx
import pytest
import respx
from bs4 import BeautifulSoup

from gabi.services.discovery import (
    # Strategies
    CrawlerDiscovery,
    DiscoveryService,
    StaticURLDiscovery,
    URLPatternDiscovery,
    # Configs
    CrawlerConfig,
    RateLimiter,
    StaticURLConfig,
    URLPatternConfig,
    # Function
    discover_source,
)
from gabi.pipeline.contracts import DiscoveredURL, DiscoveryResult


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def mock_http_client() -> Mock:
    """Cria um cliente HTTP mockado.
    
    Returns:
        Mock de httpx.AsyncClient
    """
    client = Mock(spec=httpx.AsyncClient)
    client.is_closed = False
    client.aclose = AsyncMock()
    return client


@pytest.fixture
def fast_rate_limiter() -> RateLimiter:
    """Rate limiter com taxa alta para testes rápidos.
    
    Returns:
        RateLimiter configurado para 1000 req/s
    """
    return RateLimiter(rate=1000.0, burst=100)


# =============================================================================
# RateLimiter Tests
# =============================================================================

class TestRateLimiter:
    """Testes para o rate limiter."""
    
    @pytest.mark.asyncio
    async def test_rate_limiter_initial_state(self) -> None:
        """Testa estado inicial do rate limiter."""
        limiter = RateLimiter(rate=1.0, burst=1)
        
        # Primeira aquisição deve ser imediata
        start = time.monotonic()
        await limiter.acquire()
        elapsed = time.monotonic() - start
        
        assert elapsed < 0.1  # Deve ser quase instantâneo
    
    @pytest.mark.asyncio
    async def test_rate_limiter_enforces_rate(self) -> None:
        """Testa que o rate limiter respeita a taxa configurada."""
        limiter = RateLimiter(rate=10.0, burst=1)  # 10 req/s = 100ms entre reqs
        
        # Primeira requisição
        await limiter.acquire()
        
        # Segunda requisição deve esperar
        start = time.monotonic()
        await limiter.acquire()
        elapsed = time.monotonic() - start
        
        # Deve ter esperado aproximadamente 100ms
        assert elapsed >= 0.08  # Tolerância para timing
    
    @pytest.mark.asyncio
    async def test_rate_limiter_burst(self) -> None:
        """Testa capacidade de burst do rate limiter."""
        limiter = RateLimiter(rate=1.0, burst=3)  # 3 requisições imediatas
        
        start = time.monotonic()
        for _ in range(3):
            await limiter.acquire()
        elapsed = time.monotonic() - start
        
        # As 3 primeiras devem ser instantâneas (burst)
        assert elapsed < 0.1
    
    @pytest.mark.asyncio
    async def test_rate_limiter_refill(self) -> None:
        """Testa recarga de tokens ao longo do tempo."""
        limiter = RateLimiter(rate=100.0, burst=1)  # 100 req/s
        
        # Usa o token inicial
        await limiter.acquire()
        
        # Espera recarga parcial
        await asyncio.sleep(0.05)  # 50ms = 5 tokens a 100 req/s
        
        # Próxima aquisição deve ser mais rápida
        start = time.monotonic()
        await limiter.acquire()
        elapsed = time.monotonic() - start
        
        # Deve ter esperado menos que o tempo cheio (10ms)
        assert elapsed < 0.02


# =============================================================================
# URLPatternDiscovery Tests
# =============================================================================

class TestURLPatternDiscovery:
    """Testes para discovery baseado em padrão de URL."""
    
    @pytest.mark.asyncio
    async def test_discover_url_pattern_single_year(self) -> None:
        """Testa geração de URLs para um único ano."""
        config = URLPatternConfig(
            url_template="https://example.com/data/{year}.csv",
            params={"year": {"start": 2024, "end": 2024}},
        )
        strategy = URLPatternDiscovery("test_source", config)
        
        result = await strategy.discover()
        
        assert result.total_found == 1
        assert len(result.urls) == 1
        assert result.urls[0].url == "https://example.com/data/2024.csv"
        assert result.urls[0].source_id == "test_source"
    
    @pytest.mark.asyncio
    async def test_discover_url_pattern_year_range(self) -> None:
        """Testa geração de URLs para range de anos."""
        config = URLPatternConfig(
            url_template="https://tcu.gov.br/acordaos/{year}.csv",
            params={"year": {"start": 2020, "end": 2024}},
        )
        strategy = URLPatternDiscovery("tcu_acordaos", config)
        
        result = await strategy.discover()
        
        assert result.total_found == 5  # 2020, 2021, 2022, 2023, 2024
        urls = [u.url for u in result.urls]
        
        for year in range(2020, 2025):
            assert f"https://tcu.gov.br/acordaos/{year}.csv" in urls
    
    @pytest.mark.asyncio
    async def test_discover_url_pattern_current_year(self) -> None:
        """Testa substituição de 'current' pelo ano atual."""
        current_year = datetime.now().year
        
        config = URLPatternConfig(
            url_template="https://example.com/{year}.csv",
            params={"year": {"start": 2020, "end": "current"}},
        )
        strategy = URLPatternDiscovery("test_source", config)
        
        result = await strategy.discover()
        
        expected_count = current_year - 2020 + 1
        assert result.total_found == expected_count
        
        # Verifica se o ano atual está presente
        urls = [u.url for u in result.urls]
        assert f"https://example.com/{current_year}.csv" in urls
    
    @pytest.mark.asyncio
    async def test_discover_url_pattern_multiple_params(self) -> None:
        """Testa geração com múltiplos parâmetros."""
        config = URLPatternConfig(
            url_template="https://example.com/{type}/{year}.csv",
            params={
                "type": {"start": 1, "end": 2},  # 1, 2
                "year": {"start": 2023, "end": 2024},  # 2023, 2024
            },
        )
        strategy = URLPatternDiscovery("test_source", config)
        
        result = await strategy.discover()
        
        # 2 tipos × 2 anos = 4 combinações
        assert result.total_found == 4
        urls = [u.url for u in result.urls]
        
        assert "https://example.com/1/2023.csv" in urls
        assert "https://example.com/1/2024.csv" in urls
        assert "https://example.com/2/2023.csv" in urls
        assert "https://example.com/2/2024.csv" in urls
    
    @pytest.mark.asyncio
    async def test_discover_url_pattern_no_params(self) -> None:
        """Testa template sem parâmetros."""
        config = URLPatternConfig(
            url_template="https://example.com/static.csv",
            params={},
        )
        strategy = URLPatternDiscovery("test_source", config)
        
        result = await strategy.discover()
        
        assert result.total_found == 1
        assert result.urls[0].url == "https://example.com/static.csv"
    
    @pytest.mark.asyncio
    async def test_discover_url_pattern_metadata(self) -> None:
        """Testa metadados nas URLs descobertas."""
        config = URLPatternConfig(
            url_template="https://example.com/{year}.csv",
            params={"year": {"start": 2024, "end": 2024}},
        )
        strategy = URLPatternDiscovery("test_source", config)
        
        result = await strategy.discover()
        
        assert result.urls[0].metadata["generated"] is True
        assert result.urls[0].metadata["template"] == "https://example.com/{year}.csv"
        assert result.urls[0].priority == 0
    
    @pytest.mark.asyncio
    async def test_discover_url_pattern_duration_tracking(self) -> None:
        """Testa tracking de duração do discovery."""
        config = URLPatternConfig(
            url_template="https://example.com/{year}.csv",
            params={"year": {"start": 1, "end": 100}},
        )
        strategy = URLPatternDiscovery("test_source", config)
        
        result = await strategy.discover()
        
        assert result.duration_seconds >= 0
        assert isinstance(result.duration_seconds, float)


# =============================================================================
# StaticURLDiscovery Tests
# =============================================================================

class TestStaticURLDiscovery:
    """Testes para discovery de URL estática."""
    
    @pytest.mark.asyncio
    async def test_discover_static_url(self) -> None:
        """Testa retorno de URL estática única."""
        config = StaticURLConfig(url="https://example.com/data.csv")
        strategy = StaticURLDiscovery("test_source", config)
        
        result = await strategy.discover()
        
        assert result.total_found == 1
        assert len(result.urls) == 1
        assert result.urls[0].url == "https://example.com/data.csv"
        assert result.urls[0].source_id == "test_source"
    
    @pytest.mark.asyncio
    async def test_discover_static_url_with_change_detection(self) -> None:
        """Testa URL estática com configuração de change detection."""
        config = StaticURLConfig(
            url="https://example.com/normas.csv",
            change_detection={"strategy": "etag"},
        )
        strategy = StaticURLDiscovery("tcu_normas", config)
        
        result = await strategy.discover()
        
        assert result.total_found == 1
        assert result.urls[0].metadata["static"] is True
    
    @pytest.mark.asyncio
    async def test_discover_static_url_fast(self) -> None:
        """Testa que discovery estático é rápido (não faz I/O)."""
        config = StaticURLConfig(url="https://example.com/data.csv")
        strategy = StaticURLDiscovery("test_source", config)
        
        start = time.monotonic()
        result = await strategy.discover()
        elapsed = time.monotonic() - start
        
        # Deve ser quase instantâneo (< 1ms)
        assert elapsed < 0.001
        assert result.total_found == 1


# =============================================================================
# CrawlerDiscovery Tests
# =============================================================================

class TestCrawlerDiscovery:
    """Testes para discovery via crawling."""
    
    @pytest.mark.asyncio
    async def test_crawler_extracts_pdf_links(self) -> None:
        """Testa extração de links para PDFs."""
        html = """
        <html>
            <body>
                <a href="/doc1.pdf">Documento 1</a>
                <a href="/doc2.pdf">Documento 2</a>
                <a href="/page2">Página 2</a>
            </body>
        </html>
        """
        
        with respx.mock:
            route = respx.get("https://example.com/docs").mock(
                return_value=httpx.Response(200, text=html)
            )
            
            config = CrawlerConfig(
                root_url="https://example.com/docs",
                rules={
                    "max_depth": 1,
                    "asset_selector": "a[href$='.pdf']",
                },
                rate_limit=1000.0,  # Rápido para testes
            )
            
            strategy = CrawlerDiscovery(
                "test_source",
                config,
                rate_limiter=RateLimiter(rate=1000.0),
            )
            
            result = await strategy.discover()
            
            assert result.total_found == 2
            urls = [u.url for u in result.urls]
            assert "https://example.com/doc1.pdf" in urls
            assert "https://example.com/doc2.pdf" in urls
    
    @pytest.mark.asyncio
    async def test_crawler_follows_navigation_links(self) -> None:
        """Testa que o crawler segue links de navegação."""
        page1_html = """
        <html>
            <body>
                <a href="/docs/page2">Próxima página</a>
                <a href="/doc1.pdf">PDF 1</a>
            </body>
        </html>
        """
        page2_html = """
        <html>
            <body>
                <a href="/doc2.pdf">PDF 2</a>
            </body>
        </html>
        """
        
        with respx.mock:
            respx.get("https://example.com/docs").mock(
                return_value=httpx.Response(200, text=page1_html)
            )
            respx.get("https://example.com/docs/page2").mock(
                return_value=httpx.Response(200, text=page2_html)
            )
            
            config = CrawlerConfig(
                root_url="https://example.com/docs",
                rules={
                    "max_depth": 2,
                    "asset_selector": "a[href$='.pdf']",
                    "link_selector": "a[href^='/docs']",
                },
                rate_limit=1000.0,
            )
            
            strategy = CrawlerDiscovery(
                "test_source",
                config,
                rate_limiter=RateLimiter(rate=1000.0),
            )
            
            result = await strategy.discover()
            
            assert result.total_found == 2
            urls = [u.url for u in result.urls]
            assert "https://example.com/doc1.pdf" in urls
            assert "https://example.com/doc2.pdf" in urls
    
    @pytest.mark.asyncio
    async def test_crawler_respects_max_depth(self) -> None:
        """Testa que o crawler respeita a profundidade máxima."""
        html_template = """
        <html>
            <body>
                <a href="/page{next}">Próxima</a>
                <a href="/doc{current}.pdf">PDF</a>
            </body>
        </html>
        """
        
        call_count = 0
        
        def make_handler(page_num: int):
            def handler(request: httpx.Request) -> httpx.Response:
                nonlocal call_count
                call_count += 1
                html = html_template.format(next=page_num + 1, current=page_num)
                return httpx.Response(200, text=html)
            return handler
        
        with respx.mock:
            respx.get("https://example.com/page1").side_effect = make_handler(1)
            respx.get("https://example.com/page2").side_effect = make_handler(2)
            respx.get("https://example.com/page3").side_effect = make_handler(3)
            
            config = CrawlerConfig(
                root_url="https://example.com/page1",
                rules={
                    "max_depth": 2,  # Apenas 2 níveis
                    "asset_selector": "a[href$='.pdf']",
                    "link_selector": "a[href^='/page']",
                },
                rate_limit=1000.0,
            )
            
            strategy = CrawlerDiscovery(
                "test_source",
                config,
                rate_limiter=RateLimiter(rate=1000.0),
            )
            
            result = await strategy.discover()
            
            # Deve parar na profundidade 2
            assert call_count <= 3  # root + 2 níveis
    
    @pytest.mark.asyncio
    async def test_crawler_handles_http_errors(self) -> None:
        """Testa que o crawler lida com erros HTTP."""
        with respx.mock:
            respx.get("https://example.com/docs").mock(
                return_value=httpx.Response(500, text="Server Error")
            )
            
            config = CrawlerConfig(
                root_url="https://example.com/docs",
                rules={"max_depth": 1},
                rate_limit=1000.0,
            )
            
            strategy = CrawlerDiscovery(
                "test_source",
                config,
                rate_limiter=RateLimiter(rate=1000.0),
            )
            
            result = await strategy.discover()
            
            assert result.total_found == 0
    
    @pytest.mark.asyncio
    async def test_crawler_handles_network_error(self) -> None:
        """Testa que o crawler lida com erros de rede."""
        with respx.mock:
            respx.get("https://example.com/docs").side_effect = httpx.ConnectError(
                "Connection refused"
            )
            
            config = CrawlerConfig(
                root_url="https://example.com/docs",
                rules={"max_depth": 1},
                rate_limit=1000.0,
            )
            
            strategy = CrawlerDiscovery(
                "test_source",
                config,
                rate_limiter=RateLimiter(rate=1000.0),
            )
            
            result = await strategy.discover()
            
            assert result.total_found == 0
    
    @pytest.mark.asyncio
    async def test_crawler_resolves_relative_urls(self) -> None:
        """Testa resolução de URLs relativas."""
        html = """
        <html>
            <body>
                <a href="document.pdf">PDF relativo</a>
                <a href="/abs/document.pdf">PDF absoluto</a>
            </body>
        </html>
        """
        
        with respx.mock:
            respx.get("https://example.com/docs/page").mock(
                return_value=httpx.Response(200, text=html)
            )
            
            config = CrawlerConfig(
                root_url="https://example.com/docs/page",
                rules={"max_depth": 1, "asset_selector": "a[href$='.pdf']"},
                rate_limit=1000.0,
            )
            
            strategy = CrawlerDiscovery(
                "test_source",
                config,
                rate_limiter=RateLimiter(rate=1000.0),
            )
            
            result = await strategy.discover()
            
            urls = [u.url for u in result.urls]
            # URLs relativas devem ser resolvidas
            assert "https://example.com/docs/document.pdf" in urls
            assert "https://example.com/abs/document.pdf" in urls


# =============================================================================
# DiscoveryService Factory Tests
# =============================================================================

class TestDiscoveryService:
    """Testes para o serviço de discovery (factory)."""
    
    def test_create_strategy_url_pattern(self) -> None:
        """Testa criação de estratégia url_pattern."""
        service = DiscoveryService()
        config = {
            "mode": "url_pattern",
            "url_template": "https://example.com/{year}.csv",
            "params": {"year": {"start": 2020, "end": 2024}},
        }
        
        strategy = service.create_strategy("test_source", config)
        
        assert isinstance(strategy, URLPatternDiscovery)
        assert strategy.source_id == "test_source"
    
    def test_create_strategy_static_url(self) -> None:
        """Testa criação de estratégia static_url."""
        service = DiscoveryService()
        config = {
            "mode": "static_url",
            "url": "https://example.com/data.csv",
        }
        
        strategy = service.create_strategy("test_source", config)
        
        assert isinstance(strategy, StaticURLDiscovery)
        assert strategy.config.url == "https://example.com/data.csv"
    
    def test_create_strategy_crawler(self) -> None:
        """Testa criação de estratégia crawler."""
        service = DiscoveryService()
        config = {
            "mode": "crawler",
            "root_url": "https://example.com/docs",
            "rules": {"max_depth": 2},
            "rate_limit": 0.5,
        }
        
        strategy = service.create_strategy("test_source", config)
        
        assert isinstance(strategy, CrawlerDiscovery)
        assert strategy.config.root_url == "https://example.com/docs"
        assert strategy.config.rate_limit == 0.5
    
    def test_create_strategy_invalid_mode(self) -> None:
        """Testa erro para modo inválido."""
        service = DiscoveryService()
        config = {"mode": "invalid_mode"}
        
        with pytest.raises(ValueError, match="Modo de discovery não suportado"):
            service.create_strategy("test_source", config)
    
    def test_create_strategy_uses_default_rate_limit(self) -> None:
        """Testa que rate limit padrão é aplicado."""
        service = DiscoveryService(default_rate_limit=2.0)
        config = {
            "mode": "static_url",
            "url": "https://example.com/data.csv",
        }
        
        strategy = service.create_strategy("test_source", config)
        
        assert strategy._rate_limiter.rate == 2.0
    
    @pytest.mark.asyncio
    async def test_discover_method(self) -> None:
        """Testa método discover do serviço."""
        service = DiscoveryService()
        config = {
            "mode": "static_url",
            "url": "https://example.com/data.csv",
        }
        
        result = await service.discover("test_source", config)
        
        assert result.total_found == 1
        assert result.urls[0].url == "https://example.com/data.csv"


# =============================================================================
# Helper Function Tests
# =============================================================================

class TestDiscoverSource:
    """Testes para a função utilitária discover_source."""
    
    @pytest.mark.asyncio
    async def test_discover_source_static_url(self) -> None:
        """Testa função utilitária com URL estática."""
        config = {
            "mode": "static_url",
            "url": "https://example.com/data.csv",
        }
        
        result = await discover_source("test_source", config)
        
        assert result.total_found == 1
        assert result.urls[0].url == "https://example.com/data.csv"
    
    @pytest.mark.asyncio
    async def test_discover_source_with_client(self) -> None:
        """Testa função utilitária com cliente HTTP."""
        config = {
            "mode": "static_url",
            "url": "https://example.com/data.csv",
        }
        
        async with httpx.AsyncClient() as client:
            result = await discover_source("test_source", config, client)
        
        assert result.total_found == 1
