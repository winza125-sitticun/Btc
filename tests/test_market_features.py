from __future__ import annotations

from datetime import datetime, timedelta, timezone

from btc_core.ai.models import Direction
from btc_core.market.features import build_market_feature_result
from btc_core.market.models import Candle, MarketSnapshot


def _snapshot(*, rising: bool, buy_ratio: float, funding: float, oi_change: float, spread_percent: float = 0.02) -> MarketSnapshot:
    start = datetime(2026, 9, 8, tzinfo=timezone.utc)
    candles: list[Candle] = []
    for index in range(30):
        base = 100 + index if rising else 130 - index
        close = float(base + (0.5 if rising else -0.5))
        quote_volume = 1000.0 if index < 29 else 1800.0
        candles.append(
            Candle(
                symbol="BTCUSDT",
                timeframe="15m",
                open_time=start + timedelta(minutes=15 * index),
                close_time=start + timedelta(minutes=15 * (index + 1)) - timedelta(milliseconds=1),
                open=float(base),
                high=float(base + 1),
                low=float(base - 1),
                close=close,
                volume=10.0,
                quote_volume=quote_volume,
                trade_count=20,
                taker_buy_base_volume=10.0 * buy_ratio,
                taker_buy_quote_volume=quote_volume * buy_ratio,
            )
        )

    return MarketSnapshot(
        symbol="BTCUSDT",
        timeframe="15m",
        candles=candles,
        mark_price=candles[-1].close,
        index_price=candles[-1].close,
        funding_rate=funding,
        open_interest=1100.0,
        open_interest_value=120000.0,
        open_interest_change_percent=oi_change,
        long_short_ratio=1.1 if rising else 0.9,
        best_bid=candles[-1].close - 0.01,
        best_ask=candles[-1].close + 0.01,
        spread_percent=spread_percent,
        observed_at=candles[-1].close_time,
    )


def test_rising_market_with_buy_flow_and_rising_oi_is_long():
    result = build_market_feature_result(_snapshot(rising=True, buy_ratio=0.72, funding=0.0001, oi_change=6.0))

    assert result.direction is Direction.LONG
    assert result.opportunity_score > 60
    assert result.inputs.technical > 50
    assert result.inputs.order_flow > 50


def test_falling_market_with_sell_flow_and_rising_oi_is_short():
    result = build_market_feature_result(_snapshot(rising=False, buy_ratio=0.28, funding=-0.0001, oi_change=5.0))

    assert result.direction is Direction.SHORT
    assert result.opportunity_score > 60
    assert result.inputs.momentum > 50


def test_flat_weak_market_returns_wait():
    snapshot = _snapshot(rising=True, buy_ratio=0.5, funding=0.0015, oi_change=0.1, spread_percent=0.3)
    flat_price = snapshot.candles[-1].close
    flat_candles = [candle.model_copy(update={"open": flat_price, "high": flat_price, "low": flat_price, "close": flat_price, "quote_volume": 500.0, "taker_buy_quote_volume": 250.0}) for candle in snapshot.candles]
    snapshot = snapshot.model_copy(update={"candles": flat_candles})

    result = build_market_feature_result(snapshot)

    assert result.direction is Direction.WAIT
    assert result.opportunity_score < 60


def test_phase_5a_keeps_news_macro_and_rr_neutral():
    result = build_market_feature_result(
        _snapshot(rising=True, buy_ratio=0.72, funding=0.0001, oi_change=6.0)
    )

    assert result.inputs.news == 50.0
    assert result.inputs.macro == 50.0
    assert result.inputs.risk_reward == 50.0
