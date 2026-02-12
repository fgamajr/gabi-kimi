"""Pipeline Control - Enhanced orchestrator with start/stop/restart capabilities.

This module extends the basic orchestrator with control capabilities for
the dashboard to start/stop/restart pipeline phases.
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set
from enum import Enum

from gabi.pipeline.orchestrator import PipelineOrchestrator, PipelinePhase
from gabi.types import ExecutionStatus

logger = logging.getLogger(__name__)


class PipelineControlStatus(Enum):
    """Status of pipeline control operations."""
    STOPPED = "stopped"
    RUNNING = "running"
    RESTARTING = "restarting"
    ERROR = "error"


class PipelineController:
    """Enhanced orchestrator with control capabilities.

    Adds start/stop/restart functionality to the basic orchestrator.
    """

    def __init__(self):
        self._active_executions: Dict[str, Dict] = {}  # {run_id: {source_id, phase, status, task}}
        self._pipeline_instances: Dict[str, PipelineOrchestrator] = {}  # {source_id: orchestrator}
        self._phase_locks: Dict[str, asyncio.Lock] = {}  # {source_id_phase: lock}
        self._stop_flags: Dict[str, bool] = {}  # {source_id_phase: should_stop}

    def _get_lock_key(self, source_id: str, phase: Optional[PipelinePhase] = None) -> str:
        """Generate a unique key for phase locks."""
        if phase:
            return f"{source_id}_{phase.value}"
        return f"{source_id}_all"

    def _get_stop_flag_key(self, source_id: str, phase: Optional[PipelinePhase] = None) -> str:
        """Generate a unique key for stop flags."""
        if phase:
            return f"{source_id}_{phase.value}"
        return f"{source_id}_all"

    async def start_pipeline(self, source_id: str) -> str:
        """Start the entire pipeline for a source."""
        logger.info(f"Starting full pipeline for source {source_id}")
        
        # Create orchestrator if not exists
        if source_id not in self._pipeline_instances:
            from gabi.db import get_es_client, get_redis_client
            from gabi.db import get_session_no_commit
            
            async with get_session_no_commit() as session:
                orchestrator = PipelineOrchestrator(
                    db_session=session,
                    es_client=get_es_client(),
                    redis_client=get_redis_client(),
                )
                self._pipeline_instances[source_id] = orchestrator
        
        # Generate run ID
        run_id = f"{source_id}_run_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f')[:-3]}"
        
        # Start execution task
        task = asyncio.create_task(
            self._execute_pipeline_task(run_id, source_id)
        )
        
        # Store execution info
        self._active_executions[run_id] = {
            "source_id": source_id,
            "phase": None,
            "status": PipelineControlStatus.RUNNING,
            "task": task,
            "started_at": datetime.now(timezone.utc),
        }
        
        return run_id

    async def stop_pipeline(self, source_id: str) -> bool:
        """Stop the entire pipeline for a source."""
        logger.info(f"Stopping full pipeline for source {source_id}")
        
        # Set stop flag for all phases of this source
        for key in list(self._stop_flags.keys()):
            if key.startswith(f"{source_id}_"):
                self._stop_flags[key] = True
        
        # Cancel all active executions for this source
        cancelled_count = 0
        for run_id, exec_info in list(self._active_executions.items()):
            if exec_info["source_id"] == source_id:
                task = exec_info["task"]
                if not task.done():
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
                del self._active_executions[run_id]
                cancelled_count += 1
        
        logger.info(f"Cancelled {cancelled_count} executions for source {source_id}")
        return cancelled_count > 0

    async def restart_pipeline(self, source_id: str) -> str:
        """Restart the entire pipeline for a source."""
        logger.info(f"Restarting full pipeline for source {source_id}")
        
        # Stop current pipeline
        await self.stop_pipeline(source_id)
        
        # Start new pipeline
        return await self.start_pipeline(source_id)

    async def start_phase(self, source_id: str, phase: PipelinePhase) -> str:
        """Start a specific phase for a source."""
        logger.info(f"Starting phase {phase.value} for source {source_id}")
        
        # Create orchestrator if not exists
        if source_id not in self._pipeline_instances:
            from gabi.db import get_es_client, get_redis_client
            from gabi.db import get_session_no_commit
            
            async with get_session_no_commit() as session:
                orchestrator = PipelineOrchestrator(
                    db_session=session,
                    es_client=get_es_client(),
                    redis_client=get_redis_client(),
                )
                self._pipeline_instances[source_id] = orchestrator
        
        # Generate run ID
        run_id = f"{source_id}_{phase.value}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f')[:-3]}"
        
        # Set stop flag to False
        stop_flag_key = self._get_stop_flag_key(source_id, phase)
        self._stop_flags[stop_flag_key] = False
        
        # Start execution task for specific phase
        task = asyncio.create_task(
            self._execute_phase_task(run_id, source_id, phase)
        )
        
        # Store execution info
        self._active_executions[run_id] = {
            "source_id": source_id,
            "phase": phase,
            "status": PipelineControlStatus.RUNNING,
            "task": task,
            "started_at": datetime.now(timezone.utc),
        }
        
        return run_id

    async def stop_phase(self, source_id: str, phase: PipelinePhase) -> bool:
        """Stop a specific phase for a source."""
        logger.info(f"Stopping phase {phase.value} for source {source_id}")
        
        # Set stop flag
        stop_flag_key = self._get_stop_flag_key(source_id, phase)
        self._stop_flags[stop_flag_key] = True
        
        # Find and cancel active execution for this phase
        cancelled = False
        for run_id, exec_info in list(self._active_executions.items()):
            if (exec_info["source_id"] == source_id and 
                exec_info["phase"] == phase):
                task = exec_info["task"]
                if not task.done():
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
                del self._active_executions[run_id]
                cancelled = True
                break
        
        return cancelled

    async def restart_phase(self, source_id: str, phase: PipelinePhase) -> str:
        """Restart a specific phase for a source."""
        logger.info(f"Restarting phase {phase.value} for source {source_id}")
        
        # Stop current phase
        await self.stop_phase(source_id, phase)
        
        # Start new phase
        return await self.start_phase(source_id, phase)

    async def get_active_executions_count(self, source_id: str, phase: Optional[PipelinePhase] = None) -> int:
        """Get count of active executions for a source and optional phase."""
        count = 0
        for run_id, exec_info in self._active_executions.items():
            if exec_info["source_id"] == source_id:
                if phase is None or exec_info["phase"] == phase:
                    if not exec_info["task"].done():
                        count += 1
        return count

    async def _execute_pipeline_task(self, run_id: str, source_id: str) -> None:
        """Execute the full pipeline in a task."""
        try:
            # Get orchestrator
            orchestrator = self._pipeline_instances.get(source_id)
            if not orchestrator:
                logger.error(f"No orchestrator found for source {source_id}")
                return
            
            # Load source config (in real implementation, load from DB)
            source_config = await self._load_source_config(source_id)
            
            # Run pipeline
            await orchestrator.run(source_id=source_id, source_config=source_config)
            
        except asyncio.CancelledError:
            logger.info(f"Pipeline execution {run_id} was cancelled")
            raise
        except Exception as e:
            logger.error(f"Pipeline execution {run_id} failed: {e}")
        finally:
            # Clean up execution
            if run_id in self._active_executions:
                exec_info = self._active_executions[run_id]
                exec_info["status"] = PipelineControlStatus.STOPPED
                exec_info["completed_at"] = datetime.now(timezone.utc)

    async def _execute_phase_task(self, run_id: str, source_id: str, phase: PipelinePhase) -> None:
        """Execute a specific phase in a task."""
        try:
            # Get orchestrator
            orchestrator = self._pipeline_instances.get(source_id)
            if not orchestrator:
                logger.error(f"No orchestrator found for source {source_id}")
                return
            
            # Set stop flag to False initially
            stop_flag_key = self._get_stop_flag_key(source_id, phase)
            self._stop_flags[stop_flag_key] = False
            
            # Execute specific phase based on phase type
            if phase == PipelinePhase.DISCOVERY:
                # Execute discovery phase
                source_config = await self._load_source_config(source_id)
                urls = await orchestrator._discovery_phase(source_config, {})
                logger.info(f"Discovery phase completed for {source_id}, found {len(urls)} URLs")
                
            elif phase == PipelinePhase.CHANGE_DETECTION:
                # Execute change detection phase
                source_config = await self._load_source_config(source_id)
                # Get URLs from discovery or from DB
                urls = await self._get_urls_for_change_detection(source_id)
                urls_to_process = await orchestrator._change_detection_phase(urls, source_id, source_config, {})
                logger.info(f"Change detection phase completed for {source_id}, {len(urls_to_process)} changed")
                
            # Add other phases as needed...
            
        except asyncio.CancelledError:
            logger.info(f"Phase execution {run_id} was cancelled")
            raise
        except Exception as e:
            logger.error(f"Phase execution {run_id} failed: {e}")
        finally:
            # Clean up execution
            if run_id in self._active_executions:
                exec_info = self._active_executions[run_id]
                exec_info["status"] = PipelineControlStatus.STOPPED
                exec_info["completed_at"] = datetime.now(timezone.utc)
            
            # Clear stop flag
            stop_flag_key = self._get_stop_flag_key(source_id, phase)
            self._stop_flags.pop(stop_flag_key, None)

    async def _load_source_config(self, source_id: str) -> Dict:
        """Load source configuration from database."""
        # In real implementation, load from DB
        # For now, return a minimal config
        return {
            "discovery": {
                "mode": "static_url",
                "url": f"https://example.com/{source_id}"
            },
            "fetch": {
                "method": "GET"
            },
            "parse": {
                "format": "html"
            }
        }

    async def _get_urls_for_change_detection(self, source_id: str) -> List[str]:
        """Get URLs for change detection phase."""
        # In real implementation, get from DB
        # For now, return empty list
        return []


# Global controller instance
_controller: Optional[PipelineController] = None


def get_pipeline_controller() -> PipelineController:
    """Get singleton pipeline controller instance."""
    global _controller
    if _controller is None:
        _controller = PipelineController()
    return _controller