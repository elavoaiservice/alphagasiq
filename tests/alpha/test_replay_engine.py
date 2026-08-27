"""`ReplayEngine.assemble()` (docs/alpha-intelligence.md section 9) is a pure
packaging function -- all real bitemporal filtering happens in the repository
layer (see tests/db/test_market_observations.py). These tests only prove it
packages whatever it's handed into the right shape, unmodified."""

from __future__ import annotations

from datetime import datetime, timezone

from alpha_service import ReplayEngine
from schemas import ReplayMode


def test_assemble_packages_inputs_unmodified():
    as_of = datetime(2026, 1, 1, tzinfo=timezone.utc)
    result = ReplayEngine().assemble(
        market="HENRY_HUB",
        as_of=as_of,
        price_observations=[],
        signals=[],
        impacts=[],
        consensus_views=[],
        scenario_runs=[],
        memory_records=[],
    )

    assert result.market == "HENRY_HUB"
    assert result.as_of == as_of
    assert result.price_observations == []
    assert result.signals == []


def test_assemble_always_reports_current_model_retrospective_mode():
    """Milestone 6's honesty-about-scope decision: `ReplayEngine` never claims
    `HISTORICAL_REALITY`/`ORIGINAL_MODEL_REPLAY`/`FULL_STRATEGY_REPLAY` -- those
    would require data this codebase does not have."""
    result = ReplayEngine().assemble(
        market="HENRY_HUB",
        as_of=datetime.now(timezone.utc),
        price_observations=[],
        signals=[],
        impacts=[],
        consensus_views=[],
        scenario_runs=[],
        memory_records=[],
    )
    assert result.mode == ReplayMode.CURRENT_MODEL_RETROSPECTIVE
