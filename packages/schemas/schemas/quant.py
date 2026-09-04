from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field

from .enums import Regime


class ModelType(str, Enum):
    NAIVE_PERSISTENCE = "NAIVE_PERSISTENCE"
    LINEAR_REGRESSION = "LINEAR_REGRESSION"
    ARIMA = "ARIMA"
    VAR = "VAR"
    STATE_SPACE = "STATE_SPACE"
    RANDOM_FOREST = "RANDOM_FOREST"
    XGBOOST = "XGBOOST"
    LIGHTGBM = "LIGHTGBM"
    TEMPORAL_FUSION_TRANSFORMER = "TEMPORAL_FUSION_TRANSFORMER"
    LSTM = "LSTM"


class ForecastHorizon(str, Enum):
    ONE_HOUR = "1h"
    FOUR_HOUR = "4h"
    ONE_DAY = "1d"
    THREE_DAY = "3d"
    SEVEN_DAY = "7d"
    THIRTY_DAY = "30d"
    SEASONAL = "seasonal"


class PriceForecast(BaseModel):
    """docs/architecture.md FORECAST ENGINE output contract."""

    instrument: str
    horizon: ForecastHorizon
    price_forecast: float
    return_forecast: float
    up_probability: float = Field(ge=0, le=1)
    down_probability: float = Field(ge=0, le=1)
    expected_volatility: float
    confidence: float = Field(ge=0, le=1)
    drivers: list[str] = Field(default_factory=list)
    model_contributions: dict[str, float] = Field(default_factory=dict)
    generated_at: datetime = Field(default_factory=datetime.utcnow)


class RegimeResult(BaseModel):
    regime: Regime
    confidence: float = Field(ge=0, le=1)
    drivers: list[str] = Field(default_factory=list)
    realized_volatility: float | None = None
    detected_at: datetime = Field(default_factory=datetime.utcnow)


class RelativeValueSignal(BaseModel):
    pair: str = Field(description="e.g. 'HH_TTF_NETBACK' or 'NG_M1_M2_CALENDAR_SPREAD'")
    signal_type: str
    fair_value_estimate: float
    actual_value: float
    mispricing: float = Field(description="actual - fair_value_estimate")
    direction: str = Field(description="CHEAP | RICH | FAIR")
    confidence: float = Field(ge=0, le=1)
    rationale: str = ""
    detected_at: datetime = Field(default_factory=datetime.utcnow)


class BacktestResult(BaseModel):
    """docs/architecture.md QUANTITATIVE PLATFORM walk-forward evaluation contract."""

    model_type: ModelType
    model_version: str
    instrument: str
    horizon: ForecastHorizon
    n_folds: int
    mae: float
    rmse: float
    directional_accuracy: float = Field(ge=0, le=1)
    hit_rate: float = Field(ge=0, le=1)
    sharpe_ratio: float | None = None
    sortino_ratio: float | None = None
    max_drawdown: float = Field(ge=0)
    profit_factor: float | None = None
    brier_score: float | None = Field(default=None, ge=0, le=1)
    evaluated_at: datetime = Field(default_factory=datetime.utcnow)
