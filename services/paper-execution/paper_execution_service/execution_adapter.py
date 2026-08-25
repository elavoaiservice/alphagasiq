"""ExecutionAdapter interface: the seam behind which a future regulated broker/exchange
connection could be added.

`PaperExecutionAdapter` is the ONLY implementation shipped. A `LiveBrokerExecutionAdapter`
is intentionally NOT implemented here — enabling one requires independent model
validation, legal/compliance review, credentials and entitlements, explicit human
authorization, and configured risk limits, none of which this repository can grant
itself. See docs/risk-framework.md §8.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from .engine import PaperExecutionEngine, SimulationConfig
from .models import OrderSide, OrderType, PaperFill, PaperOrder, PaperPosition
from .portfolio import PaperPortfolio


class ExecutionAdapter(ABC):
    @abstractmethod
    async def submit_order(self, order: PaperOrder, market_price: float) -> list[PaperFill]: ...


class PaperExecutionAdapter(ExecutionAdapter):
    def __init__(self, engine: PaperExecutionEngine | None = None, portfolio: PaperPortfolio | None = None):
        self.engine = engine or PaperExecutionEngine()
        self.portfolio = portfolio or PaperPortfolio()

    async def submit_order(self, order: PaperOrder, market_price: float) -> list[PaperFill]:
        fills = self.engine.simulate_fill(order, market_price)
        for fill in fills:
            self.portfolio.apply_fill(fill)
        return fills


__all__ = [
    "ExecutionAdapter",
    "PaperExecutionAdapter",
    "PaperExecutionEngine",
    "SimulationConfig",
    "OrderSide",
    "OrderType",
    "PaperFill",
    "PaperOrder",
    "PaperPosition",
    "PaperPortfolio",
]
