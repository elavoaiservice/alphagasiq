from __future__ import annotations

from .models import PaperFill, PaperPosition


class PaperPortfolio:
    """In-memory paper-position book. `apps/api` persists snapshots of this to the
    `positions` table; kept dependency-free here so it's trivially unit-testable."""

    def __init__(self) -> None:
        self.positions: dict[str, PaperPosition] = {}
        self.fills: list[PaperFill] = []

    def apply_fill(self, fill: PaperFill) -> PaperPosition:
        position = self.positions.setdefault(fill.instrument, PaperPosition(instrument=fill.instrument))
        position.apply_fill(fill)
        self.fills.append(fill)
        return position

    def total_realized_pnl(self) -> float:
        return round(sum(p.realized_pnl for p in self.positions.values()), 2)

    def total_unrealized_pnl(self, marks: dict[str, float]) -> float:
        return round(
            sum(p.unrealized_pnl(marks.get(p.instrument, p.avg_price)) for p in self.positions.values()),
            2,
        )
