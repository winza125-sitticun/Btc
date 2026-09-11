"""Deterministic, full-quality strategy performance aggregates."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from math import ceil
from statistics import median
from typing import Any, Literal, Sequence

from pydantic import BaseModel, ConfigDict, Field

Window = Literal["24H", "7D", "30D", "ALL"]


class StrategyMetrics(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    provider: str | None = None
    model: str | None = None
    timeframe: str | None = None
    direction: str | None = None
    symbol: str | None = None
    rolling_window: Window
    window_started_at: datetime | None = None
    window_ended_at: datetime
    analysis_count: int = Field(ge=0)
    eligible_signal_count: int = Field(ge=0)
    simulated_trade_count: int = Field(ge=0)
    no_fill_count: int = Field(ge=0)
    win_count: int = Field(ge=0)
    loss_count: int = Field(ge=0)
    win_rate: float | None = None
    average_net_return: float | None = None
    median_net_return: float | None = None
    expectancy: float | None = None
    profit_factor: float | None = None
    max_drawdown_percent: float | None = None
    average_mfe_percent: float | None = None
    average_mae_percent: float | None = None
    tp1_hit_rate: float | None = None
    tp2_hit_rate: float | None = None
    tp3_hit_rate: float | None = None
    sl_hit_rate: float | None = None
    provider_success_rate: float | None = None
    median_latency_ms: int | None = None
    p95_latency_ms: int | None = None
    full_data_count: int = 0
    partial_data_count: int = 0
    missing_data_count: int = 0


def _value(row: Any, key: str, default: Any = None) -> Any:
    return row.get(key, default) if isinstance(row, dict) else getattr(row, key, default)


def _rate(n: int, denominator: int) -> float | None:
    return round(n / denominator * 100, 8) if denominator else None


def _percentile(values: Sequence[int], percentile: float) -> int | None:
    if not values:
        return None
    return sorted(values)[max(0, ceil(len(values) * percentile) - 1)]


def compute_strategy_metrics(
    rows: Sequence[dict[str, Any] | Any], *, now: datetime | None = None, window: Window = "ALL",
    provider: str | None = None, model: str | None = None, timeframe: str | None = None,
    direction: str | None = None, symbol: str | None = None,
) -> StrategyMetrics:
    """Aggregate outcome/analysis rows without network calls or persistence.

    PARTIAL and MISSING rows remain in sample/data-quality counts but are excluded
    from all outcome performance statistics.
    """
    if window not in ("24H", "7D", "30D", "ALL"):
        raise ValueError("unsupported rolling window")
    ended = now or datetime.now(timezone.utc)
    if ended.tzinfo is None:
        ended = ended.replace(tzinfo=timezone.utc)
    duration = {"24H": timedelta(hours=24), "7D": timedelta(days=7), "30D": timedelta(days=30)}.get(window)
    started = ended - duration if duration else None
    selected = []
    for row in rows:
        stamp = _value(row, "created_at") or _value(row, "signal_created_at")
        if isinstance(stamp, str):
            try: stamp = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
            except ValueError: stamp = None
        if stamp is not None and stamp.tzinfo is None: stamp = stamp.replace(tzinfo=timezone.utc)
        if started and (stamp is None or stamp < started or stamp > ended): continue
        if provider is not None and _value(row, "provider") != provider: continue
        if model is not None and _value(row, "model") != model: continue
        if timeframe is not None and _value(row, "timeframe") != timeframe: continue
        if direction is not None and _value(row, "direction", _value(row, "ai_direction")) != direction: continue
        if symbol is not None and _value(row, "symbol") != symbol: continue
        selected.append(row)
    full = [r for r in selected if _value(r, "data_quality", "FULL") == "FULL"]
    returns = [float(_value(r, "final_return_percent")) for r in full if _value(r, "final_return_percent") is not None]
    wins = [r for r in full if _value(r, "outcome") == "WIN"]
    losses = [r for r in full if _value(r, "outcome") == "LOSS"]
    profit = sum(v for v in returns if v > 0)
    loss = abs(sum(v for v in returns if v < 0))
    running = peak = 0.0; drawdown = 0.0
    for value in returns:
        running += value; peak = max(peak, running)
        drawdown = max(drawdown, peak - running)
    latencies = [int(_value(r, "latency_ms")) for r in selected if _value(r, "latency_ms") is not None]
    statuses = [str(_value(r, "status")) for r in selected if _value(r, "status") is not None]
    quality = [_value(r, "data_quality", "FULL") for r in selected]
    denominator = len(full)
    def avg(key):
        vals = [float(_value(r, key)) for r in full if _value(r, key) is not None]
        return round(sum(vals) / len(vals), 8) if vals else None
    trade_count = sum(bool(_value(r, "simulated_trade", _value(r, "trade_id") is not None)) for r in selected)
    return StrategyMetrics(
        provider=provider, model=model, timeframe=timeframe, direction=direction, symbol=symbol,
        rolling_window=window, window_started_at=started, window_ended_at=ended,
        analysis_count=len(selected), eligible_signal_count=sum(bool(_value(r, "eligible", _value(r, "eligible_signal", False))) for r in selected),
        simulated_trade_count=trade_count, no_fill_count=sum(_value(r, "outcome") == "NO_FILL" for r in full),
        win_count=len(wins), loss_count=len(losses), win_rate=_rate(len(wins), denominator),
        average_net_return=round(sum(returns) / len(returns), 8) if returns else None,
        median_net_return=round(float(median(returns)), 8) if returns else None,
        expectancy=round(sum(returns) / len(returns), 8) if returns else None,
        profit_factor=round(profit / loss, 8) if loss else (None if not profit else float("inf")),
        max_drawdown_percent=round(drawdown, 8) if returns else None,
        average_mfe_percent=avg("mfe_percent"), average_mae_percent=avg("mae_percent"),
        tp1_hit_rate=_rate(sum(int(_value(r, "highest_tp_hit", 0) or 0) >= 1 for r in full), denominator),
        tp2_hit_rate=_rate(sum(int(_value(r, "highest_tp_hit", 0) or 0) >= 2 for r in full), denominator),
        tp3_hit_rate=_rate(sum(int(_value(r, "highest_tp_hit", 0) or 0) >= 3 for r in full), denominator),
        sl_hit_rate=_rate(sum(bool(_value(r, "stop_touched", False)) for r in full), denominator),
        provider_success_rate=_rate(sum(s in ("SUCCESS", "success") for s in statuses), len(statuses)),
        median_latency_ms=int(median(latencies)) if latencies else None, p95_latency_ms=_percentile(latencies, .95),
        full_data_count=quality.count("FULL"), partial_data_count=quality.count("PARTIAL"), missing_data_count=quality.count("MISSING"),
    )

compute_metrics = compute_strategy_metrics
