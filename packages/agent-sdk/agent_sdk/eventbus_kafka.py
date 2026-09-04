"""Real Kafka-protocol `EventBus` (`aiokafka`), selected via `EVENT_BUS_IMPL=redpanda`
(`config.Settings.event_bus_impl`). Isolated in its own module (rather than living in
`eventbus.py` alongside `InMemoryEventBus`) so importing `agent_sdk` never requires
`aiokafka` unless this specific class is actually constructed — every environment that
leaves `EVENT_BUS_IMPL` at its default (`memory`) never imports this module at all.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict
from datetime import datetime
from typing import Any
from uuid import UUID

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from schemas import DomainEvent, topic_for_event_type

from .eventbus import EventBus, Handler

logger = logging.getLogger(__name__)


def _json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


class RedpandaEventBus(EventBus):
    """Works against Redpanda (docker-compose's dev broker, itself Kafka-API-
    compatible) or any real Kafka cluster — nothing here is Redpanda-specific beyond
    the class name matching the existing `EVENT_BUS_IMPL=redpanda` config value.
    Implements the exact same interface as `InMemoryEventBus`, so `AppState` (or
    anything else that constructs an `EventBus`) never needs to know which one it got.

    `publish()` JSON-encodes the event and produces it to `event.topic()` — one Kafka
    topic per `EventType` (e.g. `"trade.trade_idea_created"`). `subscribe()` registers
    an in-process handler and lazily starts one background consumer task per topic the
    first time that topic is subscribed to, so a single process can both publish and
    consume without a separately deployed consumer-group service.
    """

    def __init__(self, bootstrap_servers: str, *, group_id: str = "alphagasiq") -> None:
        self._bootstrap_servers = bootstrap_servers
        self._group_id = group_id
        self._producer: AIOKafkaProducer | None = None
        self._handlers: dict[str, list[Handler]] = defaultdict(list)
        self._consumer_tasks: dict[str, asyncio.Task] = {}

    async def _ensure_producer(self) -> AIOKafkaProducer:
        if self._producer is None:
            producer = AIOKafkaProducer(
                bootstrap_servers=self._bootstrap_servers,
                value_serializer=lambda v: json.dumps(v, default=_json_default).encode("utf-8"),
            )
            await producer.start()
            self._producer = producer
        return self._producer

    async def publish(self, event: DomainEvent) -> None:
        producer = await self._ensure_producer()
        await producer.send_and_wait(event.topic(), value=event.model_dump(mode="json"))

    def subscribe(self, event_type: str, handler: Handler) -> None:
        topic = topic_for_event_type(event_type)
        self._handlers[topic].append(handler)
        if topic not in self._consumer_tasks:
            self._consumer_tasks[topic] = asyncio.get_event_loop().create_task(self._consume(topic))

    def unsubscribe(self, event_type: str, handler: Handler) -> None:
        """Reverses `subscribe`; leaves the topic's background consumer task running
        (cheap to keep, and another subscriber may still be attached to it) --
        only the handler itself stops receiving events."""
        topic = topic_for_event_type(event_type)
        handlers = self._handlers.get(topic)
        if handlers is not None and handler in handlers:
            handlers.remove(handler)

    async def _consume(self, topic: str) -> None:
        consumer = AIOKafkaConsumer(
            topic,
            bootstrap_servers=self._bootstrap_servers,
            group_id=self._group_id,
            value_deserializer=lambda v: json.loads(v.decode("utf-8")),
            auto_offset_reset="latest",
        )
        await consumer.start()
        try:
            async for record in consumer:
                event = DomainEvent.model_validate(record.value)
                for handler in self._handlers.get(topic, []):
                    try:
                        await handler(event)
                    except Exception:  # pragma: no cover - defensive logging, matches InMemoryEventBus
                        logger.exception("Event handler failed for topic %s", topic)
        finally:
            await consumer.stop()

    async def stop(self) -> None:
        """Cancels every background consumer task and stops the producer — call on
        app shutdown (mirrors `SqlAppRepository.dispose()`'s shutdown-hook pattern)."""
        for task in self._consumer_tasks.values():
            task.cancel()
        for task in self._consumer_tasks.values():
            try:
                await task
            except asyncio.CancelledError:
                pass
        if self._producer is not None:
            await self._producer.stop()
