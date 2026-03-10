"""Deterministic date selection for DOU historical harvesting.

Enumerates every calendar day in a closed range [start, end].
No filtering — DOU special editions can appear on any day.
The freezer observes reality; it does not assume publication schedules.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta


MAX_RANGE_DAYS = 7305  # ~20 years


@dataclass(frozen=True, slots=True)
class DateRange:
    """Inclusive date range [start, end]."""

    start: date
    end: date

    def __post_init__(self) -> None:
        if type(self.start) is not date or type(self.end) is not date:
            raise TypeError("start and end must be datetime.date, not subclasses")
        if self.start > self.end:
            raise ValueError(f"start ({self.start.isoformat()}) must be <= end ({self.end.isoformat()})")
        span = (self.end - self.start).days
        if span > MAX_RANGE_DAYS:
            raise ValueError(f"range spans {span} days, exceeds maximum {MAX_RANGE_DAYS}")

    def dates(self) -> list[date]:
        """Return every calendar day in [start, end], ascending."""
        result: list[date] = []
        current = self.start
        while True:
            result.append(current)
            if current == self.end:
                break
            current += timedelta(days=1)
        return result

    def __len__(self) -> int:
        return (self.end - self.start).days + 1


def select_dates(start: date, end: date) -> list[date]:
    """Return deterministic ascending list of all dates in [start, end]."""
    return DateRange(start, end).dates()
