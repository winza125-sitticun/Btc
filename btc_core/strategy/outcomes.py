from __future__ import annotations

from datetime import datetime, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class OHLCBar(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    timestamp: datetime
    open: float = Field(gt=0)
    high: float = Field(gt=0)
    low: float = Field(gt=0)
    close: float = Field(gt=0)


class SignalSpec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    direction: Literal["LONG", "SHORT", "WAIT", "EXIT"]
    entry_min: float = Field(gt=0)
    entry_max: float = Field(gt=0)
    stop: float = Field(gt=0)
    take_profits: tuple[float, ...] = ()
    signal_timestamp: datetime
    horizon: Literal["1H", "4H", "24H"]

    @model_validator(mode="after")
    def valid_range(self):
        if self.entry_min > self.entry_max:
            raise ValueError("entry_min must be less than or equal to entry_max")
        return self


class SignalOutcome(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    entry_touched: bool = False
    stop_touched: bool = False
    highest_tp_hit: int = Field(default=0, ge=0, le=3)
    mfe_percent: float | None = None
    mae_percent: float | None = None
    final_return_percent: float | None = None
    outcome: Literal["PENDING", "WIN", "LOSS", "NEUTRAL", "NO_FILL", "INVALIDATED"] = "PENDING"
    data_quality: Literal["FULL", "PARTIAL", "MISSING"] = "MISSING"


def evaluate_signal_outcome(spec: SignalSpec, bars: tuple[OHLCBar, ...] | list[OHLCBar]) -> SignalOutcome:
    ordered = tuple(sorted(bars, key=lambda item: item.timestamp))
    due = spec.signal_timestamp + timedelta(hours=int(spec.horizon[:-1]))
    bounded = tuple(item for item in ordered if spec.signal_timestamp <= item.timestamp <= due)
    if not bounded:
        return SignalOutcome()
    quality = "FULL" if bounded[-1].timestamp >= due else "PARTIAL"
    if spec.direction in ("WAIT", "EXIT"):
        return SignalOutcome(outcome="NEUTRAL", data_quality=quality)
    reference = (spec.entry_min + spec.entry_max) / 2
    touched = False
    stop_touched = False
    highest = 0
    mfe = 0.0
    mae = 0.0
    final_close = bounded[-1].close
    for item in bounded:
        if spec.direction == "LONG":
            mfe = max(mfe, (item.high - reference) / reference * 100)
            mae = min(mae, (item.low - reference) / reference * 100)
            in_entry = item.low <= spec.entry_max and item.high >= spec.entry_min
            stop = item.low <= spec.stop
            tp_hits = [i + 1 for i, tp in enumerate(spec.take_profits[:3]) if item.high >= tp]
        else:
            mfe = max(mfe, (reference - item.low) / reference * 100)
            mae = min(mae, (reference - item.high) / reference * 100)
            in_entry = item.low <= spec.entry_max and item.high >= spec.entry_min
            stop = item.high >= spec.stop
            tp_hits = [i + 1 for i, tp in enumerate(spec.take_profits[:3]) if item.low <= tp]
        if not touched and in_entry:
            touched = True
        if touched and stop:
            stop_touched = True
            break  # conservative: stop wins when TP and SL share a candle
        if touched and tp_hits:
            highest = max(highest, max(tp_hits))
    if not touched:
        return SignalOutcome(mfe_percent=round(mfe, 8), mae_percent=round(mae, 8), outcome="NO_FILL", data_quality=quality)
    if stop_touched:
        final_return = (spec.stop - reference) / reference * 100 if spec.direction == "LONG" else (reference - spec.stop) / reference * 100
        return SignalOutcome(entry_touched=True, stop_touched=True, highest_tp_hit=highest, mfe_percent=round(mfe, 8), mae_percent=round(mae, 8), final_return_percent=round(final_return, 8), outcome="LOSS", data_quality=quality)
    final_return = (final_close - reference) / reference * 100 if spec.direction == "LONG" else (reference - final_close) / reference * 100
    outcome = "WIN" if highest else "NEUTRAL"
    return SignalOutcome(entry_touched=True, stop_touched=False, highest_tp_hit=highest, mfe_percent=round(mfe, 8), mae_percent=round(mae, 8), final_return_percent=round(final_return, 8), outcome=outcome, data_quality=quality)
