from fastapi.testclient import TestClient

from services.api.app.main import app


client = TestClient(app)


def test_health_endpoint_reports_service_ready():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "btc-ai-futures-api"}


def test_public_config_defaults_to_simulation_and_exposes_no_secrets(monkeypatch):
    monkeypatch.delenv("AI_ANALYSIS_V1_ENABLED", raising=False)
    monkeypatch.delenv("AI_PROVIDER", raising=False)
    monkeypatch.delenv("AI_MODEL", raising=False)
    monkeypatch.delenv("AI_API_KEY", raising=False)

    response = client.get("/api/v1/config/public")
    payload = response.json()

    assert response.status_code == 200
    assert payload["trading_mode"] == "SIMULATION"
    assert payload["direct_ai_order_enabled"] is False
    assert payload["ai_analysis_enabled"] is False
    assert payload["ai_provider"] is None
    assert payload["ai_model"] is None
    assert payload["ai_api_key_configured"] is False
    assert "api_key" not in payload
    assert "secret" not in payload


def test_public_config_reports_provider_state_without_exposing_ai_key(monkeypatch):
    monkeypatch.setenv("AI_ANALYSIS_V1_ENABLED", "true")
    monkeypatch.setenv("AI_PROVIDER", "GEMINI")
    monkeypatch.setenv("AI_MODEL", "gemini-test")
    monkeypatch.setenv("AI_API_KEY", "super-secret-value")

    response = client.get("/api/v1/config/public")
    payload = response.json()
    serialized = response.text.lower()

    assert response.status_code == 200
    assert payload["ai_analysis_enabled"] is True
    assert payload["ai_provider"] == "GEMINI"
    assert payload["ai_model"] == "gemini-test"
    assert payload["ai_api_key_configured"] is True
    assert "super-secret-value" not in serialized
    assert "authorization" not in serialized
    assert "ai_api_key" not in payload
