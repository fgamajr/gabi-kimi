"""Pipeline control service backed by PostgreSQL + Redis + Celery."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Optional

from celery import Celery
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from gabi.models.execution import ExecutionManifest
from gabi.models.pipeline_action import PipelineAction
from gabi.types import ExecutionStatus, PipelinePhase


class PipelineControlService:
    """Coordinates persistent control actions and runtime state."""

    def __init__(self, redis_client, celery_app: Celery):
        self.redis = redis_client
        self.celery = celery_app

    @staticmethod
    def _phase_key(phase: Optional[PipelinePhase]) -> str:
        return phase.value if phase else "all"

    @staticmethod
    def _runtime_key(source_id: str, phase: Optional[PipelinePhase]) -> str:
        return f"gabi:pipeline:runtime:{source_id}:{PipelineControlService._phase_key(phase)}"

    @staticmethod
    def _cancel_key(source_id: str, phase: Optional[PipelinePhase]) -> str:
        return f"gabi:pipeline:cancel:{source_id}:{PipelineControlService._phase_key(phase)}"

    @staticmethod
    def _active_tasks_key(source_id: str) -> str:
        return f"gabi:pipeline:active_tasks:{source_id}"

    @staticmethod
    def _task_meta_key(task_id: str) -> str:
        return f"gabi:pipeline:task:{task_id}"

    async def create_action(
        self,
        db: AsyncSession,
        *,
        source_id: str,
        action: str,
        requested_by: Optional[str],
        phase: Optional[PipelinePhase] = None,
        run_id: Optional[str] = None,
        details: Optional[dict] = None,
        status: str = "requested",
    ) -> PipelineAction:
        pa = PipelineAction(
            source_id=source_id,
            phase=phase.value if phase else None,
            action=action,
            status=status,
            requested_by=requested_by,
            run_id=uuid.UUID(run_id) if run_id else None,
            details=details or {},
            task_ids=[],
        )
        db.add(pa)
        await db.flush()
        return pa

    async def mark_action(
        self,
        db: AsyncSession,
        *,
        action_id: str,
        status: str,
        error_message: Optional[str] = None,
        task_ids: Optional[list[str]] = None,
    ) -> None:
        values = {
            "status": status,
            "updated_at": datetime.now(timezone.utc),
        }
        if error_message is not None:
            values["error_message"] = error_message
        if task_ids is not None:
            values["task_ids"] = task_ids
        await db.execute(
            update(PipelineAction)
            .where(PipelineAction.action_id == uuid.UUID(action_id))
            .values(**values)
        )

    async def start(
        self,
        db: AsyncSession,
        *,
        source_id: str,
        phase: Optional[PipelinePhase],
        requested_by: Optional[str],
    ) -> tuple[str, str, str]:
        run_id = str(uuid.uuid4())
        action = await self.create_action(
            db,
            source_id=source_id,
            action="start",
            phase=phase,
            requested_by=requested_by,
            run_id=run_id,
            status="queued",
        )
        action_id = str(action.action_id)

        # Queue actual pipeline execution
        # Phase-aware execution is currently handled as full sync with metadata.
        task = self.celery.send_task(
            "gabi.tasks.sync.sync_source_task",
            kwargs={
                "source_id": source_id,
                "run_id": run_id,
                "action_id": action_id,
                "phase": phase.value if phase else None,
            },
            queue="gabi.sync",
        )
        task_id = task.id
        await self.mark_action(db, action_id=action_id, status="accepted", task_ids=[task_id])

        runtime_key = self._runtime_key(source_id, phase)
        now_iso = datetime.now(timezone.utc).isoformat()
        await self.redis.hset(
            runtime_key,
            mapping={
                "source_id": source_id,
                "phase": self._phase_key(phase),
                "action_id": action_id,
                "run_id": run_id,
                "task_id": task_id,
                "status": "queued",
                "is_running": "true",
                "cancel_requested": "false",
                "updated_at": now_iso,
            },
        )
        await self.redis.expire(runtime_key, 60 * 60 * 24)

        await self.redis.sadd(self._active_tasks_key(source_id), task_id)
        await self.redis.set(
            self._task_meta_key(task_id),
            json.dumps(
                {
                    "source_id": source_id,
                    "phase": self._phase_key(phase),
                    "run_id": run_id,
                    "action_id": action_id,
                    "updated_at": now_iso,
                }
            ),
            ex=60 * 60 * 24,
        )
        await self.redis.delete(self._cancel_key(source_id, phase))
        await self.redis.delete(self._cancel_key(source_id, None))
        return action_id, run_id, task_id

    async def stop(
        self,
        db: AsyncSession,
        *,
        source_id: str,
        phase: Optional[PipelinePhase],
        requested_by: Optional[str],
    ) -> tuple[str, list[str]]:
        action = await self.create_action(
            db,
            source_id=source_id,
            action="stop",
            phase=phase,
            requested_by=requested_by,
            status="running",
        )
        action_id = str(action.action_id)

        cancel_key = self._cancel_key(source_id, phase)
        await self.redis.set(cancel_key, "1", ex=60 * 60)
        if phase is not None:
            await self.redis.set(self._cancel_key(source_id, None), "1", ex=60 * 60)

        task_ids = list(await self.redis.smembers(self._active_tasks_key(source_id)) or [])
        for task_id in task_ids:
            # Cooperative stop first; workers check cancel flag.
            self.celery.control.revoke(task_id, terminate=False)
            await self.redis.delete(self._task_meta_key(task_id))
            await self.redis.srem(self._active_tasks_key(source_id), task_id)

        runtime_key = self._runtime_key(source_id, phase)
        await self.redis.hset(
            runtime_key,
            mapping={
                "status": "stopped",
                "is_running": "false",
                "cancel_requested": "true",
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        await self.mark_action(db, action_id=action_id, status="completed", task_ids=task_ids)

        await db.execute(
            update(ExecutionManifest)
            .where(ExecutionManifest.source_id == source_id)
            .where(ExecutionManifest.status.in_([ExecutionStatus.RUNNING.value, ExecutionStatus.PENDING.value]))
            .values(
                status=ExecutionStatus.CANCELLED.value,
                completed_at=datetime.now(timezone.utc),
                error_message="Cancelled by control-plane request",
            )
        )
        return action_id, task_ids

    async def restart(
        self,
        db: AsyncSession,
        *,
        source_id: str,
        phase: Optional[PipelinePhase],
        requested_by: Optional[str],
    ) -> tuple[str, str, str, str]:
        stop_action_id, _ = await self.stop(
            db,
            source_id=source_id,
            phase=phase,
            requested_by=requested_by,
        )
        start_action_id, run_id, task_id = await self.start(
            db,
            source_id=source_id,
            phase=phase,
            requested_by=requested_by,
        )
        return stop_action_id, start_action_id, run_id, task_id

    async def runtime_status(
        self,
        *,
        source_id: str,
        phase: Optional[PipelinePhase],
    ) -> dict:
        data = await self.redis.hgetall(self._runtime_key(source_id, phase))
        return data or {}

    async def latest_action(
        self,
        db: AsyncSession,
        *,
        source_id: str,
        phase: Optional[PipelinePhase],
    ) -> Optional[PipelineAction]:
        stmt = (
            select(PipelineAction)
            .where(PipelineAction.source_id == source_id)
            .order_by(PipelineAction.created_at.desc())
            .limit(1)
        )
        if phase:
            stmt = stmt.where(PipelineAction.phase == phase.value)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()
