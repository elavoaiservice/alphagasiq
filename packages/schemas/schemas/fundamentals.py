from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field


class GasBalanceDaily(BaseModel):
    flow_date: date
    production_bcf: float
    canadian_imports_bcf: float
    lng_sendout_bcf: float
    other_supply_bcf: float
    rescom_demand_bcf: float
    industrial_demand_bcf: float
    power_burn_bcf: float
    lng_feedgas_bcf: float
    mexico_exports_bcf: float
    other_exports_bcf: float

    @property
    def supply_total_bcf(self) -> float:
        return (
            self.production_bcf
            + self.canadian_imports_bcf
            + self.lng_sendout_bcf
            + self.other_supply_bcf
        )

    @property
    def demand_total_bcf(self) -> float:
        return (
            self.rescom_demand_bcf
            + self.industrial_demand_bcf
            + self.power_burn_bcf
            + self.lng_feedgas_bcf
            + self.mexico_exports_bcf
            + self.other_exports_bcf
        )

    @property
    def balance_bcf(self) -> float:
        """Positive => net supply surplus (storage injection pressure).
        Negative => net supply deficit (storage withdrawal pressure)."""
        return self.supply_total_bcf - self.demand_total_bcf


class StorageForecast(BaseModel):
    week_ending: date
    forecast_bcf: float
    market_consensus_bcf: float | None = None
    five_year_average_bcf: float
    last_year_bcf: float
    forecast_range_low: float
    forecast_range_high: float
    confidence: float = Field(ge=0, le=1)
    drivers: list[str] = Field(default_factory=list)
    regional_breakdown: dict[str, float] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)
