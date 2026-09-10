import asyncio

import pytest

from btc_core.ai.models import AIDecision, AIProvider, Direction
from btc_core.ai.orchestrator import AIAnalysisRunner
from btc_core.ai.providers.base import AIProviderError
from btc_core.market.scanner import MarketScanResult, MarketScannerCandidate
from btc_core.market.supabase_repo import PersistedCandidateRef, PersistedScanRef
from btc_core.risk.engine import RiskPolicy
from btc_core.scanner.scoring import OpportunityInputs
from tests.test_ai_provider_openai_compatible import make_snapshot


def candidate(rank: int, symbol: str, score: float) -> MarketScannerCandidate:
    return MarketScannerCandidate(
        rank=rank,
        symbol=symbol,
        timeframe="15m",
        direction=Direction.LONG,
        opportunity_score=score,
        directional_signal=0.5,
        components=OpportunityInputs(
            technical=80, momentum=80, volume=80, order_flow=80,
            open_interest=80, funding=80, liquidity=80, news=58,
            macro=50, risk_reward=50,
        ),
        last_price=100,
        quote_volume_24h=1_000_000,
        funding_rate=0.0001,
        open_interest_change_percent=2,
        long_short_ratio=1.1,
        spread_percent=0.01,
        market_only=False,
    )


def scan(*items: MarketScannerCandidate) -> MarketScanResult:
    return MarketScanResult(
        timeframe="15m", universe_size=len(items), candidates=list(items), failures=[]
    )


def persisted(*items: MarketScannerCandidate) -> PersistedScanRef:
    return PersistedScanRef(
        run_id="11111111-1111-1111-1111-111111111111",
        candidates=tuple(
            PersistedCandidateRef(id=1000 + item.rank, rank=item.rank, symbol=item.symbol)
            for item in items
        ),
    )


async def snapshot_builder(item: MarketScannerCandidate):
    base = make_snapshot()
    return base.model_copy(
        update={
            "symbol": item.symbol,
            "timeframe": item.timeframe,
            "scanner_direction": item.direction,
            "opportunity_score": item.opportunity_score,
            "last_price": item.last_price,
        }
    )


class FakeAnalysisRepo:
    def __init__(self):
        self.records = []

    async def persist(self, record):
        self.records.append(record)


class FakeProvider:
    def __init__(self, *, fail_symbol: str | None = None, wrong_symbol: bool = False):
        self.fail_symbol = fail_symbol
        self.wrong_symbol = wrong_symbol
        self.calls: list[str] = []
        self.active = 0
        self.max_active = 0

    async def analyze(self, snapshot):
        self.calls.append(snapshot.symbol)
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            await asyncio.sleep(0.01)
            if snapshot.symbol == self.fail_symbol:
                raise AIProviderError("bad known-secret-value", code="AUTH")
            return AIDecision(
                provider=AIProvider.GEMINI,
                model="gemini-test",
                symbol="WRONGUSDT" if self.wrong_symbol else snapshot.symbol,
                timeframe=snapshot.timeframe,
                direction=Direction.LONG,
                confidence=84,
                entry_min=99,
                entry_max=100,
                stop_loss=96,
                take_profits=[104, 108],
                risk_reward=2.5,
                reason_summary="Valid structured result.",
            )
        finally:
            self.active -= 1


def runner(provider, repo, **overrides) -> AIAnalysisRunner:
    settings = dict(
        provider_client=provider,
        analysis_repo=repo,
        snapshot_builder=snapshot_builder,
        provider=AIProvider.GEMINI,
        model="gemini-test",
        candidate_limit=3,
        concurrency=2,
        min_opportunity_score=65,
        policy=RiskPolicy(),
    )
    settings.update(overrides)
    return AIAnalysisRunner(**settings)


@pytest.mark.asyncio
async def test_candidates_below_minimum_are_skipped_without_provider_call():
    item = candidate(1, "BTCUSDT", 60)
    provider = FakeProvider()
    repo = FakeAnalysisRepo()

    summary = await runner(provider, repo).analyze_scan(scan(item), persisted(item))

    assert provider.calls == []
    assert summary.skipped == 1
    assert repo.records[0].status == "SKIPPED"


@pytest.mark.asyncio
async def test_only_top_n_eligible_candidates_run_with_bounded_concurrency():
    items = [
        candidate(1, "BTCUSDT", 90),
        candidate(2, "ETHUSDT", 85),
        candidate(3, "SOLUSDT", 80),
    ]
    provider = FakeProvider()
    repo = FakeAnalysisRepo()

    summary = await runner(provider, repo, candidate_limit=2, concurrency=2).analyze_scan(
        scan(*items), persisted(*items)
    )

    assert provider.calls == ["BTCUSDT", "ETHUSDT"]
    assert provider.max_active <= 2
    assert summary.success == 2
    assert summary.skipped == 1


@pytest.mark.asyncio
async def test_provider_failure_is_sanitized_and_other_candidates_continue():
    first = candidate(1, "BTCUSDT", 90)
    second = candidate(2, "ETHUSDT", 85)
    provider = FakeProvider(fail_symbol="BTCUSDT")
    repo = FakeAnalysisRepo()

    summary = await runner(provider, repo).analyze_scan(
        scan(first, second), persisted(first, second)
    )

    assert summary.failed == 1
    assert summary.success == 1
    failed = next(record for record in repo.records if record.symbol == "BTCUSDT")
    assert failed.status == "FAILED"
    assert failed.error_code == "AUTH"
    assert "known-secret-value" not in (failed.error_message or "")


@pytest.mark.asyncio
async def test_identity_mismatch_is_invalid_response_not_success():
    item = candidate(1, "BTCUSDT", 90)
    repo = FakeAnalysisRepo()

    summary = await runner(FakeProvider(wrong_symbol=True), repo).analyze_scan(
        scan(item), persisted(item)
    )

    assert summary.failed == 1
    assert repo.records[0].status == "INVALID_RESPONSE"
    assert repo.records[0].error_code == "IDENTITY_MISMATCH"


@pytest.mark.asyncio
async def test_cancelled_error_propagates_without_failure_record():
    item = candidate(1, "BTCUSDT", 90)
    repo = FakeAnalysisRepo()

    class CancelProvider:
        async def analyze(self, snapshot):
            raise asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        await runner(CancelProvider(), repo).analyze_scan(scan(item), persisted(item))

    assert repo.records == []
