from datetime import date

from quant_service.seed import generate_price_history


class TestGeneratePriceHistory:
    def test_generates_requested_number_of_days(self):
        obs = generate_price_history(end_date=date(2026, 8, 25), num_days=100)
        assert len(obs) == 100

    def test_deterministic_across_calls(self):
        a = generate_price_history(end_date=date(2026, 8, 25), num_days=50)
        b = generate_price_history(end_date=date(2026, 8, 25), num_days=50)
        assert [o.value for o in a] == [o.value for o in b]

    def test_all_prices_positive(self):
        obs = generate_price_history(end_date=date(2026, 8, 25), num_days=250)
        assert all(o.value > 0 for o in obs)

    def test_observations_are_chronologically_ordered(self):
        obs = generate_price_history(end_date=date(2026, 8, 25), num_days=50)
        times = [o.observation_time for o in obs]
        assert times == sorted(times)

    def test_includes_some_late_publications(self):
        obs = generate_price_history(end_date=date(2026, 8, 25), num_days=100)
        late = [o for o in obs if (o.publication_time - o.observation_time).days >= 2]
        assert len(late) > 0

    def test_most_publications_are_normal_same_or_next_day_lag(self):
        obs = generate_price_history(end_date=date(2026, 8, 25), num_days=100)
        normal = [o for o in obs if (o.publication_time - o.observation_time).days < 1]
        assert len(normal) > len(obs) / 2

    def test_all_marked_simulated(self):
        from schemas import DataClassification

        obs = generate_price_history(end_date=date(2026, 8, 25), num_days=10)
        assert all(o.source_type == DataClassification.SIMULATED for o in obs)
