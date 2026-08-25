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
        domain = self.event_type.value.split("_")[0].lower()
        return f"{domain}.{self.event_type.value.lower()}"
