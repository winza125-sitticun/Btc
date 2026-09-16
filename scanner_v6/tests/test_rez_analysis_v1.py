import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from rez_analysis_v1 import (
    _classify_15m_trigger,
    _classify_1h_structure,
    analyze_rez_candidate,
    calculate_atr,
    find_confirmed_swings,
    hybrid_state,
)


HOUR = 3_600_000
M15 = 900_000


def candle(index, open_, high, low, close, step=HOUR):
    open_time = index * step
    return {
        "open_time": open_time,
        "open": float(open_),
        "high": float(high),
        "low": float(low),
        "close": float(close),
        "volume": 1.0,
        "close_time": open_time + step - 1,
    }


def long_continuation_1h(last_close=108.0, last_low=105.5, last_high=109.0):
    return [
        candle(0, 100, 102, 99, 101),
        candle(1, 101, 103, 100, 102),
        candle(2, 102, 106, 101, 104),
        candle(3, 104, 105, 100, 101),
        candle(4, 101, 104, 98.8, 103),
        candle(5, 103, 108, 102, 107.5),
        candle(6, 107.5, last_high, last_low, last_close),
    ]


def long_reversal_1h():
    return [
        candle(0, 100, 102, 99, 101),
        candle(1, 101, 103, 100, 102),
        candle(2, 102, 106, 101, 104),
        candle(3, 104, 105, 100, 101),
        candle(4, 101, 104, 98.8, 103),
        candle(5, 103, 108, 102, 107.5),
        candle(6, 107.5, 108, 96.5, 97.0),
        candle(7, 97.0, 101, 96.0, 100.0),
        candle(8, 100.0, 106, 99.0, 105.0),
        candle(9, 105.0, 105.5, 100.0, 101.0),
        candle(10, 101.0, 109, 100.5, 108.5),
        candle(11, 108.5, 110, 107.0, 109.0),
    ]


def range_1h():
    return [
        candle(0, 100, 102, 98, 100),
        candle(1, 100, 105, 99, 102),
        candle(2, 102, 103, 95, 99),
        candle(3, 99, 104, 97, 101),
        candle(4, 101, 103, 96, 100),
    ]


def m15(rows):
    return [candle(i, *row, step=M15) for i, row in enumerate(rows)]


class RezAnalysisTests(unittest.TestCase):
    def test_missing_history_fails_closed(self):
        result = analyze_rez_candidate(
            side="LONG",
            candles_1h=[],
            candles_15m=[],
            atr_period=14,
            atr_buffer_mult=0.25,
            swing_window=2,
            analysis_version="REZ_V1",
        )
        self.assertEqual(result.structure_1h, "UNKNOWN")
        self.assertEqual(result.state, "REJECT")

    def test_atr_rejects_insufficient_history(self):
        self.assertIsNone(calculate_atr([candle(0, 1, 2, 0.5, 1.5)], period=2))

    def test_confirmed_swings_exclude_edges_and_include_timestamp(self):
        candles = range_1h()
        swings = find_confirmed_swings(candles, window=1)
        self.assertEqual(swings["highs"][0]["price"], 105.0)
        self.assertEqual(swings["highs"][0]["timestamp"], candles[1]["close_time"])
        self.assertEqual(swings["lows"][0]["price"], 95.0)
        self.assertNotIn(0, [row["index"] for row in swings["highs"] + swings["lows"]])
        self.assertNotIn(len(candles) - 1, [row["index"] for row in swings["highs"] + swings["lows"]])

    def test_long_continuation_requires_close_confirmed_bos(self):
        result = _classify_1h_structure(
            side="LONG",
            candles=long_continuation_1h(),
            atr_period=2,
            atr_buffer_mult=0.10,
            swing_window=1,
        )
        self.assertEqual(result["structure"], "CONTINUATION")
        self.assertEqual(result["trigger_level_price"], 106.0)
        self.assertEqual(result["protected_swing_price"], 98.8)

    def test_pullback_keeps_protected_swing_intact(self):
        result = _classify_1h_structure(
            side="LONG",
            candles=long_continuation_1h(last_close=106.2, last_low=105.8, last_high=108.0),
            atr_period=2,
            atr_buffer_mult=0.10,
            swing_window=1,
        )
        self.assertEqual(result["structure"], "PULLBACK")
        self.assertFalse(result["invalidated"])

    def test_wick_only_break_is_not_bos(self):
        candles = [
            candle(0, 100, 102, 99, 101),
            candle(1, 101, 103, 100, 102),
            candle(2, 102, 106, 101, 104),
            candle(3, 104, 105, 100, 101),
            candle(4, 101, 104, 98.8, 103),
            candle(5, 103, 108, 102, 106.2),
            candle(6, 106.2, 107, 103, 105.5),
        ]
        result = _classify_1h_structure(
            side="LONG", candles=candles, atr_period=2, atr_buffer_mult=0.10, swing_window=1
        )
        self.assertNotEqual(result["structure"], "CONTINUATION")

    def test_reversal_requires_invalidation_then_new_same_side_bos(self):
        result = _classify_1h_structure(
            side="LONG",
            candles=long_reversal_1h(),
            atr_period=2,
            atr_buffer_mult=0.10,
            swing_window=1,
        )
        self.assertEqual(result["structure"], "REVERSAL")
        self.assertEqual(result["trigger_level_price"], 106.0)

    def test_overlapping_swings_classify_range(self):
        result = _classify_1h_structure(
            side="LONG", candles=range_1h(), atr_period=2, atr_buffer_mult=0.10, swing_window=1
        )
        self.assertEqual(result["structure"], "RANGE")
        self.assertIsNotNone(result["trigger_level_price"])

    def test_breakout_trigger_uses_closed_close_beyond_buffer(self):
        result = _classify_15m_trigger(
            side="LONG",
            candles=m15([
                (99.5, 100.0, 99.0, 99.6),
                (99.6, 100.0, 99.3, 99.8),
                (99.8, 100.0, 99.4, 99.7),
                (99.7, 100.1, 99.5, 99.9),
                (99.9, 100.7, 99.8, 100.5),
            ]),
            trigger_level=100.0,
            atr_period=2,
            atr_buffer_mult=0.10,
            swing_window=1,
        )
        self.assertEqual(result["trigger"], "BREAKOUT")
        self.assertFalse(result["opposite_trigger"])

    def test_retest_requires_prior_breakout_then_zone_touch(self):
        result = _classify_15m_trigger(
            side="LONG",
            candles=m15([
                (99.6, 99.9, 99.3, 99.7),
                (99.7, 100.0, 99.5, 99.8),
                (99.8, 100.0, 99.6, 99.9),
                (99.9, 100.7, 99.8, 100.5),
                (100.5, 100.55, 99.98, 100.2),
            ]),
            trigger_level=100.0,
            atr_period=2,
            atr_buffer_mult=0.10,
            swing_window=1,
        )
        self.assertEqual(result["trigger"], "RETEST")

    def test_reclaim_requires_close_back_on_valid_side(self):
        result = _classify_15m_trigger(
            side="LONG",
            candles=m15([
                (100.2, 100.4, 100.0, 100.2),
                (100.2, 100.3, 99.9, 100.1),
                (100.1, 100.2, 99.8, 99.9),
                (99.9, 100.0, 99.5, 99.7),
                (99.7, 100.4, 99.6, 100.2),
            ]),
            trigger_level=100.0,
            atr_period=2,
            atr_buffer_mult=0.10,
            swing_window=1,
        )
        self.assertEqual(result["trigger"], "RECLAIM")

    def test_rejection_requires_zone_facing_wick_at_least_body(self):
        result = _classify_15m_trigger(
            side="LONG",
            candles=m15([
                (100.3, 100.5, 100.1, 100.4),
                (100.4, 100.5, 100.15, 100.3),
                (100.3, 100.45, 100.05, 100.25),
                (100.25, 100.4, 100.08, 100.2),
                (100.25, 100.45, 99.95, 100.35),
            ]),
            trigger_level=100.0,
            atr_period=2,
            atr_buffer_mult=0.10,
            swing_window=1,
        )
        self.assertEqual(result["trigger"], "REJECTION")

    def test_liquidity_sweep_is_supporting_only(self):
        result = _classify_15m_trigger(
            side="LONG",
            candles=m15([
                (100.2, 100.4, 99.9, 100.1),
                (100.1, 100.3, 99.8, 100.0),
                (100.0, 100.2, 99.6, 99.9),
                (99.9, 100.3, 99.9, 100.15),
                (100.15, 100.4, 99.5, 100.3),
            ]),
            trigger_level=100.0,
            atr_period=2,
            atr_buffer_mult=0.10,
            swing_window=1,
        )
        self.assertIn("LIQUIDITY_SWEEP", result["supporting_triggers"])
        self.assertNotEqual(result["trigger"], "LIQUIDITY_SWEEP")

    def test_opposite_breakout_rejects(self):
        result = _classify_15m_trigger(
            side="LONG",
            candles=m15([
                (100.2, 100.4, 99.9, 100.1),
                (100.1, 100.3, 99.8, 100.0),
                (100.0, 100.2, 99.5, 99.9),
                (99.9, 100.1, 99.8, 100.0),
                (100.0, 100.05, 99.0, 99.2),
            ]),
            trigger_level=100.0,
            atr_period=2,
            atr_buffer_mult=0.10,
            swing_window=1,
        )
        self.assertTrue(result["opposite_trigger"])

    def test_hybrid_matrix(self):
        self.assertEqual(hybrid_state("CONTINUATION", "RETEST", False)[0], "PASS")
        self.assertEqual(hybrid_state("PULLBACK", "NO_TRIGGER", False)[0], "WAIT")
        self.assertEqual(hybrid_state("RANGE", "BREAKOUT", False)[0], "WAIT")
        self.assertEqual(hybrid_state("CONTINUATION", "RETEST", True)[0], "REJECT")
        self.assertEqual(hybrid_state("UNKNOWN", "NO_TRIGGER", False)[0], "REJECT")


if __name__ == "__main__":
    unittest.main()
