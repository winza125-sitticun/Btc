from __future__ import annotations

import importlib
from datetime import UTC, datetime, timedelta

from btc_core.market.models import Candle


def _module():
    return importlib.import_module("btc_core.analysis.triggers")


def candle(
    i: int,
    o: float,
    h: float,
    l: float,
    c: float,
    *,
    volume: float = 100.0,
) -> Candle:
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
        volume=float(volume),
        quote_volume=float(volume) * 10,
        trade_count=10,
        taker_buy_base_volume=float(volume) / 2,
        taker_buy_quote_volume=float(volume) * 5,
    )


def test_breakout_and_breakdown_require_close_beyond_buffer_not_wick():
    m = _module()
    bars = [candle(0, 9.5, 10.8, 9.0, 9.9)]

    assert m.detect_breakout(
        bars, level=10.0, role="RESISTANCE", break_buffer=0.2
    ) is None

    bars[-1] = candle(0, 9.8, 10.8, 9.5, 10.25)
    event = m.detect_breakout(
        bars, level=10.0, role="RESISTANCE", break_buffer=0.2
    )
    assert event["event"] == "BREAKOUT_CONFIRMED"
    assert event["direction"] == "BULLISH"

    bars[-1] = candle(0, 10.2, 10.5, 9.0, 9.75)
    event = m.detect_breakout(
        bars, level=10.0, role="SUPPORT", break_buffer=0.2
    )
    assert event["event"] == "BREAKDOWN_CONFIRMED"
    assert event["direction"] == "BEARISH"


def test_reclaim_requires_prior_close_on_opposite_side():
    m = _module()
    bars = [
        candle(0, 10.0, 10.2, 9.4, 9.6),
        candle(1, 9.7, 10.4, 9.6, 10.3),
    ]
    event = m.detect_reclaim(
        bars, level=10.0, direction="BULLISH", reclaim_buffer=0.2
    )
    assert event["event"] == "RECLAIM_CONFIRMED"
    assert event["direction"] == "BULLISH"

    bars[0] = candle(0, 10.1, 10.4, 9.9, 10.05)
    assert m.detect_reclaim(
        bars, level=10.0, direction="BULLISH", reclaim_buffer=0.2
    ) is None

    bearish = [
        candle(0, 10.0, 10.5, 9.9, 10.4),
        candle(1, 10.3, 10.4, 9.6, 9.7),
    ]
    event = m.detect_reclaim(
        bearish, level=10.0, direction="BEARISH", reclaim_buffer=0.2
    )
    assert event["event"] == "RECLAIM_CONFIRMED"
    assert event["direction"] == "BEARISH"


def test_liquidity_sweep_is_distinct_from_breakout():
    m = _module()
    bullish = [candle(0, 10.1, 10.3, 9.6, 10.05)]
    sweep = m.detect_liquidity_sweep(
        bullish, level=10.0, role="SUPPORT", sweep_buffer=0.2
    )
    assert sweep["event"] == "LIQUIDITY_SWEEP"
    assert sweep["direction"] == "BULLISH"
    assert m.detect_breakout(
        bullish, level=10.0, role="SUPPORT", break_buffer=0.2
    ) is None

    bearish = [candle(0, 9.9, 10.4, 9.7, 9.95)]
    sweep = m.detect_liquidity_sweep(
        bearish, level=10.0, role="RESISTANCE", sweep_buffer=0.2
    )
    assert sweep["event"] == "LIQUIDITY_SWEEP"
    assert sweep["direction"] == "BEARISH"


def test_rejection_respects_wick_body_ratio():
    m = _module()
    bullish = [candle(0, 10.05, 10.4, 9.4, 10.25)]
    event = m.detect_rejection(
        bullish,
        level=10.0,
        role="SUPPORT",
        min_wick_body_ratio=2.0,
        test_tolerance=0.05,
    )
    assert event["event"] == "REJECTION"
    assert event["direction"] == "BULLISH"

    weak_wick = [candle(0, 9.95, 10.5, 9.9, 10.4)]
    assert m.detect_rejection(
        weak_wick,
        level=10.0,
        role="SUPPORT",
        min_wick_body_ratio=2.0,
        test_tolerance=0.05,
    ) is None

    bearish = [candle(0, 9.95, 10.6, 9.6, 9.75)]
    event = m.detect_rejection(
        bearish,
        level=10.0,
        role="RESISTANCE",
        min_wick_body_ratio=2.0,
        test_tolerance=0.05,
    )
    assert event["event"] == "REJECTION"
    assert event["direction"] == "BEARISH"


def test_volume_confirmation_uses_prior_bars_and_excludes_current():
    m = _module()
    bars = [candle(i, 10, 10.5, 9.5, 10.1, volume=100) for i in range(20)]
    bars.append(candle(20, 10, 10.5, 9.5, 10.1, volume=125))

    assert m.volume_is_confirmed(bars, period=20, multiplier=1.2) is True

    bars[-1] = candle(20, 10, 10.5, 9.5, 10.1, volume=119)
    assert m.volume_is_confirmed(bars, period=20, multiplier=1.2) is False
    assert m.volume_is_confirmed(bars[:20], period=20, multiplier=1.2) is False


def test_retest_success_failure_and_window_are_causal():
    m = _module()
    bars = [
        candle(0, 9.8, 10.4, 9.7, 10.3),  # origin breakout
        candle(1, 10.3, 10.5, 9.95, 10.2),  # successful bullish retest
    ]
    event = m.evaluate_retest(
        bars,
        level=10.0,
        direction="BULLISH",
        origin_index=0,
        min_bars=1,
        max_bars=6,
        break_buffer=0.1,
        test_tolerance=0.1,
    )
    assert event["event"] == "RETEST_CONFIRMED"
    assert event["direction"] == "BULLISH"

    bars[1] = candle(1, 10.1, 10.2, 9.6, 9.85)
    event = m.evaluate_retest(
        bars,
        level=10.0,
        direction="BULLISH",
        origin_index=0,
        min_bars=1,
        max_bars=6,
        break_buffer=0.1,
        test_tolerance=0.1,
    )
    assert event["event"] == "RETEST_FAILED"
    assert event["status"] == "INVALIDATED"

    too_late = [candle(i, 10.2, 10.5, 10.1, 10.3) for i in range(8)]
    too_late[-1] = candle(7, 10.2, 10.4, 9.95, 10.2)
    assert m.evaluate_retest(
        too_late,
        level=10.0,
        direction="BULLISH",
        origin_index=0,
        min_bars=1,
        max_bars=6,
        test_tolerance=0.1,
    ) is None


def test_bearish_retest_is_symmetric():
    m = _module()
    bars = [
        candle(0, 10.2, 10.3, 9.6, 9.7),
        candle(1, 9.7, 10.05, 9.5, 9.8),
    ]
    event = m.evaluate_retest(
        bars,
        level=10.0,
        direction="BEARISH",
        origin_index=0,
        min_bars=1,
        max_bars=6,
        test_tolerance=0.1,
    )
    assert event["event"] == "RETEST_CONFIRMED"
    assert event["direction"] == "BEARISH"


def test_unified_analyzer_returns_bounded_confirmed_result_and_sweep_is_nonactionable():
    m = _module()
    baseline = [candle(i, 10, 10.2, 9.8, 10.0, volume=100) for i in range(20)]
    breakout = baseline + [candle(20, 9.9, 10.6, 9.8, 10.4, volume=130)]

    result = m.analyze_15m_trigger(
        breakout,
        level=10.0,
        role="RESISTANCE",
        break_buffer=0.2,
        volume_period=20,
        volume_multiplier=1.2,
    )
    assert result["trigger_type"] == "BREAKOUT_CONFIRMED"
    assert result["direction"] == "BULLISH"
    assert result["status"] == "CLOSED_CONFIRMED"
    assert result["volume_confirmed"] is True
    assert result["evidence"]["actionable"] is True

    sweep_bars = baseline + [candle(20, 10.1, 10.3, 9.6, 10.05, volume=130)]
    result = m.analyze_15m_trigger(
        sweep_bars,
        level=10.0,
        role="SUPPORT",
        sweep_buffer=0.2,
        volume_period=20,
    )
    assert result["trigger_type"] == "LIQUIDITY_SWEEP"
    assert result["status"] == "CLOSED_CONFIRMED"
    assert result["evidence"]["actionable"] is False


def test_unified_analyzer_fails_closed_for_invalid_input():
    m = _module()
    result = m.analyze_15m_trigger([], level=10.0, role="SUPPORT")
    assert result == {
        "trigger_type": "NONE",
        "direction": None,
        "status": "NONE",
        "level": 10.0,
        "candle_index": None,
        "candle_time": None,
        "volume_confirmed": False,
        "evidence": {},
    }
