from datetime import date

from fundamentals_service.balance import implied_storage_flow_bcf, summarize_period
from schemas import GasBalanceDaily


def make_balance(**overrides) -> GasBalanceDaily:
    defaults = dict(
        flow_date=date(2026, 1, 1),
        production_bcf=100.0,
        canadian_imports_bcf=5.0,
        lng_sendout_bcf=0.0,
        other_supply_bcf=1.0,
        rescom_demand_bcf=40.0,
        industrial_demand_bcf=20.0,
        power_burn_bcf=30.0,
        lng_feedgas_bcf=10.0,
        mexico_exports_bcf=5.0,
        other_exports_bcf=1.0,
    )
    defaults.update(overrides)
    return GasBalanceDaily(**defaults)


def test_supply_total_sums_components():
    b = make_balance()
    assert b.supply_total_bcf == 100.0 + 5.0 + 0.0 + 1.0


def test_demand_total_sums_components():
    b = make_balance()
    assert b.demand_total_bcf == 40.0 + 20.0 + 30.0 + 10.0 + 5.0 + 1.0


def test_balance_is_supply_minus_demand():
    b = make_balance()
    assert b.balance_bcf == b.supply_total_bcf - b.demand_total_bcf


def test_implied_storage_flow_matches_balance():
    b = make_balance()
    assert implied_storage_flow_bcf(b) == b.balance_bcf


def test_surplus_day_is_positive_balance():
    b = make_balance(production_bcf=200.0)
    assert b.balance_bcf > 0


def test_deficit_day_is_negative_balance():
    b = make_balance(production_bcf=10.0)
    assert b.balance_bcf < 0


def test_summarize_period_empty_list():
    summary = summarize_period([])
    assert summary == {"supply_total_bcf": 0.0, "demand_total_bcf": 0.0, "balance_bcf": 0.0, "days": 0}


def test_summarize_period_aggregates_multiple_days():
    days = [make_balance(flow_date=date(2026, 1, i + 1)) for i in range(3)]
    summary = summarize_period(days)
    assert summary["days"] == 3
    assert summary["supply_total_bcf"] == sum(d.supply_total_bcf for d in days)
    assert summary["demand_total_bcf"] == sum(d.demand_total_bcf for d in days)
    assert summary["balance_bcf"] == sum(d.balance_bcf for d in days)
