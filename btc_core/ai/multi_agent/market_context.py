from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from btc_core.ai.multi_agent.models import FrozenSnapshotEnvelope, VortexInputs

_QUANT = Decimal("0.000001")
_TIMEFRAME_WEIGHTS = {"4h": 0.50, "1h": 0.30, "15m": 0.20}


def _q(value: float) -> float:
    return float(Decimal(str(value)).quantize(_QUANT, rounding=ROUND_HALF_UP))


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def derive_market_context(snapshot_envelope: FrozenSnapshotEnvelope) -> VortexInputs:
    technical = snapshot_envelope.snapshot.technical_by_timeframe
    missing = [timeframe for timeframe in _TIMEFRAME_WEIGHTS if timeframe not in technical]
    if missing:
        raise ValueError(f"missing technical timeframe(s): {', '.join(missing)}")

    trend_strength = 0.0
    volatility = 0.0
    momentum = 0.0
    for timeframe, weight in _TIMEFRAME_WEIGHTS.items():
        item = technical[timeframe]
        trend_strength += weight * abs(item.trend_percent / 0.5)
        range_percent = ((item.recent_high - item.recent_low) / item.close) * 100.0
        volatility += weight * (range_percent / 5.0)
        momentum += weight * (item.momentum_percent / 2.0)

    ratio = snapshot_envelope.snapshot.long_short_ratio
    order_flow_imbalance = 2.0 * (ratio - 1.0) / (ratio + 1.0)
    liquidity = 1.0 - snapshot_envelope.snapshot.spread_percent / 0.20

    return VortexInputs(
        trend_strength=_q(_clamp(trend_strength, 0.0, 1.0)),
        volatility=_q(_clamp(volatility, 0.0, 1.0)),
        momentum=_q(_clamp(momentum, -1.0, 1.0)),
        order_flow_imbalance=_q(_clamp(order_flow_imbalance, -1.0, 1.0)),
        liquidity=_q(_clamp(liquidity, 0.0, 1.0)),
        snapshot_ref=snapshot_envelope.snapshot_ref,
        observed_at=snapshot_envelope.observed_at,
        mapping_version="vortex-input-v1",
    )
