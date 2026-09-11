"""Material, deduplicated strategy alert contracts (simulation-only)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Mapping
from uuid import uuid4


class AlertType(StrEnum):
    TRADE_SETUP_READY = "TRADE_SETUP_READY"
    STRUCTURE_CHANGE = "STRUCTURE_CHANGE"
    HIGH_IMPACT_NEWS = "HIGH_IMPACT_NEWS"
    RISK_BLOCK = "RISK_BLOCK"
    PROVIDER_DEGRADED = "PROVIDER_DEGRADED"
    READINESS_CHANGED = "READINESS_CHANGED"


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class AlertEvent:
    alert_type: AlertType
    dedupe_key: str
    title: str
    short_summary: str
    severity: str = "INFO"
    payload: dict[str, Any] = field(default_factory=dict)
    first_observed_at: datetime = field(default_factory=_now)
    last_observed_at: datetime = field(default_factory=_now)
    id: str = field(default_factory=lambda: str(uuid4()))
    status: str = "NEW"
    delivery_state: dict[str, Any] = field(default_factory=dict)


class AlertEngine:
    """In-memory derivation engine; repositories provide durable persistence."""

    def __init__(self) -> None:
        self.events: list[AlertEvent] = []

    def observe(self, *, alert_type: AlertType | str, dedupe_key: str, title: str,
                short_summary: str, severity: str = "INFO",
                payload: Mapping[str, Any] | None = None,
                now: datetime | None = None) -> AlertEvent:
        kind = AlertType(alert_type)
        observed = now or _now()
        existing = next((item for item in self.events if item.dedupe_key == dedupe_key and item.status in {"NEW", "ACKNOWLEDGED"}), None)
        if existing:
            existing.last_observed_at = observed
            return existing
        # Alert payloads are intentionally data-only; credentials never belong here.
        def clean(value: Any) -> Any:
            if isinstance(value, dict):
                blocked = ("token", "secret", "key", "password", "authorization", "credential", "api_key", "apikey", "auth", "oauth", "auth_header")
                return {str(k): clean(v) for k, v in value.items() if not any(word in str(k).lower() for word in blocked)}
            if isinstance(value, list):
                return [clean(item) for item in value]
            return value
        safe_payload = clean(dict(payload or {}))
        event = AlertEvent(kind, dedupe_key, title, short_summary, severity, safe_payload, observed, observed)
        self.events.append(event)
        return event
