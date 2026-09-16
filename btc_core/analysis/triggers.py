"""Deterministic 15m trigger primitives for the REZ analysis workflow.

All functions are analysis-only, operate on already-closed candles, perform no
I/O, and expose no order-placement capability. The module accepts either
``btc_core.market.models.Candle`` instances or candle-like mappings to keep
replay fixtures deterministic and lightweight.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any


CandleLike = Any


def _field(candle: CandleLike, name: str) -> Any:
    if isinstance(candle, Mapping):
        return candle.get(name)
    return getattr(candle, name, None)


def _valid_candle(candle: CandleLike) -> bool:
    if candle is None:
        return False

    required = ("open_time", "open", "high", "low", "close", "close_time")
    if any(_field(candle, key) is None for key in required):
        return False

    try:
        open_ = float(_field(candle, "open"))
        high = float(_field(candle, "high"))
        low = float(_field(candle, "low"))
        close = float(_field(candle, "close"))
    except (TypeError, ValueError):
        return False

    return high >= max(open_, close, low) and low <= min(open_, close, high)


def _as_nonnegative(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _resolve_index(bars: list[CandleLike], event_index: int | None) -> int | None:
    if not bars:
        return None
    if event_index is None:
        return len(bars) - 1
    try:
        index = int(event_index)
    except (TypeError, ValueError):
        return None
    return index if 0 <= index < len(bars) else None


def _event_payload(
    bars: list[CandleLike],
    *,
    index: int,
    event: str,
    direction: str,
    level: float,
    status: str = "CLOSED_CONFIRMED",
) -> dict[str, Any]:
    return {
        "event": event,
        "direction": direction,
        "status": status,
        "level": float(level),
        "candle_index": index,
        "candle_time": _field(bars[index], "close_time"),
    }


def detect_breakout(
    candles: Iterable[CandleLike],
    *,
    level: float,
    role: str,
    break_buffer: float = 0.0,
    event_index: int | None = None,
) -> dict[str, Any] | None:
    """Detect a close-confirmed breakout or breakdown of a structural level."""

    bars = list(candles) if candles is not None else []
    index = _resolve_index(bars, event_index)
    buffer_value = _as_nonnegative(break_buffer)
    try:
        level_value = float(level)
    except (TypeError, ValueError):
        return None

    if index is None or buffer_value is None or not _valid_candle(bars[index]):
        return None

    role_value = str(role).upper()
    close = float(_field(bars[index], "close"))

    if role_value == "RESISTANCE" and close > level_value + buffer_value:
        return _event_payload(
            bars,
            index=index,
            event="BREAKOUT_CONFIRMED",
            direction="BULLISH",
            level=level_value,
        )
    if role_value == "SUPPORT" and close < level_value - buffer_value:
        return _event_payload(
            bars,
            index=index,
            event="BREAKDOWN_CONFIRMED",
            direction="BEARISH",
            level=level_value,
        )
    return None


def detect_reclaim(
    candles: Iterable[CandleLike],
    *,
    level: float,
    direction: str,
    reclaim_buffer: float = 0.0,
    event_index: int | None = None,
) -> dict[str, Any] | None:
    """Detect a close-confirmed reclaim after a prior opposite-side close."""

    bars = list(candles) if candles is not None else []
    index = _resolve_index(bars, event_index)
    buffer_value = _as_nonnegative(reclaim_buffer)
    try:
        level_value = float(level)
    except (TypeError, ValueError):
        return None

    if (
        index is None
        or index < 1
        or buffer_value is None
        or not _valid_candle(bars[index - 1])
        or not _valid_candle(bars[index])
    ):
        return None

    prior_close = float(_field(bars[index - 1], "close"))
    close = float(_field(bars[index], "close"))
    direction_value = str(direction).upper()

    if (
        direction_value == "BULLISH"
        and prior_close < level_value
        and close > level_value + buffer_value
    ):
        return _event_payload(
            bars,
            index=index,
            event="RECLAIM_CONFIRMED",
            direction="BULLISH",
            level=level_value,
        )
    if (
        direction_value == "BEARISH"
        and prior_close > level_value
        and close < level_value - buffer_value
    ):
        return _event_payload(
            bars,
            index=index,
            event="RECLAIM_CONFIRMED",
            direction="BEARISH",
            level=level_value,
        )
    return None


def detect_liquidity_sweep(
    candles: Iterable[CandleLike],
    *,
    level: float,
    role: str,
    sweep_buffer: float = 0.0,
    event_index: int | None = None,
) -> dict[str, Any] | None:
    """Detect wick penetration that closes back on the protected side."""

    bars = list(candles) if candles is not None else []
    index = _resolve_index(bars, event_index)
    buffer_value = _as_nonnegative(sweep_buffer)
    try:
        level_value = float(level)
    except (TypeError, ValueError):
        return None

    if index is None or buffer_value is None or not _valid_candle(bars[index]):
        return None

    candle = bars[index]
    high = float(_field(candle, "high"))
    low = float(_field(candle, "low"))
    close = float(_field(candle, "close"))
    role_value = str(role).upper()

    if role_value == "SUPPORT" and low < level_value - buffer_value and close >= level_value:
        return _event_payload(
            bars,
            index=index,
            event="LIQUIDITY_SWEEP",
            direction="BULLISH",
            level=level_value,
        )
    if role_value == "RESISTANCE" and high > level_value + buffer_value and close <= level_value:
        return _event_payload(
            bars,
            index=index,
            event="LIQUIDITY_SWEEP",
            direction="BEARISH",
            level=level_value,
        )
    return None


def detect_rejection(
    candles: Iterable[CandleLike],
    *,
    level: float,
    role: str,
    min_wick_body_ratio: float = 2.0,
    test_tolerance: float = 0.0,
    event_index: int | None = None,
) -> dict[str, Any] | None:
    """Detect a level rejection using a deterministic wick/body threshold."""

    bars = list(candles) if candles is not None else []
    index = _resolve_index(bars, event_index)
    ratio = _as_nonnegative(min_wick_body_ratio)
    tolerance = _as_nonnegative(test_tolerance)
    try:
        level_value = float(level)
    except (TypeError, ValueError):
        return None

    if (
        index is None
        or ratio is None
        or tolerance is None
        or not _valid_candle(bars[index])
    ):
        return None

    candle = bars[index]
    open_ = float(_field(candle, "open"))
    high = float(_field(candle, "high"))
    low = float(_field(candle, "low"))
    close = float(_field(candle, "close"))
    body = max(abs(close - open_), max((high - low) * 1e-9, 1e-12))
    lower_wick = max(0.0, min(open_, close) - low)
    upper_wick = max(0.0, high - max(open_, close))
    role_value = str(role).upper()

    if (
        role_value == "SUPPORT"
        and low <= level_value + tolerance
        and close > level_value
        and lower_wick / body >= ratio
    ):
        return _event_payload(
            bars,
            index=index,
            event="REJECTION",
            direction="BULLISH",
            level=level_value,
        )
    if (
        role_value == "RESISTANCE"
        and high >= level_value - tolerance
        and close < level_value
        and upper_wick / body >= ratio
    ):
        return _event_payload(
            bars,
            index=index,
            event="REJECTION",
            direction="BEARISH",
            level=level_value,
        )
    return None


def volume_is_confirmed(
    candles: Iterable[CandleLike],
    *,
    period: int = 20,
    multiplier: float = 1.2,
    event_index: int | None = None,
) -> bool:
    """Return whether current volume exceeds a prior-bars-only SMA threshold."""

    bars = list(candles) if candles is not None else []
    index = _resolve_index(bars, event_index)
    try:
        period_value = int(period)
        multiplier_value = float(multiplier)
    except (TypeError, ValueError):
        return False

    if (
        index is None
        or period_value <= 0
        or multiplier_value <= 0
        or index < period_value
        or not _valid_candle(bars[index])
    ):
        return False

    baseline = bars[index - period_value : index]
    if len(baseline) != period_value or not all(_valid_candle(bar) for bar in baseline):
        return False

    try:
        baseline_volumes = [float(_field(bar, "volume")) for bar in baseline]
        current_volume = float(_field(bars[index], "volume"))
    except (TypeError, ValueError):
        return False

    if current_volume < 0 or any(volume < 0 for volume in baseline_volumes):
        return False

    average = sum(baseline_volumes) / period_value
    if average <= 0:
        return False
    return current_volume >= average * multiplier_value


def evaluate_retest(
    candles: Iterable[CandleLike],
    *,
    level: float,
    direction: str,
    origin_index: int,
    min_bars: int = 1,
    max_bars: int = 6,
    break_buffer: float = 0.0,
    test_tolerance: float = 0.0,
    event_index: int | None = None,
) -> dict[str, Any] | None:
    """Evaluate a causal retest only after its originating confirmed event."""

    bars = list(candles) if candles is not None else []
    index = _resolve_index(bars, event_index)
    break_value = _as_nonnegative(break_buffer)
    tolerance = _as_nonnegative(test_tolerance)
    try:
        level_value = float(level)
        origin = int(origin_index)
        min_window = int(min_bars)
        max_window = int(max_bars)
    except (TypeError, ValueError):
        return None

    if (
        index is None
        or break_value is None
        or tolerance is None
        or origin < 0
        or origin >= len(bars)
        or min_window < 1
        or max_window < min_window
        or not _valid_candle(bars[index])
    ):
        return None

    bars_since_origin = index - origin
    if bars_since_origin < min_window or bars_since_origin > max_window:
        return None

    candle = bars[index]
    high = float(_field(candle, "high"))
    low = float(_field(candle, "low"))
    close = float(_field(candle, "close"))
    direction_value = str(direction).upper()

    if direction_value == "BULLISH":
        if close < level_value - break_value:
            return _event_payload(
                bars,
                index=index,
                event="RETEST_FAILED",
                direction="BULLISH",
                level=level_value,
                status="INVALIDATED",
            )
        if low <= level_value + tolerance and close >= level_value:
            return _event_payload(
                bars,
                index=index,
                event="RETEST_CONFIRMED",
                direction="BULLISH",
                level=level_value,
            )
        return None

    if direction_value == "BEARISH":
        if close > level_value + break_value:
            return _event_payload(
                bars,
                index=index,
                event="RETEST_FAILED",
                direction="BEARISH",
                level=level_value,
                status="INVALIDATED",
            )
        if high >= level_value - tolerance and close <= level_value:
            return _event_payload(
                bars,
                index=index,
                event="RETEST_CONFIRMED",
                direction="BEARISH",
                level=level_value,
            )
    return None


def _none_result(level: Any) -> dict[str, Any]:
    try:
        level_value = float(level)
    except (TypeError, ValueError):
        level_value = level
    return {
        "trigger_type": "NONE",
        "direction": None,
        "status": "NONE",
        "level": level_value,
        "candle_index": None,
        "candle_time": None,
        "volume_confirmed": False,
        "evidence": {},
    }


def analyze_15m_trigger(
    candles: Iterable[CandleLike],
    *,
    level: float,
    role: str,
    break_buffer: float = 0.0,
    reclaim_buffer: float = 0.0,
    sweep_buffer: float = 0.0,
    rejection_wick_body_ratio: float = 2.0,
    test_tolerance: float = 0.0,
    volume_period: int = 20,
    volume_multiplier: float = 1.2,
    origin_event: Mapping[str, Any] | None = None,
    retest_min_bars: int = 1,
    retest_max_bars: int = 6,
) -> dict[str, Any]:
    """Return one bounded deterministic trigger result for the latest candle.

    Priority is causal retest, close-confirmed breakout/breakdown, reclaim,
    liquidity sweep, then rejection. Sweeps/rejections are evidence-only and
    therefore explicitly marked non-actionable.
    """

    bars = list(candles) if candles is not None else []
    try:
        level_value = float(level)
    except (TypeError, ValueError):
        return _none_result(level)

    role_value = str(role).upper()
    if not bars or role_value not in {"SUPPORT", "RESISTANCE"}:
        return _none_result(level_value)
    if not all(_valid_candle(bar) for bar in bars):
        return _none_result(level_value)

    index = len(bars) - 1
    volume_confirmed = volume_is_confirmed(
        bars,
        period=volume_period,
        multiplier=volume_multiplier,
        event_index=index,
    )

    event: dict[str, Any] | None = None
    if origin_event is not None:
        try:
            origin_index = int(origin_event["candle_index"])
            origin_direction = str(origin_event["direction"]).upper()
        except (KeyError, TypeError, ValueError):
            origin_index = -1
            origin_direction = ""
        if origin_direction in {"BULLISH", "BEARISH"}:
            event = evaluate_retest(
                bars,
                level=level_value,
                direction=origin_direction,
                origin_index=origin_index,
                min_bars=retest_min_bars,
                max_bars=retest_max_bars,
                break_buffer=break_buffer,
                test_tolerance=test_tolerance,
                event_index=index,
            )

    if event is None:
        event = detect_breakout(
            bars,
            level=level_value,
            role=role_value,
            break_buffer=break_buffer,
            event_index=index,
        )

    if event is None:
        reclaim_direction = "BULLISH" if role_value == "SUPPORT" else "BEARISH"
        event = detect_reclaim(
            bars,
            level=level_value,
            direction=reclaim_direction,
            reclaim_buffer=reclaim_buffer,
            event_index=index,
        )

    if event is None:
        event = detect_liquidity_sweep(
            bars,
            level=level_value,
            role=role_value,
            sweep_buffer=sweep_buffer,
            event_index=index,
        )

    if event is None:
        event = detect_rejection(
            bars,
            level=level_value,
            role=role_value,
            min_wick_body_ratio=rejection_wick_body_ratio,
            test_tolerance=test_tolerance,
            event_index=index,
        )

    if event is None:
        return _none_result(level_value)

    trigger_type = str(event["event"])
    actionable = trigger_type in {
        "BREAKOUT_CONFIRMED",
        "BREAKDOWN_CONFIRMED",
        "RECLAIM_CONFIRMED",
        "RETEST_CONFIRMED",
    }

    return {
        "trigger_type": trigger_type,
        "direction": event.get("direction"),
        "status": event.get("status", "CLOSED_CONFIRMED"),
        "level": level_value,
        "candle_index": event.get("candle_index"),
        "candle_time": event.get("candle_time"),
        "volume_confirmed": volume_confirmed,
        "evidence": {
            "actionable": actionable,
            "event": trigger_type,
        },
    }
