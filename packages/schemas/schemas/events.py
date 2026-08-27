from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class EventType(str, Enum):
    MARKET_PRICE_UPDATED = "MARKET_PRICE_UPDATED"
    WEATHER_FORECAST_UPDATED = "WEATHER_FORECAST_UPDATED"
    PIPELINE_FLOW_UPDATED = "PIPELINE_FLOW_UPDATED"
    PIPELINE_NOTICE_DETECTED = "PIPELINE_NOTICE_DETECTED"
    LNG_FLOW_UPDATED = "LNG_FLOW_UPDATED"
    PRODUCTION_ESTIMATE_UPDATED = "PRODUCTION_ESTIMATE_UPDATED"
    POWER_BURN_UPDATED = "POWER_BURN_UPDATED"
    NEWS_EVENT_DETECTED = "NEWS_EVENT_DETECTED"
    STORAGE_FORECAST_UPDATED = "STORAGE_FORECAST_UPDATED"
    EIA_REPORT_RELEASED = "EIA_REPORT_RELEASED"
    MODEL_FORECAST_UPDATED = "MODEL_FORECAST_UPDATED"
    TRADE_IDEA_CREATED = "TRADE_IDEA_CREATED"
    TRADE_IDEA_CHALLENGED = "TRADE_IDEA_CHALLENGED"
    TRADE_APPROVED = "TRADE_APPROVED"
    TRADE_REJECTED = "TRADE_REJECTED"
    RISK_LIMIT_BREACHED = "RISK_LIMIT_BREACHED"
    POSITION_UPDATED = "POSITION_UPDATED"
    SIGNAL_DETECTED = "SIGNAL_DETECTED"
    SIGNAL_ESCALATED = "SIGNAL_ESCALATED"
    IMPACT_ANALYSIS_CREATED = "IMPACT_ANALYSIS_CREATED"
    IMPACT_UPDATED = "IMPACT_UPDATED"
    AGENT_FORECAST_CREATED = "AGENT_FORECAST_CREATED"
    CONSENSUS_UPDATED = "CONSENSUS_UPDATED"
    CONSENSUS_DIVERGENCE_DETECTED = "CONSENSUS_DIVERGENCE_DETECTED"
    SCENARIO_RUN = "SCENARIO_RUN"
    SCENARIO_COMPARISON_RUN = "SCENARIO_COMPARISON_RUN"
    MEMORY_RECORD_CREATED = "MEMORY_RECORD_CREATED"
    LESSON_PROPOSED = "LESSON_PROPOSED"
    LESSON_REVIEWED = "LESSON_REVIEWED"
    OBSERVATION_REVISED = "OBSERVATION_REVISED"
    INTELLIGENCE_BRIEF_GENERATED = "INTELLIGENCE_BRIEF_GENERATED"


def topic_for_event_type(event_type: EventType | str) -> str:
    """Kafka/Redpanda topic name for an `EventType` — a pure function (rather than a
    `DomainEvent` method only) so a subscriber can compute the topic to consume from
    given only the `event_type` string `EventBus.subscribe()` takes, without needing a
    constructed event instance."""
    value = event_type.value if isinstance(event_type, EventType) else event_type
    domain = value.split("_")[0].lower()
    return f"{domain}.{value.lower()}"


class DomainEvent(BaseModel):
    event_id: UUID = Field(default_factory=uuid4)
    event_type: EventType
    occurred_at: datetime = Field(default_factory=datetime.utcnow)
    published_at: datetime = Field(default_factory=datetime.utcnow)
    source_service: str
    schema_version: str = "1.0"
    payload: dict[str, Any] = Field(default_factory=dict)
    lineage_ids: list[str] = Field(default_factory=list)

    def topic(self) -> str:
        return topic_for_event_type(self.event_type)
