from datetime import date

from fundamentals_service.storage_forecast import (
    forecast_storage_week,
    project_end_of_season,
    week_ending_for,
)
from tests.fundamentals.test_balance import make_balance


def test_week_ending_for_friday_is_itself():
    friday = date(2026, 8, 21)
    assert friday.weekday() == 4
    assert week_ending_for(friday) == friday


def test_week_ending_for_mid_week():
    wednesday = date(2026, 8, 26)
    assert week_ending_for(wednesday) == date(2026, 8, 21)


def test_forecast_storage_week_matches_balance_sum():
    week = [make_balance(flow_date=date(2026, 8, 15 + i)) for i in range(7)]
    forecast = forecast_storage_week(
        week_ending=date(2026, 8, 21),
        daily_balances=week,
        five_year_average_bcf=3000,
        last_year_bcf=2950,
    )
    expected = round(sum(b.balance_bcf for b in week))
    assert forecast.forecast_bcf == expected
    assert forecast.forecast_range_low < forecast.forecast_bcf < forecast.forecast_range_high


def test_forecast_storage_week_empty_balances_is_zero():
    forecast = forecast_storage_week(
        week_ending=date(2026, 8, 21), daily_balances=[], five_year_average_bcf=3000, last_year_bcf=2950
    )
    assert forecast.forecast_bcf == 0
    assert forecast.confidence == 0.5


def test_forecast_confidence_higher_with_full_week():
    full_week = [make_balance(flow_date=date(2026, 8, 15 + i)) for i in range(7)]
    partial_week = full_week[:2]
    full = forecast_storage_week(week_ending=date(2026, 8, 21), daily_balances=full_week, five_year_average_bcf=3000, last_year_bcf=2950)
    partial = forecast_storage_week(week_ending=date(2026, 8, 21), daily_balances=partial_week, five_year_average_bcf=3000, last_year_bcf=2950)
    assert full.confidence > partial.confidence


def test_project_end_of_season_sums_weekly_forecasts():
    result = project_end_of_season(current_inventory_bcf=2000, weekly_forecasts_bcf=[50, 40, -10])
    assert result == 2000 + 50 + 40 - 10
