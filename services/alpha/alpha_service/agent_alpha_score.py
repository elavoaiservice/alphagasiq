"""Agent Alpha Score(TM) (docs/alpha-intelligence.md section 6): a deterministic,
non-LLM rating of how much to trust a given agent's directional read, in the same
design philosophy as `MaterialityEngine`/`RiskGovernor` -- pure function of its
input, exhaustively unit-tested.

Milestone 3 is honest about scope: only the Forecasting agent has a genuine
historical-accuracy figure available today (the Quantitative Team's real
walk-forward backtests already computed by `services/quant`). Every other agent
gets a "confidence consistency" proxy score -- explicitly NOT a claim of historical
predictive accuracy, since no resolved-outcome ledger per fundamental agent exists
yet (building one requires linking each forecast to what actually happened later,
which is AlphaMemory's decision-memory infrastructure, a later milestone).
"""

from __future__ import annotations

from statistics import fmean, pstdev

from schemas import AgentAlphaScore, AgentType, BacktestResult, PriceForecast

METHOD_BACKTESTED = "BACKTESTED_DIRECTIONAL_ACCURACY"
METHOD_CONFIDENCE_PROXY = "CONFIDENCE_CONSISTENCY_PROXY"

# Weights for the confidence-consistency proxy -- provisional, like AlphaSignal's
# materiality weights: tunable once a real resolved-outcome ledger exists to
# calibrate against, not derived from data yet.
_WEIGHT_MEAN_CONFIDENCE = 0.5
_WEIGHT_CONSISTENCY = 0.3
_WEIGHT_EVIDENCE = 0.2

# A confidence standard deviation at or above this scores zero consistency.
_CONSISTENCY_STDEV_SATURATION = 0.5

_NEUTRAL_DEFAULT_SCORE = 50.0


class AgentAlphaScoreEngine:
    def score(
        self,
        agent_type: AgentType,
        *,
        recent_confidences: list[float] | None = None,
        has_citations_fraction: float | None = None,
        price_forecast: PriceForecast | None = None,
        latest_backtests: dict[str, BacktestResult] | None = None,
    ) -> AgentAlphaScore:
        if agent_type == AgentType.FORECASTING and price_forecast is not None and latest_backtests:
            backtested = self._score_backtested(agent_type, price_forecast, latest_backtests)
            if backtested is not None:
                return backtested
        return self._score_confidence_consistency(agent_type, recent_confidences or [], has_citations_fraction)

    def _score_backtested(
        self, agent_type: AgentType, price_forecast: PriceForecast, latest_backtests: dict[str, BacktestResult]
    ) -> AgentAlphaScore | None:
        total_weight = 0.0
        weighted_accuracy = 0.0
        for model_name, contribution_weight in price_forecast.model_contributions.items():
            backtest = latest_backtests.get(model_name)
            if backtest is None or contribution_weight <= 0:
                continue
            weighted_accuracy += contribution_weight * backtest.directional_accuracy
            total_weight += contribution_weight
        if total_weight == 0:
            return None

        accuracy = weighted_accuracy / total_weight
        score = round(accuracy * 100, 2)
        return AgentAlphaScore(
            agent_type=agent_type,
            score=score,
            method=METHOD_BACKTESTED,
            sample_size=len(latest_backtests),
            components={"weighted_directional_accuracy": score},
        )

    def _score_confidence_consistency(
        self, agent_type: AgentType, recent_confidences: list[float], has_citations_fraction: float | None
    ) -> AgentAlphaScore:
        if not recent_confidences:
            return AgentAlphaScore(
                agent_type=agent_type, score=_NEUTRAL_DEFAULT_SCORE, method=METHOD_CONFIDENCE_PROXY, sample_size=0
            )

        mean_confidence = fmean(recent_confidences) * 100
        consistency = 100.0
        if len(recent_confidences) >= 2:
            stdev = pstdev(recent_confidences)
            consistency = max(0.0, 100.0 - min(1.0, stdev / _CONSISTENCY_STDEV_SATURATION) * 100.0)
        evidence_quality = (has_citations_fraction or 0.0) * 100

        score = round(
            _WEIGHT_MEAN_CONFIDENCE * mean_confidence
            + _WEIGHT_CONSISTENCY * consistency
            + _WEIGHT_EVIDENCE * evidence_quality,
            2,
        )
        return AgentAlphaScore(
            agent_type=agent_type,
            score=max(0.0, min(100.0, score)),
            method=METHOD_CONFIDENCE_PROXY,
            sample_size=len(recent_confidences),
            components={
                "mean_confidence": round(mean_confidence, 2),
                "consistency": round(consistency, 2),
                "evidence_quality": round(evidence_quality, 2),
            },
        )
