from __future__ import annotations

import random
from dataclasses import dataclass

from .models import OrderSide, OrderStatus, OrderType, PaperFill, PaperOrder


@dataclass(frozen=True)
class SimulationConfig:
    """Tunable simulated-market-microstructure parameters. Defaults are conservative,
    illustrative values for NYMEX Henry Hub futures liquidity — not calibrated to any
    proprietary execution model."""

    slippage_bps: float = 2.0
    spread_bps: float = 3.0
    commission_per_contract: float = 2.50
    latency_ms_mean: float = 120.0
    latency_ms_jitter: float = 60.0
    min_partial_fill_fraction: float = 0.6
    max_partial_fill_probability: float = 0.15  # chance a market order only partially fills
    seed: int | None = None


class PaperExecutionEngine:
    """Simulates order execution. Never touches a live venue — this is the only
    execution path the platform ships with (see docs/risk-framework.md §8)."""

    def __init__(self, config: SimulationConfig | None = None):
        self.config = config or SimulationConfig()
        self._rng = random.Random(self.config.seed)

    def simulate_fill(self, order: PaperOrder, market_price: float) -> list[PaperFill]:
        if order.order_type == OrderType.LIMIT and not self._is_marketable(order, market_price):
            order.status = OrderStatus.PENDING
            return []

        spread_cost_per_unit = market_price * (self.config.spread_bps / 10_000)
        slippage_per_unit = market_price * (self.config.slippage_bps / 10_000) * self._rng.uniform(0.5, 1.5)
        direction = 1 if order.side == OrderSide.BUY else -1
        fill_price = round(market_price + direction * (spread_cost_per_unit + slippage_per_unit), 4)

        fill_quantity = order.quantity
        if self._rng.random() < self.config.max_partial_fill_probability:
            fraction = self._rng.uniform(self.config.min_partial_fill_fraction, 0.99)
            fill_quantity = round(order.quantity * fraction, 4)

        latency_ms = max(0.0, self._rng.gauss(self.config.latency_ms_mean, self.config.latency_ms_jitter))
        commission = self.config.commission_per_contract * fill_quantity

        fill = PaperFill(
            order_id=order.order_id,
            instrument=order.instrument,
            side=order.side,
            quantity=fill_quantity,
            fill_price=fill_price,
            slippage=round(slippage_per_unit * fill_quantity, 4),
            commission=round(commission, 2),
            spread_cost=round(spread_cost_per_unit * fill_quantity, 4),
            latency_ms=round(latency_ms, 1),
        )

        order.filled_quantity += fill_quantity
        order.status = (
            OrderStatus.FILLED if order.filled_quantity >= order.quantity - 1e-9 else OrderStatus.PARTIALLY_FILLED
        )

        return [fill]

    @staticmethod
    def _is_marketable(order: PaperOrder, market_price: float) -> bool:
        if order.limit_price is None:
            return False
        if order.side == OrderSide.BUY:
            return order.limit_price >= market_price
        return order.limit_price <= market_price
