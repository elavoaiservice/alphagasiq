import pytest
from paper_execution_service import (
    OrderSide,
    OrderStatus,
    OrderType,
    PaperExecutionAdapter,
    PaperExecutionEngine,
    PaperOrder,
    PaperPortfolio,
    SimulationConfig,
)


def make_engine(**overrides) -> PaperExecutionEngine:
    defaults = dict(seed=42, max_partial_fill_probability=0.0)
    defaults.update(overrides)
    return PaperExecutionEngine(SimulationConfig(**defaults))


def test_market_buy_fills_above_market_price_due_to_spread_and_slippage():
    engine = make_engine()
    order = PaperOrder(instrument="NGZ26", order_type=OrderType.MARKET, side=OrderSide.BUY, quantity=10)
    fills = engine.simulate_fill(order, market_price=3.00)
    assert len(fills) == 1
    assert fills[0].fill_price > 3.00
    assert order.status == OrderStatus.FILLED


def test_market_sell_fills_below_market_price():
    engine = make_engine()
    order = PaperOrder(instrument="NGZ26", order_type=OrderType.MARKET, side=OrderSide.SELL, quantity=10)
    fills = engine.simulate_fill(order, market_price=3.00)
    assert fills[0].fill_price < 3.00


def test_limit_order_not_marketable_produces_no_fill():
    engine = make_engine()
    order = PaperOrder(
        instrument="NGZ26", order_type=OrderType.LIMIT, side=OrderSide.BUY, quantity=10, limit_price=2.50
    )
    fills = engine.simulate_fill(order, market_price=3.00)
    assert fills == []
    assert order.status == OrderStatus.PENDING


def test_limit_buy_marketable_fills():
    engine = make_engine()
    order = PaperOrder(
        instrument="NGZ26", order_type=OrderType.LIMIT, side=OrderSide.BUY, quantity=10, limit_price=3.10
    )
    fills = engine.simulate_fill(order, market_price=3.00)
    assert len(fills) == 1


def test_commission_scales_with_quantity():
    engine = make_engine()
    small = engine.simulate_fill(
        PaperOrder(instrument="NGZ26", order_type=OrderType.MARKET, side=OrderSide.BUY, quantity=1), 3.0
    )[0]
    large = engine.simulate_fill(
        PaperOrder(instrument="NGZ26", order_type=OrderType.MARKET, side=OrderSide.BUY, quantity=100), 3.0
    )[0]
    assert large.commission > small.commission


def test_partial_fill_marks_order_partially_filled():
    engine = make_engine(max_partial_fill_probability=1.0, min_partial_fill_fraction=0.5)
    order = PaperOrder(instrument="NGZ26", order_type=OrderType.MARKET, side=OrderSide.BUY, quantity=10)
    fills = engine.simulate_fill(order, market_price=3.0)
    assert fills[0].quantity < 10
    assert order.status == OrderStatus.PARTIALLY_FILLED


def test_portfolio_apply_fill_opens_position():
    portfolio = PaperPortfolio()
    engine = make_engine()
    order = PaperOrder(instrument="NGZ26", order_type=OrderType.MARKET, side=OrderSide.BUY, quantity=10)
    fill = engine.simulate_fill(order, 3.0)[0]
    position = portfolio.apply_fill(fill)
    assert position.quantity == 10
    assert position.avg_price == fill.fill_price


def test_portfolio_realizes_pnl_on_close():
    portfolio = PaperPortfolio()
    engine = make_engine()

    buy = PaperOrder(instrument="NGZ26", order_type=OrderType.MARKET, side=OrderSide.BUY, quantity=10)
    buy_fill = engine.simulate_fill(buy, 3.0)[0]
    portfolio.apply_fill(buy_fill)

    sell = PaperOrder(instrument="NGZ26", order_type=OrderType.MARKET, side=OrderSide.SELL, quantity=10)
    sell_fill = engine.simulate_fill(sell, 3.50)[0]
    position = portfolio.apply_fill(sell_fill)

    assert position.quantity == 0
    assert portfolio.total_realized_pnl() > 0  # bought low, sold high


def test_portfolio_flips_through_zero():
    portfolio = PaperPortfolio()
    engine = make_engine()

    buy = PaperOrder(instrument="NGZ26", order_type=OrderType.MARKET, side=OrderSide.BUY, quantity=10)
    portfolio.apply_fill(engine.simulate_fill(buy, 3.0)[0])

    big_sell = PaperOrder(instrument="NGZ26", order_type=OrderType.MARKET, side=OrderSide.SELL, quantity=25)
    position = portfolio.apply_fill(engine.simulate_fill(big_sell, 3.0)[0])

    assert position.quantity == -15


@pytest.mark.asyncio
async def test_execution_adapter_updates_portfolio():
    adapter = PaperExecutionAdapter(engine=make_engine())
    order = PaperOrder(instrument="NGZ26", order_type=OrderType.MARKET, side=OrderSide.BUY, quantity=5)
    fills = await adapter.submit_order(order, market_price=3.0)
    assert len(fills) == 1
    assert adapter.portfolio.positions["NGZ26"].quantity == 5


def test_all_simulated_fills_flagged():
    engine = make_engine()
    order = PaperOrder(instrument="NGZ26", order_type=OrderType.MARKET, side=OrderSide.BUY, quantity=5)
    fill = engine.simulate_fill(order, 3.0)[0]
    assert fill.is_simulated is True
    assert order.is_simulated is True
