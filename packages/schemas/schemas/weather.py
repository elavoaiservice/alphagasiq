from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class WeatherDemandImpact(BaseModel):
    model: str = Field(description="e.g. ECMWF, GFS")
    run: str = Field(description="model initialization run, e.g. 2026-08-25T00:00:00Z")
    comparison_run: str
    hdd_delta: float
    cdd_delta: float
    estimated_rescom_delta_bcf: float
    estimated_power_burn_delta_bcf: float
    total_demand_delta_bcf: float
    price_direction: str = Field(description="BULLISH | BEARISH | NEUTRAL")
    confidence: float = Field(ge=0, le=1)
    created_at: datetime = Field(default_factory=datetime.utcnow)
