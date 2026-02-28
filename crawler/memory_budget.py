"""Runtime memory budget manager for long-running crawler workloads."""

from __future__ import annotations

from dataclasses import dataclass
import gc
import threading
import time
from typing import Any, Callable

from crawler.memory_levels import MemoryLevel, level_for_ratio


EventEmitter = Callable[[str, dict[str, Any]], None]


def _noop_emit(_: str, __: dict[str, Any]) -> None:
    return None


@dataclass(slots=True)
class MemoryBudgetConfig:
    limit_mb: int = 1024
    sample_interval_sec: float = 1.0
    pressure_threshold: float = 0.60
    high_threshold: float = 0.75
    critical_threshold: float = 0.90
    critical_resume_threshold: float = 0.70
    pause_sleep_sec: float = 0.25


class MemoryBudgetManager:
    """Thread-safe memory governor with mitigation levels and pause semantics."""

    def __init__(
        self,
        config: MemoryBudgetConfig,
        emit_event: EventEmitter | None = None,
    ) -> None:
        self._cfg = config
        self._emit_event = emit_event or _noop_emit
        self._lock = threading.RLock()
        self._caches: dict[str, Any] = {}
        self._buffers: dict[str, Any] = {}
        self._level = MemoryLevel.NORMAL
        self._paused = False
        self._last_sample_ts = 0.0
        self._last_rss_mb = 0
        self._concurrency_cap: int | None = None
        self._speculative_fetch_enabled = True

    def register_cache(self, name: str, cache_obj: Any) -> None:
        try:
            with self._lock:
                self._caches[name] = cache_obj
        except Exception:
            pass

    def register_buffer(self, name: str, buffer_obj: Any) -> None:
        try:
            with self._lock:
                self._buffers[name] = buffer_obj
        except Exception:
            pass

    def current_level(self) -> str:
        try:
            with self._lock:
                return self._level.value
        except Exception:
            return MemoryLevel.NORMAL.value

    def should_pause(self) -> bool:
        try:
            with self._lock:
                return self._paused
        except Exception:
            return False

    def concurrency_cap(self) -> int | None:
        try:
            with self._lock:
                return self._concurrency_cap
        except Exception:
            return None

    def speculative_fetch_enabled(self) -> bool:
        try:
            with self._lock:
                return self._speculative_fetch_enabled
        except Exception:
            return True

    def checkpoint(self, stage: str) -> None:
        """Sample memory and apply mitigation actions when needed."""
        try:
            now = time.monotonic()
            with self._lock:
                if (now - self._last_sample_ts) < self._cfg.sample_interval_sec:
                    return
                self._last_sample_ts = now

            rss_mb = self._read_rss_mb()
            if rss_mb <= 0:
                return

            limit_mb = max(1, self._cfg.limit_mb)
            ratio = rss_mb / limit_mb
            level = level_for_ratio(
                ratio,
                pressure_threshold=self._cfg.pressure_threshold,
                high_threshold=self._cfg.high_threshold,
                critical_threshold=self._cfg.critical_threshold,
            )

            self._emit(
                "mem_sample",
                rss_mb=rss_mb,
                limit_mb=limit_mb,
                level=level.value,
                stage=stage,
            )

            with self._lock:
                self._last_rss_mb = rss_mb

            self._apply_level(level=level, rss_mb=rss_mb, stage=stage)
        except Exception as ex:
            self._emit("error", stage="memory", error_type=type(ex).__name__, error_message=str(ex))

    def pause_if_needed(self) -> None:
        """Optional helper for loops that want built-in pause behavior."""
        try:
            while self.should_pause():
                self.checkpoint("critical_wait")
                time.sleep(self._cfg.pause_sleep_sec)
        except Exception:
            return

    def _apply_level(self, level: MemoryLevel, rss_mb: int, stage: str) -> None:
        with self._lock:
            previous = self._level
            self._level = level

        if level == MemoryLevel.NORMAL:
            self._recover_from_critical_if_needed(rss_mb)
            return

        if level in (MemoryLevel.PRESSURE, MemoryLevel.HIGH, MemoryLevel.CRITICAL):
            gc_t0 = time.monotonic()
            gc.collect()
            gc_ms = int((time.monotonic() - gc_t0) * 1000)
            self._clear_registered_resources()
            self._emit("mem_pressure", rss_mb=rss_mb, gc_ms=gc_ms, stage=stage)

        if level in (MemoryLevel.HIGH, MemoryLevel.CRITICAL):
            with self._lock:
                self._concurrency_cap = 1
                self._speculative_fetch_enabled = False
            self._emit("mem_high", rss_mb=rss_mb, action="reduce_concurrency", stage=stage)

        if level == MemoryLevel.CRITICAL:
            entered = False
            with self._lock:
                if not self._paused:
                    self._paused = True
                    entered = True
            if entered or previous != MemoryLevel.CRITICAL:
                self._emit("mem_critical_enter", rss_mb=rss_mb, paused=True, stage=stage)

        self._recover_from_critical_if_needed(rss_mb)

    def _recover_from_critical_if_needed(self, rss_mb: int) -> None:
        try:
            limit_mb = max(1, self._cfg.limit_mb)
            resume_ratio = rss_mb / limit_mb
            if resume_ratio >= self._cfg.critical_resume_threshold:
                return
            was_paused = False
            with self._lock:
                if self._paused:
                    self._paused = False
                    was_paused = True
                if self._level == MemoryLevel.NORMAL:
                    self._concurrency_cap = None
                    self._speculative_fetch_enabled = True
            if was_paused:
                self._emit("mem_critical_exit", rss_mb=rss_mb, resumed=True)
        except Exception:
            return

    def _clear_registered_resources(self) -> None:
        for name, obj in list(self._caches.items()):
            try:
                clear_fn = getattr(obj, "clear", None)
                if callable(clear_fn):
                    clear_fn()
                else:
                    self._emit("error", stage="memory", error_type="CacheMissingClear", error_message=name)
            except Exception as ex:
                self._emit("error", stage="memory", error_type=type(ex).__name__, error_message=f"{name}:{ex}")

        for name, obj in list(self._buffers.items()):
            try:
                trim_fn = getattr(obj, "trim", None)
                if callable(trim_fn):
                    trim_fn()
                else:
                    self._emit("error", stage="memory", error_type="BufferMissingTrim", error_message=name)
            except Exception as ex:
                self._emit("error", stage="memory", error_type=type(ex).__name__, error_message=f"{name}:{ex}")

    def _read_rss_mb(self) -> int:
        try:
            import psutil  # type: ignore

            rss = psutil.Process().memory_info().rss
            return int(rss / (1024 * 1024))
        except Exception:
            pass

        try:
            import resource

            usage = resource.getrusage(resource.RUSAGE_SELF)
            kb = int(usage.ru_maxrss)
            return int(kb / 1024)
        except Exception:
            return 0

    def _emit(self, evt: str, **fields: Any) -> None:
        try:
            self._emit_event(evt, fields)
        except Exception:
            return
