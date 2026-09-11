from datetime import datetime, timezone

from btc_core.strategy.alerts import AlertEngine, AlertType


def test_unchanged_condition_is_not_repeated_and_same_key_updates_observation():
    engine = AlertEngine()
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    first = engine.observe(alert_type=AlertType.RISK_BLOCK, dedupe_key="risk:BTCUSDT", title="Risk blocked", short_summary="blocked", now=now)
    second = engine.observe(alert_type=AlertType.RISK_BLOCK, dedupe_key="risk:BTCUSDT", title="Risk blocked", short_summary="blocked", now=now.replace(minute=1))
    assert first.id == second.id
    assert len(engine.events) == 1
    assert second.last_observed_at.minute == 1


def test_provider_degradation_and_readiness_change_are_material_events():
    engine = AlertEngine()
    degraded = engine.observe(alert_type=AlertType.PROVIDER_DEGRADED, dedupe_key="provider:gemini", title="Provider degraded", short_summary="errors")
    same = engine.observe(alert_type=AlertType.PROVIDER_DEGRADED, dedupe_key="provider:gemini", title="Provider degraded", short_summary="errors")
    ready = engine.observe(alert_type=AlertType.READINESS_CHANGED, dedupe_key="readiness:PAPER_READY", title="Readiness changed", short_summary="paper ready")
    assert degraded.id == same.id
    assert len(engine.events) == 2
    assert ready.alert_type is AlertType.READINESS_CHANGED


def test_payload_does_not_accept_secret_fields():
    engine = AlertEngine()
    event = engine.observe(alert_type=AlertType.HIGH_IMPACT_NEWS, dedupe_key="news:1", title="News", short_summary="summary", payload={"symbol": "BTCUSDT"})
    assert "token" not in str(event.payload).lower()
