"""Tasks de health check para o GABI.

Verifica saúde de todos os serviços dependentes:
- PostgreSQL
- Redis
- Elasticsearch
- TEI (embeddings)
- Celery workers

Baseado em GABI_SPECS_FINAL_v1.md §2.9
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import aiohttp
import redis.asyncio as redis
from elasticsearch import AsyncElasticsearch
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from gabi.config import settings
from gabi.worker import celery_app

logger = logging.getLogger(__name__)


# =============================================================================
# Task: Health Check
# =============================================================================

@celery_app.task(
    bind=True,
    name="gabi.tasks.health.health_check_task",
    queue="gabi.health",
    max_retries=0,
    time_limit=60,
)
def health_check_task(self, include_details: bool = False) -> Dict[str, Any]:
    """Executa health check completo de todos os serviços.
    
    Verifica conectividade e saúde de todos os componentes
    necessários para o funcionamento do GABI.
    
    Args:
        include_details: Se True, inclui detalhes adicionais de cada serviço
        
    Returns:
        Dict com status geral e de cada serviço
    """
    logger.info("[health_check_task] Running health check")
    
    try:
        result = asyncio.run(_run_health_check(include_details))
        
        # Determina status geral
        all_healthy = all(
            s.get("status") == "healthy" 
            for s in result.get("services", {}).values()
        )
        result["overall_status"] = "healthy" if all_healthy else "unhealthy"
        
        return result
        
    except Exception as exc:
        logger.exception("[health_check_task] Health check failed")
        return {
            "overall_status": "error",
            "error": str(exc),
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }


# =============================================================================
# Task: Check Specific Service
# =============================================================================

@celery_app.task(
    bind=True,
    name="gabi.tasks.health.check_service_task",
    queue="gabi.health",
    max_retries=2,
    default_retry_delay=5,
)
def check_service_task(self, service_name: str) -> Dict[str, Any]:
    """Verifica saúde de um serviço específico.
    
    Args:
        service_name: Nome do serviço (postgresql, redis, elasticsearch, tei, celery)
        
    Returns:
        Dict com status do serviço
    """
    logger.info(f"[check_service_task] Checking service: {service_name}")
    
    try:
        return asyncio.run(_check_single_service(service_name))
    except Exception as exc:
        logger.exception(f"[check_service_task] Failed to check {service_name}")
        raise self.retry(exc=exc)


# =============================================================================
# Implementation
# =============================================================================

@dataclass
class HealthResult:
    """Resultado de health check de um serviço."""
    name: str
    status: str  # healthy, unhealthy, unknown
    response_time_ms: float
    message: str = ""
    details: Dict[str, Any] = field(default_factory=dict)


async def _run_health_check(include_details: bool = False) -> Dict[str, Any]:
    """Executa health checks em paralelo.
    
    Args:
        include_details: Incluir detalhes adicionais
        
    Returns:
        Resultado consolidado
    """
    start_time = datetime.now(timezone.utc)
    
    # Executa todos os checks em paralelo
    results = await asyncio.gather(
        _check_postgresql(include_details),
        _check_redis(include_details),
        _check_elasticsearch(include_details),
        _check_tei(include_details),
        _check_celery(include_details),
        return_exceptions=True,
    )
    
    services = {}
    for result in results:
        if isinstance(result, Exception):
            logger.error(f"Health check exception: {result}")
            continue
        services[result.name] = {
            "status": result.status,
            "response_time_ms": result.response_time_ms,
            "message": result.message,
        }
        if include_details:
            services[result.name]["details"] = result.details
    
    return {
        "services": services,
        "checked_at": start_time.isoformat(),
        "check_duration_ms": (
            datetime.now(timezone.utc) - start_time
        ).total_seconds() * 1000,
    }


async def _check_single_service(service_name: str) -> Dict[str, Any]:
    """Verifica um serviço específico.
    
    Args:
        service_name: Nome do serviço
        
    Returns:
        Status do serviço
    """
    checkers = {
        "postgresql": _check_postgresql,
        "redis": _check_redis,
        "elasticsearch": _check_elasticsearch,
        "tei": _check_tei,
        "celery": _check_celery,
    }
    
    checker = checkers.get(service_name.lower())
    if not checker:
        return {
            "name": service_name,
            "status": "unknown",
            "error": f"Unknown service: {service_name}",
        }
    
    result = await checker(include_details=True)
    return {
        "name": result.name,
        "status": result.status,
        "response_time_ms": result.response_time_ms,
        "message": result.message,
        "details": result.details,
    }


# =============================================================================
# Individual Service Checks
# =============================================================================

async def _check_postgresql(include_details: bool = False) -> HealthResult:
    """Verifica conectividade com PostgreSQL."""
    start = datetime.now(timezone.utc)
    details = {}
    
    try:
        # Cria engine temporário para teste
        engine = create_async_engine(
            settings.database_url.replace("postgresql://", "postgresql+asyncpg://"),
            pool_size=1,
            max_overflow=0,
        )
        
        async with engine.connect() as conn:
            # Testa conexão básica
            result = await conn.execute(text("SELECT 1"))
            await result.fetchone()
            
            # Detalhes adicionais
            if include_details:
                # Versão
                version_result = await conn.execute(text("SELECT version()"))
                version_row = await version_result.fetchone()
                details["version"] = version_row[0] if version_row else "unknown"
                
                # Conexões ativas
                active_result = await conn.execute(
                    text("SELECT count(*) FROM pg_stat_activity")
                )
                active_row = await active_result.fetchone()
                details["active_connections"] = active_row[0] if active_row else 0
                
                # Database size
                size_result = await conn.execute(
                    text("SELECT pg_database_size(current_database())")
                )
                size_row = await size_result.fetchone()
                details["database_size_bytes"] = size_row[0] if size_row else 0
        
        await engine.dispose()
        
        response_time = (datetime.now(timezone.utc) - start).total_seconds() * 1000
        
        return HealthResult(
            name="postgresql",
            status="healthy",
            response_time_ms=response_time,
            message="PostgreSQL is responding",
            details=details,
        )
        
    except Exception as exc:
        response_time = (datetime.now(timezone.utc) - start).total_seconds() * 1000
        return HealthResult(
            name="postgresql",
            status="unhealthy",
            response_time_ms=response_time,
            message=f"PostgreSQL check failed: {str(exc)}",
            details=details,
        )


async def _check_redis(include_details: bool = False) -> HealthResult:
    """Verifica conectividade com Redis."""
    start = datetime.now(timezone.utc)
    details = {}
    
    try:
        client = redis.from_url(settings.redis_url)
        
        # Testa PING
        pong = await client.ping()
        
        if include_details:
            # Info
            info = await client.info()
            details["version"] = info.get("redis_version", "unknown")
            details["used_memory_mb"] = info.get("used_memory", 0) / (1024 * 1024)
            details["connected_clients"] = info.get("connected_clients", 0)
            
            # DB size
            dbsize = await client.dbsize()
            details["keys_in_db"] = dbsize
        
        await client.close()
        
        response_time = (datetime.now(timezone.utc) - start).total_seconds() * 1000
        
        status = "healthy" if pong else "unhealthy"
        return HealthResult(
            name="redis",
            status=status,
            response_time_ms=response_time,
            message="Redis is responding" if pong else "Redis PING failed",
            details=details,
        )
        
    except Exception as exc:
        response_time = (datetime.now(timezone.utc) - start).total_seconds() * 1000
        return HealthResult(
            name="redis",
            status="unhealthy",
            response_time_ms=response_time,
            message=f"Redis check failed: {str(exc)}",
            details=details,
        )


async def _check_elasticsearch(include_details: bool = False) -> HealthResult:
    """Verifica conectividade com Elasticsearch."""
    start = datetime.now(timezone.utc)
    details = {}
    
    try:
        es = AsyncElasticsearch(
            hosts=[settings.elasticsearch_url],
            timeout=10,
        )
        
        # Testa cluster health
        health = await es.cluster.health()
        cluster_status = health.get("status", "unknown")
        
        if include_details:
            details["cluster_status"] = cluster_status
            details["number_of_nodes"] = health.get("number_of_nodes", 0)
            details["active_shards"] = health.get("active_shards", 0)
            
            # Info
            info = await es.info()
            details["version"] = info.get("version", {}).get("number", "unknown")
            details["cluster_name"] = info.get("cluster_name", "unknown")
        
        await es.close()
        
        response_time = (datetime.now(timezone.utc) - start).total_seconds() * 1000
        
        # Cluster status: green=healthy, yellow=degraded, red=critical
        status = "healthy" if cluster_status == "green" else "unhealthy" if cluster_status == "red" else "degraded"
        
        return HealthResult(
            name="elasticsearch",
            status=status,
            response_time_ms=response_time,
            message=f"Elasticsearch cluster status: {cluster_status}",
            details=details,
        )
        
    except Exception as exc:
        response_time = (datetime.now(timezone.utc) - start).total_seconds() * 1000
        return HealthResult(
            name="elasticsearch",
            status="unhealthy",
            response_time_ms=response_time,
            message=f"Elasticsearch check failed: {str(exc)}",
            details=details,
        )


async def _check_tei(include_details: bool = False) -> HealthResult:
    """Verifica conectividade com TEI (embeddings service)."""
    start = datetime.now(timezone.utc)
    details = {}
    
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
            # Health endpoint do TEI
            async with session.get(f"{settings.embeddings_url}/health") as resp:
                response_time = (datetime.now(timezone.utc) - start).total_seconds() * 1000
                
                if resp.status == 200:
                    if include_details:
                        try:
                            data = await resp.json()
                            details["model_id"] = data.get("model_id", "unknown")
                            details["revision"] = data.get("revision", "unknown")
                        except:
                            pass
                    
                    return HealthResult(
                        name="tei",
                        status="healthy",
                        response_time_ms=response_time,
                        message="TEI is responding",
                        details=details,
                    )
                else:
                    return HealthResult(
                        name="tei",
                        status="unhealthy",
                        response_time_ms=response_time,
                        message=f"TEI returned status {resp.status}",
                        details=details,
                    )
                    
    except asyncio.TimeoutError:
        response_time = (datetime.now(timezone.utc) - start).total_seconds() * 1000
        return HealthResult(
            name="tei",
            status="unhealthy",
            response_time_ms=response_time,
            message="TEI health check timed out",
            details=details,
        )
    except Exception as exc:
        response_time = (datetime.now(timezone.utc) - start).total_seconds() * 1000
        return HealthResult(
            name="tei",
            status="unhealthy",
            response_time_ms=response_time,
            message=f"TEI check failed: {str(exc)}",
            details=details,
        )


async def _check_celery(include_details: bool = False) -> HealthResult:
    """Verifica saúde do Celery."""
    start = datetime.now(timezone.utc)
    details = {}
    
    try:
        # Usa inspect para verificar workers
        from celery.app.control import Inspect
        
        inspect = Inspect(app=celery_app)
        
        # Timeout para não bloquear
        ping = await asyncio.get_event_loop().run_in_executor(
            None, lambda: inspect.ping()
        )
        
        stats = await asyncio.get_event_loop().run_in_executor(
            None, lambda: inspect.stats()
        )
        
        response_time = (datetime.now(timezone.utc) - start).total_seconds() * 1000
        
        if ping:
            workers = list(ping.keys())
            
            if include_details:
                details["active_workers"] = len(workers)
                details["worker_names"] = workers
                
                if stats:
                    total_processed = sum(
                        s.get("total", {}).get("tasks", 0) 
                        for s in stats.values()
                    )
                    details["total_tasks_processed"] = total_processed
            
            return HealthResult(
                name="celery",
                status="healthy",
                response_time_ms=response_time,
                message=f"Celery has {len(workers)} active worker(s)",
                details=details,
            )
        else:
            return HealthResult(
                name="celery",
                status="unhealthy",
                response_time_ms=response_time,
                message="No Celery workers responding to ping",
                details=details,
            )
            
    except Exception as exc:
        response_time = (datetime.now(timezone.utc) - start).total_seconds() * 1000
        return HealthResult(
            name="celery",
            status="unhealthy",
            response_time_ms=response_time,
            message=f"Celery check failed: {str(exc)}",
            details=details,
        )


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    "health_check_task",
    "check_service_task",
]
