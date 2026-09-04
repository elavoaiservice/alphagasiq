"""Weather-demand impact engine: converts model-run HDD/CDD deltas into estimated
Bcf/day demand changes and a price-direction read.

Example: ECMWF 00z vs ECMWF 12z, or GFS 00z vs GFS 06z.
"""

from __future__ import annotations

from schemas import WeatherDemandImpact

# Rough population-weighted sensitivities (Bcf/day per degree-day, illustrative
# defaults suitable for demo/seed use; production values should be calibrated against
# historical EIA demand data by region).
DEFAULT_RESCOM_BCF_PER_HDD = 0.09
DEFAULT_POWER_BURN_BCF_PER_CDD = 0.05


def compute_weather_demand_impact(
    *,
    model: str,
    run: str,
    comparison_run: str,
    hdd_run: float,
    hdd_comparison: float,
    cdd_run: float,
    cdd_comparison: float,
    rescom_bcf_per_hdd: float = DEFAULT_RESCOM_BCF_PER_HDD,
    power_burn_bcf_per_cdd: float = DEFAULT_POWER_BURN_BCF_PER_CDD,
) -> WeatherDemandImpact:
    hdd_delta = hdd_run - hdd_comparison
    cdd_delta = cdd_run - cdd_comparison

    rescom_delta = hdd_delta * rescom_bcf_per_hdd
    power_burn_delta = cdd_delta * power_burn_bcf_per_cdd
    total_delta = rescom_delta + power_burn_delta

    if total_delta > 0.15:
        direction = "BULLISH"
    elif total_delta < -0.15:
        direction = "BEARISH"
    else:
        direction = "NEUTRAL"

    magnitude = min(1.0, abs(total_delta) / 5.0)
    confidence = round(0.5 + 0.5 * magnitude, 2)

    return WeatherDemandImpact(
        model=model,
        run=run,
        comparison_run=comparison_run,
        hdd_delta=round(hdd_delta, 2),
        cdd_delta=round(cdd_delta, 2),
        estimated_rescom_delta_bcf=round(rescom_delta, 3),
        estimated_power_burn_delta_bcf=round(power_burn_delta, 3),
        total_demand_delta_bcf=round(total_delta, 3),
        price_direction=direction,
        confidence=confidence,
    )
