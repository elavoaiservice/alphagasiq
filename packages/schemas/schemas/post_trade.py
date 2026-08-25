from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from .enums import OutcomeQuadrant
from .quant import ModelType


class PostTradeAnalysis(BaseModel):
    """Generated once a paper position closes (docs/architecture.md "POST-TRADE
    ANALYSIS"). Distinguishes decision quality (was this a well-reasoned, properly
    risk-managed call given what was knowable at the time) from outcome quality (did
    it make money) — the two are not the same thing, and conflating them is exactly
    what this object exists to prevent.

    `forecast_error`/`thesis_accuracy`/`timing_accuracy`/`risk_accuracy` score the
    *strategy's* stated thesis (target/stop/expected_return) — always present. The
    `quant_*` fields separately score the *Quantitative Team's* actual `PriceForecast`
    for this trade's instrument, when one was attached at trade-creation time — this is
    what lets `GET /models/performance` compare a model's walk-forward-backtested
    skill (`services/quant`) against its live, real-decision skill using the exact
    same metrics (see `services/quant/quant_service/metrics.py`), rather than the two
    living as unrelated numbers. `quant_*` fields are None when no forecast was
    attached (e.g. a trade opened before the Quantitative Team's forecast for that
    cycle was generated).
    """

    id: UUID = Field(default_factory=uuid4)
    trade_id: UUID
    expected_outcome: dict = Field(default_factory=dict)
    actual_outcome: dict = Field(default_factory=dict)
    forecast_error: float | None = None
    thesis_accuracy: float = Field(ge=0, le=1)
    timing_accuracy: float = Field(ge=0, le=1)
    risk_accuracy: float = Field(ge=0, le=1)
    model_contribution: dict = Field(default_factory=dict)
    unexpected_events: list[str] = Field(default_factory=list)
    lessons: str = ""
    quadrant: OutcomeQuadrant
    quant_model_type: ModelType | None = None
    quant_model_version: str | None = None
    quant_predicted_return: float | None = None
    quant_forecast_error: float | None = None
    quant_up_probability: float | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
