from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from collections import defaultdict
from typing import Awaitable, Callable

from schemas import DomainEvent

logger = logging.getLogger(__name__)

Handler = Callable[[DomainEvent], Awaitable[None]]


class EventBus(ABC):
    """Abstraction over the streaming backend.

    `InMemoryEventBus` is the default so `docker compose up` (and pytest) works with
    zero external dependencies. A Kafka/Redpanda-backed implementation
    (`services/data/app/eventbus_redpanda.py`) implements the same interface and is
    selected via `EVENT_BUS_IMPL=redpanda`.
    """

    @abstractmethod
    async def publish(self, event: DomainEvent) -> None: ...

    @abstractmethod
    def subscribe(self, event_type: str, handler: Handler) -> None: ...


class InMemoryEventBus(EventBus):
    def __init__(self) -> None:
        self._handlers: dict[str, list[Handler]] = defaultdict(list)
        self.published: list[DomainEvent] = []

    async def publish(self, event: DomainEvent) -> None:
        self.published.append(event)
        for handler in self._handlers.get(event.event_type.value, []):
            try:
                await handler(event)
            except Exception:  # pragma: no cover - defensive logging
                logger.exception("Event handler failed for %s", event.event_type)

    def subscribe(self, event_type: str, handler: Handler) -> None:
        self._handlers[event_type].append(handler)
