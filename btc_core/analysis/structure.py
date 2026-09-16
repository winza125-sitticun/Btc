"""Deterministic market-structure primitives for the REZ analysis workflow.

The module consumes closed candles only, performs no I/O, and has no order
placement capability. It accepts either ``btc_core.market.models.Candle``
instances or candle-like mappings so deterministic replay fixtures stay simple.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any


CandleLike = Any
Swing = dict[str, Any]


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


def find_confirmed_swings(
    candles: Iterable[CandleLike],
    left_bars: int = 2,
    right_bars: int = 2,
) -> dict[str, list[Swing]]:
    """Return causally confirmed local swing highs/lows.

    A pivot at index ``i`` is not available until ``right_bars`` candles after
    it have closed. The confirmation timestamp is the close time of that last
    required right-side candle.
    """

    bars = list(candles) if candles is not None else []
    if left_bars < 1 or right_bars < 1:
        return {"highs": [], "lows": []}
    if len(bars) < left_bars + right_bars + 1:
        return {"highs": [], "lows": []}
    if not all(_valid_candle(candle) for candle in bars):
        return {"highs": [], "lows": []}

    highs: list[Swing] = []
    lows: list[Swing] = []
    last_pivot_index = len(bars) - right_bars - 1

    for index in range(left_bars, last_pivot_index + 1):
        pivot = bars[index]
        left = bars[index - left_bars : index]
        right = bars[index + 1 : index + right_bars + 1]
        confirmation_index = index + right_bars

        pivot_high = float(_field(pivot, "high"))
        if all(
            pivot_high > float(_field(candle, "high"))
            for candle in [*left, *right]
        ):
            highs.append(
                {
                    "kind": "HIGH",
                    "index": index,
                    "price": pivot_high,
                    "pivot_time": _field(pivot, "close_time"),
                    "confirmation_index": confirmation_index,
                    "confirmation_time": _field(
                        bars[confirmation_index], "close_time"
                    ),
                }
            )

        pivot_low = float(_field(pivot, "low"))
        if all(
            pivot_low < float(_field(candle, "low"))
            for candle in [*left, *right]
        ):
            lows.append(
                {
                    "kind": "LOW",
                    "index": index,
                    "price": pivot_low,
                    "pivot_time": _field(pivot, "close_time"),
                    "confirmation_index": confirmation_index,
                    "confirmation_time": _field(
                        bars[confirmation_index], "close_time"
                    ),
                }
            )

    return {"highs": highs, "lows": lows}


def _relation(
    current: float,
    previous: float,
    tolerance: float,
    higher: str,
    lower: str,
    equal: str,
) -> str:
    if abs(current - previous) <= tolerance:
        return equal
    return higher if current > previous else lower


def label_swing_sequence(
    swings: dict[str, list[Swing]],
    equality_tolerance: float = 0.0,
) -> dict[str, list[Swing]]:
    """Label each confirmed pivot relative to the previous same-kind pivot."""

    try:
        tolerance = float(equality_tolerance)
    except (TypeError, ValueError):
        tolerance = -1.0

    if tolerance < 0 or not isinstance(swings, dict):
        return {"highs": [], "lows": []}

    labeled_highs: list[Swing] = []
    labeled_lows: list[Swing] = []

    previous_price: float | None = None
    for swing in list(swings.get("highs") or []):
        item = dict(swing)
        try:
            price = float(item["price"])
        except (KeyError, TypeError, ValueError):
            return {"highs": [], "lows": []}
        item["label"] = (
            None
            if previous_price is None
            else _relation(price, previous_price, tolerance, "HH", "LH", "EQH")
        )
        labeled_highs.append(item)
        previous_price = price

    previous_price = None
    for swing in list(swings.get("lows") or []):
        item = dict(swing)
        try:
            price = float(item["price"])
        except (KeyError, TypeError, ValueError):
            return {"highs": [], "lows": []}
        item["label"] = (
            None
            if previous_price is None
            else _relation(price, previous_price, tolerance, "HL", "LL", "EQL")
        )
        labeled_lows.append(item)
        previous_price = price

    return {"highs": labeled_highs, "lows": labeled_lows}


def classify_structure_state(
    swings: dict[str, list[Swing]],
    equality_tolerance: float = 0.0,
) -> str:
    """Classify the latest confirmed high/low pair into a bounded state."""

    labeled = label_swing_sequence(
        swings, equality_tolerance=equality_tolerance
    )
    highs = labeled["highs"]
    lows = labeled["lows"]
    if len(highs) < 2 or len(lows) < 2:
        return "INSUFFICIENT"

    high_label = highs[-1].get("label")
    low_label = lows[-1].get("label")
    if high_label == "HH" and low_label == "HL":
        return "BULLISH"
    if high_label == "LH" and low_label == "LL":
        return "BEARISH"
    if high_label == "EQH" and low_label == "EQL":
        return "RANGE"
    return "TRANSITION"


def _latest_confirmed_swing(
    swings: Iterable[Swing],
    event_index: int,
) -> Swing | None:
    eligible: list[Swing] = []
    for swing in list(swings or []):
        if not isinstance(swing, dict):
            continue
        try:
            confirmation_index = int(swing["confirmation_index"])
            float(swing["price"])
        except (KeyError, TypeError, ValueError):
            continue
        if confirmation_index <= event_index:
            eligible.append(swing)

    if not eligible:
        return None

    return max(
        eligible,
        key=lambda item: (
            int(item["confirmation_index"]),
            int(item.get("index", -1)),
        ),
    )


def detect_structure_break(
    candles: Iterable[CandleLike],
    swings: dict[str, list[Swing]],
    prior_state: str,
    breakout_buffer: float = 0.0,
    event_index: int | None = None,
) -> dict[str, Any] | None:
    """Detect close-confirmed BOS/CHoCH against already confirmed structure."""

    bars = list(candles) if candles is not None else []
    if not bars or not isinstance(swings, dict):
        return None

    try:
        buffer_value = float(breakout_buffer)
    except (TypeError, ValueError):
        return None
    if buffer_value < 0:
        return None

    if event_index is None:
        index = len(bars) - 1
    else:
        try:
            index = int(event_index)
        except (TypeError, ValueError):
            return None

    if index < 0 or index >= len(bars) or not _valid_candle(bars[index]):
        return None

    state = str(prior_state).upper()
    if state not in {"BULLISH", "BEARISH"}:
        return None

    latest_high = _latest_confirmed_swing(swings.get("highs") or [], index)
    latest_low = _latest_confirmed_swing(swings.get("lows") or [], index)
    close = float(_field(bars[index], "close"))

    def payload(event: str, direction: str, level: float) -> dict[str, Any]:
        return {
            "event": event,
            "direction": direction,
            "level": float(level),
            "close": close,
            "candle_index": index,
            "candle_time": _field(bars[index], "close_time"),
            "breakout_buffer": buffer_value,
        }

    if state == "BULLISH":
        if latest_high is not None:
            high_level = float(latest_high["price"])
            if close > high_level + buffer_value:
                return payload("BOS", "BULLISH", high_level)
        if latest_low is not None:
            low_level = float(latest_low["price"])
            if close < low_level - buffer_value:
                return payload("CHOCH", "BEARISH", low_level)
        return None

    if latest_low is not None:
        low_level = float(latest_low["price"])
        if close < low_level - buffer_value:
            return payload("BOS", "BEARISH", low_level)
    if latest_high is not None:
        high_level = float(latest_high["price"])
        if close > high_level + buffer_value:
            return payload("CHOCH", "BULLISH", high_level)
    return None


def analyze_market_structure(
    candles: Iterable[CandleLike],
    left_bars: int = 2,
    right_bars: int = 2,
    equality_tolerance: float = 0.0,
    breakout_buffer: float = 0.0,
) -> dict[str, Any]:
    """Analyze latest closed-candle structure without lookahead."""

    bars = list(candles) if candles is not None else []
    empty = {
        "state": "INSUFFICIENT",
        "prior_state": "INSUFFICIENT",
        "swings": {"highs": [], "lows": []},
        "labeled_swings": {"highs": [], "lows": []},
        "event": None,
    }
    if not bars or not all(_valid_candle(candle) for candle in bars):
        return empty

    swings = find_confirmed_swings(
        bars, left_bars=left_bars, right_bars=right_bars
    )
    labeled = label_swing_sequence(
        swings, equality_tolerance=equality_tolerance
    )
    state = classify_structure_state(
        swings, equality_tolerance=equality_tolerance
    )

    prior_bars = bars[:-1]
    prior_swings = find_confirmed_swings(
        prior_bars, left_bars=left_bars, right_bars=right_bars
    )
    prior_state = classify_structure_state(
        prior_swings, equality_tolerance=equality_tolerance
    )

    event = detect_structure_break(
        bars,
        swings,
        prior_state=prior_state,
        breakout_buffer=breakout_buffer,
        event_index=len(bars) - 1,
    )

    return {
        "state": state,
        "prior_state": prior_state,
        "swings": swings,
        "labeled_swings": labeled,
        "event": event,
    }
