"""Fail-closed, deterministic dry-run order intent generation.

This module deliberately has no exchange client dependency.  An intent is an
audit record for a paper-approved setup, never an instruction to submit an
order.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping

from btc_core.risk.engine import RiskPolicy
from .risk import FullRiskContext, evaluate_full_risk, size_position

ORDER_INTENT_MODE = "DRY_RUN"
EXCHANGE_SUBMISSION_ALLOWED = False


@dataclass(frozen=True, slots=True)
class OrderIntent:
    idempotency_key: str
    analysis_id: int
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


def generate_order_intent(
    setup: Any,
    risk_context: FullRiskContext | Mapping[str, Any] | None,
    policy: RiskPolicy,
    *,
    readiness_status: str = "PAPER_READY",
    target_risk_percent: float = 0.5,
) -> OrderIntent | None:
    """Return one fixed DRY_RUN intent, or ``None`` when any guard fails."""
    if risk_context is None:
        return None
    if not isinstance(risk_context, FullRiskContext):
        try:
            risk_context = FullRiskContext(**dict(risk_context))
        except (TypeError, ValueError):
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
        sized = size_position(risk_context, policy, (entry_min + entry_max) / 2, stop_loss,
                              target_risk_percent=target_risk_percent)
        analysis_id = int(_get(setup, "analysis_id"))
        symbol = str(_get(setup, "symbol")).strip().upper()
        if analysis_id <= 0 or not symbol or entry_min <= 0 or entry_max < entry_min:
            return None
    except (TypeError, ValueError, OverflowError):
        return None
    canonical = {"analysis_id": analysis_id, "symbol": symbol, "side": side,
                 "entry": [entry_min, entry_max], "stop_loss": stop_loss,
                 "take_profits": list(take_profits), "quantity": sized.quantity,
                 "leverage": risk_context.requested_leverage}
    key = hashlib.sha256(json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    evidence = {"approved": True, "reasons": list(decision.reasons),
                "risk_amount": sized.risk_amount, "risk_percent": sized.risk_percent,
                "stop_distance": sized.stop_distance, "readiness_status": readiness_status}
    return OrderIntent(key, analysis_id, symbol, side, sized.quantity,
                       risk_context.requested_leverage, (entry_min, entry_max), stop_loss,
                       take_profits, evidence)


create_order_intent = generate_order_intent
