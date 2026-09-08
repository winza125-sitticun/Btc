from __future__ import annotations

from datetime import timezone

import httpx
import pytest

from btc_core.market.binance_usdm import BinanceMarketDataError, BinanceUsdMClient


def _client(handler) -> BinanceUsdMClient:
    transport = httpx.MockTransport(handler)
    return BinanceUsdMClient(transport=transport)


@pytest.mark.asyncio
async def test_list_usdt_perpetuals_filters_non_trading_and_delivery_contracts():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/fapi/v1/exchangeInfo"
        return httpx.Response(
            200,
            json={
                "symbols": [
                    {
                        "symbol": "BTCUSDT",
                        "pair": "BTCUSDT",
                        "contractType": "PERPETUAL",
                        "status": "TRADING",
                        "baseAsset": "BTC",
                        "quoteAsset": "USDT",
                        "pricePrecision": 1,
                        "quantityPrecision": 3,
                    },
                    {
                        "symbol": "ETHUSDT_260925",
                        "pair": "ETHUSDT",
                        "contractType": "CURRENT_QUARTER",
                        "status": "TRADING",
                        "baseAsset": "ETH",
                        "quoteAsset": "USDT",
                        "pricePrecision": 2,
                        "quantityPrecision": 3,
                    },
                    {
                        "symbol": "OLDUSDT",
                        "pair": "OLDUSDT",
                        "contractType": "PERPETUAL",
                        "status": "SETTLING",
                        "baseAsset": "OLD",
                        "quoteAsset": "USDT",
                        "pricePrecision": 3,
                        "quantityPrecision": 0,
                    },
                ]
            },
        )

    async with _client(handler) as client:
        symbols = await client.list_usdt_perpetuals()

    assert [item.symbol for item in symbols] == ["BTCUSDT"]
    assert symbols[0].quote_asset == "USDT"


@pytest.mark.asyncio
async def test_klines_normalize_quote_and_taker_buy_volume():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/fapi/v1/klines"
        assert request.url.params["symbol"] == "BTCUSDT"
        assert request.url.params["interval"] == "15m"
        return httpx.Response(
            200,
            json=[
                [
                    1_700_000_000_000,
                    "100.0",
                    "110.0",
                    "95.0",
                    "108.0",
                    "12.5",
                    1_700_000_899_999,
                    "1310.0",
                    42,
                    "7.5",
                    "810.0",
                    "0",
                ]
            ],
        )

    async with _client(handler) as client:
        candles = await client.klines("btcusdt", "15m", limit=1)

    candle = candles[0]
    assert candle.symbol == "BTCUSDT"
    assert candle.close == 108.0
    assert candle.quote_volume == 1310.0
    assert candle.taker_buy_quote_volume == 810.0
    assert candle.trade_count == 42
    assert candle.open_time.tzinfo == timezone.utc


@pytest.mark.asyncio
async def test_market_snapshot_combines_public_derivatives_context():
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/fapi/v1/klines":
            rows = []
            for index in range(30):
                price = 100 + index
                rows.append(
                    [
                        1_700_000_000_000 + index * 900_000,
                        str(price),
                        str(price + 2),
                        str(price - 1),
                        str(price + 1),
                        "10",
                        1_700_000_899_999 + index * 900_000,
                        "1000",
                        25,
                        "6",
                        "650",
                        "0",
                    ]
                )
            return httpx.Response(200, json=rows)
        if path == "/fapi/v1/premiumIndex":
            return httpx.Response(
                200,
                json={
                    "symbol": "BTCUSDT",
                    "markPrice": "130.1",
                    "indexPrice": "130.0",
                    "lastFundingRate": "0.0001",
                    "nextFundingTime": 1_700_100_000_000,
                    "time": 1_700_000_100_000,
                },
            )
        if path == "/futures/data/openInterestHist":
            return httpx.Response(
                200,
                json=[
                    {"symbol": "BTCUSDT", "sumOpenInterest": "1000", "sumOpenInterestValue": "100000", "timestamp": 1000},
                    {"symbol": "BTCUSDT", "sumOpenInterest": "1100", "sumOpenInterestValue": "115000", "timestamp": 2000},
                ],
            )
        if path == "/futures/data/globalLongShortAccountRatio":
            return httpx.Response(
                200,
                json=[{"symbol": "BTCUSDT", "longShortRatio": "1.2", "longAccount": "0.545", "shortAccount": "0.455", "timestamp": 2000}],
            )
        if path == "/fapi/v1/ticker/bookTicker":
            return httpx.Response(
                200,
                json={"symbol": "BTCUSDT", "bidPrice": "130.0", "bidQty": "12", "askPrice": "130.02", "askQty": "9", "time": 2000},
            )
        raise AssertionError(f"unexpected path: {path}")

    async with _client(handler) as client:
        snapshot = await client.market_snapshot("BTCUSDT", "15m", candle_limit=30)

    assert snapshot.symbol == "BTCUSDT"
    assert len(snapshot.candles) == 30
    assert snapshot.mark_price == 130.1
    assert snapshot.funding_rate == 0.0001
    assert snapshot.open_interest_change_percent == pytest.approx(10.0)
    assert snapshot.long_short_ratio == 1.2
    assert snapshot.spread_percent == pytest.approx((0.02 / 130.01) * 100)


@pytest.mark.asyncio
async def test_binance_error_payload_raises_typed_market_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"code": -1121, "msg": "Invalid symbol."})

    async with _client(handler) as client:
        with pytest.raises(BinanceMarketDataError) as exc_info:
            await client.klines("NOPEUSDT", "15m", limit=1)

    assert exc_info.value.code == -1121
    assert "Invalid symbol" in str(exc_info.value)
