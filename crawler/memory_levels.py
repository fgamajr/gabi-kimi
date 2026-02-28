"""Memory pressure level definitions."""

from __future__ import annotations

from enum import Enum


class MemoryLevel(str, Enum):
    NORMAL = "normal"
    PRESSURE = "pressure"
    HIGH = "high"
    CRITICAL = "critical"


def level_for_ratio(
    ratio: float,
    pressure_threshold: float = 0.60,
    high_threshold: float = 0.75,
    critical_threshold: float = 0.90,
) -> MemoryLevel:
    if ratio >= critical_threshold:
        return MemoryLevel.CRITICAL
    if ratio >= high_threshold:
        return MemoryLevel.HIGH
    if ratio >= pressure_threshold:
        return MemoryLevel.PRESSURE
    return MemoryLevel.NORMAL
