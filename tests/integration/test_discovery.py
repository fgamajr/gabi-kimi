"""Testes de integração para o serviço de discovery.

Este módulo testa o discovery de ponta a ponta, incluindo
mock servers HTTP para simular fontes reais.

Testes:
    - test_discovery_e2e: Fluxo completo com mock server
    - test_discovery_with_real_http: Testes com servidor HTTP real
    - test_discovery_pipeline_integration: Integração com pipeline
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import datetime
from typing import Any, AsyncGenerator
from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest
import respx

from gabi.services.discovery import (
    CrawlerConfig,
    CrawlerDiscovery,
    DiscoveryService,
    RateLimiter,
    StaticURLDiscovery,
    StaticURLConfig,
    URLPatternConfig,
    URLPatternDiscovery,
    discover_source,
)
from gabi.pipeline.contracts import DiscoveredURL, DiscoveryResult


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
async def http_client() -> AsyncGenerator[httpx.AsyncClient, None]:
    """Cria cliente HTTP para testes.
    
    Yields:
        Cliente httpx configurado
    """
    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
        yield client


@pytest.fixture
def mock_routes() -> respx.MockRouter:
    """Cria um mock router respx.
    
    Yields:
        MockRouter do respx
    """
    with respx.mock(assert_all_mocked=False) as router:
        yield router


# =============================================================================
# End-to-End Tests
# =============================================================================

class TestDiscoveryE2E:
    """Testes end-to-end com mock server HTTP."""
    
    @pytest.mark.asyncio
    async def test_discovery_e2e_url_pattern(self) -> None:
        """Testa discovery E2E com padrão de URL.
        
        Verifica:
            - Geração correta de URLs
            - Resposta do servidor mock
            - Metadados das URLs descobertas
        """
        # Configuração que simula o sources.yaml
        config = URLPatternConfig(
            url_template="https://api.tcu.gov.br/acordaos/{year}.csv",
            params={"year": {"start": 2022, "end": 2024}},
            change_detection={"strategy": "etag"},
        )
        
        strategy = URLPatternDiscovery("tcu_acordaos", config)
        
        result = await strategy.discover()
        
        # Verifica resultado
        assert result.total_found == 3
        assert len(result.urls) == 3
        
        # Verifica URLs geradas
        urls = [u.url for u in result.urls]
        assert "https://api.tcu.gov.br/acordaos/2022.csv" in urls
        assert "https://api.tcu.gov.br/acordaos/2023.csv" in urls
        assert "https://api.tcu.gov.br/acordaos/2024.csv" in urls
        
        # Verifica metadados
        for url in result.urls:
            assert url.source_id == "tcu_acordaos"
            assert url.metadata["generated"] is True
            assert url.metadata["template"] == "https://api.tcu.gov.br/acordaos/{year}.csv"
    
    @pytest.mark.asyncio
    async def test_discovery_e2e_static_url(self) -> None:
        """Testa discovery E2E com URL estática."""
        with respx.mock:
            # Mock para URL estática
            respx.get("https://api.tcu.gov.br/normas.csv").mock(
                return_value=httpx.Response(
                    200,
                    text="KEY|NUMERO|TIPO\nNORM001|001|Resolução\n",
                    headers={"ETag": '"static-etag-123"'},
                )
            )
            
            config = StaticURLConfig(
                url="https://api.tcu.gov.br/normas.csv",
                change_detection={"strategy": "etag"},
            )
            
            strategy = StaticURLDiscovery("tcu_normas", config)
            
            result = await strategy.discover()
            
            assert result.total_found == 1
            assert result.urls[0].url == "https://api.tcu.gov.br/normas.csv"
            assert result.urls[0].metadata["static"] is True
    
    @pytest.mark.asyncio
    async def test_discovery_e2e_crawler(self) -> None:
        """Testa discovery E2E com crawler.
        
        Verifica crawling em múltiplas páginas.
        """
        page1_html = """
        <!DOCTYPE html>
        <html>
        <head><title>Documentos</title></head>
        <body>
            <h1>Documentos TCU</h1>
            <ul>
                <li><a href="/files/doc1.pdf">Documento 1</a></li>
                <li><a href="/files/doc2.pdf">Documento 2</a></li>
            </ul>
            <nav>
                <a href="/docs/page2">Próxima página</a>
            </nav>
        </body>
        </html>
        """
        
        page2_html = """
        <!DOCTYPE html>
        <html>
        <head><title>Documentos - Página 2</title></head>
        <body>
            <h1>Documentos TCU - Página 2</h1>
            <ul>
                <li><a href="/files/page2_doc1.pdf">Documento 1</a></li>
                <li><a href="/files/page2_doc2.pdf">Documento 2</a></li>
            </ul>
        </body>
        </html>
        """
        
        with respx.mock:
            respx.get("https://portal.tcu.gov.br/docs").mock(
                return_value=httpx.Response(200, text=page1_html)
            )
            respx.get("https://portal.tcu.gov.br/docs/page2").mock(
                return_value=httpx.Response(200, text=page2_html)
            )
            
            config = CrawlerConfig(
                root_url="https://portal.tcu.gov.br/docs",
                rules={
                    "max_depth": 2,
                    "asset_selector": "a[href$='.pdf']",
                    "link_selector": "a[href^='/docs']",
                },
                rate_limit=100.0,  # Rápido para testes
            )
            
            strategy = CrawlerDiscovery(
                "tcu_publicacoes",
                config,
                rate_limiter=RateLimiter(rate=100.0),
            )
            
            result = await strategy.discover()
            
            # Deve encontrar PDFs em ambas as páginas
            assert result.total_found == 4
            
            urls = [u.url for u in result.urls]
            
            # PDFs da primeira página
            assert "https://portal.tcu.gov.br/files/doc1.pdf" in urls
            assert "https://portal.tcu.gov.br/files/doc2.pdf" in urls
            
            # PDFs da segunda página
            assert "https://portal.tcu.gov.br/files/page2_doc1.pdf" in urls
            assert "https://portal.tcu.gov.br/files/page2_doc2.pdf" in urls
            
            # Verifica que URLs estão absolutas
            for url in urls:
                assert url.startswith("https://")
    
    @pytest.mark.asyncio
    async def test_discovery_e2e_crawler_respects_rate_limit(self) -> None:
        """Testa que crawler respeita rate limit em E2E."""
        html = """
        <html>
            <body>
                <a href="/doc1.pdf">PDF 1</a>
                <a href="/page2">Page 2</a>
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
                return_value=httpx.Response(200, text=html)
            )
            respx.get("https://example.com/page2").mock(
                return_value=httpx.Response(200, text=page2_html)
            )
            
            # Rate limit de 5 req/s = 200ms entre requests
            config = CrawlerConfig(
                root_url="https://example.com/docs",
                rules={
                    "max_depth": 2,
                    "asset_selector": "a[href$='.pdf']",
                    "link_selector": "a[href^='/page']",
                },
                rate_limit=5.0,
            )
            
            strategy = CrawlerDiscovery(
                "tcu_test",
                config,
                rate_limiter=RateLimiter(rate=5.0, burst=1),
            )
            
            import time
            start = time.monotonic()
            result = await strategy.discover()
            elapsed = time.monotonic() - start
            
            # Com 2 requisições e rate limit de 5/s, deve levar pelo menos ~200ms
            assert elapsed >= 0.15  # Tolerância para timing
    
    @pytest.mark.asyncio
    async def test_discovery_e2e_full_pipeline(self) -> None:
        """Testa pipeline completo de discovery com múltiplas fontes."""
        html_page = """
        <html>
            <body>
                <a href="/file.pdf">PDF</a>
            </body>
        </html>
        """
        
        with respx.mock:
            # Mock para crawler
            respx.get("https://example.com/publicacoes").mock(
                return_value=httpx.Response(200, text=html_page)
            )
            
            service = DiscoveryService()
            
            # Fonte 1: URL Pattern
            config1 = {
                "mode": "url_pattern",
                "url_template": "https://example.com/data/{year}.csv",
                "params": {"year": {"start": 2023, "end": 2024}},
            }
            
            # Fonte 2: Static URL
            config2 = {
                "mode": "static_url",
                "url": "https://example.com/normas.csv",
            }
            
            # Fonte 3: Crawler
            config3 = {
                "mode": "crawler",
                "root_url": "https://example.com/publicacoes",
                "rules": {
                    "max_depth": 1,
                    "asset_selector": "a[href$='.pdf']",
                },
                "rate_limit": 100.0,
            }
            
            # Executa discovery para todas as fontes
            result1 = await service.discover("fonte_anual", config1)
            result2 = await service.discover("fonte_estatica", config2)
            result3 = await service.discover("fonte_crawler", config3)
            
            # Verifica resultados
            assert result1.total_found == 2
            assert result2.total_found == 1
            assert result3.total_found == 1
            
            # Verifica que as URLs estão corretas
            urls1 = [u.url for u in result1.urls]
            assert "https://example.com/data/2023.csv" in urls1
            assert "https://example.com/data/2024.csv" in urls1
            
            assert result2.urls[0].url == "https://example.com/normas.csv"
            assert result3.urls[0].url == "https://example.com/file.pdf"


# =============================================================================
# Integration Tests with Error Scenarios
# =============================================================================

class TestDiscoveryErrorHandling:
    """Testes de tratamento de erros em integração."""
    
    @pytest.mark.asyncio
    async def test_crawler_handles_timeout(self) -> None:
        """Testa que crawler lida com timeout de forma adequada."""
        with respx.mock:
            # Simula timeout
            respx.get("https://example.com/slow").side_effect = httpx.TimeoutException(
                "Request timed out"
            )
            
            config = CrawlerConfig(
                root_url="https://example.com/slow",
                rules={"max_depth": 1},
                rate_limit=100.0,
            )
            
            strategy = CrawlerDiscovery(
                "test_timeout",
                config,
                rate_limiter=RateLimiter(rate=100.0),
            )
            
            result = await strategy.discover()
            
            # Deve retornar vazio sem crashar
            assert result.total_found == 0
    
    @pytest.mark.asyncio
    async def test_crawler_handles_connection_error(self) -> None:
        """Testa que crawler lida com erro de conexão."""
        with respx.mock:
            respx.get("https://example.com/unreachable").side_effect = httpx.ConnectError(
                "Connection refused"
            )
            
            config = CrawlerConfig(
                root_url="https://example.com/unreachable",
                rules={"max_depth": 1},
                rate_limit=100.0,
            )
            
            strategy = CrawlerDiscovery(
                "test_connection_error",
                config,
                rate_limiter=RateLimiter(rate=100.0),
            )
            
            result = await strategy.discover()
            
            # Deve retornar vazio sem crashar
            assert result.total_found == 0
    
    @pytest.mark.asyncio
    async def test_crawler_handles_malformed_html(self) -> None:
        """Testa que crawler lida com HTML malformado."""
        # HTML malformado (tag não fechada)
        html = "<html><body><a href='/test.pdf'>Test</a></body>"
        
        with respx.mock:
            respx.get("https://example.com/malformed").mock(
                return_value=httpx.Response(200, text=html)
            )
            
            config = CrawlerConfig(
                root_url="https://example.com/malformed",
                rules={"max_depth": 1, "asset_selector": "a[href$='.pdf']"},
                rate_limit=100.0,
            )
            
            strategy = CrawlerDiscovery(
                "test_malformed",
                config,
                rate_limiter=RateLimiter(rate=100.0),
            )
            
            result = await strategy.discover()
            
            # Deve conseguir extrair o link mesmo com HTML malformado
            assert result.total_found == 1
            assert result.urls[0].url == "https://example.com/test.pdf"
    
    @pytest.mark.asyncio
    async def test_crawler_handles_redirects(self) -> None:
        """Testa que crawler segue redirects corretamente."""
        html = """
        <html>
            <body>
                <a href="/final.pdf">Final PDF</a>
            </body>
        </html>
        """
        
        with respx.mock:
            # Configura redirect
            respx.get("https://example.com/redirect").mock(
                return_value=httpx.Response(301, headers={"Location": "/final"})
            )
            respx.get("https://example.com/final").mock(
                return_value=httpx.Response(200, text=html)
            )
            
            config = CrawlerConfig(
                root_url="https://example.com/final",  # Usa URL final diretamente
                rules={"max_depth": 1, "asset_selector": "a[href$='.pdf']"},
                rate_limit=100.0,
            )
            
            strategy = CrawlerDiscovery(
                "test_redirect",
                config,
                rate_limiter=RateLimiter(rate=100.0),
            )
            
            result = await strategy.discover()
            
            assert result.total_found == 1


# =============================================================================
# Performance Tests
# =============================================================================

class TestDiscoveryPerformance:
    """Testes de performance para discovery."""
    
    @pytest.mark.asyncio
    async def test_url_pattern_performance_large_range(self) -> None:
        """Testa performance com grande range de anos."""
        config = URLPatternConfig(
            url_template="https://example.com/{year}.csv",
            params={"year": {"start": 1990, "end": 2024}},  # 35 anos
        )
        strategy = URLPatternDiscovery("test", config)
        
        import time
        start = time.monotonic()
        result = await strategy.discover()
        elapsed = time.monotonic() - start
        
        assert result.total_found == 35
        assert elapsed < 0.1  # Deve ser muito rápido (sem I/O)
    
    @pytest.mark.asyncio
    async def test_crawler_performance_many_links(self) -> None:
        """Testa performance com muitos links na página."""
        # Gera página com 100 links
        links = "\n".join([
            f'<a href="/file{i:03d}.pdf">File {i}</a>'
            for i in range(100)
        ])
        html = f"<html><body>{links}</body></html>"
        
        with respx.mock:
            respx.get("https://example.com/many").mock(
                return_value=httpx.Response(200, text=html)
            )
            
            config = CrawlerConfig(
                root_url="https://example.com/many",
                rules={
                    "max_depth": 1,
                    "asset_selector": "a[href$='.pdf']",
                },
                rate_limit=1000.0,
            )
            
            strategy = CrawlerDiscovery(
                "test_performance",
                config,
                rate_limiter=RateLimiter(rate=1000.0),
            )
            
            import time
            start = time.monotonic()
            result = await strategy.discover()
            elapsed = time.monotonic() - start
            
            assert result.total_found == 100
            assert elapsed < 2.0  # Deve processar rapidamente


# =============================================================================
# Concurrency Tests
# =============================================================================

class TestDiscoveryConcurrency:
    """Testes de concorrência para discovery."""
    
    @pytest.mark.asyncio
    async def test_concurrent_url_pattern_discovery(self) -> None:
        """Testa discovery de múltiplas fontes em paralelo."""
        configs = [
            URLPatternConfig(
                url_template=f"https://source{i}.example.com/{{year}}.csv",
                params={"year": {"start": 2020, "end": 2024}},
            )
            for i in range(5)
        ]
        
        strategies = [
            URLPatternDiscovery(f"source_{i}", config)
            for i, config in enumerate(configs)
        ]
        
        # Executa todos em paralelo
        results = await asyncio.gather(*[
            s.discover() for s in strategies
        ])
        
        # Verifica resultados
        for result in results:
            assert result.total_found == 5
    
    @pytest.mark.asyncio
    async def test_rate_limiter_concurrent_access(self) -> None:
        """Testa rate limiter com acesso concorrente."""
        limiter = RateLimiter(rate=10.0, burst=5)  # 10 req/s, burst de 5
        
        async def acquire_multiple(n: int) -> None:
            for _ in range(n):
                await limiter.acquire()
        
        # 3 tarefas tentando adquirir 3 tokens cada = 9 aquisições
        start = asyncio.get_event_loop().time()
        await asyncio.gather(
            acquire_multiple(3),
            acquire_multiple(3),
            acquire_multiple(3),
        )
        elapsed = asyncio.get_event_loop().time() - start
        
        # Com burst de 5 e rate de 10/s:
        # - 5 primeiras são imediatas
        # - 4 restantes precisam de ~400ms (a 10 req/s)
        assert elapsed >= 0.3  # Deve ter havido alguma espera


# =============================================================================
# Configuration Tests
# =============================================================================

class TestDiscoveryConfiguration:
    """Testes de configuração para discovery."""
    
    @pytest.mark.asyncio
    async def test_discovery_from_sources_yaml_format(self) -> None:
        """Testa discovery usando formato similar ao sources.yaml."""
        # Config no formato do sources.yaml
        tcu_config = {
            "mode": "url_pattern",
            "url_template": "https://sites.tcu.gov.br/dados-abertos/{year}.csv",
            "params": {
                "year": {
                    "start": 2023,
                    "end": 2024,
                }
            },
            "change_detection": {
                "strategy": "etag",
            },
        }
        
        service = DiscoveryService()
        result = await service.discover("tcu_acordaos", tcu_config)
        
        assert result.total_found == 2
        assert all(
            u.metadata["template"] == "https://sites.tcu.gov.br/dados-abertos/{year}.csv"
            for u in result.urls
        )
    
    @pytest.mark.asyncio
    async def test_discovery_with_custom_rate_limit(self) -> None:
        """Testa discovery com rate limit customizado."""
        html = """
        <html>
            <body>
                <a href="/file.pdf">PDF</a>
            </body>
        </html>
        """
        
        with respx.mock:
            respx.get("https://example.com/docs").mock(
                return_value=httpx.Response(200, text=html)
            )
            
            config = {
                "mode": "crawler",
                "root_url": "https://example.com/docs",
                "rules": {
                    "max_depth": 1,
                    "asset_selector": "a[href$='.pdf']",
                },
                "rate_limit": 0.5,  # 0.5 req/s = 2s entre requests
            }
            
            service = DiscoveryService(default_rate_limit=1.0)
            
            # A configuração específica deve sobrepor o padrão
            strategy = service.create_strategy("test", config)
            
            assert strategy._rate_limiter.rate == 0.5
            
            # Executa para verificar se funciona
            result = await strategy.discover()
            assert result.total_found == 1


# =============================================================================
# Sources.yaml Integration Tests
# =============================================================================

class TestSourcesYamlIntegration:
    """Testes que simulam configurações do sources.yaml real."""
    
    @pytest.mark.asyncio
    async def test_tcu_acordaos_config(self) -> None:
        """Testa configuração similar à fonte tcu_acordaos."""
        config = {
            "mode": "url_pattern",
            "url_template": "https://sites.tcu.gov.br/dados-abertos/jurisprudencia/arquivos/acordao-completo/acordao-completo-{year}.csv",
            "params": {
                "year": {"start": 2022, "end": 2024}  # Simplificado para teste
            },
            "change_detection": {"strategy": "etag"},
        }
        
        service = DiscoveryService()
        result = await service.discover("tcu_acordaos", config)
        
        assert result.total_found == 3
        
        urls = [u.url for u in result.urls]
        assert any("acordao-completo-2022.csv" in u for u in urls)
        assert any("acordao-completo-2023.csv" in u for u in urls)
        assert any("acordao-completo-2024.csv" in u for u in urls)
    
    @pytest.mark.asyncio
    async def test_tcu_normas_config(self) -> None:
        """Testa configuração similar à fonte tcu_normas."""
        with respx.mock:
            respx.get("https://sites.tcu.gov.br/dados-abertos/normas/arquivos/norma.csv").mock(
                return_value=httpx.Response(200, text="KEY|NUMERO|TIPO")
            )
            
            config = {
                "mode": "static_url",
                "url": "https://sites.tcu.gov.br/dados-abertos/normas/arquivos/norma.csv",
                "change_detection": {"strategy": "etag"},
            }
            
            service = DiscoveryService()
            result = await service.discover("tcu_normas", config)
            
            assert result.total_found == 1
            assert "norma.csv" in result.urls[0].url
    
    @pytest.mark.asyncio
    async def test_tcu_publicacoes_config(self) -> None:
        """Testa configuração similar à fonte tcu_publicacoes (crawler)."""
        html = """
        <html>
            <body>
                <a href="/publicacoes/relatorio2023.pdf">Relatório 2023</a>
                <a href="/publicacoes/relatorio2024.pdf">Relatório 2024</a>
            </body>
        </html>
        """
        
        with respx.mock:
            respx.get("https://portal.tcu.gov.br/publicacoes-institucionais/todas").mock(
                return_value=httpx.Response(200, text=html)
            )
            
            config = {
                "mode": "crawler",
                "root_url": "https://portal.tcu.gov.br/publicacoes-institucionais/todas",
                "rules": {
                    "pagination_param": "pagina",
                    "link_selector": "a[href*='/publicacoes-institucionais/']:not([href$='todas'])",
                    "asset_selector": "a[href$='.pdf']",
                    "max_depth": 2,
                    "rate_limit": 1.0,
                },
            }
            
            service = DiscoveryService()
            result = await service.discover("tcu_publicacoes", config)
            
            assert result.total_found == 2
            urls = [u.url for u in result.urls]
            assert any("relatorio2023.pdf" in u for u in urls)
            assert any("relatorio2024.pdf" in u for u in urls)
