from fastapi.testclient import TestClient

from services.api.app.main import app


client = TestClient(app)


def test_health_endpoint_reports_service_ready():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "btc-ai-futures-api"}


def test_public_config_defaults_to_simulation_and_exposes_no_secrets():
    response = client.get("/api/v1/config/public")
    payload = response.json()
    assert response.status_code == 200
    assert payload["trading_mode"] == "SIMULATION"
    assert payload["direct_ai_order_enabled"] is False
    assert "api_key" not in payload
    assert "secret" not in payload
