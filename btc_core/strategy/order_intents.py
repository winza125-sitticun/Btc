"""Fail-closed, deterministic dry-run order intent generation.

This module deliberately has no exchange client dependency. An intent is an
audit record for a paper-approved setup, never an instruction to submit an
order.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping
from uuid import UUID

from btc_core.risk.engine import RiskPolicy
from .risk import FullRiskContext, evaluate_full_risk, size_position

ORDER_INTENT_MODE = "DRY_RUN"
EXCHANGE_SUBMISSION_ALLOWED = False


@dataclass(frozen=True, slots=True)
class OrderIntent:
    idempotency_key: str
    analysis_id: int | None
    symbol: str
    side: str
    quantity: float
    leverage: float
    entry: tuple[float, float]
    stop_loss: float
    take_profits: tuple[float, ...]
    risk_evidence: dict[str, Any]
    mode: str = ORDER_INTENT_MODE
    exchange_submission_allowed: bool = False
    multi_agent_run_id: str | None = None

    def __post_init__(self) -> None:
        analysis_valid = type(self.analysis_id) is int and self.analysis_id > 0
        run_valid = _valid_run_id(self.multi_agent_run_id)
        if analysis_valid == run_valid:
            raise ValueError("exactly one analysis source is required")
        if self.analysis_id is not None and not analysis_valid:
            raise ValueError("analysis_id must be a positive integer")
        if self.multi_agent_run_id is not None and not run_valid:
            raise ValueError("multi_agent_run_id must be a UUID")

    @property
    def entry_min(self) -> float:
        return self.entry[0]

    @property
    def entry_max(self) -> float:
        return self.entry[1]

    @property
    def client_intent_key(self) -> str:
        return self.idempotency_key


def _get(source: Any, name: str, default: Any = None) -> Any:
    if isinstance(source, Mapping):
        return source.get(name, default)
    return getattr(source, name, default)


def _valid_run_id(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        UUID(value.strip())
    except (TypeError, ValueError, AttributeError):
        return False
    return True


def _normalize_run_id(value: Any) -> str | None:
    if value is None:
        return None
    if not _valid_run_id(value):
        raise ValueError("invalid multi_agent_run_id")
    return str(UUID(str(value).strip()))


def _mode_value(value: Any) -> str:
    raw = getattr(value, "value", value)
    return str(raw or "OFF").strip().upper()


def generate_order_intent(
    setup: Any,
    risk_context: FullRiskContext | Mapping[str, Any] | None,
    policy: RiskPolicy,
    *,
    readiness_status: str = "PAPER_READY",
    target_risk_percent: float = 0.5,
    multi_agent_mode: Any = "OFF",
) -> OrderIntent | None:
    """Return one fixed DRY_RUN intent, or ``None`` when any guard fails.

    Legacy single-provider setups remain valid in every rollout mode. A
    multi-agent setup is operationally eligible only in PRIMARY and still must
    pass the same deterministic full-risk gate as a legacy setup.
    """
    if risk_context is None:
        return None
    if not isinstance(risk_context, FullRiskContext):
        try:
            risk_context = FullRiskContext(**dict(risk_context))
        except (TypeError, ValueError):
            return None

    try:
        raw_analysis_id = _get(setup, "analysis_id")
        analysis_id = None if raw_analysis_id is None else int(raw_analysis_id)
        if analysis_id is not None and analysis_id <= 0:
            return None
        multi_agent_run_id = _normalize_run_id(_get(setup, "multi_agent_run_id"))
    except (TypeError, ValueError, OverflowError):
        return None
    if (analysis_id is None) == (multi_agent_run_id is None):
        return None
    if multi_agent_run_id is not None and _mode_value(multi_agent_mode) != "PRIMARY":
        return None

    side = str(_get(setup, "side", _get(setup, "direction", ""))).upper()
    if side not in {"LONG", "SHORT"}:
        return None
    if str(_get(setup, "precheck_status", "PASS")).upper() in {"PRECHECK_FAILED", "WAIT"}:
        return None
    if readiness_status.upper() in {"NOT_READY", "BLOCKED", "PRECHECK_FAILED"}:
        return None
    if _get(setup, "full_risk_approved", True) is not True:
        return None
    decision = evaluate_full_risk(risk_context, policy, readiness_sensitive=True)
    if not decision.approved:
        return None
    try:
        entry_min = float(_get(setup, "entry_min"))
        entry_max = float(_get(setup, "entry_max", entry_min))
        stop_loss = float(_get(setup, "stop_loss"))
        take_profits = tuple(float(x) for x in (_get(setup, "take_profits", ()) or ()))
        sized = size_position(
            risk_context,
            policy,
            (entry_min + entry_max) / 2,
            stop_loss,
            target_risk_percent=target_risk_percent,
        )
        symbol = str(_get(setup, "symbol")).strip().upper()
        if not symbol or entry_min <= 0 or entry_max < entry_min:
            return None
    except (TypeError, ValueError, OverflowError):
        return None

    source = (
        {"analysis_id": analysis_id}
        if analysis_id is not None
        else {"multi_agent_run_id": multi_agent_run_id}
    )
    canonical = {
        **source,
        "symbol": symbol,
        "side": side,
        "entry": [entry_min, entry_max],
        "stop_loss": stop_loss,
        "take_profits": list(take_profits),
        "quantity": sized.quantity,
        "leverage": risk_context.requested_leverage,
    }
    key = hashlib.sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    evidence = {
        "approved": True,
        "reasons": list(decision.reasons),
        "risk_amount": sized.risk_amount,
        "risk_percent": sized.risk_percent,
        "stop_distance": sized.stop_distance,
        "readiness_status": readiness_status,
    }
    return OrderIntent(
        key,
        analysis_id,
        symbol,
        side,
        sized.quantity,
        risk_context.requested_leverage,
        (entry_min, entry_max),
        stop_loss,
        take_profits,
        evidence,
        multi_agent_run_id=multi_agent_run_id,
    )


create_order_intent = generate_order_intent
