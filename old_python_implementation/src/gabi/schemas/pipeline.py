"""Pipeline execution request schema."""

from typing import List, Optional
from pydantic import BaseModel, Field

from gabi.types import PipelinePhase


class PipelineExecutionRequest(BaseModel):
    """Request to execute pipeline with specific parameters."""
    source_id: str = Field(..., description="ID of the source to execute")
    phases: Optional[List[PipelinePhase]] = Field(None, description="Specific phases to execute (None=all phases)")
    force_refresh: bool = Field(False, description="Force refresh of cached data")
    dry_run: bool = Field(False, description="Run in dry-run mode without persisting changes")