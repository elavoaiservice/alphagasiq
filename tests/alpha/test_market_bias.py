from datetime import date, datetime, timezone

from alpha_service.market_bias import compute_market_bias
from schemas import GasBalanceDaily, MarketBiasLabel


def _balance(day: int, **overrides) -> GasBalanceDaily:
    base = dict(
        flow_date=date(2026, 8, day),
        production_bcf=100.0,
        canadian_imports_bcf=5.0,
        lng_sendout_bcf=0.0,
        other_supply_bcf=0.0,
        rescom_demand_bcf=30.0,
        industrial_demand_bcf=20.0,
        power_burn_bcf=25.0,
        lng_feedgas_bcf=14.0,
        mexico_exports_bcf=6.0,
        other_exports_bcf=0.0,
    )
    base.update(overrides)
    return GasBalanceDaily(**base)


def test_insufficient_data_when_no_inputs_provided():
    result = compute_market_bias()
    assert result.label == MarketBiasLabel.INSUFFICIENT_DATA
    assert result.score is None
    assert result.drivers == []


def test_weather_driver_missing_required_keys_returns_none_driver():
    # hdd_comparison missing -> weather driver omitted, but storage still contributes.
    result = compute_market_bias(
        weather_kwargs={"hdd_run": 10.0, "cdd_run": 1.0, "cdd_comparison": 1.0},
        storage_baseline={"current_inventory_bcf": 2900.0, "five_year_average_bcf": 3000.0},
    )
    assert all(d.name != "Weather" for d in result.drivers)
    assert any(d.name == "Storage" for d in result.drivers)


def test_weather_driver_colder_and_hotter_than_prior_is_bullish():
    result = compute_market_bias(
        weather_kwargs={
            "hdd_run": 15.0,
            "hdd_comparison": 10.0,
            "cdd_run": 8.0,
            "cdd_comparison": 4.0,
        }
    )
    weather = next(d for d in result.drivers if d.name == "Weather")
    assert weather.points > 0
    assert result.score is not None
    assert result.score > 50.0


def test_storage_deficit_vs_five_year_average_is_bullish():
    result = compute_market_bias(
        storage_baseline={"current_inventory_bcf": 2800.0, "five_year_average_bcf": 3100.0}
    )
    storage = next(d for d in result.drivers if d.name == "Storage")
    assert storage.points > 0
    assert "deficit" in storage.rationale


def test_storage_surplus_vs_five_year_average_is_bearish():
    result = compute_market_bias(
        storage_baseline={"current_inventory_bcf": 3300.0, "five_year_average_bcf": 3100.0}
    )
    storage = next(d for d in result.drivers if d.name == "Storage")
    assert storage.points < 0
    assert "surplus" in storage.rationale


def test_storage_driver_none_when_fields_missing():
    result = compute_market_bias(storage_baseline={"current_inventory_bcf": 2900.0})
    assert all(d.name != "Storage" for d in result.drivers)


def test_balance_derived_drivers_require_two_full_weeks_of_history():
    # Only 10 days of balances -- fewer than 2 full 7-day weeks -> no balance drivers.
    balances = [_balance(d) for d in range(1, 11)]
    result = compute_market_bias(recent_balances=balances)
    names = {d.name for d in result.drivers}
    assert names.isdisjoint({"Production", "Demand", "LNG", "Power"})


def test_production_increase_week_over_week_is_bearish():
    prior_week = [_balance(d, production_bcf=95.0) for d in range(1, 8)]
    recent_week = [_balance(d, production_bcf=105.0) for d in range(8, 15)]
    result = compute_market_bias(recent_balances=prior_week + recent_week)
    production = next(d for d in result.drivers if d.name == "Production")
    assert production.points < 0


def test_demand_increase_week_over_week_is_bullish():
    prior_week = [_balance(d, rescom_demand_bcf=30.0, industrial_demand_bcf=20.0) for d in range(1, 8)]
    recent_week = [_balance(d, rescom_demand_bcf=40.0, industrial_demand_bcf=25.0) for d in range(8, 15)]
    result = compute_market_bias(recent_balances=prior_week + recent_week)
    demand = next(d for d in result.drivers if d.name == "Demand")
    assert demand.points > 0


def test_lng_feedgas_increase_is_bullish():
    prior_week = [_balance(d, lng_feedgas_bcf=10.0) for d in range(1, 8)]
    recent_week = [_balance(d, lng_feedgas_bcf=16.0) for d in range(8, 15)]
    result = compute_market_bias(recent_balances=prior_week + recent_week)
    lng = next(d for d in result.drivers if d.name == "LNG")
    assert lng.points > 0


def test_power_burn_increase_is_bullish():
    prior_week = [_balance(d, power_burn_bcf=20.0) for d in range(1, 8)]
    recent_week = [_balance(d, power_burn_bcf=28.0) for d in range(8, 15)]
    result = compute_market_bias(recent_balances=prior_week + recent_week)
    power = next(d for d in result.drivers if d.name == "Power")
    assert power.points > 0


def test_price_momentum_up_is_bullish():
    result = compute_market_bias(recent_prices=[2.50, 2.55, 2.60, 2.75])
    momentum = next(d for d in result.drivers if d.name == "Price/market")
    assert momentum.points > 0


def test_price_momentum_requires_at_least_two_points():
    result = compute_market_bias(recent_prices=[2.50])
    assert all(d.name != "Price/market" for d in result.drivers)


def test_consensus_driver_bullish_net_probability():
    result = compute_market_bias(
        consensus_bull_probability=0.7, consensus_bear_probability=0.2, consensus_confidence=0.8
    )
    consensus = next(d for d in result.drivers if d.name == "Agent consensus")
    assert consensus.points > 0


def test_consensus_driver_none_when_any_component_missing():
    result = compute_market_bias(consensus_bull_probability=0.7, consensus_bear_probability=0.2)
    assert all(d.name != "Agent consensus" for d in result.drivers)


def test_score_clamped_to_0_100_with_extreme_inputs():
    prior_week = [_balance(d, production_bcf=200.0, rescom_demand_bcf=0.0, industrial_demand_bcf=0.0) for d in range(1, 8)]
    recent_week = [_balance(d, production_bcf=0.0, rescom_demand_bcf=200.0, industrial_demand_bcf=200.0) for d in range(8, 15)]
    result = compute_market_bias(
        weather_kwargs={"hdd_run": 100.0, "hdd_comparison": 0.0, "cdd_run": 100.0, "cdd_comparison": 0.0},
        storage_baseline={"current_inventory_bcf": 0.0, "five_year_average_bcf": 10000.0},
        recent_balances=prior_week + recent_week,
        recent_prices=[1.0, 100.0],
        consensus_bull_probability=1.0,
        consensus_bear_probability=0.0,
        consensus_confidence=1.0,
    )
    assert 0.0 <= result.score <= 100.0
    assert result.label == MarketBiasLabel.STRONGLY_BULLISH


def test_computed_at_defaults_to_now_utc_when_not_provided():
    before = datetime.now(timezone.utc)
    result = compute_market_bias(recent_prices=[2.0, 2.1])
    after = datetime.now(timezone.utc)
    assert before <= result.computed_at <= after


def test_computed_at_uses_provided_now():
    fixed = datetime(2026, 1, 1, tzinfo=timezone.utc)
    result = compute_market_bias(recent_prices=[2.0, 2.1], now=fixed)
    assert result.computed_at == fixed
