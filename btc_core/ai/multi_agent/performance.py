from __future__ import annotations

from datetime import datetime, timedelta
from enum import StrEnum
from statistics import fmean
from typing import Literal, Protocol, Sequence

from pydantic import BaseModel, ConfigDict, Field

from btc_core.ai.models import AIProvider, Direction
from btc_core.ai.multi_agent.models import AgentRole
from btc_core.ai.multi_agent.repository import AgentPerformanceSnapshot, DecisionOutcomeRecord, OutcomeState


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class EvaluationHorizon(StrEnum):
    M15 = "15M"
    H1 = "1H"
    H4 = "4H"


class MarketRegime(StrEnum):
    BULL = "BULL"
    BEAR = "BEAR"
    SIDEWAYS = "SIDEWAYS"
    UNKNOWN = "UNKNOWN"


_HORIZON_DURATION = {
    EvaluationHorizon.M15: timedelta(minutes=15),
    EvaluationHorizon.H1: timedelta(hours=1),
    EvaluationHorizon.H4: timedelta(hours=4),
}
_HORIZON_TIMEFRAME = {
    EvaluationHorizon.M15: "15m",
    EvaluationHorizon.H1: "1h",
    EvaluationHorizon.H4: "4h",
}
_HORIZONS = (EvaluationHorizon.M15, EvaluationHorizon.H1, EvaluationHorizon.H4)


class MarketOutcomeBar(_FrozenModel):
    symbol: str = Field(min_length=1, max_length=30)
    timeframe: str = Field(min_length=1, max_length=10)
    open_time: datetime
    close_time: datetime
    high: float = Field(gt=0)
    low: float = Field(gt=0)
    close: float = Field(gt=0)


class OutcomeEvaluationCandidate(_FrozenModel):
    multi_agent_run_id: str = Field(min_length=1, max_length=100)
    agent_attempt_id: int = Field(gt=0)
    role: AgentRole
    provider: AIProvider
    model: str = Field(min_length=1, max_length=120)
    symbol: str = Field(min_length=1, max_length=30)
    direction: Direction
    started_at: datetime
    reference_price: float = Field(gt=0)
    market_regime: MarketRegime = MarketRegime.UNKNOWN
    existing_horizons: tuple[EvaluationHorizon, ...] = ()


class PerformanceEvidence(_FrozenModel):
    multi_agent_run_id: str = Field(min_length=1, max_length=100)
    agent_attempt_id: int = Field(gt=0)
    role: AgentRole
    provider: AIProvider
    model: str = Field(min_length=1, max_length=120)
    symbol: str = Field(min_length=1, max_length=30)
    direction: Direction
    market_regime: MarketRegime = MarketRegime.UNKNOWN
    horizon: EvaluationHorizon
    state: OutcomeState
    data_quality: Literal["FULL", "PARTIAL", "MISSING"]
    matured_at: datetime
    directional_hit: bool | None = None
    signed_return_pct: float | None = None


class PerformanceSummary(_FrozenModel):
    as_of: datetime
    role: AgentRole | None = None
    provider: AIProvider | None = None
    model: str | None = None
    symbol: str | None = None
    direction: Direction | None = None
    market_regime: MarketRegime | None = None
    horizon: EvaluationHorizon | None = None
    sample_count: int = Field(ge=0)
    hit_rate: float | None = Field(default=None, ge=0, le=1)
    mean_signed_return_pct: float | None = None
    normalized_expectancy: float | None = Field(default=None, ge=0, le=1)
    quality_score: float = Field(ge=0, le=1)
    multiplier: float = Field(ge=0.75, le=1.25)


class PerformanceRepositoryProtocol(Protocol):
    async def list_performance_evidence(self, as_of: datetime) -> tuple[PerformanceEvidence, ...]: ...
    async def append_performance_snapshot(self, item: AgentPerformanceSnapshot) -> int: ...
    async def list_outcome_evaluation_candidates(self, as_of: datetime) -> tuple[OutcomeEvaluationCandidate, ...]: ...
    async def load_market_outcome_bars(self, symbol: str, timeframe: str, start: datetime, end: datetime) -> tuple[MarketOutcomeBar, ...]: ...
    async def append_outcome(self, outcome: DecisionOutcomeRecord) -> int: ...


def _q(value: float) -> float:
    return round(float(value), 6)


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def evaluate_outcome(candidate: OutcomeEvaluationCandidate, horizon: EvaluationHorizon, *, horizon_bars: Sequence[MarketOutcomeBar], mfe_bars: Sequence[MarketOutcomeBar], now: datetime) -> DecisionOutcomeRecord:
    duration = _HORIZON_DURATION[horizon]
    matured_at = candidate.started_at + duration
    if now < matured_at:
        return DecisionOutcomeRecord(
            multi_agent_run_id=candidate.multi_agent_run_id, agent_attempt_id=candidate.agent_attempt_id,
            horizon=horizon.value, state=OutcomeState.PENDING, reference_price=candidate.reference_price,
            matured_at=matured_at, market_regime=candidate.market_regime.value, data_quality="MISSING",
        )

    timeframe = _HORIZON_TIMEFRAME[horizon]
    horizon_rows = sorted(
        (item for item in horizon_bars if item.symbol == candidate.symbol and item.timeframe == timeframe and matured_at <= item.close_time < matured_at + duration),
        key=lambda item: item.close_time,
    )
    if not horizon_rows:
        return DecisionOutcomeRecord(
            multi_agent_run_id=candidate.multi_agent_run_id, agent_attempt_id=candidate.agent_attempt_id,
            horizon=horizon.value, state=OutcomeState.INVALID_DATA, reference_price=candidate.reference_price,
            matured_at=matured_at, evaluated_at=now, market_regime=candidate.market_regime.value,
            data_quality="MISSING", invalid_reason="MISSING_HORIZON_CLOSE",
        )

    horizon_price = horizon_rows[0].close
    bounded = sorted(
        (item for item in mfe_bars if item.symbol == candidate.symbol and item.timeframe == "15m" and candidate.started_at < item.close_time <= matured_at),
        key=lambda item: item.close_time,
    )
    expected = max(1, int(duration / timedelta(minutes=15)))
    quality: Literal["FULL", "PARTIAL", "MISSING"] = "FULL" if len(bounded) >= expected else "PARTIAL"
    if candidate.market_regime is MarketRegime.UNKNOWN:
        quality = "PARTIAL"

    signed_return = directional_hit = mfe = mae = None
    if candidate.direction in (Direction.LONG, Direction.SHORT):
        raw_return = ((horizon_price / candidate.reference_price) - 1.0) * 100.0
        signed_return = raw_return if candidate.direction is Direction.LONG else -raw_return
        directional_hit = signed_return > 0
        if bounded:
            highest = max(item.high for item in bounded)
            lowest = min(item.low for item in bounded)
            if candidate.direction is Direction.LONG:
                mfe = max(0.0, ((highest / candidate.reference_price) - 1.0) * 100.0)
                mae = min(0.0, ((lowest / candidate.reference_price) - 1.0) * 100.0)
            else:
                mfe = max(0.0, (1.0 - (lowest / candidate.reference_price)) * 100.0)
                mae = min(0.0, (1.0 - (highest / candidate.reference_price)) * 100.0)

    return DecisionOutcomeRecord(
        multi_agent_run_id=candidate.multi_agent_run_id, agent_attempt_id=candidate.agent_attempt_id,
        horizon=horizon.value, state=OutcomeState.EVALUATED, reference_price=candidate.reference_price,
        horizon_price=horizon_price, matured_at=matured_at, evaluated_at=now,
        directional_hit=directional_hit, signed_return_pct=None if signed_return is None else _q(signed_return),
        mfe_pct=None if mfe is None else _q(mfe), mae_pct=None if mae is None else _q(mae),
        market_regime=candidate.market_regime.value, data_quality=quality,
    )


def summarize_performance(rows: Sequence[PerformanceEvidence], *, as_of: datetime, role: AgentRole | None = None, provider: AIProvider | None = None, model: str | None = None, symbol: str | None = None, direction: Direction | None = None, market_regime: MarketRegime | None = None, horizon: EvaluationHorizon | None = None) -> PerformanceSummary:
    eligible: list[PerformanceEvidence] = []
    for item in rows:
        if item.matured_at > as_of or item.state is not OutcomeState.EVALUATED or item.data_quality != "FULL":
            continue
        if item.direction not in (Direction.LONG, Direction.SHORT) or item.directional_hit is None or item.signed_return_pct is None:
            continue
        if role is not None and item.role is not role: continue
        if provider is not None and item.provider is not provider: continue
        if model is not None and item.model != model: continue
        if symbol is not None and item.symbol != symbol: continue
        if direction is not None and item.direction is not direction: continue
        if market_regime is not None and item.market_regime is not market_regime: continue
        if horizon is not None and item.horizon is not horizon: continue
        eligible.append(item)

    count = len(eligible)
    if count:
        hit_rate = _q(sum(1 for item in eligible if item.directional_hit) / count)
        mean_return = _q(fmean(item.signed_return_pct for item in eligible if item.signed_return_pct is not None))
        normalized = _q(_clamp(0.5 + mean_return / 4.0, 0.0, 1.0))
        quality_score = _q(0.70 * hit_rate + 0.30 * normalized)
    else:
        hit_rate = mean_return = normalized = None
        quality_score = 0.5
    multiplier = 1.0 if count < 30 else _q(_clamp(0.75 + 0.50 * quality_score, 0.75, 1.25))
    return PerformanceSummary(
        as_of=as_of, role=role, provider=provider, model=model, symbol=symbol,
        direction=direction, market_regime=market_regime, horizon=horizon,
        sample_count=count, hit_rate=hit_rate, mean_signed_return_pct=mean_return,
        normalized_expectancy=normalized, quality_score=quality_score, multiplier=multiplier,
    )


class MultiAgentPerformanceService:
    def __init__(self, repository: PerformanceRepositoryProtocol) -> None:
        self._repository = repository

    async def evaluate_mature_outcomes(self, now: datetime) -> tuple[DecisionOutcomeRecord, ...]:
        created: list[DecisionOutcomeRecord] = []
        candidates = await self._repository.list_outcome_evaluation_candidates(now)
        for candidate in candidates:
            existing = set(candidate.existing_horizons)
            for horizon in _HORIZONS:
                if horizon in existing:
                    continue
                duration = _HORIZON_DURATION[horizon]
                matured_at = candidate.started_at + duration
                if matured_at > now:
                    continue
                timeframe = _HORIZON_TIMEFRAME[horizon]
                horizon_bars = await self._repository.load_market_outcome_bars(
                    candidate.symbol, timeframe, matured_at, matured_at + duration
                )
                mfe_bars = await self._repository.load_market_outcome_bars(
                    candidate.symbol, "15m", candidate.started_at, matured_at + timedelta(microseconds=1)
                )
                outcome = evaluate_outcome(
                    candidate, horizon, horizon_bars=horizon_bars, mfe_bars=mfe_bars, now=now
                )
                await self._repository.append_outcome(outcome)
                created.append(outcome)
        return tuple(created)

    async def historical_weight_for(self, role: AgentRole, provider: AIProvider, model: str, as_of: datetime) -> float:
        rows = await self._repository.list_performance_evidence(as_of)
        summary = summarize_performance(rows, as_of=as_of, role=role, provider=provider, model=model, horizon=EvaluationHorizon.H1)
        await self._repository.append_performance_snapshot(AgentPerformanceSnapshot(
            role=role, provider=provider, model=model, as_of=as_of, horizon="1H",
            sample_count=summary.sample_count, hit_rate=summary.hit_rate,
            mean_signed_return_pct=summary.mean_signed_return_pct,
            normalized_expectancy=summary.normalized_expectancy, quality_score=summary.quality_score,
            multiplier=summary.multiplier, performance_algorithm_version="performance-v1",
        ))
        return summary.multiplier
