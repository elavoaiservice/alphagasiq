from fundamentals_service.weather_impact import compute_weather_demand_impact


def test_colder_run_is_bullish():
    impact = compute_weather_demand_impact(
        model="ECMWF", run="00z", comparison_run="12z",
        hdd_run=10.0, hdd_comparison=2.0, cdd_run=0.0, cdd_comparison=0.0,
    )
    assert impact.hdd_delta == 8.0
    assert impact.total_demand_delta_bcf > 0
    assert impact.price_direction == "BULLISH"


def test_warmer_run_is_bearish():
    impact = compute_weather_demand_impact(
        model="GFS", run="06z", comparison_run="00z",
        hdd_run=1.0, hdd_comparison=8.0, cdd_run=0.0, cdd_comparison=0.0,
    )
    assert impact.total_demand_delta_bcf < 0
    assert impact.price_direction == "BEARISH"


def test_negligible_change_is_neutral():
    impact = compute_weather_demand_impact(
        model="GFS", run="06z", comparison_run="00z",
        hdd_run=2.0, hdd_comparison=2.0, cdd_run=2.0, cdd_comparison=2.0,
    )
    assert impact.hdd_delta == 0
    assert impact.cdd_delta == 0
    assert impact.price_direction == "NEUTRAL"


def test_confidence_scales_with_magnitude():
    small = compute_weather_demand_impact(model="GFS", run="a", comparison_run="b", hdd_run=2.1, hdd_comparison=2.0, cdd_run=0, cdd_comparison=0)
    large = compute_weather_demand_impact(model="GFS", run="a", comparison_run="b", hdd_run=20.0, hdd_comparison=2.0, cdd_run=0, cdd_comparison=0)
    assert large.confidence >= small.confidence
