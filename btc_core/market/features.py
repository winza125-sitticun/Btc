from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from btc_core.ai.models import Direction
from btc_core.market.models import MarketSnapshot
from btc_core.scanner.scoring import OpportunityInputs, calculate_opportunity_score


def _clamp(value: float, minimum: float = 0.0, maximum: float = 100.0) -> float:
    return max(minimum, min(maximum, value))


def _signal_clamp(value: float) -> float:
    return max(-1.0, min(1.0, value))


def _ema(values: list[float], period: int) -> float:
    if not values:
        raise ValueError("EMA requires values")
    multiplier = 2.0 / (period + 1.0)
    result = values[0]
    for value in values[1:]:
        result = ((value - result) * multiplier) + result
    return result


class MarketFeatureResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    direction: Direction
    opportunity_score: float = Field(ge=0, le=100)
    directional_signal: float = Field(ge=-1, le=1)
    inputs: OpportunityInputs
    taker_buy_ratio: float = Field(ge=0, le=1)
    momentum_percent: float
    trend_percent: float


def build_market_feature_result(snapshot: MarketSnapshot) -> MarketFeatureResult:
    candles = snapshot.candles
    if len(candles) < 20:
        raise ValueError("at least 20 candles are required")

    closes = [item.close for item in candles]
    fast_ema = _ema(closes[-12:], 5)
    slow_ema = _ema(closes[-20:], 12)
    trend_percent = 0.0 if slow_ema == 0 else ((fast_ema / slow_ema) - 1.0) * 100.0

    reference_close = closes[-6]
    momentum_percent = 0.0 if reference_close == 0 else ((closes[-1] / reference_close) - 1.0) * 100.0

    recent = candles[-5:]
    recent_quote_volume = sum(item.quote_volume for item in recent)
    recent_taker_buy_quote = sum(item.taker_buy_quote_volume for item in recent)
    taker_buy_ratio = 0.5 if recent_quote_volume <= 0 else recent_taker_buy_quote / recent_quote_volume
    taker_buy_ratio = max(0.0, min(1.0, taker_buy_ratio))

    prior_volume = [item.quote_volume for item in candles[-21:-1]]
    average_prior_volume = sum(prior_volume) / len(prior_volume) if prior_volume else candles[-1].quote_volume
    volume_ratio = 1.0 if average_prior_volume <= 0 else candles[-1].quote_volume / average_prior_volume

    trend_signal = _signal_clamp(trend_percent / 0.5)
    momentum_signal = _signal_clamp(momentum_percent / 2.0)
    flow_signal = _signal_clamp((taker_buy_ratio - 0.5) / 0.2)
    oi_strength = max(0.0, min(1.0, snapshot.open_interest_change_percent / 5.0))
    oi_signal = oi_strength * (1.0 if momentum_signal > 0 else -1.0 if momentum_signal < 0 else 0.0)
    funding_signal = -_signal_clamp(snapshot.funding_rate / 0.001)

    directional_signal = (
        trend_signal * 0.30
        + momentum_signal * 0.25
        + flow_signal * 0.25
        + oi_signal * 0.15
        + funding_signal * 0.05
    )
    directional_signal = _signal_clamp(directional_signal)

    if directional_signal >= 0.20:
        direction = Direction.LONG
    elif directional_signal <= -0.20:
        direction = Direction.SHORT
    else:
        direction = Direction.WAIT

    technical_score = _clamp(40.0 + abs(trend_signal) * 60.0)
    momentum_score = _clamp(40.0 + abs(momentum_signal) * 60.0)
    volume_score = _clamp(30.0 + volume_ratio * 30.0)
    order_flow_score = _clamp(40.0 + abs(flow_signal) * 60.0)
    oi_score = _clamp(40.0 + min(abs(snapshot.open_interest_change_percent) / 5.0, 1.0) * 60.0)
    funding_score = _clamp(100.0 - min(abs(snapshot.funding_rate) / 0.001, 1.0) * 80.0)
    liquidity_score = _clamp(100.0 - (snapshot.spread_percent / 0.20) * 100.0)

    inputs = OpportunityInputs(
        technical=technical_score,
        momentum=momentum_score,
        volume=volume_score,
        order_flow=order_flow_score,
        open_interest=oi_score,
        funding=funding_score,
        liquidity=liquidity_score,
        news=50.0,
        macro=50.0,
        risk_reward=50.0,
    )
    opportunity_score = calculate_opportunity_score(inputs)

    return MarketFeatureResult(
        direction=direction,
        opportunity_score=opportunity_score,
        directional_signal=round(directional_signal, 6),
        inputs=inputs,
        taker_buy_ratio=round(taker_buy_ratio, 6),
        momentum_percent=round(momentum_percent, 6),
        trend_percent=round(trend_percent, 6),
    )
