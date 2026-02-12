"""Crawler - Coleta e indexação de documentos.

Módulo de crawling multi-agente com suporte a:
- Navegação via Playwright
- Respeito a robots.txt
- Rate limiting e politeness
- Orquestração de múltiplos agents
"""

from .base_agent import (
    AgentStats,
    BaseCrawlerAgent,
    CrawlResult,
)
from .navigator import (
    Navigator,
    PlaywrightCrawlerAgent,
    RateLimiter,
    RobotsCache,
)
from .orchestrator import (
    CrawlJob,
    Orchestrator,
    OrchestratorConfig,
    OrchestratorStats,
)

__all__ = [
    # Base Agent
    "BaseCrawlerAgent",
    "CrawlResult",
    "AgentStats",
    # Navigator
    "Navigator",
    "PlaywrightCrawlerAgent",
    "RateLimiter",
    "RobotsCache",
    # Orchestrator
    "Orchestrator",
    "OrchestratorConfig",
    "OrchestratorStats",
    "CrawlJob",
]
