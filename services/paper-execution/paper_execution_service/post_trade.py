"""Post-trade analysis: generated once a paper position closes.

This is a first-pass, deterministic heuristic — not the full walk-forward model
evaluation framework described for the Quantitative Team (`services/quant`, not yet
built). It exists to make the platform's core discipline concrete: **decision quality
and outcome quality are scored separately and never conflated.** A well-reasoned trade
that lost money is not the same failure as a reckless trade that happened to work, and
`OutcomeQuadrant` is what keeps that distinction visible in the record instead of
collapsing everything to "was it profitable."
"""

from __future__ import annotations

from datetime import datetime

from schemas import (
    Direction,
    InvestmentCommitteeDecision,
    OutcomeQuadrant,
    PostTradeAnalysis,
    RiskCheckResult,
    RiskVerdict,
    TradeIdea,
)

GOOD_DECISION_CONSENSUS_THRESHOLD = 0.6


def evaluate_post_trade(
    *,
    trade: TradeIdea,
    committee: InvestmentCommitteeDecision,
    risk_check: RiskCheckResult,
    entry_price: float,
    exit_price: float,
    opened_at: datetime,
    closed_at: datetime,
) -> PostTradeAnalysis:
    direction_sign = 1 if trade.direction == Direction.LONG else -1
    actual_return = direction_sign * (exit_price - entry_price)
    expected_return = trade.expected_return
    forecast_error = round(actual_return - expected_return, 4)

    # Thesis accuracy: did the move go the right way, and how close in magnitude?
    same_direction = (actual_return >= 0) == (expected_return >= 0)
    magnitude_gap = abs(forecast_error) / max(abs(expected_return), 0.01)
    thesis_accuracy = round(max(0.0, min(1.0, (1.0 if same_direction else 0.2) - 0.3 * min(1.0, magnitude_gap))), 3)

    # Timing accuracy: did the exit land inside the planned range, hit target, or blow
    # through the stop/invalidation level?
    breached_stop = direction_sign * (exit_price - trade.stop_or_invalidation) < 0
    reached_target = direction_sign * (exit_price - trade.target) >= 0
    if breached_stop:
        timing_accuracy = 0.3
    elif reached_target:
        timing_accuracy = 1.0
    else:
        timing_accuracy = 0.7

    # Risk accuracy: was any realized loss within the pre-trade expected_loss bound?
    if actual_return >= 0:
        risk_accuracy = 1.0
    else:
        risk_accuracy = round(max(0.0, min(1.0, 1 - (abs(actual_return) / max(trade.expected_loss, 0.01) - 1))), 3)

    was_good_decision = (
        committee.consensus_score >= GOOD_DECISION_CONSENSUS_THRESHOLD and risk_check.verdict == RiskVerdict.ALLOW
    )
    was_good_outcome = actual_return > 0

    if was_good_decision and was_good_outcome:
        quadrant = OutcomeQuadrant.GOOD_DECISION_GOOD_OUTCOME
    elif was_good_decision and not was_good_outcome:
        quadrant = OutcomeQuadrant.GOOD_DECISION_BAD_OUTCOME
    elif not was_good_decision and was_good_outcome:
        quadrant = OutcomeQuadrant.BAD_DECISION_GOOD_OUTCOME
    else:
        quadrant = OutcomeQuadrant.BAD_DECISION_BAD_OUTCOME

    lessons_parts = [
        f"Thesis was {'directionally correct' if same_direction else 'directionally wrong'} "
        f"(expected {expected_return:+.3f}, actual {actual_return:+.3f} per unit).",
    ]
    if breached_stop:
        lessons_parts.append("Exit breached the pre-trade invalidation level — the stop discipline held but the thesis did not.")
    elif reached_target:
        lessons_parts.append("Trade reached its target — thesis and timing both validated.")
    if quadrant == OutcomeQuadrant.BAD_DECISION_GOOD_OUTCOME:
        lessons_parts.append("Profitable, but the committee/risk record does not support calling this a well-reasoned decision — avoid treating this as validation of the process.")
    elif quadrant == OutcomeQuadrant.GOOD_DECISION_BAD_OUTCOME:
        lessons_parts.append("Process was sound (committee consensus + risk-approved); the loss reflects normal variance, not a process failure.")

    return PostTradeAnalysis(
        trade_id=trade.trade_id,
        expected_outcome={
            "target": trade.target,
            "expected_return": expected_return,
            "expected_loss": trade.expected_loss,
            "probability_success": trade.probability_success,
        },
        actual_outcome={
            "entry_price": entry_price,
            "exit_price": exit_price,
            "actual_return_per_unit": round(actual_return, 4),
            "opened_at": opened_at.isoformat(),
            "closed_at": closed_at.isoformat(),
        },
        forecast_error=forecast_error,
        thesis_accuracy=thesis_accuracy,
        timing_accuracy=timing_accuracy,
        risk_accuracy=risk_accuracy,
        model_contribution={
            "committee_consensus_score": committee.consensus_score,
            "trade_confidence": trade.confidence,
            "risk_governor_verdict_at_approval": risk_check.verdict.value,
        },
        unexpected_events=[],
        lessons=" ".join(lessons_parts),
        quadrant=quadrant,
    )
