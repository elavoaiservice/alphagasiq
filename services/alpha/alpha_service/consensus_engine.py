"""AlphaConsensus(TM) (docs/alpha-intelligence.md section 6): aggregates
`AgentForecast`s into a single `ConsensusView`, weighted by each contributing
agent's `AgentAlphaScore` and its own forecast confidence -- never equal-weighted.
Pure function, no DB/LLM/event-bus access, same design philosophy as every other
engine in this package.
"""

from __future__ import annotations

from schemas import AgentAlphaScore, AgentForecast, AgentType, ConsensusView, ConsensusWeight, SignalDirection

# Provisional agreement-label thresholds -- tunable, like AlphaSignal's materiality
# threshold, not derived from data yet.
_HIGH_AGREEMENT_THRESHOLD = 0.7
_MEDIUM_AGREEMENT_THRESHOLD = 0.5

_FALLBACK_ALPHA_SCORE = 50.0


class ConsensusEngine:
    def compute(
        self,
        *,
        consensus_type: str,
        target: str,
        market: str = "HENRY_HUB",
        horizon: str = "",
        forecasts: list[AgentForecast],
        scores: dict[AgentType, AgentAlphaScore],
        organization_id: str | None = None,
        market_consensus_value: float | None = None,
    ) -> ConsensusView | None:
        """Returns `None` when there are no contributing forecasts -- there is
        nothing to reach a consensus about, and a `ConsensusView` with zeroed-out
        probabilities would misleadingly look like a real "no conviction" reading
        rather than "not computed at all"."""
        if not forecasts:
            return None

        raw_weights = [
            (scores.get(f.agent_type).score if scores.get(f.agent_type) is not None else _FALLBACK_ALPHA_SCORE)
            / 100.0
            * f.confidence
            for f in forecasts
        ]
        total = sum(raw_weights)
        if total <= 0:
            # Every contributor had zero effective weight (e.g. all zero-confidence)
            # -- fall back to equal weighting rather than dividing by zero.
            raw_weights = [1.0] * len(forecasts)
            total = float(len(forecasts))

        weights: list[ConsensusWeight] = []
        bull = bear = neutral = 0.0
        for forecast, raw_weight in zip(forecasts, raw_weights):
            score = scores.get(forecast.agent_type)
            alpha_score = score.score if score is not None else _FALLBACK_ALPHA_SCORE
            normalized = raw_weight / total
            weights.append(
                ConsensusWeight(
                    agent_type=forecast.agent_type,
                    weight=round(normalized, 4),
                    alpha_score=alpha_score,
                    forecast_confidence=forecast.confidence,
                    direction=forecast.direction,
                )
            )
            if forecast.direction == SignalDirection.BULLISH:
                bull += normalized
            elif forecast.direction == SignalDirection.BEARISH:
                bear += normalized
            else:
                neutral += normalized

        confidence = sum(f.confidence * w for f, w in zip(forecasts, raw_weights)) / total

        # A single scalar consensus_value only makes sense when every contributor is
        # forecasting the literal same target (e.g. all STORAGE_BCF) -- averaging a
        # price forecast with a production-trend forecast would be meaningless.
        consensus_value = None
        if all(f.target == target for f in forecasts):
            numeric = [(f, w) for f, w in zip(forecasts, raw_weights) if f.forecast_value is not None]
            value_weight_total = sum(w for _, w in numeric)
            if numeric and value_weight_total > 0:
                consensus_value = round(
                    sum(f.forecast_value * w for f, w in numeric) / value_weight_total, 4
                )

        max_share = max(bull, bear, neutral)
        if max_share >= _HIGH_AGREEMENT_THRESHOLD:
            agreement_label = "HIGH"
        elif max_share >= _MEDIUM_AGREEMENT_THRESHOLD:
            agreement_label = "MEDIUM"
        else:
            agreement_label = "LOW"

        share_by_direction = {
            SignalDirection.BULLISH: bull,
            SignalDirection.BEARISH: bear,
            SignalDirection.NEUTRAL: neutral,
        }
        majority_direction = max(share_by_direction, key=lambda d: share_by_direction[d])
        leading = sorted(
            (w for w in weights if w.direction == majority_direction), key=lambda w: w.weight, reverse=True
        )
        dissenting = sorted(
            (w for w in weights if w.direction != majority_direction), key=lambda w: w.weight, reverse=True
        )

        variance_vs_market = None
        if consensus_value is not None and market_consensus_value is not None:
            variance_vs_market = round(consensus_value - market_consensus_value, 4)

        drivers: list[str] = []
        for f in forecasts:
            for d in f.drivers:
                if d not in drivers:
                    drivers.append(d)

        return ConsensusView(
            organization_id=organization_id,
            consensus_type=consensus_type,
            market=market,
            target=target,
            horizon=horizon,
            consensus_value=consensus_value,
            bull_probability=round(bull, 4),
            bear_probability=round(bear, 4),
            neutral_probability=round(neutral, 4),
            confidence=round(confidence, 4),
            dispersion=round(1.0 - max_share, 4),
            agreement_label=agreement_label,
            agent_count=len(forecasts),
            agent_weights=weights,
            leading_agents=[w.agent_type.value for w in leading],
            dissenting_agents=[w.agent_type.value for w in dissenting],
            drivers=drivers,
            market_consensus_value=market_consensus_value,
            variance_vs_market=variance_vs_market,
        )
