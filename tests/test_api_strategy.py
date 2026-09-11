from fastapi.testclient import TestClient

from services.api.app.main import app, get_strategy_reader


class FakeStrategyReader:
    async def read(self, resource, *, limit, cursor=None, mode=None):
        assert limit == 2
        return {"items": [{"resource": resource, "safe": True}], "next_cursor": "next"}


client = TestClient(app)


def test_strategy_lists_are_bounded_and_cursor_paginated():
    app.dependency_overrides[get_strategy_reader] = lambda: FakeStrategyReader()
    try:
        response = client.get("/api/v1/alerts?limit=2&cursor=abc")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json()["next_cursor"] == "next"


def test_strategy_endpoints_expose_sanitized_reads_only():
    app.dependency_overrides[get_strategy_reader] = lambda: FakeStrategyReader()
    try:
        response = client.get("/api/v1/order-intents?mode=DRY_RUN&limit=2")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200
    assert "input_snapshot" not in response.text
    assert "api_key" not in response.text


def test_strategy_list_limit_is_rejected_outside_bounds():
    app.dependency_overrides[get_strategy_reader] = lambda: FakeStrategyReader()
    try:
        assert client.get("/api/v1/experiments?limit=0").status_code == 422
        assert client.get("/api/v1/experiments?limit=501").status_code == 422
    finally:
        app.dependency_overrides.clear()


def test_strategy_api_has_no_mutation_routes():
    assert client.post("/api/v1/order-intents", json={}).status_code == 405
