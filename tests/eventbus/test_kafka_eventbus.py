"""Tests for the real Kafka-protocol EventBus (`RedpandaEventBus`, `agent_sdk.eventbus_kafka`).

No live Kafka/Redpanda broker is reachable in this environment (no Docker daemon; see
`docker-compose.yml`'s `redpanda` service for what a real deployment runs this
against), so `AIOKafkaProducer`/`AIOKafkaConsumer` are replaced with faithful in-memory
test doubles at exactly the network boundary — everything on this side of that
boundary (topic derivation, JSON serialization/deserialization via the exact
`value_serializer`/`value_deserializer` callables passed to the real aiokafka classes,
subscribe-once-per-topic consumer lifecycle, event reconstruction) is real, unmocked
code. This mirrors how `tests/api/test_oidc.py` validates real PKCE/JWT logic against a
mocked IdP network boundary.
"""

from __future__ import annotations

import asyncio

import pytest
from agent_sdk import InMemoryEventBus, build_event_bus
from agent_sdk.eventbus_kafka import RedpandaEventBus
from schemas import DomainEvent, EventType


class _FakeProducer:
    instances: list["_FakeProducer"] = []

    def __init__(self, *, bootstrap_servers, value_serializer):
        self.bootstrap_servers = bootstrap_servers
        self.value_serializer = value_serializer
        self.started = False
        self.sent: list[tuple[str, bytes]] = []
        _FakeProducer.instances.append(self)

    async def start(self):
        self.started = True

    async def send_and_wait(self, topic, value):
        assert self.started, "publish() must start the producer before sending"
        self.sent.append((topic, self.value_serializer(value)))

    async def stop(self):
        self.started = False


class _Deserialized:
    def __init__(self, value):
        self.value = value


class _FakeConsumer:
    """Blocks on an empty queue (like a real long-polling Kafka consumer) rather than
    raising `StopAsyncIteration` — so the background consumer task started at
    `subscribe()` time stays alive waiting for records queued afterward, exactly like
    `RedpandaEventBus._consume`'s real `async for record in consumer` loop does
    against a live broker. `bus.stop()`'s `task.cancel()` unblocks it."""

    instances: list["_FakeConsumer"] = []

    def __init__(self, *topics, bootstrap_servers, group_id, value_deserializer, **kwargs):
        self.topics = topics
        self.bootstrap_servers = bootstrap_servers
        self.group_id = group_id
        self.value_deserializer = value_deserializer
        self.started = False
        self.stopped = False
        self._queue: asyncio.Queue[bytes] = asyncio.Queue()
        _FakeConsumer.instances.append(self)

    def queue_raw(self, raw_value: bytes) -> None:
        self._queue.put_nowait(raw_value)

    async def start(self):
        self.started = True

    async def stop(self):
        self.stopped = True

    def __aiter__(self):
        return self

    async def __anext__(self):
        raw_value = await self._queue.get()
        return _Deserialized(self.value_deserializer(raw_value))


@pytest.fixture(autouse=True)
def _reset_fakes(monkeypatch):
    _FakeProducer.instances.clear()
    _FakeConsumer.instances.clear()
    monkeypatch.setattr("agent_sdk.eventbus_kafka.AIOKafkaProducer", _FakeProducer)
    monkeypatch.setattr("agent_sdk.eventbus_kafka.AIOKafkaConsumer", _FakeConsumer)


def test_build_event_bus_defaults_to_in_memory():
    bus = build_event_bus(impl="memory", kafka_bootstrap_servers="localhost:9092")
    assert isinstance(bus, InMemoryEventBus)


def test_build_event_bus_selects_redpanda():
    bus = build_event_bus(impl="redpanda", kafka_bootstrap_servers="redpanda:9092")
    assert isinstance(bus, RedpandaEventBus)


async def test_publish_sends_json_encoded_event_to_the_correct_topic():
    bus = RedpandaEventBus("redpanda:9092")
    event = DomainEvent(
        event_type=EventType.TRADE_IDEA_CREATED,
        source_service="test",
        payload={"trade_id": "abc-123"},
    )
    await bus.publish(event)

    assert len(_FakeProducer.instances) == 1
    producer = _FakeProducer.instances[0]
    assert producer.bootstrap_servers == "redpanda:9092"
    assert producer.started is True
    assert len(producer.sent) == 1
    topic, raw = producer.sent[0]
    assert topic == "trade.trade_idea_created" == event.topic()

    import json

    decoded = json.loads(raw.decode("utf-8"))
    assert decoded["payload"]["trade_id"] == "abc-123"
    assert decoded["event_type"] == "TRADE_IDEA_CREATED"


async def test_publish_reuses_the_same_producer_across_calls():
    bus = RedpandaEventBus("redpanda:9092")
    event = DomainEvent(event_type=EventType.POSITION_UPDATED, source_service="test")
    await bus.publish(event)
    await bus.publish(event)
    assert len(_FakeProducer.instances) == 1
    assert len(_FakeProducer.instances[0].sent) == 2


async def test_subscribe_starts_exactly_one_consumer_task_per_topic():
    bus = RedpandaEventBus("redpanda:9092", group_id="test-group")

    async def handler_one(event: DomainEvent) -> None:
        pass

    async def handler_two(event: DomainEvent) -> None:
        pass

    bus.subscribe(EventType.TRADE_APPROVED.value, handler_one)
    bus.subscribe(EventType.TRADE_APPROVED.value, handler_two)
    await asyncio.sleep(0)  # let the scheduled consumer task actually start

    assert len(_FakeConsumer.instances) == 1
    consumer = _FakeConsumer.instances[0]
    assert consumer.topics == ("trade.trade_approved",)
    assert consumer.group_id == "test-group"
    assert consumer.started is True

    await bus.stop()


async def test_in_memory_bus_unsubscribe_stops_further_delivery():
    bus = InMemoryEventBus()
    received: list[DomainEvent] = []

    async def handler(event: DomainEvent) -> None:
        received.append(event)

    bus.subscribe(EventType.SIGNAL_DETECTED.value, handler)
    await bus.publish(DomainEvent(event_type=EventType.SIGNAL_DETECTED, source_service="test"))
    bus.unsubscribe(EventType.SIGNAL_DETECTED.value, handler)
    await bus.publish(DomainEvent(event_type=EventType.SIGNAL_DETECTED, source_service="test"))

    assert len(received) == 1


def test_in_memory_bus_unsubscribe_of_unknown_handler_is_a_no_op():
    bus = InMemoryEventBus()

    async def handler(event: DomainEvent) -> None:
        pass

    bus.unsubscribe(EventType.SIGNAL_DETECTED.value, handler)  # never subscribed -- must not raise


async def test_redpanda_bus_unsubscribe_stops_further_delivery():
    bus = RedpandaEventBus("redpanda:9092")
    received: list[DomainEvent] = []

    async def handler(event: DomainEvent) -> None:
        received.append(event)

    bus.subscribe(EventType.TRADE_IDEA_CREATED.value, handler)
    await asyncio.sleep(0)
    consumer = _FakeConsumer.instances[0]

    import json

    consumer.queue_raw(
        json.dumps(DomainEvent(event_type=EventType.TRADE_IDEA_CREATED, source_service="test").model_dump(mode="json")).encode(
            "utf-8"
        )
    )
    for _ in range(5):
        await asyncio.sleep(0)
    assert len(received) == 1

    bus.unsubscribe(EventType.TRADE_IDEA_CREATED.value, handler)
    consumer.queue_raw(
        json.dumps(DomainEvent(event_type=EventType.TRADE_IDEA_CREATED, source_service="test").model_dump(mode="json")).encode(
            "utf-8"
        )
    )
    for _ in range(5):
        await asyncio.sleep(0)
    # Still 1 -- the consumer task keeps running (another subscriber could still be
    # attached to the same topic), but this handler no longer receives events.
    assert len(received) == 1

    await bus.stop()


async def test_subscribed_handler_receives_a_reconstructed_domain_event():
    bus = RedpandaEventBus("redpanda:9092")
    received: list[DomainEvent] = []

    async def handler(event: DomainEvent) -> None:
        received.append(event)

    bus.subscribe(EventType.RISK_LIMIT_BREACHED.value, handler)
    await asyncio.sleep(0)

    consumer = _FakeConsumer.instances[0]
    original = DomainEvent(
        event_type=EventType.RISK_LIMIT_BREACHED,
        source_service="risk_service.governor",
        payload={"trade_id": "xyz", "verdict": "BLOCK"},
    )
    import json

    consumer.queue_raw(json.dumps(original.model_dump(mode="json")).encode("utf-8"))

    # Give the background consumer task a few event-loop turns to drain the queue.
    for _ in range(5):
        await asyncio.sleep(0)

    assert len(received) == 1
    assert received[0].event_type == EventType.RISK_LIMIT_BREACHED
    assert received[0].payload == {"trade_id": "xyz", "verdict": "BLOCK"}

    await bus.stop()


async def test_stop_stops_producer_and_cancels_consumer_tasks():
    bus = RedpandaEventBus("redpanda:9092")
    await bus.publish(DomainEvent(event_type=EventType.TRADE_IDEA_CREATED, source_service="test"))

    async def handler(event: DomainEvent) -> None:
        pass

    bus.subscribe(EventType.TRADE_IDEA_CREATED.value, handler)
    await asyncio.sleep(0)

    await bus.stop()

    assert _FakeProducer.instances[0].started is False
    assert _FakeConsumer.instances[0].stopped is True
