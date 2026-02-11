"""Testes unitários para os endpoints de dashboard.

Testa schemas Pydantic, helpers internos e endpoints com mocks.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from gabi.schemas.dashboard import (
    ActivityEvent,
    ComponentHealth,
    DashboardActivityResponse,
    DashboardHealthResponse,
    DashboardPipelineResponse,
    DashboardSourceSummary,
    DashboardStatsResponse,
    PipelineStageInfo,
    TriggerIngestionResponse,
)
from gabi.types import (
    AuditEventType,
    AuditSeverity,
    PipelinePhase,
    SourceStatus,
    SourceType,
)


# =============================================================================
# Schema Tests
# =============================================================================


class TestDashboardSourceSummary:
    """Testes para DashboardSourceSummary schema."""

    def test_minimal_fields(self):
        """Cria instância com campos obrigatórios."""
        s = DashboardSourceSummary(
            id="src-1",
            name="Portal Gov",
            source_type=SourceType.WEB,
            status=SourceStatus.ACTIVE,
            enabled=True,
            document_count=42,
        )
        assert s.id == "src-1"
        assert s.source_type == SourceType.WEB
        assert s.status == SourceStatus.ACTIVE
        assert s.document_count == 42
        assert s.description is None
        assert s.consecutive_errors == 0

    def test_all_fields(self):
        """Cria instância com todos os campos."""
        now = datetime.now(timezone.utc)
        s = DashboardSourceSummary(
            id="src-2",
            name="Portal Educação",
            description="Portal x",
            source_type=SourceType.API,
            status=SourceStatus.DISABLED,
            enabled=False,
            document_count=0,
            last_sync_at=now,
            last_success_at=now,
            consecutive_errors=3,
        )
        assert s.description == "Portal x"
        assert s.enabled is False
        assert s.consecutive_errors == 3

    def test_serializes_enums_as_values(self):
        """Enums são serializados como strings no JSON."""
        s = DashboardSourceSummary(
            id="x",
            name="y",
            source_type=SourceType.WEB,
            status=SourceStatus.ACTIVE,
            enabled=True,
            document_count=1,
        )
        data = s.model_dump(mode="json")
        assert isinstance(data["source_type"], str)
        assert isinstance(data["status"], str)


class TestDashboardStatsResponse:
    """Testes para DashboardStatsResponse schema."""

    def test_defaults(self):
        """Verifica defaults quando há poucos dados."""
        now = datetime.now(timezone.utc)
        r = DashboardStatsResponse(
            sources=[],
            total_documents=0,
            total_chunks=0,
            total_indexed=0,
            total_embeddings=0,
            active_sources=0,
            documents_last_24h=0,
            dlq_pending=0,
            elasticsearch_available=False,
            generated_at=now,
        )
        assert r.total_elastic_docs is None
        assert r.sources == []

    def test_with_sources(self):
        """Verifica inclusão de lista de fontes."""
        now = datetime.now(timezone.utc)
        r = DashboardStatsResponse(
            sources=[
                DashboardSourceSummary(
                    id="1", name="A", source_type=SourceType.WEB,
                    status=SourceStatus.ACTIVE, enabled=True, document_count=5,
                ),
            ],
            total_documents=5,
            total_chunks=20,
            total_indexed=5,
            total_embeddings=20,
            active_sources=1,
            documents_last_24h=2,
            dlq_pending=0,
            elasticsearch_available=True,
            total_elastic_docs=5,
            generated_at=now,
        )
        assert len(r.sources) == 1
        assert r.total_elastic_docs == 5


class TestPipelineStageInfo:
    """Testes para PipelineStageInfo schema."""

    def test_creates_with_enum(self):
        """Cria com PipelinePhase enum."""
        stage = PipelineStageInfo(
            name=PipelinePhase.CHUNKING,
            label="Chunking",
            description="Divide em chunks",
            count=100,
            total=200,
            failed=0,
            status="active",
        )
        assert stage.name == PipelinePhase.CHUNKING
        assert stage.status == "active"

    def test_all_statuses(self):
        """Verifica que aceita todos os valores de status."""
        for status in ("idle", "active", "error"):
            stage = PipelineStageInfo(
                name=PipelinePhase.DISCOVERY,
                label="Descoberta",
                description="desc",
                count=0,
                total=0,
                failed=0,
                status=status,
            )
            assert stage.status == status


class TestDashboardPipelineResponse:
    """Testes para DashboardPipelineResponse schema."""

    def test_nine_stages(self):
        """Verifica que pipeline tem 9 fases."""
        now = datetime.now(timezone.utc)
        stages = [
            PipelineStageInfo(
                name=phase,
                label=phase.value,
                description="desc",
                count=0,
                total=10,
                failed=0,
                status="idle",
            )
            for phase in PipelinePhase
        ]
        r = DashboardPipelineResponse(
            stages=stages,
            overall_status="stalled",
            generated_at=now,
        )
        assert len(r.stages) == 9

    def test_overall_statuses(self):
        """Verifica valores possíveis de overall_status."""
        now = datetime.now(timezone.utc)
        nine_stages = [
            PipelineStageInfo(
                name=phase, label=phase.value, description="desc",
                count=0, total=0, failed=0, status="idle",
            )
            for phase in PipelinePhase
        ]
        for status in ("healthy", "degraded", "stalled"):
            r = DashboardPipelineResponse(
                stages=nine_stages, overall_status=status, generated_at=now,
            )
            assert r.overall_status == status


class TestActivityEvent:
    """Testes para ActivityEvent schema."""

    def test_minimal(self):
        """Cria com campos obrigatórios."""
        now = datetime.now(timezone.utc)
        e = ActivityEvent(
            id="e1",
            timestamp=now,
            event_type=AuditEventType.SYNC_STARTED,
            severity=AuditSeverity.INFO,
            description="Sincronização iniciada",
        )
        assert e.source_id is None
        assert e.details is None
        assert e.run_id is None

    def test_serialization_roundtrip(self):
        """Verifica serialize/deserialize com JSON."""
        now = datetime.now(timezone.utc)
        e = ActivityEvent(
            id="e2",
            timestamp=now,
            event_type=AuditEventType.DOCUMENT_CREATED,
            severity=AuditSeverity.INFO,
            source_id="src-1",
            description="Documento criado",
            details={"key": "value"},
            run_id="run-abc",
        )
        data = e.model_dump(mode="json")
        e2 = ActivityEvent.model_validate(data)
        assert e2.id == "e2"
        assert e2.details == {"key": "value"}


class TestComponentHealth:
    """Testes para ComponentHealth schema."""

    def test_online_component(self):
        """Cria componente online."""
        c = ComponentHealth(
            name="postgresql",
            status="online",
            latency_ms=1.5,
        )
        assert c.version is None
        assert c.details == {}

    def test_offline_with_error(self):
        """Cria componente offline com erro."""
        c = ComponentHealth(
            name="elasticsearch",
            status="offline",
            latency_ms=2000.0,
            details={"error": "Connection refused"},
        )
        assert c.status == "offline"
        assert c.details["error"] == "Connection refused"


class TestDashboardHealthResponse:
    """Testes para DashboardHealthResponse schema."""

    def test_healthy_system(self):
        """Sistema saudável com todos os componentes online."""
        now = datetime.now(timezone.utc)
        r = DashboardHealthResponse(
            status="healthy",
            uptime_seconds=3600.0,
            components=[
                ComponentHealth(name="postgresql", status="online", latency_ms=1.0),
                ComponentHealth(name="elasticsearch", status="online", latency_ms=5.0),
                ComponentHealth(name="redis", status="online", latency_ms=0.5),
                ComponentHealth(name="tei", status="online", latency_ms=20.0),
            ],
            generated_at=now,
        )
        assert r.status == "healthy"
        assert len(r.components) == 4

    def test_degraded_system(self):
        """Sistema degradado com componente offline."""
        now = datetime.now(timezone.utc)
        r = DashboardHealthResponse(
            status="degraded",
            uptime_seconds=100.0,
            components=[
                ComponentHealth(name="postgresql", status="online", latency_ms=1.0),
                ComponentHealth(name="tei", status="offline", latency_ms=2000.0),
            ],
            generated_at=now,
        )
        assert r.status == "degraded"


class TestTriggerIngestionResponse:
    """Testes para TriggerIngestionResponse schema."""

    def test_creates(self):
        """Cria resposta de trigger."""
        now = datetime.now(timezone.utc)
        r = TriggerIngestionResponse(
            message="Ingestion triggered for source src-1",
            source_id="src-1",
            source_name="Portal Gov",
            status="queued",
            timestamp=now,
        )
        assert r.status == "queued"


# =============================================================================
# Helper Function Tests
# =============================================================================


class TestBuildEventDescription:
    """Testes para _build_event_description."""

    def test_basic_description(self):
        from gabi.api.dashboard import _build_event_description

        desc = _build_event_description(
            AuditEventType.SYNC_STARTED, None, None,
        )
        assert desc == "Sincronização iniciada"

    def test_with_resource_id(self):
        from gabi.api.dashboard import _build_event_description

        desc = _build_event_description(
            AuditEventType.DOCUMENT_CREATED, None, "doc-123",
        )
        assert "[doc-123]" in desc

    def test_with_details(self):
        from gabi.api.dashboard import _build_event_description

        desc = _build_event_description(
            AuditEventType.SYNC_COMPLETED,
            {"documents_processed": 15, "duration_seconds": 3.2},
            "run-abc",
        )
        assert "15 docs" in desc
        assert "3.2s" in desc

    def test_with_error_truncation(self):
        from gabi.api.dashboard import _build_event_description

        long_error = "E" * 200
        desc = _build_event_description(
            AuditEventType.SYNC_FAILED,
            {"error_message": long_error},
            None,
        )
        # Error should be truncated to 80 chars
        assert len(desc) < 200


class TestBuildEmptyStages:
    """Testes para _build_empty_stages."""

    def test_returns_nine_stages(self):
        from gabi.api.dashboard import _build_empty_stages

        now = datetime.now(timezone.utc)
        stages = _build_empty_stages(now)
        assert len(stages) == 9

    def test_all_idle_and_zero(self):
        from gabi.api.dashboard import _build_empty_stages

        now = datetime.now(timezone.utc)
        stages = _build_empty_stages(now)
        for stage in stages:
            assert stage.status == "idle"
            assert stage.count == 0
            assert stage.total == 0
            assert stage.failed == 0

    def test_phases_match_enum(self):
        from gabi.api.dashboard import _build_empty_stages

        now = datetime.now(timezone.utc)
        stages = _build_empty_stages(now)
        expected_phases = list(PipelinePhase)
        actual_phases = [s.name for s in stages]
        assert actual_phases == expected_phases


# =============================================================================
# Endpoint Tests (with mocked DB)
# =============================================================================


class TestGetDashboardStats:
    """Testes para GET /stats."""

    @pytest.mark.asyncio
    async def test_returns_stats_empty_db(self):
        """Stats com banco vazio retorna zeros."""
        from gabi.api.dashboard import get_dashboard_stats

        mock_db = AsyncMock()

        # Source query returns empty
        src_result = MagicMock()
        src_result.mappings.return_value = []

        # Counts CTE query returns zeros
        counts_mapping = MagicMock()
        counts_mapping.fetchone.return_value = {
            "active_docs": 0, "indexed_docs": 0, "recent_docs": 0,
            "total_chunks": 0, "embedded_chunks": 0, "pending": 0,
        }
        counts_result = MagicMock()
        counts_result.mappings.return_value = counts_mapping

        mock_db.execute = AsyncMock(side_effect=[src_result, counts_result])

        with patch("gabi.api.dashboard.get_db_session"):
            result = await get_dashboard_stats(db=mock_db, _user={"sub": "u1"})

        assert isinstance(result, DashboardStatsResponse)
        assert result.total_documents == 0
        assert result.sources == []


class TestGetDashboardPipeline:
    """Testes para GET /pipeline."""

    @pytest.mark.asyncio
    async def test_returns_empty_pipeline(self):
        """Pipeline com banco vazio retorna 9 stages idle."""
        from gabi.api.dashboard import get_dashboard_pipeline

        mock_db = AsyncMock()
        result_mock = MagicMock()
        mapping_mock = MagicMock()
        mapping_mock.fetchone.return_value = None
        result_mock.mappings.return_value = mapping_mock
        mock_db.execute = AsyncMock(return_value=result_mock)

        result = await get_dashboard_pipeline(db=mock_db, _user={"sub": "u1"})

        assert isinstance(result, DashboardPipelineResponse)
        assert len(result.stages) == 9
        assert result.overall_status == "stalled"


class TestGetDashboardActivity:
    """Testes para GET /activity."""

    @pytest.mark.asyncio
    async def test_returns_empty_activity(self):
        """Activity sem eventos retorna lista vazia."""
        from gabi.api.dashboard import get_dashboard_activity

        mock_db = AsyncMock()

        # Count returns 0
        count_result = MagicMock()
        count_result.scalar.return_value = 0

        # Rows return empty
        rows_result = MagicMock()
        rows_mapping = MagicMock()
        rows_mapping.fetchall.return_value = []
        rows_result.mappings.return_value = rows_mapping

        mock_db.execute = AsyncMock(side_effect=[count_result, rows_result])

        result = await get_dashboard_activity(
            db=mock_db, _user={"sub": "u1"},
            limit=50, severity=None, event_type=None, source_id=None,
        )

        assert isinstance(result, DashboardActivityResponse)
        assert result.events == []
        assert result.total == 0
        assert result.has_more is False


class TestTriggerIngestion:
    """Testes para POST /trigger-ingestion."""

    @pytest.mark.asyncio
    async def test_source_not_found(self):
        """404 quando fonte não existe."""
        from gabi.api.dashboard import trigger_ingestion

        mock_db = AsyncMock()
        result_mock = MagicMock()
        mapping_mock = MagicMock()
        mapping_mock.fetchone.return_value = None
        result_mock.mappings.return_value = mapping_mock
        mock_db.execute = AsyncMock(return_value=result_mock)

        with pytest.raises(HTTPException) as exc_info:
            await trigger_ingestion(
                source_id="nonexistent",
                db=mock_db,
                _user={"sub": "admin", "roles": ["admin"]},
            )

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_source_found_returns_queued(self):
        """Retorna queued quando fonte existe."""
        from gabi.api.dashboard import trigger_ingestion

        mock_db = AsyncMock()
        result_mock = MagicMock()
        mapping_mock = MagicMock()
        mapping_mock.fetchone.return_value = {"id": "src-1", "name": "Portal Gov"}
        result_mock.mappings.return_value = mapping_mock
        mock_db.execute = AsyncMock(return_value=result_mock)

        result = await trigger_ingestion(
            source_id="src-1",
            db=mock_db,
            _user={"sub": "admin", "roles": ["admin"]},
        )

        assert isinstance(result, TriggerIngestionResponse)
        assert result.status == "queued"
        assert result.source_name == "Portal Gov"


class TestGetDashboardHealth:
    """Testes para GET /health."""

    @pytest.mark.asyncio
    async def test_all_healthy(self):
        """Retorna healthy quando todos os componentes estão online."""
        from gabi.api.dashboard import get_dashboard_health

        online = ComponentHealth(name="test", status="online", latency_ms=1.0)

        with patch("gabi.api.dashboard._probe_postgres", return_value=online), \
             patch("gabi.api.dashboard._probe_elasticsearch", return_value=online), \
             patch("gabi.api.dashboard._probe_redis", return_value=online), \
             patch("gabi.api.dashboard._probe_tei", return_value=online):
            result = await get_dashboard_health(_user={"sub": "u1"})

        assert isinstance(result, DashboardHealthResponse)
        assert result.status == "healthy"
        assert len(result.components) == 4

    @pytest.mark.asyncio
    async def test_critical_down_is_unhealthy(self):
        """Retorna unhealthy quando PG ou ES estão offline."""
        from gabi.api.dashboard import get_dashboard_health

        online = ComponentHealth(name="redis", status="online", latency_ms=1.0)
        pg_down = ComponentHealth(name="postgresql", status="offline", latency_ms=2000.0)

        with patch("gabi.api.dashboard._probe_postgres", return_value=pg_down), \
             patch("gabi.api.dashboard._probe_elasticsearch", return_value=online), \
             patch("gabi.api.dashboard._probe_redis", return_value=online), \
             patch("gabi.api.dashboard._probe_tei", return_value=online):
            result = await get_dashboard_health(_user={"sub": "u1"})

        assert result.status == "unhealthy"

    @pytest.mark.asyncio
    async def test_noncritical_down_is_degraded(self):
        """Retorna degraded quando TEI está offline."""
        from gabi.api.dashboard import get_dashboard_health

        online = ComponentHealth(name="postgresql", status="online", latency_ms=1.0)
        tei_down = ComponentHealth(name="tei", status="offline", latency_ms=2000.0)

        with patch("gabi.api.dashboard._probe_postgres", return_value=online), \
             patch("gabi.api.dashboard._probe_elasticsearch", return_value=online), \
             patch("gabi.api.dashboard._probe_redis", return_value=online), \
             patch("gabi.api.dashboard._probe_tei", return_value=tei_down):
            result = await get_dashboard_health(_user={"sub": "u1"})

        assert result.status == "degraded"
