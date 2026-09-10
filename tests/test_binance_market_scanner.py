from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from btc_core.market.models import Candle, MarketSnapshot, MarketSymbol, Ticker24h
from btc_core.market.scanner import BinanceOpportunityScanner


class FakeMarketClient:
    def __init__(self):
        self.snapshot_calls: list[str] = []

    async def list_usdt_perpetuals(self) -> list[MarketSymbol]:
        return [
            MarketSymbol(symbol="BTCUSDT", pair="BTCUSDT", base_asset="BTC", quote_asset="USDT", status="TRADING", contract_type="PERPETUAL", price_precision=1, quantity_precision=3),
            MarketSymbol(symbol="SOLUSDT", pair="SOLUSDT", base_asset="SOL", quote_asset="USDT", status="TRADING", contract_type="PERPETUAL", price_precision=3, quantity_precision=0),
            MarketSymbol(symbol="XRPUSDT", pair="XRPUSDT", base_asset="XRP", quote_asset="USDT", status="TRADING", contract_type="PERPETUAL", price_precision=4, quantity_precision=1),
        ]

    async def ticker_24h(self) -> list[Ticker24h]:
        now = datetime.now(timezone.utc)
        return [
            Ticker24h(symbol="BTCUSDT", last_price=100.0, price_change_percent=1.0, quote_volume=1_000_000_000, observed_at=now),
            Ticker24h(symbol="SOLUSDT", last_price=200.0, price_change_percent=4.0, quote_volume=900_000_000, observed_at=now),
            Ticker24h(symbol="XRPUSDT", last_price=1.0, price_change_percent=2.0, quote_volume=100_000_000, observed_at=now),
        ]

    async def market_snapshot(self, symbol: str, timeframe: str, candle_limit: int = 60) -> MarketSnapshot:
        self.snapshot_calls.append(symbol)
        if symbol == "BTCUSDT":
            raise RuntimeError("temporary market data failure")
        rising = symbol == "SOLUSDT"
        start = datetime(2026, 9, 8, tzinfo=timezone.utc)
        candles: list[Candle] = []
        for index in range(30):
            base = (100 + index) if rising else (130 - index)
            quote_volume = 1000.0 if index < 29 else 1800.0
            buy_ratio = 0.72 if rising else 0.28
            candles.append(
                Candle(
                    symbol=symbol,
                    timeframe=timeframe,
                    open_time=start + timedelta(minutes=15 * index),
                    close_time=start + timedelta(minutes=15 * (index + 1)) - timedelta(milliseconds=1),
                    open=float(base), high=float(base + 1), low=float(base - 1), close=float(base + (0.5 if rising else -0.5)),
                    volume=10, quote_volume=quote_volume, trade_count=20,
                    taker_buy_base_volume=10 * buy_ratio,
                    taker_buy_quote_volume=quote_volume * buy_ratio,
                )
            )
        return MarketSnapshot(
            symbol=symbol, timeframe=timeframe, candles=candles,
            mark_price=candles[-1].close, index_price=candles[-1].close,
            funding_rate=0.0001 if rising else -0.0001,
            open_interest=1100, open_interest_value=120000,
            open_interest_change_percent=5.0,
            long_short_ratio=1.1 if rising else 0.9,
            best_bid=candles[-1].close - 0.01, best_ask=candles[-1].close + 0.01,
            spread_percent=0.02, observed_at=candles[-1].close_time,
        )


class FakeNewsScoreProvider:
    def __init__(self, score: float = 80.0, *, fail: bool = False):
        self.value = score
        self.fail = fail
        self.calls: list[str] = []

    async def score(self, symbol: str) -> float:
        self.calls.append(symbol)
        if self.fail:
            raise RuntimeError("news unavailable")
        return self.value


@pytest.mark.asyncio
async def test_scanner_uses_top_volume_universe_and_isolates_symbol_failures():
    client = FakeMarketClient()
    scanner = BinanceOpportunityScanner(client=client, concurrency=2)

    result = await scanner.scan(timeframe="15m", universe_limit=2, candidate_limit=5)

    assert client.snapshot_calls == ["BTCUSDT", "SOLUSDT"]
    assert [candidate.symbol for candidate in result.candidates] == ["SOLUSDT"]
    assert result.failures[0].symbol == "BTCUSDT"
    assert "temporary market data failure" in result.failures[0].reason
    assert result.candidates[0].rank == 1
    assert result.candidates[0].quote_volume_24h == 900_000_000


@pytest.mark.asyncio
async def test_news_enrichment_changes_score_not_direction():
    baseline = await BinanceOpportunityScanner(
        client=FakeMarketClient(),
        concurrency=2,
    ).scan(timeframe="15m", universe_limit=2, candidate_limit=5)
    provider = FakeNewsScoreProvider(80.0)
    enriched = await BinanceOpportunityScanner(
        client=FakeMarketClient(),
        concurrency=2,
        news_score_provider=provider,
    ).scan(timeframe="15m", universe_limit=2, candidate_limit=5)

    base_candidate = baseline.candidates[0]
    enriched_candidate = enriched.candidates[0]

    assert provider.calls == ["SOLUSDT"]
    assert enriched_candidate.direction == base_candidate.direction
    assert enriched_candidate.directional_signal == base_candidate.directional_signal
    assert enriched_candidate.components.news == 80.0
    assert enriched_candidate.opportunity_score == round(base_candidate.opportunity_score + 3.0, 2)
    assert enriched_candidate.market_only is False
    assert enriched.enrichment_status == "NEWS_V1"


@pytest.mark.asyncio
async def test_news_enrichment_failure_falls_back_to_market_only_candidate():
    provider = FakeNewsScoreProvider(fail=True)
    result = await BinanceOpportunityScanner(
        client=FakeMarketClient(),
        concurrency=2,
        news_score_provider=provider,
    ).scan(timeframe="15m", universe_limit=2, candidate_limit=5)

    assert provider.calls == ["SOLUSDT"]
    assert [candidate.symbol for candidate in result.candidates] == ["SOLUSDT"]
    assert result.candidates[0].components.news == 50.0
    assert result.candidates[0].market_only is True
    assert len(result.failures) == 1
    assert result.failures[0].symbol == "BTCUSDT"
