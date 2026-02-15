import datetime as dt
import unittest

from score_engine import ampel, clamp_score, night_window_for


class ScoreEngineTests(unittest.TestCase):
    def test_ampel_thresholds(self) -> None:
        self.assertEqual(ampel(70), "green")
        self.assertEqual(ampel(45), "yellow")
        self.assertEqual(ampel(10), "red")

    def test_clamp_score(self) -> None:
        self.assertEqual(clamp_score(-20), 0)
        self.assertEqual(clamp_score(120), 100)

    def test_night_window(self) -> None:
        ref = dt.datetime(2026, 2, 15, 23, 30, tzinfo=dt.timezone.utc)
        start, end = night_window_for(ref)
        self.assertEqual(start.hour, 22)
        self.assertEqual(end.hour, 6)


if __name__ == "__main__":
    unittest.main()
