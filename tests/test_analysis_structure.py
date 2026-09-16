from __future__ import annotations

import importlib
from datetime import UTC, datetime, timedelta

from btc_core.market.models import Candle


def _module():
    return importlib.import_module("btc_core.analysis.structure")


def candle(i: int, o: float, h: float, l: float, c: float) -> Candle:
    start = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(minutes=15 * i)
    return Candle(
        symbol="REZUSDT",
        timeframe="15m",
        open_time=start,
        close_time=start + timedelta(minutes=15) - timedelta(milliseconds=1),
        open=float(o),
        high=float(h),
        low=float(l),
        close=float(c),
        volume=100.0,
        quote_volume=1_000.0,
        trade_count=10,
        taker_buy_base_volume=50.0,
        taker_buy_quote_volume=500.0,
    )


def test_pivot_is_not_confirmed_until_required_right_bars_exist():
    m = _module()
    bars = [
        candle(0, 8, 9, 7, 8),
        candle(1, 9, 10, 8, 9),
        candle(2, 10, 15, 9, 12),
        candle(3, 12, 13, 10, 11),
    ]

    swings = m.find_confirmed_swings(bars, left_bars=2, right_bars=2)
    assert swings["highs"] == []

    bars.append(candle(4, 11, 12, 9, 10))
    swings = m.find_confirmed_swings(bars, left_bars=2, right_bars=2)

    assert len(swings["highs"]) == 1
    pivot = swings["highs"][0]
    assert pivot["index"] == 2
    assert pivot["price"] == 15.0
    assert pivot["confirmation_index"] == 4
    assert pivot["confirmation_time"] == bars[4].close_time


def test_labels_higher_lower_and_equal_structure_points():
    m = _module()
    swings = {
        "highs": [
            {"index": 2, "price": 10.0},
            {"index": 6, "price": 12.0},
            {"index": 10, "price": 12.04},
        ],
        "lows": [
            {"index": 4, "price": 5.0},
            {"index": 8, "price": 6.0},
            {"index": 12, "price": 5.97},
        ],
    }

    labeled = m.label_swing_sequence(swings, equality_tolerance=0.05)

    assert [item["label"] for item in labeled["highs"]] == [None, "HH", "EQH"]
    assert [item["label"] for item in labeled["lows"]] == [None, "HL", "EQL"]


def test_classifies_bullish_bearish_range_transition_and_insufficient():
    m = _module()
    bullish = {
        "highs": [{"index": 1, "price": 10.0}, {"index": 5, "price": 12.0}],
        "lows": [{"index": 3, "price": 5.0}, {"index": 7, "price": 6.0}],
    }
    bearish = {
        "highs": [{"index": 1, "price": 12.0}, {"index": 5, "price": 10.0}],
        "lows": [{"index": 3, "price": 6.0}, {"index": 7, "price": 5.0}],
    }
    ranging = {
        "highs": [{"index": 1, "price": 10.0}, {"index": 5, "price": 10.02}],
        "lows": [{"index": 3, "price": 5.0}, {"index": 7, "price": 4.99}],
    }
    transition = {
        "highs": [{"index": 1, "price": 10.0}, {"index": 5, "price": 12.0}],
        "lows": [{"index": 3, "price": 6.0}, {"index": 7, "price": 5.0}],
    }

    assert m.classify_structure_state(bullish) == "BULLISH"
    assert m.classify_structure_state(bearish) == "BEARISH"
    assert m.classify_structure_state(ranging, equality_tolerance=0.05) == "RANGE"
    assert m.classify_structure_state(transition) == "TRANSITION"
    assert m.classify_structure_state({"highs": [], "lows": []}) == "INSUFFICIENT"


def confirmed_swings(high: float = 12.0, low: float = 6.0):
    return {
        "highs": [{"index": 5, "price": high, "confirmation_index": 7}],
        "lows": [{"index": 6, "price": low, "confirmation_index": 8}],
    }


def test_bos_and_choch_require_close_confirmation_not_wick():
    m = _module()
    bars = [candle(i, 8, 11, 7, 9) for i in range(9)]
    bars.append(candle(9, 11, 13.0, 10, 12.5))

    event = m.detect_structure_break(
        bars, confirmed_swings(), prior_state="BULLISH", breakout_buffer=0.2
    )
    assert event["event"] == "BOS"
    assert event["direction"] == "BULLISH"
    assert event["level"] == 12.0

    bars[-1] = candle(9, 11, 13.0, 10, 11.9)
    assert m.detect_structure_break(
        bars, confirmed_swings(), prior_state="BULLISH", breakout_buffer=0.2
    ) is None

    bars[-1] = candle(9, 7, 8, 5.4, 5.5)
    event = m.detect_structure_break(
        bars, confirmed_swings(), prior_state="BULLISH", breakout_buffer=0.2
    )
    assert event["event"] == "CHOCH"
    assert event["direction"] == "BEARISH"


def test_future_unconfirmed_pivot_is_not_used_for_break_detection():
    m = _module()
    bars = [candle(i, 8, 11, 7, 9) for i in range(10)]
    bars[-1] = candle(9, 11, 14, 10, 13.0)
    swings = {
        "highs": [{"index": 8, "price": 12.0, "confirmation_index": 10}],
        "lows": [{"index": 6, "price": 6.0, "confirmation_index": 8}],
    }

    assert m.detect_structure_break(
        bars, swings, prior_state="BULLISH", breakout_buffer=0.0, event_index=9
    ) is None


def test_analysis_fails_closed_for_insufficient_or_malformed_data():
    m = _module()
    insufficient = m.analyze_market_structure([candle(0, 8, 9, 7, 8)])
    assert insufficient["state"] == "INSUFFICIENT"
    assert insufficient["prior_state"] == "INSUFFICIENT"
    assert insufficient["event"] is None

    malformed = [{
        "open_time": 0,
        "open": 10,
        "high": 9,
        "low": 8,
        "close": 10,
        "close_time": 1,
    }]
    result = m.analyze_market_structure(malformed)
    assert result["state"] == "INSUFFICIENT"
    assert result["event"] is None


def test_analysis_emits_bullish_bos_from_prior_bullish_structure():
    m = _module()
    bars = [
        candle(0, 9.0, 10.0, 8.0, 9.0),
        candle(1, 10.0, 12.0, 9.0, 11.0),
        candle(2, 9.0, 11.0, 7.0, 8.0),
        candle(3, 11.0, 14.0, 8.0, 13.0),
        candle(4, 9.0, 13.0, 7.5, 10.0),
        candle(5, 10.0, 13.0, 10.0, 12.0),
        candle(6, 13.0, 15.5, 11.0, 15.0),
    ]

    result = m.analyze_market_structure(
        bars, left_bars=1, right_bars=1, breakout_buffer=0.2
    )

    assert result["prior_state"] == "BULLISH"
    assert result["event"]["event"] == "BOS"
    assert result["event"]["direction"] == "BULLISH"
    assert result["event"]["level"] == 14.0
