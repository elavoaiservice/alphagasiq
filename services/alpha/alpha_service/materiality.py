"""AlphaSignal(TM)'s materiality engine (docs/alpha-intelligence.md section 3).

A deterministic, non-LLM rules engine, deliberately mirroring the design philosophy of
`risk_service.governor.RiskGovernor`: every input is passed in already-resolved, so
`MaterialityEngine.score()` is a pure function of its input and therefore trivially and
exhaustively testable (see tests/alpha/test_materiality.py). No signal's importance is
ever decided by an LLM's judgment in this module.

The four weighted components below are a *provisional*, documented business judgment
call (docs/alpha-intelligence.md section on "Milestone 1 provisional decisions") --
tunable once real signal volume exists to calibrate against, not derived from data yet.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from schemas import DataClassification, SignalType

MATERIALITY_ENGINE_VERSION = "1.0.0"

# Provisional component weights -- must sum to 1.0.
_WEIGHT_MAGNITUDE = 0.4
_WEIGHT_RARITY = 0.3
_WEIGHT_CONFIDENCE = 0.2
_WEIGHT_QUALITY = 0.1

# Provisional default: a signal must score at least this high (0-100) to be persisted
# and published. Per-SignalType overrides can be supplied to `MaterialityEngine`.
DEFAULT_MATERIALITY_THRESHOLD = 60.0

# A percent_change of this magnitude (as a fraction, e.g. 0.20 = 20%) or larger maps to
# a full-scale (100) magnitude component. Below this, magnitude scales linearly.
_MAGNITUDE_SATURATION_PCT = 0.20

# A |z_score| of this magnitude or larger maps to a full-scale (100) rarity component.
_RARITY_SATURATION_Z = 4.0

# Deterministic, fixed lookup: how much a data classification is trusted for
# materiality purposes. Reuses the existing provenance `DataClassification` enum
# (docs/alpha-intelligence.md is explicit that this is a different concept from the
# enterprise *security*-tier classification a later milestone introduces).
_QUALITY_SCORE_BY_CLASSIFICATION: dict[DataClassification, float] = {
    DataClassification.LICENSED: 100.0,
    DataClassification.PUBLIC: 80.0,
    DataClassification.USER_PROVIDED: 70.0,
    DataClassification.SIMULATED: 60.0,
}

# A stale reading is discounted -- still usable, but never allowed to drive a signal on
# its own credibility.
_STALE_QUALITY_MULTIPLIER = 0.5


@dataclass
class MaterialityInput:
    """Every fact `MaterialityEngine.score()` needs, already resolved by the caller
    (`SignalDetector`) -- no I/O happens inside this module."""

    signal_type: SignalType
    absolute_change: float | None = None
    percent_change: float | None = None
    z_score: float | None = None
    historical_percentile: float | None = None
    confidence: float = 1.0
    data_quality: DataClassification = DataClassification.SIMULATED
    is_stale: bool = False


@dataclass
class MaterialityScore:
    score: float
    components: dict[str, float] = field(default_factory=dict)
    passed_threshold: bool = False


def _magnitude_component(inp: MaterialityInput) -> float:
    if inp.percent_change is None:
        # No magnitude information at all -- treated as medium rather than silently
        # scoring zero (which would make "no data" indistinguishable from "no change").
        return 50.0
    return min(100.0, abs(inp.percent_change) / _MAGNITUDE_SATURATION_PCT * 100.0)


def _rarity_component(inp: MaterialityInput) -> float:
    if inp.z_score is not None:
        return min(100.0, abs(inp.z_score) / _RARITY_SATURATION_Z * 100.0)
    if inp.historical_percentile is not None:
        # Distance from the median percentile (50), rescaled to 0-100.
        return min(100.0, abs(inp.historical_percentile - 50.0) / 50.0 * 100.0)
    # No rarity information -- treated as unremarkable rather than overstating
    # materiality from thin/absent history.
    return 0.0


def _confidence_component(inp: MaterialityInput) -> float:
    return max(0.0, min(1.0, inp.confidence)) * 100.0


def _quality_component(inp: MaterialityInput) -> float:
    base = _QUALITY_SCORE_BY_CLASSIFICATION.get(inp.data_quality, 60.0)
    return base * _STALE_QUALITY_MULTIPLIER if inp.is_stale else base


class MaterialityEngine:
    """Stateless evaluator. Construct once, call `score()` per candidate signal."""

    version = MATERIALITY_ENGINE_VERSION

    def __init__(self, thresholds: dict[SignalType, float] | None = None):
        self._thresholds = thresholds or {}

    def score(self, inp: MaterialityInput) -> MaterialityScore:
        components = {
            "magnitude": round(_magnitude_component(inp), 3),
            "rarity": round(_rarity_component(inp), 3),
            "confidence": round(_confidence_component(inp), 3),
            "quality": round(_quality_component(inp), 3),
        }
        raw_score = (
            _WEIGHT_MAGNITUDE * components["magnitude"]
            + _WEIGHT_RARITY * components["rarity"]
            + _WEIGHT_CONFIDENCE * components["confidence"]
            + _WEIGHT_QUALITY * components["quality"]
        )
        score = round(max(0.0, min(100.0, raw_score)), 2)
        threshold = self._thresholds.get(inp.signal_type, DEFAULT_MATERIALITY_THRESHOLD)
        return MaterialityScore(score=score, components=components, passed_threshold=score >= threshold)
