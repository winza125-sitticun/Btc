"""Deterministic PRIMARY multi-agent -> dry-run intent -> paper-trade runtime.

This module has no exchange client dependency. It consumes persisted evidence,
completes the deterministic account/event risk check, and writes only DRY_RUN
intent and simulation records.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from math import isfinite
from typing import Any, Mapping

from btc_core.risk.engine import RiskPolicy

from .order_intents import generate_order_intent
from .risk import FullRiskContext, evaluate_full_risk

_ROLE_PRIORITY = {
    "TECHNICAL": 0,
    "MOMENTUM": 1,
    "ORDER_FLOW": 2,
    "NEWS": 3,
    "CONTRARIAN": 4,
    "RISK_REVIEW": 5,
}
_TERMINAL_RUN_STATUSES = "COMPLETED,PARTIAL"
_PENDING_CONTEXT_REASON = "FULL_RISK_CONTEXT_PENDING"
_DEFAULT_PAPER_LEVERAGE = 1.0
_DEFAULT_TARGET_RISK_PERCENT = 0.5
_DEFAULT_ENTRY_VALIDITY_MINUTES = 60
_FLOAT_TOLERANCE = 1e-9


def _float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if isfinite(result) else None


def _positive(value: Any) -> float | None:
    result = _float(value)
    return result if result is not None and result > 0 else None


def _close(left: Any, right: Any) -> bool:
    a = _float(left)
    b = _float(right)
    return a is not None and b is not None and abs(a - b) <= _FLOAT_TOLERANCE


def _valid_geometry(attempt: Mapping[str, Any], side: str) -> dict[str, Any] | None:
    entry_min = _positive(attempt.get("entry_min"))
    entry_max = _positive(attempt.get("entry_max"))
    stop_loss = _positive(attempt.get("stop_loss"))
    risk_reward = _positive(attempt.get("risk_reward"))
    raw_tps = attempt.get("take_profits") or []
    if not isinstance(raw_tps, (list, tuple)):
        return None
    take_profits = tuple(_positive(value) for value in raw_tps)
    if (
        entry_min is None
        or entry_max is None
        or entry_max < entry_min
        or stop_loss is None
        or risk_reward is None
        or not take_profits
        or any(value is None for value in take_profits)
    ):
        return None
    typed_tps = tuple(float(value) for value in take_profits if value is not None)
    if side == "LONG":
        if stop_loss >= entry_min or any(tp <= entry_max for tp in typed_tps):
            return None
    elif side == "SHORT":
        if stop_loss <= entry_max or any(tp >= entry_min for tp in typed_tps):
            return None
    else:
        return None
    return {
        "entry_min": entry_min,
        "entry_max": entry_max,
        "stop_loss": stop_loss,
        "take_profits": typed_tps,
        "risk_reward": risk_reward,
    }


def select_multi_agent_geometry(
    consensus: Mapping[str, Any], attempts: list[dict[str, Any]]
) -> dict[str, Any] | None:
    """Pick one reproducible geometry source from persisted successful attempts."""
    side = str(consensus.get("direction") or "").strip().upper()
    if consensus.get("actionable") is not True or side not in {"LONG", "SHORT"}:
        return None

    contributions = consensus.get("role_contributions") or []
    if not isinstance(contributions, list):
        return None
    weights: dict[str, float] = {}
    for item in contributions:
        if not isinstance(item, Mapping) or item.get("participated") is not True:
            continue
        role = str(item.get("role") or "").strip().upper()
        weight = _float(item.get("effective_weight"))
        if role in _ROLE_PRIORITY and weight is not None and weight >= 0:
            weights[role] = weight

    eligible: list[tuple[float, int, dict[str, Any]]] = []
    for attempt in attempts:
        role = str(attempt.get("role") or "").strip().upper()
        if (
            role not in weights
            or str(attempt.get("status") or "").strip().upper() != "SUCCESS"
            or str(attempt.get("direction") or "").strip().upper() != side
        ):
            continue
        geometry = _valid_geometry(attempt, side)
        if geometry is None:
            continue
        eligible.append((
            -weights[role],
            _ROLE_PRIORITY[role],
            {
                **geometry,
                "selected_role": role,
                "selected_attempt_id": attempt.get("id"),
                "effective_weight": weights[role],
            },
        ))
    if not eligible:
        return None
    eligible.sort(key=lambda item: (item[0], item[1]))
    return eligible[0][2]


async def _rows(repository: Any, path: str, params: dict[str, str]) -> list[dict[str, Any]]:
    response = await repository._request("GET", path, params=params)
    payload = response.json()
    return payload if isinstance(payload, list) else []


async def _latest(repository: Any, path: str, params: dict[str, str]) -> dict[str, Any] | None:
    rows = await _rows(repository, path, {**params, "limit": "1"})
    return rows[0] if rows else None


def _parse_time(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _full_risk_reason(reason: str) -> str:
    return f"FULL_RISK_{reason.upper()}"


def _recoverable_existing_intent(
    existing: Mapping[str, Any],
    *,
    current_intent: Any,
    geometry: Mapping[str, Any],
    symbol: str,
    side: str,
) -> dict[str, Any] | None:
    """Return immutable persisted execution values when an orphan intent is safe to recover."""
    if (
        str(existing.get("mode") or "").strip().upper() != "DRY_RUN"
        or existing.get("exchange_submission_allowed") is not False
        or str(existing.get("validation_status") or "").strip().upper() != "VALID"
        or str(existing.get("symbol") or "").strip().upper() != symbol
        or str(existing.get("side") or "").strip().upper() != side
    ):
        return None
    idempotency_key = str(existing.get("idempotency_key") or "").strip()
    quantity = _positive(existing.get("quantity"))
    leverage = _positive(existing.get("leverage"))
    if (
        not idempotency_key
        or quantity is None
        or leverage is None
        or quantity - current_intent.quantity > _FLOAT_TOLERANCE
        or leverage - current_intent.leverage > _FLOAT_TOLERANCE
    ):
        return None

    expected_mid = (float(geometry["entry_min"]) + float(geometry["entry_max"])) / 2
    raw_tps = existing.get("take_profit_instructions") or []
    if not isinstance(raw_tps, list) or len(raw_tps) != len(geometry["take_profits"]):
        return None
    if (
        not _close(existing.get("entry_price"), expected_mid)
        or not _close(existing.get("stop_loss"), geometry["stop_loss"])
        or any(not _close(actual, expected) for actual, expected in zip(raw_tps, geometry["take_profits"]))
    ):
        return None

    evidence = existing.get("risk_decision_snapshot")
    if not isinstance(evidence, Mapping) or evidence.get("approved") is not True:
        return None
    if (
        str(evidence.get("geometry_role") or "").strip().upper() != geometry["selected_role"]
        or evidence.get("geometry_attempt_id") != geometry["selected_attempt_id"]
    ):
        return None
    risk_amount = abs(expected_mid - float(geometry["stop_loss"])) * quantity
    if risk_amount <= 0:
        return None
    return {
        "idempotency_key": idempotency_key,
        "quantity": quantity,
        "leverage": leverage,
        "risk_amount": risk_amount,
    }


async def _append_resolved_risk(
    repository: Any,
    *,
    run_id: str,
    consensus_id: int,
    policy_version: str,
    approved: bool,
    reasons: tuple[str, ...],
) -> None:
    payload = {
        "multi_agent_run_id": run_id,
        "consensus_id": consensus_id,
        "status": "APPROVED" if approved else "REJECTED",
        "approved": approved,
        "reason_codes": [] if approved else [_full_risk_reason(reason) for reason in reasons],
        "risk_policy_version": policy_version,
    }
    await repository._request(
        "POST",
        "/ai_multi_agent_risk_results",
        headers={"Prefer": "return=representation"},
        json=payload,
    )


async def _process_run(repository: Any, run: dict[str, Any]) -> dict[str, Any] | None:
    run_id = str(run.get("id") or "").strip()
    if not run_id:
        return None
    if (
        str(run.get("rollout_mode") or "").strip().upper() != "PRIMARY"
        or str(run.get("status") or "").strip().upper() not in {"COMPLETED", "PARTIAL"}
    ):
        return None

    existing = await _latest(
        repository,
        "/market_order_intents",
        {
            "select": "id,idempotency_key,simulation_trade_id,multi_agent_run_id,symbol,side,quantity,leverage,entry_price,stop_loss,take_profit_instructions,risk_decision_snapshot,validation_status,mode,exchange_submission_allowed",
            "multi_agent_run_id": f"eq.{run_id}",
        },
    )
    if existing is not None and existing.get("simulation_trade_id") is not None:
        return None

    risk = await _latest(
        repository,
        "/ai_multi_agent_risk_results",
        {
            "select": "id,multi_agent_run_id,consensus_id,status,approved,reason_codes,risk_policy_version",
            "multi_agent_run_id": f"eq.{run_id}",
            "order": "id.desc",
        },
    )
    if risk is None or str(risk.get("status") or "") == "REJECTED":
        return None
    if str(risk.get("status") or "") == "PENDING":
        reasons = tuple(str(item) for item in (risk.get("reason_codes") or []))
        if reasons != (_PENDING_CONTEXT_REASON,):
            return None
    elif str(risk.get("status") or "") != "APPROVED" or risk.get("approved") is not True:
        return None

    consensus = await _latest(
        repository,
        "/ai_consensus_decisions",
        {
            "select": "id,multi_agent_run_id,direction,consensus_confidence,actionable,role_contributions",
            "multi_agent_run_id": f"eq.{run_id}",
            "order": "id.desc",
        },
    )
    if consensus is None:
        return None
    side = str(consensus.get("direction") or "").strip().upper()
    if consensus.get("actionable") is not True or side not in {"LONG", "SHORT"}:
        return None

    attempts = await _rows(
        repository,
        "/ai_agent_attempts",
        {
            "select": "id,role,status,direction,confidence,entry_min,entry_max,stop_loss,take_profits,risk_reward",
            "multi_agent_run_id": f"eq.{run_id}",
            "order": "id.asc",
            "limit": "6",
        },
    )
    geometry = select_multi_agent_geometry(consensus, attempts)
    if geometry is None:
        return None

    candidate_id = run.get("scanner_candidate_id")
    candidate = await _latest(
        repository,
        "/market_scanner_candidates",
        {"select": "id,opportunity_score", "id": f"eq.{candidate_id}"},
    )
    opportunity_score = _float(candidate.get("opportunity_score")) if candidate else None
    consensus_confidence = _float(consensus.get("consensus_confidence"))
    if opportunity_score is None or consensus_confidence is None:
        return None

    account = await _latest(
        repository,
        "/market_simulation_accounts",
        {
            "select": "id,name,starting_balance,balance,equity,daily_realized_loss",
            "name": "eq.Production Canary",
        },
    )
    if account is None or account.get("name") != "Production Canary":
        return None
    starting_balance = _positive(account.get("starting_balance"))
    balance = _positive(account.get("balance"))
    equity = _positive(account.get("equity"))
    daily_loss = _float(account.get("daily_realized_loss"))
    if starting_balance is None or balance is None or equity is None or daily_loss is None:
        return None

    active_trades = await _rows(
        repository,
        "/market_simulation_trades",
        {
            "select": "id,status",
            "account_id": f"eq.{account['id']}",
            "status": "in.(PENDING_ENTRY,OPEN)",
            "limit": "100",
        },
    )
    active_events = await _rows(
        repository,
        "/market_alert_events",
        {
            "select": "id,symbol,alert_type,status",
            "alert_type": "eq.HIGH_IMPACT_NEWS",
            "status": "in.(NEW,ACKNOWLEDGED)",
            "limit": "100",
        },
    )
    symbol = str(run.get("symbol") or "").strip().upper()
    event_blocked = any(
        not str(item.get("symbol") or "").strip()
        or str(item.get("symbol") or "").strip().upper() == symbol
        for item in active_events
    )
    readiness = await _latest(
        repository,
        "/market_readiness_checks",
        {"select": "overall_status", "order": "created_at.desc"},
    )
    if readiness is None:
        return None
    readiness_status = str(readiness.get("overall_status") or "NOT_READY").strip().upper()

    context = FullRiskContext(
        confidence=consensus_confidence,
        opportunity_score=opportunity_score,
        risk_reward=float(geometry["risk_reward"]),
        requested_leverage=_DEFAULT_PAPER_LEVERAGE,
        daily_realized_loss_percent=max(0.0, daily_loss) / starting_balance * 100,
        open_positions=len(active_trades),
        event_blocked=event_blocked,
        balance=balance,
        equity=equity,
    )
    policy = RiskPolicy()
    current_risk = evaluate_full_risk(context, policy, readiness_sensitive=True)
    risk_status = str(risk.get("status") or "")
    if risk_status == "PENDING" or (risk_status == "APPROVED" and not current_risk.approved):
        await _append_resolved_risk(
            repository,
            run_id=run_id,
            consensus_id=int(consensus["id"]),
            policy_version=str(risk.get("risk_policy_version") or "multi-agent-risk-v1"),
            approved=current_risk.approved,
            reasons=current_risk.reasons,
        )
    if not current_risk.approved:
        return None

    setup = {
        "analysis_id": None,
        "multi_agent_run_id": run_id,
        "symbol": symbol,
        "side": side,
        "entry_min": geometry["entry_min"],
        "entry_max": geometry["entry_max"],
        "stop_loss": geometry["stop_loss"],
        "take_profits": geometry["take_profits"],
        "full_risk_approved": True,
        "geometry_role": geometry["selected_role"],
        "geometry_attempt_id": geometry["selected_attempt_id"],
        "geometry_effective_weight": geometry["effective_weight"],
        "consensus_confidence": consensus_confidence,
        "opportunity_score": opportunity_score,
    }
    current_intent = generate_order_intent(
        setup,
        context,
        policy,
        readiness_status=readiness_status,
        target_risk_percent=_DEFAULT_TARGET_RISK_PERCENT,
        multi_agent_mode="PRIMARY",
    )
    if current_intent is None:
        return None

    signal_created_at = _parse_time(run.get("completed_at")) or _parse_time(run.get("started_at"))
    if signal_created_at is None:
        return None

    if existing is None:
        await repository.upsert_order_intent(current_intent)
        execution = {
            "idempotency_key": current_intent.idempotency_key,
            "quantity": current_intent.quantity,
            "leverage": current_intent.leverage,
            "risk_amount": current_intent.risk_evidence["risk_amount"],
        }
    else:
        execution = _recoverable_existing_intent(
            existing,
            current_intent=current_intent,
            geometry=geometry,
            symbol=symbol,
            side=side,
        )
        if execution is None:
            return None

    trade = await repository.create_pending_trade(
        account_id=str(account["id"]),
        account_name="Production Canary",
        idempotency_key=execution["idempotency_key"],
        trade={
            "ai_analysis_id": None,
            "multi_agent_run_id": run_id,
            "scanner_candidate_id": candidate_id,
            "symbol": symbol,
            "side": side,
            "planned_entry_min": geometry["entry_min"],
            "planned_entry_max": geometry["entry_max"],
            "quantity": execution["quantity"],
            "leverage": execution["leverage"],
            "risk_amount": execution["risk_amount"],
            "stop_loss": geometry["stop_loss"],
            "take_profits": list(geometry["take_profits"]),
            "expires_at": (signal_created_at + timedelta(minutes=_DEFAULT_ENTRY_VALIDITY_MINUTES)).isoformat(),
            "full_risk_approved": True,
            "full_risk_reasons": [],
        },
    )
    trade_id = trade.get("id") if isinstance(trade, Mapping) else None
    if type(trade_id) is int and trade_id > 0:
        await repository._request(
            "PATCH",
            "/market_order_intents",
            params={"idempotency_key": f"eq.{execution['idempotency_key']}"},
            headers={"Prefer": "return=minimal"},
            json={"simulation_trade_id": trade_id},
        )
    return {
        "multi_agent_run_id": run_id,
        "selected_role": geometry["selected_role"],
        "simulation_trade_id": trade_id,
        "idempotency_key": execution["idempotency_key"],
    }


async def create_multi_agent_order_intents(
    repository: Any, multi_agent_mode: Any = "OFF"
) -> list[dict[str, Any]]:
    """Create bounded, fail-closed PRIMARY dry-run artifacts from persisted evidence."""
    mode = str(getattr(multi_agent_mode, "value", multi_agent_mode) or "OFF").strip().upper()
    if mode != "PRIMARY":
        return []
    runs = await _rows(
        repository,
        "/ai_multi_agent_runs",
        {
            "select": "id,scanner_candidate_id,symbol,timeframe,started_at,completed_at,status,rollout_mode",
            "rollout_mode": "eq.PRIMARY",
            "status": f"in.({_TERMINAL_RUN_STATUSES})",
            "order": "completed_at.asc",
            "limit": "25",
        },
    )
    created: list[dict[str, Any]] = []
    for run in runs:
        result = await _process_run(repository, run)
        if result is not None:
            created.append(result)
    return created
