from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def _uuid_str() -> str:
    return str(uuid.uuid4())


class TradeIdeaRow(Base):
    __tablename__ = "trade_ideas"

    trade_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid_str)
    strategy: Mapped[str] = mapped_column(String, nullable=False)
    instrument: Mapped[str] = mapped_column(String, nullable=False)
    instrument_type: Mapped[str] = mapped_column(String, nullable=False)
    direction: Mapped[str] = mapped_column(String, nullable=False)
    entry: Mapped[float] = mapped_column(Float, nullable=False)
    target: Mapped[float] = mapped_column(Float, nullable=False)
    stop_or_invalidation: Mapped[float] = mapped_column(Float, nullable=False)
    time_horizon: Mapped[str] = mapped_column(String, nullable=False)
    expected_return: Mapped[float] = mapped_column(Float, nullable=False)
    expected_loss: Mapped[float] = mapped_column(Float, nullable=False)
    probability_success: Mapped[float] = mapped_column(Float, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    thesis: Mapped[str] = mapped_column(String, nullable=False)
    catalysts: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    risks: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    invalidation_conditions: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    supporting_data: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    source_citations: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Quant/post-trade unification: the PriceForecast attached at trade creation,
    # stored as its raw dict so it round-trips without needing its own table.
    forecast: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class CommitteeDecisionRow(Base):
    __tablename__ = "committee_decisions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid_str)
    original_trade_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("trade_ideas.trade_id"), nullable=False
    )
    original_trade: Mapped[dict] = mapped_column(JSON, nullable=False)
    bull_case: Mapped[str] = mapped_column(String, nullable=False)
    bear_case: Mapped[str] = mapped_column(String, nullable=False)
    skeptic_case: Mapped[str] = mapped_column(String, nullable=False)
    data_quality_assessment: Mapped[str] = mapped_column(String, nullable=False)
    portfolio_effect: Mapped[str] = mapped_column(String, nullable=False)
    consensus_score: Mapped[float] = mapped_column(Float, nullable=False)
    unresolved_questions: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    recommended_action: Mapped[str] = mapped_column(String, nullable=False)
    decided_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)


class RiskCheckRow(Base):
    __tablename__ = "risk_checks"

    check_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid_str)
    trade_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("trade_ideas.trade_id"), nullable=False
    )
    verdict: Mapped[str] = mapped_column(String, nullable=False)
    rule_results: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    governor_version: Mapped[str] = mapped_column(String, nullable=False)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)


class ApprovalRow(Base):
    __tablename__ = "approvals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid_str)
    trade_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("trade_ideas.trade_id"), nullable=False
    )
    state: Mapped[str] = mapped_column(String, nullable=False)
    actions: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    current_user_id: Mapped[str | None] = mapped_column(String, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)


class DecisionJournalRow(Base):
    __tablename__ = "decision_journal"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid_str)
    trade_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("trade_ideas.trade_id"), nullable=False
    )
    entry: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)


class PostTradeAnalysisRow(Base):
    __tablename__ = "post_trade_analyses"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid_str)
    trade_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("trade_ideas.trade_id"), nullable=False
    )
    expected_outcome: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    actual_outcome: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    forecast_error: Mapped[float | None] = mapped_column(Float, nullable=True)
    thesis_accuracy: Mapped[float] = mapped_column(Float, nullable=False)
    timing_accuracy: Mapped[float] = mapped_column(Float, nullable=False)
    risk_accuracy: Mapped[float] = mapped_column(Float, nullable=False)
    model_contribution: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    unexpected_events: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    lessons: Mapped[str] = mapped_column(String, nullable=False, default="")
    quadrant: Mapped[str] = mapped_column(String, nullable=False)
    quant_model_type: Mapped[str | None] = mapped_column(String, nullable=True)
    quant_model_version: Mapped[str | None] = mapped_column(String, nullable=True)
    quant_predicted_return: Mapped[float | None] = mapped_column(Float, nullable=True)
    quant_forecast_error: Mapped[float | None] = mapped_column(Float, nullable=True)
    quant_up_probability: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)


class RiskLimitsRow(Base):
    __tablename__ = "risk_limits"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid_str)
    max_position_size: Mapped[float] = mapped_column(Float, nullable=False)
    max_risk_per_trade: Mapped[float] = mapped_column(Float, nullable=False)
    max_daily_loss: Mapped[float] = mapped_column(Float, nullable=False)
    max_drawdown: Mapped[float] = mapped_column(Float, nullable=False)
    max_portfolio_var: Mapped[float] = mapped_column(Float, nullable=False)
    max_sector_exposure: Mapped[float] = mapped_column(Float, nullable=False)
    max_contract_exposure: Mapped[float] = mapped_column(Float, nullable=False)
    max_correlated_exposure: Mapped[float] = mapped_column(Float, nullable=False)
    effective_from: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )
    effective_to: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    set_by_user_id: Mapped[str | None] = mapped_column(String, nullable=True)
