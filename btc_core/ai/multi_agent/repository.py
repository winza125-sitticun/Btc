from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Protocol

import httpx
from pydantic import BaseModel, ConfigDict, Field, model_validator

from btc_core.ai.models import AIProvider, Direction
from btc_core.ai.multi_agent.models import (
    AgentRole,
    ConsensusDecision,
    FrozenConfigSnapshot,
    HesitationSnapshot,
    RolloutMode,
    VortexInputs,
)


_SECRET_KEYS = {
    "authorization",
    "api_key",
    "apikey",
    "api-key",
    "access_token",
    "secret",
    "token",
}


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RunStatus(StrEnum):
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    PARTIAL = "PARTIAL"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    FAILED = "FAILED"


class AttemptPersistenceStatus(StrEnum):
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    INVALID_RESPONSE = "INVALID_RESPONSE"
    SKIPPED = "SKIPPED"


class RiskResultStatus(StrEnum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    PENDING = "PENDING"


class OutcomeState(StrEnum):
    PENDING = "PENDING"
    EVALUABLE = "EVALUABLE"
    EVALUATED = "EVALUATED"
    INVALID_DATA = "INVALID_DATA"


class MultiAgentRunRecord(_FrozenModel):
    id: str = Field(min_length=1, max_length=100)
    scanner_candidate_id: int = Field(gt=0)
    scanner_run_id: str = Field(min_length=1, max_length=100)
    symbol: str = Field(min_length=1, max_length=30)
    timeframe: str = Field(min_length=1, max_length=10)
    started_at: datetime
    snapshot_ref: str = Field(min_length=1, max_length=200)
    snapshot_observed_at: datetime
    config_version: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
    enabled_role_count: int = Field(ge=0, le=6)
    rollout_mode: RolloutMode
    market_context_summary: VortexInputs
    legacy_analysis_ref: int | None = Field(default=None, gt=0)


class AgentAttemptRecord(_FrozenModel):
    multi_agent_run_id: str = Field(min_length=1, max_length=100)
    role: AgentRole
    provider: AIProvider
    model: str = Field(min_length=1, max_length=120)
    prompt_version: str = Field(min_length=1, max_length=40)
    prompt_digest: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
    status: AttemptPersistenceStatus
    direction: Direction | None = None
    confidence: float | None = Field(default=None, ge=0, le=100)
    entry_min: float | None = Field(default=None, gt=0)
    entry_max: float | None = Field(default=None, gt=0)
    stop_loss: float | None = Field(default=None, gt=0)
    take_profits: tuple[float, ...] = ()
    risk_reward: float | None = Field(default=None, gt=0)
    reason_summary: str | None = Field(default=None, max_length=1000)
    latency_ms: int | None = Field(default=None, ge=0)
    error_code: str | None = Field(default=None, max_length=100)
    error_message: str | None = None
    snapshot_ref: str = Field(min_length=1, max_length=200)
    created_at: datetime

    @model_validator(mode="after")
    def validate_success_payload(self):
        if self.status is AttemptPersistenceStatus.SUCCESS and (
            self.direction is None or self.confidence is None
        ):
            raise ValueError("successful persisted attempts require direction and confidence")
        if self.entry_min is not None and self.entry_max is not None and self.entry_min > self.entry_max:
            raise ValueError("entry_min must be less than or equal to entry_max")
        return self


class ConsensusRecord(_FrozenModel):
    multi_agent_run_id: str = Field(min_length=1, max_length=100)
    decision: ConsensusDecision
    created_at: datetime


class HesitationRecord(_FrozenModel):
    multi_agent_run_id: str = Field(min_length=1, max_length=100)
    consensus_id: int = Field(gt=0)
    snapshot: HesitationSnapshot
    created_at: datetime


class RiskResultRecord(_FrozenModel):
    multi_agent_run_id: str = Field(min_length=1, max_length=100)
    consensus_id: int = Field(gt=0)
    status: RiskResultStatus
    approved: bool
    reason_codes: tuple[str, ...] = ()
    risk_policy_version: str = Field(min_length=1, max_length=100)
    created_at: datetime

    @model_validator(mode="after")
    def validate_approval(self):
        if self.status is RiskResultStatus.APPROVED and not self.approved:
            raise ValueError("APPROVED risk result must set approved=True")
        if self.status is not RiskResultStatus.APPROVED and self.approved:
            raise ValueError("non-APPROVED risk result must set approved=False")
        return self


class DashboardEventRecord(_FrozenModel):
    multi_agent_run_id: str = Field(min_length=1, max_length=100)
    sequence: int = Field(ge=1)
    event_type: str = Field(min_length=1, max_length=100)
    role: AgentRole | None = None
    status: str = Field(min_length=1, max_length=100)
    message: str = Field(min_length=1, max_length=500)
    metadata_safe: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class DecisionOutcomeRecord(_FrozenModel):
    multi_agent_run_id: str = Field(min_length=1, max_length=100)
    agent_attempt_id: int | None = Field(default=None, gt=0)
    horizon: str = Field(pattern=r"^(15M|1H|4H)$")
    state: OutcomeState
    reference_price: float = Field(gt=0)
    horizon_price: float | None = Field(default=None, gt=0)
    matured_at: datetime
    evaluated_at: datetime | None = None
    directional_hit: bool | None = None
    signed_return_pct: float | None = None
    mfe_pct: float | None = None
    mae_pct: float | None = None
    market_regime: str = Field(min_length=1, max_length=100)
    data_quality: str = Field(pattern=r"^(FULL|PARTIAL|MISSING)$")
    invalid_reason: str | None = Field(default=None, max_length=500)


class AgentPerformanceSnapshot(_FrozenModel):
    role: AgentRole
    provider: AIProvider
    model: str = Field(min_length=1, max_length=120)
    as_of: datetime
    horizon: str = Field(pattern=r"^(15M|1H|4H)$")
    sample_count: int = Field(ge=0)
    hit_rate: float | None = Field(default=None, ge=0, le=1)
    mean_signed_return_pct: float | None = None
    normalized_expectancy: float | None = None
    quality_score: float = Field(ge=0, le=1)
    multiplier: float = Field(ge=0)
    performance_algorithm_version: str = Field(min_length=1, max_length=100)


class SupabaseMultiAgentRepositoryError(RuntimeError):
    pass


class MultiAgentRepository(Protocol):
    async def ensure_config_snapshot(self, config: FrozenConfigSnapshot) -> str: ...
    async def create_run(self, run: MultiAgentRunRecord) -> str: ...
    async def finalize_run(
        self,
        run_id: str,
        *,
        status: RunStatus,
        completed_at: datetime,
        valid_role_count: int,
    ) -> None: ...
    async def append_attempt(self, attempt: AgentAttemptRecord) -> int: ...
    async def append_consensus(self, consensus: ConsensusRecord) -> int: ...
    async def append_hesitation(self, hesitation: HesitationRecord) -> int: ...
    async def append_risk_result(self, risk: RiskResultRecord) -> int: ...
    async def append_event(self, event: DashboardEventRecord) -> int: ...
    async def append_outcome(self, outcome: DecisionOutcomeRecord) -> int: ...
    async def append_performance_snapshot(self, item: AgentPerformanceSnapshot) -> int: ...


def _sanitize(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _sanitize(item)
            for key, item in value.items()
            if str(key).strip().lower() not in _SECRET_KEYS
        }
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    if isinstance(value, tuple):
        return [_sanitize(item) for item in value]
    return value


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("timestamps must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


class SupabaseMultiAgentRepository:
    def __init__(
        self,
        *,
        supabase_url: str,
        api_key: str,
        timeout_seconds: float = 10.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not supabase_url.strip() or not api_key.strip():
            raise ValueError("Supabase URL and API key are required")
        self._client = httpx.AsyncClient(
            base_url=f"{supabase_url.rstrip('/')}/rest/v1",
            timeout=httpx.Timeout(timeout_seconds),
            transport=transport,
            headers={
                "apikey": api_key,
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
        )

    async def __aenter__(self) -> "SupabaseMultiAgentRepository":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        try:
            response = await self._client.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise SupabaseMultiAgentRepositoryError("Supabase multi-agent request failed") from exc
        if response.is_error:
            raise SupabaseMultiAgentRepositoryError(
                f"Supabase multi-agent repository returned HTTP {response.status_code}"
            )
        return response

    async def _append(self, table: str, payload: dict[str, Any]) -> int:
        response = await self._request(
            "POST",
            f"/{table}",
            headers={"Prefer": "return=representation"},
            json=_sanitize(payload),
        )
        rows = response.json()
        if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
            raise SupabaseMultiAgentRepositoryError(f"{table} insert did not return one row")
        row_id = rows[0].get("id")
        if not isinstance(row_id, int):
            raise SupabaseMultiAgentRepositoryError(f"{table} insert did not return an integer id")
        return row_id

    async def ensure_config_snapshot(self, config: FrozenConfigSnapshot) -> str:
        sanitized_assignments = [
            {
                "role": item.role.value,
                "provider": item.provider.value,
                "model": item.model,
                "base_weight": item.base_weight,
                "prompt_version": item.prompt_version,
                "prompt_digest": item.prompt_digest,
            }
            for item in config.assignments
        ]
        prompt_bundle = [
            {
                "role": item.role.value,
                "prompt_version": item.prompt_version,
                "prompt_digest": item.prompt_digest,
                "prompt_text": item.prompt_text,
            }
            for item in config.assignments
        ]
        payload = {
            "config_version": config.config_version,
            "sanitized_config": {
                "mode": config.mode.value,
                "assignments": sanitized_assignments,
                "min_valid_roles": config.min_valid_roles,
                "min_coverage": config.min_coverage,
                "min_agreement": config.min_agreement,
                "min_signed_score": config.min_signed_score,
                "market_context_mapping_version": config.market_context_mapping_version,
            },
            "role_prompt_bundle": prompt_bundle,
            "decision_contract_version": config.decision_contract_version,
            "consensus_algorithm_version": config.consensus_version,
            "hesitation_algorithm_version": config.hesitation_version,
            "performance_algorithm_version": config.performance_version,
            "market_context_mapping_version": config.market_context_mapping_version,
        }
        await self._request(
            "POST",
            "/ai_multi_agent_configs",
            params={"on_conflict": "config_version"},
            headers={"Prefer": "resolution=ignore-duplicates,return=minimal"},
            json=_sanitize(payload),
        )
        return config.config_version

    async def create_run(self, run: MultiAgentRunRecord) -> str:
        payload = run.model_dump(mode="json", exclude_none=True)
        payload["status"] = RunStatus.RUNNING.value
        payload["valid_role_count"] = 0
        response = await self._request(
            "POST",
            "/ai_multi_agent_runs",
            headers={"Prefer": "return=representation"},
            json=_sanitize(payload),
        )
        rows = response.json()
        if not isinstance(rows, list) or len(rows) != 1 or rows[0].get("id") != run.id:
            raise SupabaseMultiAgentRepositoryError("run insert did not return the expected id")
        return run.id

    async def finalize_run(
        self,
        run_id: str,
        *,
        status: RunStatus,
        completed_at: datetime,
        valid_role_count: int,
    ) -> None:
        if status is RunStatus.RUNNING:
            raise ValueError("finalize_run requires a terminal status")
        if not 0 <= valid_role_count <= 6:
            raise ValueError("valid_role_count must be between 0 and 6")
        response = await self._request(
            "PATCH",
            "/ai_multi_agent_runs",
            params={"id": f"eq.{run_id}", "status": "eq.RUNNING", "select": "id"},
            headers={"Prefer": "return=representation"},
            json={
                "completed_at": _iso(completed_at),
                "status": status.value,
                "valid_role_count": valid_role_count,
            },
        )
        rows = response.json()
        if not isinstance(rows, list) or len(rows) != 1 or rows[0].get("id") != run_id:
            raise SupabaseMultiAgentRepositoryError("multi-agent run is already terminal or missing")

    async def append_attempt(self, attempt: AgentAttemptRecord) -> int:
        payload = attempt.model_dump(mode="json", exclude_none=True)
        if payload.get("error_message") is not None:
            payload["error_message"] = str(payload["error_message"])[:500]
        return await self._append("ai_agent_attempts", payload)

    async def append_consensus(self, consensus: ConsensusRecord) -> int:
        payload = consensus.decision.model_dump(mode="json")
        payload.update(
            {
                "multi_agent_run_id": consensus.multi_agent_run_id,
                "created_at": _iso(consensus.created_at),
            }
        )
        return await self._append("ai_consensus_decisions", payload)

    async def append_hesitation(self, hesitation: HesitationRecord) -> int:
        payload = hesitation.snapshot.model_dump(mode="json")
        payload.update(
            {
                "multi_agent_run_id": hesitation.multi_agent_run_id,
                "consensus_id": hesitation.consensus_id,
                "created_at": _iso(hesitation.created_at),
            }
        )
        return await self._append("ai_hesitation_snapshots", payload)

    async def append_risk_result(self, risk: RiskResultRecord) -> int:
        return await self._append(
            "ai_multi_agent_risk_results",
            risk.model_dump(mode="json", exclude_none=True),
        )

    async def append_event(self, event: DashboardEventRecord) -> int:
        payload = event.model_dump(mode="json", exclude_none=True)
        payload["metadata_safe"] = _sanitize(payload.get("metadata_safe", {}))
        return await self._append("ai_dashboard_events", payload)

    async def append_outcome(self, outcome: DecisionOutcomeRecord) -> int:
        return await self._append(
            "ai_decision_outcomes",
            outcome.model_dump(mode="json", exclude_none=True),
        )

    async def append_performance_snapshot(self, item: AgentPerformanceSnapshot) -> int:
        return await self._append(
            "ai_agent_performance_snapshots",
            item.model_dump(mode="json", exclude_none=True),
        )

    async def list_outcome_evaluation_candidates(self, as_of: datetime):
        from btc_core.ai.multi_agent.performance import (
            EvaluationHorizon,
            MarketRegime,
            OutcomeEvaluationCandidate,
        )

        response = await self._request(
            "GET",
            "/ai_agent_attempts",
            params={
                "select": "id,multi_agent_run_id,role,provider,model,direction,ai_multi_agent_runs!inner(symbol,started_at,market_context_summary)",
                "status": "eq.SUCCESS",
                "ai_multi_agent_runs.started_at": f"lte.{_iso(as_of)}",
                "order": "created_at.asc",
            },
        )
        rows = response.json()
        if not isinstance(rows, list):
            raise SupabaseMultiAgentRepositoryError("candidate read did not return a list")
        attempt_ids = [row.get("id") for row in rows if isinstance(row, dict) and isinstance(row.get("id"), int)]
        existing: dict[int, set[EvaluationHorizon]] = {attempt_id: set() for attempt_id in attempt_ids}
        if attempt_ids:
            outcome_response = await self._request(
                "GET",
                "/ai_decision_outcomes",
                params={
                    "select": "agent_attempt_id,horizon",
                    "agent_attempt_id": f"in.({','.join(str(item) for item in attempt_ids)})",
                },
            )
            outcome_rows = outcome_response.json()
            if not isinstance(outcome_rows, list):
                raise SupabaseMultiAgentRepositoryError("outcome identity read did not return a list")
            for row in outcome_rows:
                if not isinstance(row, dict):
                    continue
                attempt_id = row.get("agent_attempt_id")
                try:
                    horizon = EvaluationHorizon(str(row.get("horizon")))
                except ValueError:
                    continue
                if isinstance(attempt_id, int) and attempt_id in existing:
                    existing[attempt_id].add(horizon)

        result = []
        horizon_order = (EvaluationHorizon.M15, EvaluationHorizon.H1, EvaluationHorizon.H4)
        for row in rows:
            if not isinstance(row, dict):
                continue
            run = row.get("ai_multi_agent_runs")
            if not isinstance(run, dict):
                continue
            context = run.get("market_context_summary")
            if not isinstance(context, dict):
                continue
            reference_price = context.get("reference_price")
            if not isinstance(reference_price, (int, float)) or reference_price <= 0:
                continue
            started_at = datetime.fromisoformat(str(run.get("started_at")).replace("Z", "+00:00"))
            if started_at > as_of:
                continue
            attempt_id = row.get("id")
            if not isinstance(attempt_id, int):
                continue
            try:
                regime = MarketRegime(str(context.get("predecision_regime", "UNKNOWN")))
                result.append(OutcomeEvaluationCandidate(
                    multi_agent_run_id=str(row["multi_agent_run_id"]),
                    agent_attempt_id=attempt_id,
                    role=AgentRole(str(row["role"])),
                    provider=AIProvider(str(row["provider"])),
                    model=str(row["model"]),
                    symbol=str(run["symbol"]),
                    direction=Direction(str(row["direction"])),
                    started_at=started_at,
                    reference_price=float(reference_price),
                    market_regime=regime,
                    existing_horizons=tuple(item for item in horizon_order if item in existing.get(attempt_id, set())),
                ))
            except (KeyError, TypeError, ValueError):
                continue
        return tuple(result)

    async def load_market_outcome_bars(self, symbol: str, timeframe: str, start: datetime, end: datetime):
        from btc_core.ai.multi_agent.performance import MarketOutcomeBar

        if end <= start:
            raise ValueError("market outcome end must be after start")
        response = await self._request(
            "GET",
            "/market_candles",
            params={
                "select": "symbol,timeframe,open_time,close_time,high,low,close",
                "symbol": f"eq.{symbol}",
                "timeframe": f"eq.{timeframe}",
                "close_time": f"gte.{_iso(start)}",
                "and": f"(close_time.lt.{_iso(end)})",
                "order": "close_time.asc",
            },
        )
        rows = response.json()
        if not isinstance(rows, list):
            raise SupabaseMultiAgentRepositoryError("market candle read did not return a list")
        return tuple(MarketOutcomeBar.model_validate(row) for row in rows if isinstance(row, dict))

    async def list_performance_evidence(self, as_of: datetime):
        from btc_core.ai.multi_agent.performance import MarketRegime, PerformanceEvidence

        response = await self._request(
            "GET",
            "/ai_decision_outcomes",
            params={
                "select": "multi_agent_run_id,agent_attempt_id,horizon,state,data_quality,matured_at,directional_hit,signed_return_pct,market_regime,ai_agent_attempts!inner(role,provider,model,direction),ai_multi_agent_runs!inner(symbol)",
                "state": "eq.EVALUATED",
                "data_quality": "eq.FULL",
                "matured_at": f"lte.{_iso(as_of)}",
                "order": "matured_at.asc",
            },
        )
        rows = response.json()
        if not isinstance(rows, list):
            raise SupabaseMultiAgentRepositoryError("performance evidence read did not return a list")
        result = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            attempt = row.get("ai_agent_attempts")
            run = row.get("ai_multi_agent_runs")
            if not isinstance(attempt, dict) or not isinstance(run, dict):
                continue
            attempt_id = row.get("agent_attempt_id")
            if not isinstance(attempt_id, int):
                continue
            try:
                matured_at = datetime.fromisoformat(str(row["matured_at"]).replace("Z", "+00:00"))
                if matured_at > as_of:
                    continue
                result.append(PerformanceEvidence(
                    multi_agent_run_id=str(row["multi_agent_run_id"]),
                    agent_attempt_id=attempt_id,
                    role=AgentRole(str(attempt["role"])),
                    provider=AIProvider(str(attempt["provider"])),
                    model=str(attempt["model"]),
                    symbol=str(run["symbol"]),
                    direction=Direction(str(attempt["direction"])),
                    market_regime=MarketRegime(str(row.get("market_regime", "UNKNOWN"))),
                    horizon=str(row["horizon"]),
                    state=OutcomeState(str(row["state"])),
                    data_quality=str(row["data_quality"]),
                    matured_at=matured_at,
                    directional_hit=row.get("directional_hit"),
                    signed_return_pct=row.get("signed_return_pct"),
                ))
            except (KeyError, TypeError, ValueError):
                continue
        return tuple(result)
