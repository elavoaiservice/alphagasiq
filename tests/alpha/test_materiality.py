"""Table-driven tests for AlphaSignal(TM)'s materiality engine (docs/alpha-intelligence.md
section 3), mirroring tests/risk/test_governor.py's style: one test per scoring
component, plus threshold-boundary and defensive "thin/absent data" cases. This engine
carries the same "must be trivially and exhaustively testable" bar the Risk Governor
does -- it decides which signals ever reach a trader or the Chief Trading Agent.
"""

from __future__ import annotations

from alpha_service.materiality import DEFAULT_MATERIALITY_THRESHOLD, MaterialityEngine, MaterialityInput
from schemas import DataClassification, SignalType


def make_input(**overrides) -> MaterialityInput:
    defaults = dict(
        signal_type=SignalType.PRICE_MOVE,
        confidence=1.0,
        data_quality=DataClassification.PUBLIC,
    )
    defaults.update(overrides)
    return MaterialityInput(**defaults)


class TestMagnitudeComponent:
    def test_large_percent_change_saturates_at_100(self):
        engine = MaterialityEngine()
        result = engine.score(make_input(percent_change=0.5, confidence=0.0, data_quality=DataClassification.SIMULATED))
        assert result.components["magnitude"] == 100.0

    def test_zero_percent_change_scores_zero_magnitude(self):
        engine = MaterialityEngine()
        result = engine.score(make_input(percent_change=0.0, confidence=0.0, data_quality=DataClassification.SIMULATED))
        assert result.components["magnitude"] == 0.0

    def test_missing_percent_change_treated_as_medium(self):
        engine = MaterialityEngine()
        result = engine.score(make_input(percent_change=None, confidence=0.0, data_quality=DataClassification.SIMULATED))
        assert result.components["magnitude"] == 50.0

    def test_magnitude_scales_linearly_below_saturation(self):
        engine = MaterialityEngine()
        result = engine.score(make_input(percent_change=0.10, confidence=0.0, data_quality=DataClassification.SIMULATED))
        # 0.10 / 0.20 saturation * 100 = 50.0
        assert result.components["magnitude"] == 50.0

    def test_negative_percent_change_uses_absolute_value(self):
        engine = MaterialityEngine()
        result = engine.score(make_input(percent_change=-0.5, confidence=0.0, data_quality=DataClassification.SIMULATED))
        assert result.components["magnitude"] == 100.0


class TestRarityComponent:
    def test_large_zscore_saturates_at_100(self):
        engine = MaterialityEngine()
        result = engine.score(make_input(z_score=10.0, confidence=0.0, data_quality=DataClassification.SIMULATED))
        assert result.components["rarity"] == 100.0

    def test_zero_zscore_scores_zero_rarity(self):
        engine = MaterialityEngine()
        result = engine.score(make_input(z_score=0.0, confidence=0.0, data_quality=DataClassification.SIMULATED))
        assert result.components["rarity"] == 0.0

    def test_missing_rarity_information_scores_zero_not_max(self):
        """No z-score and no percentile -> treated as unremarkable, not overstated."""
        engine = MaterialityEngine()
        result = engine.score(make_input(z_score=None, historical_percentile=None, confidence=0.0, data_quality=DataClassification.SIMULATED))
        assert result.components["rarity"] == 0.0

    def test_percentile_used_when_zscore_absent(self):
        engine = MaterialityEngine()
        result = engine.score(
            make_input(z_score=None, historical_percentile=99.0, confidence=0.0, data_quality=DataClassification.SIMULATED)
        )
        assert result.components["rarity"] == 98.0  # |99-50|/50*100

    def test_negative_zscore_uses_absolute_value(self):
        engine = MaterialityEngine()
        result = engine.score(make_input(z_score=-4.0, confidence=0.0, data_quality=DataClassification.SIMULATED))
        assert result.components["rarity"] == 100.0


class TestConfidenceComponent:
    def test_full_confidence_scores_100(self):
        engine = MaterialityEngine()
        result = engine.score(make_input(confidence=1.0, data_quality=DataClassification.SIMULATED))
        assert result.components["confidence"] == 100.0

    def test_zero_confidence_scores_zero(self):
        engine = MaterialityEngine()
        result = engine.score(make_input(confidence=0.0, data_quality=DataClassification.SIMULATED))
        assert result.components["confidence"] == 0.0

    def test_confidence_is_clamped_to_valid_range(self):
        engine = MaterialityEngine()
        result = engine.score(make_input(confidence=5.0, data_quality=DataClassification.SIMULATED))
        assert result.components["confidence"] == 100.0


class TestQualityComponent:
    def test_licensed_data_scores_highest(self):
        engine = MaterialityEngine()
        result = engine.score(make_input(confidence=0.0, data_quality=DataClassification.LICENSED))
        assert result.components["quality"] == 100.0

    def test_simulated_data_scores_lowest_of_the_named_tiers(self):
        engine = MaterialityEngine()
        result = engine.score(make_input(confidence=0.0, data_quality=DataClassification.SIMULATED))
        assert result.components["quality"] == 60.0

    def test_stale_data_is_discounted(self):
        engine = MaterialityEngine()
        result = engine.score(make_input(confidence=0.0, data_quality=DataClassification.PUBLIC, is_stale=True))
        assert result.components["quality"] == 40.0  # 80 * 0.5


class TestThreshold:
    def test_default_threshold_used_when_no_override_given(self):
        engine = MaterialityEngine()
        just_below = engine.score(
            make_input(percent_change=0.0, z_score=0.0, confidence=0.0, data_quality=DataClassification.SIMULATED)
        )
        assert just_below.score < DEFAULT_MATERIALITY_THRESHOLD
        assert not just_below.passed_threshold

    def test_high_signal_across_every_component_passes(self):
        engine = MaterialityEngine()
        result = engine.score(
            make_input(percent_change=0.5, z_score=10.0, confidence=1.0, data_quality=DataClassification.LICENSED)
        )
        assert result.score == 100.0
        assert result.passed_threshold

    def test_per_signal_type_override_threshold_is_honored(self):
        engine = MaterialityEngine(thresholds={SignalType.PRICE_MOVE: 5.0})
        result = engine.score(
            make_input(
                signal_type=SignalType.PRICE_MOVE,
                percent_change=0.0,
                z_score=0.0,
                confidence=0.1,
                data_quality=DataClassification.SIMULATED,
            )
        )
        assert result.passed_threshold  # would fail the default 60.0 threshold

    def test_score_never_exceeds_100_or_drops_below_0(self):
        engine = MaterialityEngine()
        result = engine.score(
            make_input(percent_change=1000.0, z_score=1000.0, confidence=1.0, data_quality=DataClassification.LICENSED)
        )
        assert 0.0 <= result.score <= 100.0
