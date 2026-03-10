"""Structured JSON logging — single line per event, stdout (Fly captures it).

Configure once at app startup. Context (request_id, run_id, file_id, phase) is
bound via contextvars and included in every log line.

Log levels:
  DEBUG: Detailed technical info (query plans, raw responses). Use LOG_LEVEL=DEBUG.
  INFO:  Operational events (request served, file downloaded, phase complete). Default.
  WARNING: Recoverable issues (retry triggered, fallback used, slow query).
  ERROR: Failures (download failed, ES unreachable, auth error).
"""

from __future__ import annotations

import json
import logging
import os
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any

# Context vars — bound per request or per pipeline step, cleared when done
_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)
_run_id: ContextVar[str | None] = ContextVar("run_id", default=None)
_file_id: ContextVar[int | None] = ContextVar("file_id", default=None)
_phase: ContextVar[str | None] = ContextVar("phase", default=None)
_job_id: ContextVar[str | None] = ContextVar("job_id", default=None)

_configured = False


def bind_request_id(request_id: str) -> None:
    _request_id.set(request_id)


def bind_pipeline(run_id: str | None = None, file_id: int | None = None, phase: str | None = None) -> None:
    if run_id is not None:
        _run_id.set(run_id)
    if file_id is not None:
        _file_id.set(file_id)
    if phase is not None:
        _phase.set(phase)


def bind_job_id(job_id: str) -> None:
    _job_id.set(job_id)


def clear_context() -> None:
    for var in (_request_id, _run_id, _file_id, _phase, _job_id):
        try:
            var.set(None)
        except LookupError:
            pass


class _ContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        rid = _request_id.get(None)
        if rid is not None:
            record.request_id = rid
        run_id = _run_id.get(None)
        if run_id is not None:
            record.run_id = run_id
        file_id = _file_id.get(None)
        if file_id is not None:
            record.file_id = file_id
        phase = _phase.get(None)
        if phase is not None:
            record.phase = phase
        job_id = _job_id.get(None)
        if job_id is not None:
            record.job_id = job_id
        return True


class _JsonFormatter(logging.Formatter):
    def __init__(self, app_name: str = "gabi", service: str = "web", environment: str = "development") -> None:
        super().__init__()
        self._app_name = app_name
        self._service = service
        self._environment = environment

    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if getattr(record, "request_id", None):
            entry["request_id"] = record.request_id
        if getattr(record, "run_id", None):
            entry["run_id"] = record.run_id
        if getattr(record, "file_id", None) is not None:
            entry["file_id"] = record.file_id
        if getattr(record, "phase", None):
            entry["phase"] = record.phase
        if getattr(record, "job_id", None):
            entry["job_id"] = record.job_id
        entry["app_name"] = self._app_name
        entry["environment"] = self._environment
        entry["service"] = self._service
        if getattr(record, "event", None):
            entry["event"] = record.event
        if record.exc_info and record.exc_info[1]:
            entry["exception"] = f"{type(record.exc_info[1]).__name__}: {record.exc_info[1]}"
        # Any extra passed to log.info(..., extra={...}) goes into record.__dict__
        for k, v in record.__dict__.items():
            if k in (
                "name",
                "msg",
                "args",
                "created",
                "filename",
                "funcName",
                "levelname",
                "levelno",
                "lineno",
                "module",
                "msecs",
                "pathname",
                "process",
                "processName",
                "relativeCreated",
                "stack_info",
                "exc_info",
                "exc_text",
                "thread",
                "threadName",
                "message",
                "request_id",
                "run_id",
                "file_id",
                "phase",
                "job_id",
                "event",
            ):
                continue
            if k.startswith("_"):
                continue
            entry[k] = v
        return json.dumps(entry, ensure_ascii=True)


def configure_logging(
    *,
    app_name: str = "gabi",
    service: str = "web",
    environment: str | None = None,
) -> None:
    """Call once at application startup. Configures root logger for JSON stdout."""
    global _configured
    if _configured:
        return
    env = environment or os.getenv("ENVIRONMENT", os.getenv("GABI_ENV", "development"))
    level_name = os.getenv("LOG_LEVEL", "INFO").strip().upper()
    level = getattr(logging, level_name, logging.INFO)

    handler = logging.StreamHandler()
    handler.setFormatter(_JsonFormatter(app_name=app_name, service=service, environment=env))
    handler.addFilter(_ContextFilter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)
    _configured = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
