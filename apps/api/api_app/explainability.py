from __future__ import annotations

from schemas import InvestmentCommitteeDecision, RiskCheckResult, TradeIdea


def build_explainability(
    trade: TradeIdea,
    committee: InvestmentCommitteeDecision | None,
    risk_check: RiskCheckResult | None,
) -> dict:
    """WHAT / WHY / WHY NOW / CATALYST / EXPECTED OUTCOME / ALTERNATIVE VIEW /
    WHAT INVALIDATES THE TRADE / CONFIDENCE / DATA QUALITY / RISK / SOURCES —
    every AI trade recommendation must carry this (see docs/architecture.md)."""
    return {
        "what": f"{trade.direction.value} {trade.instrument} ({trade.instrument_type.value})",
        "why": trade.thesis,
        "why_now": f"Time horizon: {trade.time_horizon}; expires {trade.expires_at.isoformat() if trade.expires_at else 'n/a'}",
        "catalyst": trade.catalysts,
        "expected_outcome": {
            "target": trade.target,
            "expected_return": trade.expected_return,
            "probability_success": trade.probability_success,
        },
        "alternative_view": committee.bear_case if committee else None,
        "what_invalidates_the_trade": trade.invalidation_conditions,
        "confidence": trade.confidence,
        "data_quality": committee.data_quality_assessment if committee else None,
        "risk": {
            "expected_loss": trade.expected_loss,
            "stop_or_invalidation": trade.stop_or_invalidation,
            "governor_verdict": risk_check.verdict.value if risk_check else None,
            "blocking_rule": (risk_check.blocking_rule.detail if risk_check and risk_check.blocking_rule else None),
        },
        "sources": trade.source_citations,
    }
