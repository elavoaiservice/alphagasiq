from quant_service.relative_value import calendar_spread_signal, hh_ttf_netback_signal


class TestHhTtfNetbackSignal:
    def test_large_positive_netback_is_cheap(self):
        result = hh_ttf_netback_signal(henry_hub_price=2.0, ttf_price=9.0)
        assert result.direction == "CHEAP"
        assert result.mispricing > 0

    def test_hh_richer_than_ttf_net_of_costs_is_rich(self):
        result = hh_ttf_netback_signal(henry_hub_price=9.0, ttf_price=9.5)
        assert result.direction == "RICH"
        assert result.mispricing < 0

    def test_near_zero_netback_is_fair(self):
        # HH ~= TTF - full cost chain (~3.8) => netback near 0
        result = hh_ttf_netback_signal(henry_hub_price=5.7, ttf_price=9.5)
        assert result.direction == "FAIR"

    def test_confidence_bounded(self):
        result = hh_ttf_netback_signal(henry_hub_price=2.0, ttf_price=9.0)
        assert 0 <= result.confidence <= 1

    def test_pair_and_signal_type_are_stable_identifiers(self):
        result = hh_ttf_netback_signal(henry_hub_price=3.0, ttf_price=9.0)
        assert result.pair == "HH_TTF_NETBACK"
        assert result.signal_type == "LNG_EXPORT_ARBITRAGE"


class TestCalendarSpreadSignal:
    def test_wide_contango_is_rich(self):
        result = calendar_spread_signal(m1_price=2.5, m2_price=2.7)
        assert result.direction == "RICH"
        assert result.mispricing > 0

    def test_backwardation_is_cheap(self):
        result = calendar_spread_signal(m1_price=2.7, m2_price=2.5)
        assert result.direction == "CHEAP"
        assert result.mispricing < 0

    def test_spread_matching_cost_of_carry_is_fair(self):
        result = calendar_spread_signal(m1_price=2.5, m2_price=2.58)
        assert result.direction == "FAIR"

    def test_fair_value_estimate_equals_carry_cost_constant(self):
        result = calendar_spread_signal(m1_price=3.0, m2_price=3.0)
        assert result.fair_value_estimate == 0.08
