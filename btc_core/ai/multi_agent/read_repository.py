from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from btc_core.ai.models import AIProvider, Direction
from btc_core.ai.multi_agent.models import AgentRole
from btc_core.ai.multi_agent.performance import EvaluationHorizon, summarize_performance
from btc_core.ai.multi_agent.repository import SupabaseMultiAgentRepository, SupabaseMultiAgentRepositoryError


_RUN_SELECT = (
    "id,scanner_candidate_id,scanner_run_id,symbol,timeframe,started_at,completed_at,status,"
    "snapshot_ref,snapshot_observed_at,config_version,enabled_role_count,valid_role_count,"
    "rollout_mode,market_context_summary,legacy_analysis_ref"
)
_ATTEMPT_SELECT = (
    "id,multi_agent_run_id,role,provider,model,prompt_version,prompt_digest,status,direction,confidence,"
    "entry_min,entry_max,stop_loss,take_profits,risk_reward,reason_summary,latency_ms,error_code,"
    "snapshot_ref,created_at"
)
_CONSENSUS_SELECT = (
    "id,multi_agent_run_id,direction,consensus_confidence,winning_agreement,coverage,signed_score,"
    "actionable,supporting_roles,opposing_roles,reason_codes,role_contributions,config_version,"
    "consensus_algorithm_version,created_at"
)
_HESITATION_SELECT = (
    "id,multi_agent_run_id,consensus_id,total,disagreement,confidence_dispersion,timeframe_conflict,"
    "market_uncertainty,disagreement_contribution,confidence_dispersion_contribution,"
    "timeframe_conflict_contribution,market_uncertainty_contribution,hesitation_algorithm_version,created_at"
)
_RISK_SELECT = "id,multi_agent_run_id,consensus_id,status,approved,reason_codes,risk_policy_version,created_at"


class MultiAgentReadRepository(SupabaseMultiAgentRepository):
    """Anon-safe persisted read surface for the multi-agent dashboard.

    The base repository owns transport and immutable evidence writes.  This
    subclass is used by the public API with SUPABASE_ANON_KEY only and queries
    only columns explicitly granted to anon/authenticated roles.
    """

    async def _rows(self, path: str, params: dict[str, str]) -> list[dict[str, Any]]:
        response = await self._request("GET", path, params=params)
        rows = response.json()
        if not isinstance(rows, list):
            raise SupabaseMultiAgentRepositoryError(f"{path} read did not return a list")
        return [row for row in rows if isinstance(row, dict)]

    async def _run_row(self, run_id: str) -> dict[str, Any] | None:
        rows = await self._rows(
            "/ai_multi_agent_runs",
            {"select": _RUN_SELECT, "id": f"eq.{run_id}", "limit": "1"},
        )
        return rows[0] if rows else None

    async def _attempts(self, run_id: str) -> list[dict[str, Any]]:
        return await self._rows(
            "/ai_agent_attempts",
            {
                "select": _ATTEMPT_SELECT,
                "multi_agent_run_id": f"eq.{run_id}",
                "order": "id.asc",
            },
        )

    async def _consensus(self, run_id: str) -> dict[str, Any] | None:
        rows = await self._rows(
            "/ai_consensus_decisions",
            {
                "select": _CONSENSUS_SELECT,
                "multi_agent_run_id": f"eq.{run_id}",
                "order": "id.desc",
                "limit": "1",
            },
        )
        return rows[0] if rows else None

    async def _hesitation(self, run_id: str) -> dict[str, Any] | None:
        rows = await self._rows(
            "/ai_hesitation_snapshots",
            {
                "select": _HESITATION_SELECT,
                "multi_agent_run_id": f"eq.{run_id}",
                "order": "id.desc",
                "limit": "1",
            },
        )
        return rows[0] if rows else None

    async def _risk(self, run_id: str) -> dict[str, Any] | None:
        rows = await self._rows(
            "/ai_multi_agent_risk_results",
            {
                "select": _RISK_SELECT,
                "multi_agent_run_id": f"eq.{run_id}",
                "order": "id.desc",
                "limit": "1",
            },
        )
        return rows[0] if rows else None

    @staticmethod
    def _public_attempt(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": row["id"],
            "role": row["role"],
            "provider": row["provider"],
            "model": row["model"],
            "prompt_version": row["prompt_version"],
            "prompt_digest": row["prompt_digest"],
            "status": row["status"],
            "direction": row.get("direction"),
            "confidence": row.get("confidence"),
            "entry_min": row.get("entry_min"),
            "entry_max": row.get("entry_max"),
            "stop_loss": row.get("stop_loss"),
            "take_profits": row.get("take_profits") or [],
            "risk_reward": row.get("risk_reward"),
            "reason_summary": row.get("reason_summary"),
            "latency_ms": int(row.get("latency_ms") or 0),
            "error_code": row.get("error_code"),
            # Raw provider error messages are deliberately not granted to anon.
            "error_message": None,
            "snapshot_ref": row["snapshot_ref"],
            "created_at": row["created_at"],
        }

    @staticmethod
    def _public_hesitation(row: dict[str, Any] | None) -> dict[str, Any]:
        if row is None:
            return {
                "total": 0.0,
                "disagreement": 0.0,
                "confidence_dispersion": 0.0,
                "timeframe_conflict": 0.0,
                "market_uncertainty": 0.0,
                "disagreement_contribution": 0.0,
                "confidence_dispersion_contribution": 0.0,
                "timeframe_conflict_contribution": 0.0,
                "market_uncertainty_contribution": 0.0,
                "algorithm_version": "hesitation-v1",
            }
        return {
            "total": row["total"],
            "disagreement": row["disagreement"],
            "confidence_dispersion": row["confidence_dispersion"],
            "timeframe_conflict": row["timeframe_conflict"],
            "market_uncertainty": row["market_uncertainty"],
            "disagreement_contribution": row["disagreement_contribution"],
            "confidence_dispersion_contribution": row["confidence_dispersion_contribution"],
            "timeframe_conflict_contribution": row["timeframe_conflict_contribution"],
            "market_uncertainty_contribution": row["market_uncertainty_contribution"],
            "algorithm_version": row["hesitation_algorithm_version"],
        }

    @staticmethod
    def _public_risk(row: dict[str, Any] | None) -> dict[str, Any] | None:
        if row is None:
            return None
        return {
            "status": row["status"],
            "approved": bool(row["approved"]),
            "reason_codes": row.get("reason_codes") or [],
            "risk_policy_version": row["risk_policy_version"],
            "created_at": row["created_at"],
        }

    @staticmethod
    def _public_vortex(
        run: dict[str, Any],
        consensus: dict[str, Any] | None,
        hesitation: dict[str, Any] | None,
    ) -> dict[str, Any]:
        context = run.get("market_context_summary") or {}
        if not isinstance(context, dict):
            context = {}
        return {
            "trend_strength": float(context.get("trend_strength", 0.0)),
            "volatility": float(context.get("volatility", 0.0)),
            "momentum": float(context.get("momentum", 0.0)),
            "order_flow_imbalance": float(context.get("order_flow_imbalance", 0.0)),
            "liquidity": float(context.get("liquidity", 0.0)),
            "consensus_direction": (
                consensus.get("direction") if consensus is not None else context.get("consensus_direction") or "WAIT"
            ),
            "winning_agreement": float(
                consensus.get("winning_agreement", 0.0) if consensus is not None else context.get("winning_agreement") or 0.0
            ),
            "hesitation_total": float(
                hesitation.get("total", 0.0) if hesitation is not None else context.get("hesitation_total") or 0.0
            ),
            "observed_at": context.get("observed_at") or run["snapshot_observed_at"],
            "snapshot_ref": context.get("snapshot_ref") or run["snapshot_ref"],
            "mapping_version": context.get("mapping_version") or "vortex-input-v1",
        }

    @staticmethod
    def _public_consensus(
        row: dict[str, Any] | None,
        hesitation: dict[str, Any] | None,
        attempts: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        if row is None:
            return None
        attempt_by_role = {str(item.get("role")): item.get("id") for item in attempts}
        contributions = []
        for item in row.get("role_contributions") or []:
            if not isinstance(item, dict):
                continue
            contribution = {
                "role": item.get("role"),
                "provider": item.get("provider", ""),
                "model": item.get("model", ""),
                "direction": item.get("direction"),
                "confidence": item.get("confidence"),
                "base_weight": item.get("base_weight", 1.0),
                "historical_multiplier": item.get("historical_multiplier", 1.0),
                "effective_weight": item.get("effective_weight", 0.0),
                "unsigned_strength": item.get("unsigned_strength", 0.0),
                "signed_contribution": item.get("signed_contribution", 0.0),
                "participated": bool(item.get("participated", False)),
                "attempt_id": attempt_by_role.get(str(item.get("role"))),
            }
            contributions.append(contribution)
        return {
            "id": row["id"],
            "direction": row["direction"],
            "consensus_confidence": row["consensus_confidence"],
            "winning_agreement": row["winning_agreement"],
            "coverage": row["coverage"],
            "signed_score": row["signed_score"],
            "actionable": bool(row["actionable"]),
            "supporting_roles": row.get("supporting_roles") or [],
            "opposing_roles": row.get("opposing_roles") or [],
            "reason_codes": row.get("reason_codes") or [],
            "role_contributions": contributions,
            "config_version": row["config_version"],
            "algorithm_version": row["consensus_algorithm_version"],
            "hesitation": MultiAgentReadRepository._public_hesitation(hesitation),
            "created_at": row["created_at"],
        }

    async def _hydrate_run(self, run: dict[str, Any], *, include_attempts: bool) -> dict[str, Any]:
        run_id = str(run["id"])
        attempts = await self._attempts(run_id)
        consensus = await self._consensus(run_id)
        hesitation = await self._hesitation(run_id)
        risk = await self._risk(run_id)
        payload = {
            "record_type": "MULTI_AGENT",
            "id": run_id,
            "scanner_candidate_id": run["scanner_candidate_id"],
            "symbol": run["symbol"],
            "timeframe": run["timeframe"],
            "started_at": run["started_at"],
            "completed_at": run.get("completed_at"),
            "status": run["status"],
            "config_version": run["config_version"],
            "enabled_role_count": run["enabled_role_count"],
            "valid_role_count": run["valid_role_count"],
            "rollout_mode": run["rollout_mode"],
            "vortex_inputs": self._public_vortex(run, consensus, hesitation),
            "consensus": self._public_consensus(consensus, hesitation, attempts),
            "risk": self._public_risk(risk),
        }
        if include_attempts:
            payload["attempts"] = [self._public_attempt(item) for item in attempts]
        return payload

    async def latest_runs(self, *, timeframe: str, limit: int) -> list[dict[str, Any]]:
        if not 1 <= limit <= 50:
            raise ValueError("limit must be between 1 and 50")
        rows = await self._rows(
            "/ai_multi_agent_runs",
            {
                "select": _RUN_SELECT,
                "timeframe": f"eq.{timeframe.strip()}",
                "order": "started_at.desc",
                "limit": str(limit),
            },
        )
        return [await self._hydrate_run(row, include_attempts=False) for row in rows]

    async def run_detail(self, run_id: str) -> dict[str, Any] | None:
        row = await self._run_row(run_id)
        return None if row is None else await self._hydrate_run(row, include_attempts=True)

    async def dashboard_events(self, *, run_id: str, limit: int) -> list[dict[str, Any]]:
        if not 1 <= limit <= 500:
            raise ValueError("limit must be between 1 and 500")
        multi = await self._rows(
            "/ai_dashboard_events",
            {
                "select": "id,multi_agent_run_id,sequence,event_type,role,status,message,metadata_safe,created_at",
                "multi_agent_run_id": f"eq.{run_id}",
                "order": "created_at.asc,id.asc",
                "limit": str(limit),
            },
        )
        intents = await self._rows(
            "/market_order_intents",
            {
                "select": "id,simulation_trade_id,multi_agent_run_id,mode,symbol,side,validation_status,exchange_submission_allowed,created_at,updated_at",
                "multi_agent_run_id": f"eq.{run_id}",
                "order": "created_at.asc,id.asc",
                "limit": str(limit),
            },
        )
        trades = await self._rows(
            "/market_simulation_trades",
            {
                "select": "id,multi_agent_run_id,symbol,side,status,opened_at,closed_at,created_at,updated_at",
                "multi_agent_run_id": f"eq.{run_id}",
                "order": "created_at.asc,id.asc",
                "limit": str(limit),
            },
        )
        events: list[dict[str, Any]] = []
        for row in multi:
            events.append({
                "id": row["id"], "run_id": run_id, "source": "MULTI_AGENT",
                "event_type": row["event_type"], "role": row.get("role"), "status": row["status"],
                "message": row["message"], "metadata_safe": row.get("metadata_safe") or {},
                "created_at": row["created_at"],
            })
        for row in intents:
            events.append({
                "id": row["id"], "run_id": run_id, "source": "ORDER_INTENT",
                "event_type": "ORDER_INTENT", "role": None, "status": row["validation_status"],
                "message": f"Dry-run order intent {row['validation_status']}",
                "metadata_safe": {
                    "simulation_trade_id": row.get("simulation_trade_id"), "mode": row.get("mode"),
                    "symbol": row.get("symbol"), "side": row.get("side"),
                    "exchange_submission_allowed": row.get("exchange_submission_allowed", False),
                },
                "created_at": row["created_at"],
            })
        for row in trades:
            events.append({
                "id": row["id"], "run_id": run_id, "source": "SIMULATION",
                "event_type": "SIMULATION_TRADE", "role": None, "status": row["status"],
                "message": f"Simulation trade {row['status']}",
                "metadata_safe": {
                    "symbol": row.get("symbol"), "side": row.get("side"),
                    "opened_at": row.get("opened_at"), "closed_at": row.get("closed_at"),
                },
                "created_at": row["created_at"],
            })
        priority = {"MULTI_AGENT": 0, "ORDER_INTENT": 1, "SIMULATION": 2}
        events.sort(key=lambda item: (str(item["created_at"]), priority[item["source"]], int(item["id"])))
        return events[:limit]

    async def performance_summaries(
        self,
        *,
        role: str | None,
        symbol: str | None,
        horizon: str | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        role_filter = AgentRole(role) if role else None
        horizon_filter = EvaluationHorizon(horizon) if horizon else None
        symbol_filter = symbol.strip().upper() if symbol else None
        as_of = datetime.now(timezone.utc)
        rows = await self.list_performance_evidence(as_of)
        filtered = [
            item for item in rows
            if (role_filter is None or item.role is role_filter)
            and (symbol_filter is None or item.symbol == symbol_filter)
            and (horizon_filter is None or item.horizon is horizon_filter)
        ]
        keys = sorted(
            {(item.role, item.provider, item.model, item.horizon) for item in filtered},
            key=lambda item: (item[0].value, item[1].value, item[2], item[3].value),
        )
        result: list[dict[str, Any]] = []
        for item_role, provider, model, item_horizon in keys[:limit]:
            summary = summarize_performance(
                rows,
                as_of=as_of,
                role=item_role,
                provider=provider,
                model=model,
                symbol=symbol_filter,
                horizon=item_horizon,
            )
            if summary.sample_count == 0 or summary.hit_rate is None or summary.mean_signed_return_pct is None or summary.normalized_expectancy is None:
                continue
            result.append({
                "role": item_role.value,
                "provider": provider.value,
                "model": model,
                "symbol": symbol_filter,
                "direction": None,
                "market_regime": None,
                "horizon": item_horizon.value,
                "sample_count": summary.sample_count,
                "hit_rate": summary.hit_rate,
                "mean_signed_return_pct": summary.mean_signed_return_pct,
                "normalized_expectancy": summary.normalized_expectancy,
                "quality_score": summary.quality_score,
                "multiplier": summary.multiplier,
                "as_of": as_of.isoformat(),
                "algorithm_version": "performance-v1",
            })
        return result
