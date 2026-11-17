"""Forecasting: the tests and estimates behind the automatic ARIMA / SARIMA choice."""

import math
import random
import unittest

from server import forecast


def ar1(n, phi, mu=0.0, seed=1):
    rnd = random.Random(seed)
    y, prev = [], 0.0
    for _ in range(n + 50):
        prev = phi * prev + rnd.gauss(0, 1)
        y.append(mu + prev)
    return y[50:]


def seasonal(n, seed=2, first_month=4):
    """A yearly pattern (best in January, worst in August) around a gentle rise, with noise."""
    rnd = random.Random(seed)
    shape = {1: 30, 2: 5, 3: 0, 4: -10, 5: 20, 6: 0, 7: -5, 8: -30, 9: 15, 10: 0, 11: -5, 12: -20}
    return [100 + 0.5 * t + shape[(first_month - 1 + t) % 12 + 1] + rnd.gauss(0, 3) for t in range(n)]


class ForecastTests(unittest.TestCase):

    def test_an_ar1_is_estimated_close_to_the_truth(self):
        y = ar1(240, 0.7, mu=5)
        m = forecast.fit_arma(y, 1, 0, 0, 0, True, 1)
        self.assertAlmostEqual(m["phi"][0], 0.7, delta=0.1)
        self.assertAlmostEqual(m["mu"], 5, delta=0.6)
        self.assertAlmostEqual(math.sqrt(m["sigma2"]), 1, delta=0.15)

    def test_a_yearly_pattern_is_found_and_carried_forward(self):
        y = seasonal(48)
        out = forecast.forecast(y, 4, 24)
        m = out["model"]
        self.assertEqual(m["method"], "sarima")
        self.assertEqual(m["seasonalOrder"][1], 1)                 # seasonally differenced
        self.assertGreater(m["seasonalStrength"], forecast.SEASONAL_STRENGTH)
        best = max(m["seasonality"], key=m["seasonality"].get)
        worst = min(m["seasonality"], key=m["seasonality"].get)
        self.assertEqual((best, worst), (1, 8))                     # January and August
        # The forecast for next January beats next August, as the history does.
        months = [(4 - 1 + 48 + i) % 12 + 1 for i in range(24)]
        jan = out["points"][months.index(1)]["net"]
        aug = out["points"][months.index(8)]["net"]
        self.assertGreater(jan - aug, 40)
        self.assertLess(m["backtest"]["mae"], m["backtest"]["lineMae"])

    def test_ranges_hold_the_forecast_and_widen_ahead(self):
        out = forecast.forecast(ar1(60, 0.6, mu=10, seed=5), 1, 12)
        for p in out["points"]:
            self.assertTrue(p["lo95"] <= p["lo80"] <= p["net"] <= p["hi80"] <= p["hi95"], p)
        widths = [p["hi95"] - p["lo95"] for p in out["points"]]
        self.assertGreaterEqual(widths[-1], widths[0])

    def test_short_series_use_a_straight_line_or_nothing(self):
        self.assertIsNone(forecast.forecast([1, 2, 3], 1, 12))
        out = forecast.forecast([10, 12, 13, 15, 16, 18, 19, 21], 1, 6)
        self.assertEqual(out["model"]["method"], "line")
        self.assertIsNone(out["model"]["backtest"])
        self.assertAlmostEqual(out["points"][0]["net"], 22.5, delta=0.6)

    def test_kpss_tells_a_drift_from_a_level(self):
        rnd = random.Random(7)
        noise = [rnd.gauss(0, 1) for _ in range(60)]
        walk = []
        for v in noise:
            walk.append((walk[-1] if walk else 0) + v + 0.5)
        self.assertLess(forecast.kpss(noise), forecast.KPSS_CRITICAL)
        self.assertGreater(forecast.kpss(walk), forecast.KPSS_CRITICAL)

    def test_ljung_box_and_its_chi_square(self):
        self.assertAlmostEqual(forecast._gammaincc(0.5, 3.841 / 2), 0.05, places=3)     # chi-square(1) at 3.841
        self.assertAlmostEqual(forecast._gammaincc(5, 18.307 / 2), 0.05, places=3)     # chi-square(10) at 18.307
        rnd = random.Random(11)
        self.assertGreater(forecast.ljung_box([rnd.gauss(0, 1) for _ in range(120)], 12, 0), 0.05)
        self.assertLess(forecast.ljung_box(ar1(120, 0.8, seed=12), 12, 0), 0.01)

    def test_the_same_figures_give_the_same_cached_forecast(self):
        y = ar1(30, 0.5, seed=13)
        self.assertIs(forecast.forecast(y, 1, 12), forecast.forecast(list(y), 1, 12))


if __name__ == "__main__":
    unittest.main()
