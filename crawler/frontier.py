"""Frontier queue and visited-state manager."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field


@dataclass(slots=True)
class Frontier:
    queue: deque[str] = field(default_factory=deque)
    visited: set[str] = field(default_factory=set)
    queued: set[str] = field(default_factory=set)

    def enqueue(self, url: str) -> bool:
        if not url or url in self.visited or url in self.queued:
            return False
        self.queue.append(url)
        self.queued.add(url)
        return True

    def enqueue_many(self, urls: list[str]) -> int:
        count = 0
        for url in urls:
            if self.enqueue(url):
                count += 1
        return count

    def dequeue(self) -> str | None:
        if not self.queue:
            return None
        url = self.queue.popleft()
        self.queued.discard(url)
        return url

    def mark_visited(self, url: str) -> None:
        if url:
            self.visited.add(url)

    def is_empty(self) -> bool:
        return not self.queue
