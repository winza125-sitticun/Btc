from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


PASS_MATRIX = {
    "CONTINUATION": {"BREAKOUT", "RETEST", "REJECTION"},
    "PULLBACK": {"RETEST", "REJECTION", "RECLAIM"},
    "REVERSAL": {"RECLAIM", "BREAKOUT"},
}


@dataclass(frozen=True)
class RezAnalysisResult:
    analysis_version: str
    state: str
    structure_1h: str
    trigger_15m: str
    supporting_triggers: tuple[str, ...]
    reason: str
    protected_swing_timestamp: Optional[int]
    protected_swing_price: Optional[float]
    trigger_level_kind: Optional[str]
    trigger_level_price: Optional[float]
    closed_1h_at_ms: Optional[int]
    closed_15m_at_ms: Optional[int]


def _valid_closed_candle(candle: dict) -> bool:
    try:
        open_ = float(candle["open"])
        high = float(candle["high"])
        low = float(candle["low"])
        close = float(candle["close"])
        open_time = int(candle["open_time"])
        close_time = int(candle["close_time"])
    except (KeyError, TypeError, ValueError):
        return False
    return open_time < close_time and high >= max(open_, close) and low <= min(open_, close)


def calculate_atr(candles: list[dict], period: int = 14) -> Optional[float]:
    if period <= 0 or len(candles) < period + 1:
        return None
    window = candles[-(period + 1):]
    if not all(_valid_closed_candle(row) for row in window):
        return None
    values: list[float] = []
    for index in range(1, len(window)):
        current = window[index]
        previous = window[index - 1]
        high = float(current["high"])
        low = float(current["low"])
        previous_close = float(previous["close"])
        values.append(max(high - low, abs(high - previous_close), abs(low - previous_close)))
    return sum(values) / period if values else None


def find_confirmed_swings(candles: list[dict], window: int = 2) -> dict[str, list[dict]]:
    if window < 1 or len(candles) < window * 2 + 1:
        return {"highs": [], "lows": []}
    if not all(_valid_closed_candle(row) for row in candles):
        return {"highs": [], "lows": []}
    highs: list[dict] = []
    lows: list[dict] = []
    for index in range(window, len(candles) - window):
        candle = candles[index]
        high = float(candle["high"])
        low = float(candle["low"])
        neighbors = candles[index - window:index] + candles[index + 1:index + window + 1]
        if all(high > float(row["high"]) for row in neighbors):
            highs.append({"index": index, "price": high, "timestamp": int(candle["close_time"])})
        if all(low < float(row["low"]) for row in neighbors):
            lows.append({"index": index, "price": low, "timestamp": int(candle["close_time"])})
    return {"highs": highs, "lows": lows}


def _first_break_index(side: str, candles: list[dict], swing: dict, buffer_dist: float, swing_window: int) -> Optional[int]:
    start = int(swing["index"]) + swing_window + 1
    level = float(swing["price"])
    for index in range(start, len(candles)):
        close = float(candles[index]["close"])
        if side == "LONG" and close > level + buffer_dist:
            return index
        if side == "SHORT" and close < level - buffer_dist:
            return index
    return None


def _protected_swing(side: str, opposite_swings: list[dict], same_swing: dict, break_index: int) -> Optional[dict]:
    between = [
        row for row in opposite_swings
        if int(same_swing["index"]) < int(row["index"]) < int(break_index)
    ]
    if between:
        return between[-1]
    before = [row for row in opposite_swings if int(row["index"]) < int(break_index)]
    return before[-1] if before else None


def _invalidation_index(side: str, candles: list[dict], protected: Optional[dict], break_index: int, buffer_dist: float) -> Optional[int]:
    if protected is None:
        return None
    level = float(protected["price"])
    for index in range(break_index + 1, len(candles)):
        close = float(candles[index]["close"])
        if side == "LONG" and close < level - buffer_dist:
            return index
        if side == "SHORT" and close > level + buffer_dist:
            return index
    return None


def _structure_dict(
    *,
    structure: str,
    protected: Optional[dict],
    trigger_kind: Optional[str],
    trigger_price: Optional[float],
    closed_at: Optional[int],
    invalidated: bool,
    reason: str,
) -> dict:
    return {
        "structure": structure,
        "protected_swing_timestamp": None if protected is None else int(protected["timestamp"]),
        "protected_swing_price": None if protected is None else float(protected["price"]),
        "trigger_level_kind": trigger_kind,
        "trigger_level_price": None if trigger_price is None else float(trigger_price),
        "closed_1h_at_ms": closed_at,
        "invalidated": bool(invalidated),
        "reason": reason,
    }


def _classify_1h_structure(
    *,
    side: str,
    candles: list[dict],
    atr_period: int,
    atr_buffer_mult: float,
    swing_window: int,
) -> dict:
    side = str(side).upper()
    if side not in {"LONG", "SHORT"} or atr_buffer_mult < 0:
        return _structure_dict(
            structure="UNKNOWN", protected=None, trigger_kind=None, trigger_price=None,
            closed_at=None, invalidated=False, reason="INVALID_STRUCTURE_INPUT",
        )
    atr = calculate_atr(candles, atr_period)
    if atr is None or atr <= 0:
        return _structure_dict(
            structure="UNKNOWN", protected=None, trigger_kind=None, trigger_price=None,
            closed_at=None, invalidated=False, reason="INSUFFICIENT_1H_ATR",
        )
    swings = find_confirmed_swings(candles, swing_window)
    same_swings = swings["highs"] if side == "LONG" else swings["lows"]
    opposite_swings = swings["lows"] if side == "LONG" else swings["highs"]
    closed_at = int(candles[-1]["close_time"])
    buffer_dist = atr * atr_buffer_mult

    events: list[dict] = []
    for swing in same_swings:
        break_index = _first_break_index(side, candles, swing, buffer_dist, swing_window)
        if break_index is None:
            continue
        protected = _protected_swing(side, opposite_swings, swing, break_index)
        invalidation = _invalidation_index(side, candles, protected, break_index, buffer_dist)
        events.append({
            "swing": swing,
            "break_index": break_index,
            "protected": protected,
            "invalidation_index": invalidation,
        })

    events.sort(key=lambda row: (int(row["break_index"]), int(row["swing"]["index"])))

    reversal_event: Optional[dict] = None
    for previous in events:
        invalidation = previous["invalidation_index"]
        if invalidation is None:
            continue
        later = [
            event for event in events
            if int(event["break_index"]) > int(invalidation)
            and int(event["swing"]["index"]) > int(invalidation)
        ]
        if later:
            reversal_event = later[-1]

    if reversal_event is not None:
        swing = reversal_event["swing"]
        trigger_kind = "BOS_HIGH" if side == "LONG" else "BOS_LOW"
        return _structure_dict(
            structure="REVERSAL",
            protected=reversal_event["protected"],
            trigger_kind=trigger_kind,
            trigger_price=float(swing["price"]),
            closed_at=closed_at,
            invalidated=False,
            reason="INVALIDATION_THEN_NEW_BOS",
        )

    intact_events = [event for event in events if event["invalidation_index"] is None]
    if intact_events:
        active = intact_events[-1]
        swing = active["swing"]
        trigger = float(swing["price"])
        latest_close = float(candles[-1]["close"])
        trigger_kind = "BOS_HIGH" if side == "LONG" else "BOS_LOW"
        if side == "LONG":
            is_pullback = latest_close <= trigger + buffer_dist
        else:
            is_pullback = latest_close >= trigger - buffer_dist
        return _structure_dict(
            structure="PULLBACK" if is_pullback else "CONTINUATION",
            protected=active["protected"],
            trigger_kind=trigger_kind,
            trigger_price=trigger,
            closed_at=closed_at,
            invalidated=False,
            reason="INTACT_BOS_PULLBACK" if is_pullback else "INTACT_BOS_CONTINUATION",
        )

    if same_swings and opposite_swings:
        boundary = same_swings[-1]
        trigger_kind = "RANGE_HIGH" if side == "LONG" else "RANGE_LOW"
        return _structure_dict(
            structure="RANGE",
            protected=boundary,
            trigger_kind=trigger_kind,
            trigger_price=float(boundary["price"]),
            closed_at=closed_at,
            invalidated=bool(events),
            reason="NO_ACTIVE_DIRECTIONAL_BOS",
        )

    return _structure_dict(
        structure="UNKNOWN", protected=None, trigger_kind=None, trigger_price=None,
        closed_at=closed_at, invalidated=False, reason="NO_CONFIRMED_STRUCTURE_ANCHOR",
    )


def _latest_confirmed_opposite_swing(side: str, swings: dict[str, list[dict]], last_index: int) -> Optional[dict]:
    candidates = swings["lows"] if side == "LONG" else swings["highs"]
    candidates = [row for row in candidates if int(row["index"]) < last_index]
    return candidates[-1] if candidates else None


def _latest_discrete_breakout_index(side: str, candles: list[dict], breakout_threshold: float) -> Optional[int]:
    latest_index: Optional[int] = None
    for index in range(1, len(candles)):
        previous_close = float(candles[index - 1]["close"])
        current_close = float(candles[index]["close"])
        if side == "LONG" and previous_close <= breakout_threshold < current_close:
            latest_index = index
        elif side == "SHORT" and previous_close >= breakout_threshold > current_close:
            latest_index = index
    return latest_index


def _breakout_remains_valid(side: str, candles: list[dict], breakout_index: Optional[int], trigger_level: float) -> bool:
    if breakout_index is None:
        return False
    for row in candles[breakout_index + 1:]:
        close = float(row["close"])
        if side == "LONG" and close < trigger_level:
            return False
        if side == "SHORT" and close > trigger_level:
            return False
    return True


def _classify_15m_trigger(
    *,
    side: str,
    candles: list[dict],
    trigger_level: float,
    atr_period: int,
    atr_buffer_mult: float,
    swing_window: int,
) -> dict:
    side = str(side).upper()
    atr = calculate_atr(candles, atr_period)
    if side not in {"LONG", "SHORT"} or atr is None or atr <= 0 or atr_buffer_mult < 0:
        return {
            "trigger": "NO_TRIGGER",
            "supporting_triggers": (),
            "opposite_trigger": False,
            "closed_15m_at_ms": None,
            "data_valid": False,
            "reason": "INVALID_15M_DATA",
        }
    trigger_level = float(trigger_level)
    buffer_dist = atr * atr_buffer_mult
    latest = candles[-1]
    latest_index = len(candles) - 1
    latest_close = float(latest["close"])
    latest_open = float(latest["open"])
    latest_high = float(latest["high"])
    latest_low = float(latest["low"])
    closed_at = int(latest["close_time"])
    swings = find_confirmed_swings(candles, swing_window)
    opposite_swing = _latest_confirmed_opposite_swing(side, swings, latest_index)

    opposite_trigger = False
    supporting: list[str] = []
    if opposite_swing is not None:
        opposite_level = float(opposite_swing["price"])
        if side == "LONG":
            opposite_trigger = latest_close < opposite_level - buffer_dist
            swept = latest_low < opposite_level and latest_close > opposite_level
        else:
            opposite_trigger = latest_close > opposite_level + buffer_dist
            swept = latest_high > opposite_level and latest_close < opposite_level
        if swept:
            supporting.append("LIQUIDITY_SWEEP")

    if opposite_trigger:
        return {
            "trigger": "NO_TRIGGER",
            "supporting_triggers": tuple(sorted(set(supporting))),
            "opposite_trigger": True,
            "closed_15m_at_ms": closed_at,
            "data_valid": True,
            "reason": "OPPOSITE_15M_BREAKOUT",
        }

    zone_low = trigger_level - buffer_dist
    zone_high = trigger_level + buffer_dist
    touches_zone = latest_high >= zone_low and latest_low <= zone_high
    valid_close = latest_close > trigger_level if side == "LONG" else latest_close < trigger_level
    breakout_threshold = trigger_level + buffer_dist if side == "LONG" else trigger_level - buffer_dist
    prior = candles[:-1]
    breakout_index = _latest_discrete_breakout_index(side, prior, breakout_threshold)
    prior_breakout = _breakout_remains_valid(side, prior, breakout_index, trigger_level)
    if side == "LONG":
        current_breakout = latest_close > breakout_threshold
        previous_invalid = bool(prior) and float(prior[-1]["close"]) < trigger_level
        had_valid_before = any(float(row["close"]) > trigger_level for row in prior[:-1])
        crossed_level = latest_low <= trigger_level <= latest_high
        zone_wick = min(latest_open, latest_close) - latest_low
    else:
        current_breakout = latest_close < breakout_threshold
        previous_invalid = bool(prior) and float(prior[-1]["close"]) > trigger_level
        had_valid_before = any(float(row["close"]) < trigger_level for row in prior[:-1])
        crossed_level = latest_low <= trigger_level <= latest_high
        zone_wick = latest_high - max(latest_open, latest_close)

    body = abs(latest_close - latest_open)
    if prior_breakout and touches_zone and valid_close:
        trigger = "RETEST"
        reason = "PRIOR_BREAKOUT_RETEST_CONFIRMED"
    elif previous_invalid and had_valid_before and crossed_level and valid_close:
        trigger = "RECLAIM"
        reason = "LEVEL_RECLAIM_CONFIRMED"
    elif touches_zone and valid_close and body > 0 and zone_wick >= body:
        trigger = "REJECTION"
        reason = "ZONE_REJECTION_CONFIRMED"
    elif current_breakout:
        trigger = "BREAKOUT"
        reason = "CLOSE_CONFIRMED_BREAKOUT"
    else:
        trigger = "NO_TRIGGER"
        reason = "NO_CONFIRMED_15M_TRIGGER"

    return {
        "trigger": trigger,
        "supporting_triggers": tuple(sorted(set(supporting))),
        "opposite_trigger": False,
        "closed_15m_at_ms": closed_at,
        "data_valid": True,
        "reason": reason,
    }


def hybrid_state(structure: str, trigger: str, opposite_trigger: bool) -> tuple[str, str]:
    structure = str(structure).upper()
    trigger = str(trigger).upper()
    if opposite_trigger:
        return "REJECT", "OPPOSITE_15M_BREAKOUT"
    if structure == "UNKNOWN":
        return "REJECT", "UNKNOWN_STRUCTURE"
    if structure == "RANGE":
        return "WAIT", "RANGE_CONTEXT"
    if trigger in PASS_MATRIX.get(structure, set()):
        return "PASS", f"{structure}_{trigger}_CONFIRMED"
    return "WAIT", f"{structure}_NO_CONFIRMED_TRIGGER"


def _reject_unknown(analysis_version: str, reason: str) -> RezAnalysisResult:
    return RezAnalysisResult(
        analysis_version=analysis_version,
        state="REJECT",
        structure_1h="UNKNOWN",
        trigger_15m="NO_TRIGGER",
        supporting_triggers=(),
        reason=reason,
        protected_swing_timestamp=None,
        protected_swing_price=None,
        trigger_level_kind=None,
        trigger_level_price=None,
        closed_1h_at_ms=None,
        closed_15m_at_ms=None,
    )


def analyze_rez_candidate(
    *,
    side: str,
    candles_1h: list[dict],
    candles_15m: list[dict],
    atr_period: int,
    atr_buffer_mult: float,
    swing_window: int,
    analysis_version: str = "REZ_V1",
) -> RezAnalysisResult:
    side = str(side).upper()
    if side not in {"LONG", "SHORT"} or atr_period <= 0 or atr_buffer_mult < 0 or swing_window < 1:
        return _reject_unknown(analysis_version, "INVALID_INPUT")
    if not candles_1h or not candles_15m:
        return _reject_unknown(analysis_version, "INSUFFICIENT_HISTORY")

    structure = _classify_1h_structure(
        side=side,
        candles=candles_1h,
        atr_period=atr_period,
        atr_buffer_mult=atr_buffer_mult,
        swing_window=swing_window,
    )
    if structure["structure"] == "UNKNOWN" or structure["trigger_level_price"] is None:
        return RezAnalysisResult(
            analysis_version=analysis_version,
            state="REJECT",
            structure_1h=structure["structure"],
            trigger_15m="NO_TRIGGER",
            supporting_triggers=(),
            reason=structure["reason"],
            protected_swing_timestamp=structure["protected_swing_timestamp"],
            protected_swing_price=structure["protected_swing_price"],
            trigger_level_kind=structure["trigger_level_kind"],
            trigger_level_price=structure["trigger_level_price"],
            closed_1h_at_ms=structure["closed_1h_at_ms"],
            closed_15m_at_ms=None,
        )

    trigger = _classify_15m_trigger(
        side=side,
        candles=candles_15m,
        trigger_level=float(structure["trigger_level_price"]),
        atr_period=atr_period,
        atr_buffer_mult=atr_buffer_mult,
        swing_window=swing_window,
    )
    if not trigger["data_valid"]:
        state, reason = "REJECT", trigger["reason"]
    else:
        state, reason = hybrid_state(
            structure["structure"], trigger["trigger"], bool(trigger["opposite_trigger"])
        )

    return RezAnalysisResult(
        analysis_version=analysis_version,
        state=state,
        structure_1h=structure["structure"],
        trigger_15m=trigger["trigger"],
        supporting_triggers=tuple(trigger["supporting_triggers"]),
        reason=reason,
        protected_swing_timestamp=structure["protected_swing_timestamp"],
        protected_swing_price=structure["protected_swing_price"],
        trigger_level_kind=structure["trigger_level_kind"],
        trigger_level_price=structure["trigger_level_price"],
        closed_1h_at_ms=structure["closed_1h_at_ms"],
        closed_15m_at_ms=trigger["closed_15m_at_ms"],
    )
