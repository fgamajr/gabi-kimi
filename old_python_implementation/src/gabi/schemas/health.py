"""Health check schemas for GABI API."""

from typing import Optional, Dict, Any
from pydantic import BaseModel, Field
from datetime import datetime
from enum import Enum


class HealthStatus(str, Enum):
    """Status de saúde do sistema."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


class ComponentStatus(BaseModel):
    """Status de um componente do sistema."""
    name: str = Field(..., description="Nome do componente")
    status: HealthStatus = Field(..., description="Status do componente")
    response_time_ms: Optional[float] = Field(None, description="Tempo de resposta em ms")
    message: Optional[str] = Field(None, description="Mensagem descritiva")
    last_check: datetime = Field(default_factory=datetime.utcnow, description="Último check")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Metadados adicionais")


class HealthResponse(BaseModel):
    """Resposta do health check geral."""
    status: HealthStatus = Field(..., description="Status geral do sistema")
    version: str = Field(..., description="Versão da API")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Timestamp do check")
    uptime_seconds: Optional[float] = Field(None, description="Uptime em segundos")
    components: list[ComponentStatus] = Field(default_factory=list, description="Status dos componentes")
    environment: Optional[str] = Field(None, description="Ambiente (dev/staging/prod)")


class LivenessResponse(BaseModel):
    """Resposta do liveness probe."""
    alive: bool = Field(..., description="Indica se a aplicação está viva")
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class ReadinessCheck(BaseModel):
    """Check individual de readiness."""
    name: str = Field(..., description="Nome do check")
    ready: bool = Field(..., description="Está pronto?")
    critical: bool = Field(default=True, description="Se True, falha impede readiness")
    message: Optional[str] = Field(None, description="Mensagem descritiva")
    response_time_ms: Optional[float] = Field(None, description="Tempo de resposta")


class ReadinessResponse(BaseModel):
    """Resposta do readiness probe."""
    ready: bool = Field(..., description="Indica se a aplicação está pronta para receber tráfego")
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    checks: list[ReadinessCheck] = Field(default_factory=list, description="Checks individuais")
