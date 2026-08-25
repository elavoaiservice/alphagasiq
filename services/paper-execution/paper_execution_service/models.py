from __future__ import annotations

from datetime import datetime
from enum import Enum
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"


class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderStatus(str, Enum):
    PENDING = "PENDING"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class PaperOrder(BaseModel):
    order_id: UUID = Field(default_factory=uuid4)
    trade_id: UUID | None = None
    instrument: str
    order_type: OrderType
    side: OrderSide
    quantity: float
    limit_price: float | None = None
    status: OrderStatus = OrderStatus.PENDING
    filled_quantity: float = 0.0
    submitted_at: datetime = Field(default_factory=datetime.utcnow)
    is_simulated: bool = True


class PaperFill(BaseModel):
    fill_id: UUID = Field(default_factory=uuid4)
    order_id: UUID
    instrument: str
    side: OrderSide
    quantity: float
    fill_price: float
    slippage: float
    commission: float
    spread_cost: float
    latency_ms: float
    filled_at: datetime = Field(default_factory=datetime.utcnow)
    is_simulated: bool = True


class PaperPosition(BaseModel):
    instrument: str
    quantity: float = 0.0
    avg_price: float = 0.0
    realized_pnl: float = 0.0

    def apply_fill(self, fill: PaperFill) -> None:
        signed_qty = fill.quantity if fill.side == OrderSide.BUY else -fill.quantity
        if self.quantity == 0 or (self.quantity > 0) == (signed_qty > 0):
            # Adding to (or opening) a position: blend the average price.
            total_qty = self.quantity + signed_qty
            if total_qty != 0:
                self.avg_price = (
                    self.avg_price * self.quantity + fill.fill_price * signed_qty
                ) / total_qty
            self.quantity = total_qty
        else:
            # Reducing or flipping a position: realize P&L on the closed portion.
            closing_qty = min(abs(signed_qty), abs(self.quantity))
            direction = 1 if self.quantity > 0 else -1
            self.realized_pnl += direction * closing_qty * (fill.fill_price - self.avg_price)
            self.quantity += signed_qty
            if abs(self.quantity) < 1e-9:
                self.quantity = 0.0
                self.avg_price = 0.0
            elif (self.quantity > 0) != (direction > 0):
                # Flipped through zero: new position opens at the fill price.
                self.avg_price = fill.fill_price

    def unrealized_pnl(self, mark_price: float) -> float:
        return (mark_price - self.avg_price) * self.quantity
