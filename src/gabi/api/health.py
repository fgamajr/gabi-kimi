"""Health check endpoints for GABI API.

Este módulo fornece endpoints de health check para monitoramento
e orquestração de containers (Kubernetes/Docker).

Endpoints:
- GET /health: Status geral do sistema
- GET /health/live: Liveness probe
- GET /health/ready: Readiness probe
"""

import time
from datetime import datetime
from typing import Dict, Any

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from gabi.db import get_db_session, get_redis_client, get_es_client
from gabi.schemas.health import (
    HealthResponse,
    HealthStatus,
    ComponentStatus,
    LivenessResponse,
    ReadinessResponse,
    ReadinessCheck,
)

router = APIRouter(tags=["health"])

# Startup timestamp para cálculo de uptime
_STARTUP_TIME = time.time()


async def check_database(db: AsyncSession) -> ComponentStatus:
    """Verifica saúde do banco de dados.
    
    Args:
        db: Sessão do banco de dados
        
    Returns:
        ComponentStatus com resultado do check
    """
    start = time.time()
    try:
        result = await db.execute(text("SELECT 1"))
        await result.scalar_one()
        response_time = (time.time() - start) * 1000
        return ComponentStatus(
            name="database",
            status=HealthStatus.HEALTHY,
            response_time_ms=round(response_time, 2),
            message="PostgreSQL responding",
        )
    except Exception as e:
        response_time = (time.time() - start) * 1000
        return ComponentStatus(
            name="database",
            status=HealthStatus.UNHEALTHY,
            response_time_ms=round(response_time, 2),
            message=f"PostgreSQL error: {str(e)}",
        )


async def check_elasticsearch() -> ComponentStatus:
    """Verifica saúde do Elasticsearch.
    
    Returns:
        ComponentStatus com resultado do check
    """
    start = time.time()
    try:
        es_client = get_es_client()
        info = await es_client.info()
        response_time = (time.time() - start) * 1000
        return ComponentStatus(
            name="elasticsearch",
            status=HealthStatus.HEALTHY,
            response_time_ms=round(response_time, 2),
            message=f"Elasticsearch {info.get('version', {}).get('number', 'unknown')} responding",
        )
    except Exception as e:
        response_time = (time.time() - start) * 1000
        return ComponentStatus(
            name="elasticsearch",
            status=HealthStatus.UNHEALTHY,
            response_time_ms=round(response_time, 2),
            message=f"Elasticsearch error: {str(e)}",
        )


async def check_redis() -> ComponentStatus:
    """Verifica saúde do Redis.
    
    Returns:
        ComponentStatus com resultado do check
    """
    start = time.time()
    try:
        redis_client = get_redis_client()
        await redis_client.ping()
        response_time = (time.time() - start) * 1000
        return ComponentStatus(
            name="redis",
            status=HealthStatus.HEALTHY,
            response_time_ms=round(response_time, 2),
            message="Redis responding",
        )
    except Exception as e:
        response_time = (time.time() - start) * 1000
        return ComponentStatus(
            name="redis",
            status=HealthStatus.UNHEALTHY,
            response_time_ms=round(response_time, 2),
            message=f"Redis error: {str(e)}",
        )


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Health check geral",
    description="Retorna o status geral do sistema e seus componentes.",
)
async def health_check(db: AsyncSession = Depends(get_db_session)) -> HealthResponse:
    """Health check geral do sistema.
    
    Verifica:
    - Conectividade com PostgreSQL
    - Status geral da aplicação
    - Uptime
    
    Returns:
        HealthResponse com status detalhado
    """
    components: list[ComponentStatus] = []
    
    # Check database
    db_status = await check_database(db)
    components.append(db_status)
    
    # Check Elasticsearch
    es_status = await check_elasticsearch()
    components.append(es_status)
    
    # Check Redis
    redis_status = await check_redis()
    components.append(redis_status)
    
    # Determina status geral
    # Only database is critical - others are optional
    db_status = next((c.status for c in components if c.name == "database"), HealthStatus.HEALTHY)
    if db_status == HealthStatus.UNHEALTHY:
        overall_status = HealthStatus.UNHEALTHY
    elif any(c.status == HealthStatus.UNHEALTHY for c in components if c.name != "database"):
        # Non-critical components unhealthy = degraded overall
        overall_status = HealthStatus.DEGRADED
    elif any(c.status == HealthStatus.DEGRADED for c in components):
        overall_status = HealthStatus.DEGRADED
    else:
        overall_status = HealthStatus.HEALTHY
    
    return HealthResponse(
        status=overall_status,
        version="1.0.0",  # TODO: Pegar do settings/config
        timestamp=datetime.utcnow(),
        uptime_seconds=round(time.time() - _STARTUP_TIME, 2),
        components=components,
        environment="production",  # TODO: Pegar do settings
    )


@router.get(
    "/health/live",
    response_model=LivenessResponse,
    summary="Liveness probe",
    description="Indica se a aplicação está viva (não travou/deadlock).",
)
async def liveness_check() -> LivenessResponse:
    """Liveness probe para Kubernetes.
    
    Este endpoint deve retornar 200 se a aplicação está viva,
    mesmo que não esteja pronta para receber tráfego.
    
    Returns:
        LivenessResponse com alive=True
    """
    return LivenessResponse(alive=True)


@router.get(
    "/health/ready",
    response_model=ReadinessResponse,
    summary="Readiness probe",
    description="Indica se a aplicação está pronta para receber tráfego.",
)
async def readiness_check(db: AsyncSession = Depends(get_db_session)) -> ReadinessResponse:
    """Readiness probe para Kubernetes.
    
    Verifica se todos os componentes críticos estão prontos:
    - Banco de dados (crítico)
    
    Returns:
        ReadinessResponse indicando se está pronto
    """
    checks: list[ReadinessCheck] = []
    all_ready = True
    
    # Check database (crítico)
    start = time.time()
    try:
        await db.execute(text("SELECT 1"))
        db_time = (time.time() - start) * 1000
        checks.append(ReadinessCheck(
            name="database",
            ready=True,
            critical=True,
            message="PostgreSQL ready",
            response_time_ms=round(db_time, 2),
        ))
    except Exception as e:
        db_time = (time.time() - start) * 1000
        checks.append(ReadinessCheck(
            name="database",
            ready=False,
            critical=True,
            message=f"PostgreSQL not ready: {str(e)}",
            response_time_ms=round(db_time, 2),
        ))
        all_ready = False
    
    # Check Elasticsearch (não crítico)
    start = time.time()
    try:
        es_client = get_es_client()
        await es_client.info()
        es_time = (time.time() - start) * 1000
        checks.append(ReadinessCheck(
            name="elasticsearch",
            ready=True,
            critical=False,
            message="Elasticsearch ready",
            response_time_ms=round(es_time, 2),
        ))
    except Exception as e:
        es_time = (time.time() - start) * 1000
        checks.append(ReadinessCheck(
            name="elasticsearch",
            ready=False,
            critical=False,
            message=f"Elasticsearch not ready: {str(e)}",
            response_time_ms=round(es_time, 2),
        ))
    
    # Check Redis (não crítico)
    start = time.time()
    try:
        redis_client = get_redis_client()
        await redis_client.ping()
        redis_time = (time.time() - start) * 1000
        checks.append(ReadinessCheck(
            name="redis",
            ready=True,
            critical=False,
            message="Redis ready",
            response_time_ms=round(redis_time, 2),
        ))
    except Exception as e:
        redis_time = (time.time() - start) * 1000
        checks.append(ReadinessCheck(
            name="redis",
            ready=False,
            critical=False,
            message=f"Redis not ready: {str(e)}",
            response_time_ms=round(redis_time, 2),
        ))
    
    return ReadinessResponse(
        ready=all_ready,
        timestamp=datetime.utcnow(),
        checks=checks,
    )
