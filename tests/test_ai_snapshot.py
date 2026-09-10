from datetime import datetime, timedelta, timezone

import pytest

from btc_core.ai.models import Direction
from btc_core.ai.snapshot import build_ai_snapshot
from btc_core.market.models import Candle
from btc_core.market.scanner import MarketScannerCandidate
from btc_core.scanner.scoring import OpportunityInputs


def make_candidate(symbol: str = "BTCUSDT", timeframe: str = "15m") -> MarketScannerCandidate:
    return MarketScannerCandidate(
        rank=1,
        symbol=symbol,
        timeframe=timeframe,
        direction=Direction.LONG,
        opportunity_score=82,
        directional_signal=0.6,
        components=OpportunityInputs(
            technical=82,
            momentum=78,
            volume=74,
            order_flow=80,
            open_interest=76,
            funding=70,
            liquidity=90,
            news=58,
            macro=50,
            risk_reward=50,
        ),
        last_price=100,
        quote_volume_24h=1_000_000,
        funding_rate=0.0001,
        open_interest_change_percent=2.1,
        long_short_ratio=1.05,
        spread_percent=0.01,
        market_only=False,
    )


def make_candles(symbol: str, timeframe: str) -> list[Candle]:
    start = datetime(2026, 9, 9, tzinfo=timezone.utc)
    candles: list[Candle] = []
    for index in range(60):
        close = 100 + index * 0.1
        candles.append(
            Candle(
                symbol=symbol,
                timeframe=timeframe,
                open_time=start + timedelta(minutes=index),
                close_time=start + timedelta(minutes=index + 1),
                open=close - 0.05,
                high=close + 0.2,
                low=close - 0.2,
                close=close,
                volume=10 + index,
                quote_volume=(10 + index) * close,
                trade_count=100 + index,
                taker_buy_base_volume=(10 + index) * 0.55,
                taker_buy_quote_volume=(10 + index) * close * 0.55,
            )
        )
    return candles


class FakeKlineClient:
    def __init__(self):
        self.calls: list[tuple[str, str, int]] = []

    async def klines(self, symbol: str, timeframe: str, *, limit: int = 60):
        self.calls.append((symbol, timeframe, limit))
        return make_candles(symbol, timeframe)


class FakeNewsStory:
    def model_dump(self, *, mode="python"):
        assert mode == "json"
        return {
            "title": "ETF flow update",
            "summary": "Institutional flow increased.",
            "published_at": "2026-09-10T02:30:00Z",
            "impact_level": "MEDIUM",
            "credibility_score": 90,
        }


class FakeNewsRepo:
    def __init__(self):
        self.calls = []

    async def recent_asset_context(self, symbol, since, until, limit=5):
        self.calls.append((symbol, since, until, limit))
        return [FakeNewsStory()]


@pytest.mark.asyncio
async def test_snapshot_fetches_only_required_timeframes_and_no_unbounded_history():
    client = FakeKlineClient()
    now = datetime(2026, 9, 10, 3, 0, tzinfo=timezone.utc)
    snapshot = await build_ai_snapshot(
        make_candidate(),
        market_client=client,
        news_repo=FakeNewsRepo(),
        now=now,
    )

    assert client.calls == [
        ("BTCUSDT", "4h", 60),
        ("BTCUSDT", "1h", 60),
        ("BTCUSDT", "15m", 60),
    ]
    assert set(snapshot.technical_by_timeframe) == {"4h", "1h", "15m"}
    dumped = snapshot.model_dump(mode="json")
    assert "candles" not in str(dumped).lower()


@pytest.mark.asyncio
async def test_snapshot_uses_closed_24h_news_window_and_bounded_story_count():
    news_repo = FakeNewsRepo()
    now = datetime(2026, 9, 10, 3, 0, tzinfo=timezone.utc)
    snapshot = await build_ai_snapshot(
        make_candidate(),
        market_client=FakeKlineClient(),
        news_repo=news_repo,
        now=now,
    )

    assert news_repo.calls == [
        ("BTCUSDT", now - timedelta(hours=24), now, 5)
    ]
    assert snapshot.news.score == 58
    assert snapshot.news.stories[0]["title"] == "ETF flow update"
