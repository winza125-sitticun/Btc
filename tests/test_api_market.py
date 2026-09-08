from fastapi.testclient import TestClient

from services.api.app.main import app, get_market_reader


class FakeMarketReader:
    async def latest_candidates(self, timeframe: str, limit: int):
        assert timeframe == "15m"
        assert limit == 5
        return [
            {
                "rank": 1,
                "symbol": "SOLUSDT",
                "timeframe": "15m",
                "direction": "LONG",
                "opportunity_score": 86.4,
                "last_price": 150.25,
                "quote_volume_24h": 500000000,
                "funding_rate": 0.0001,
                "open_interest_change_percent": 2.5,
                "long_short_ratio": 1.08,
                "spread_percent": 0.01,
                "created_at": "2026-09-08T03:00:00+00:00",
            }
        ]

    async def live_states(self, symbols: list[str]):
        assert symbols == ["BTCUSDT", "SOLUSDT"]
        return [{"symbol": "BTCUSDT", "mark_price": 62000, "updated_at": "2026-09-08T03:00:01+00:00"}]


client = TestClient(app)


def test_latest_scanner_candidates_endpoint_uses_repository():
    app.dependency_overrides[get_market_reader] = lambda: FakeMarketReader()
    try:
        response = client.get("/api/v1/scanner/latest?timeframe=15m&limit=5")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload[0]["symbol"] == "SOLUSDT"
    assert payload[0]["opportunity_score"] == 86.4


def test_market_live_endpoint_normalizes_symbol_list():
    app.dependency_overrides[get_market_reader] = lambda: FakeMarketReader()
    try:
        response = client.get("/api/v1/market/live?symbols=btcusdt, solusdt")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()[0]["symbol"] == "BTCUSDT"
