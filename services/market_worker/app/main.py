from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack
import os
import time

from btc_core.market.binance_usdm import BinanceUsdMClient
from btc_core.market.realtime import BinanceUsdMRealtimeClient, LiveMarketAggregator
from btc_core.market.scanner import BinanceOpportunityScanner, MarketScanResult
from btc_core.market.supabase_repo import SupabaseMarketRepository
from btc_core.news.enrichment import RecentNewsScoreProvider
from btc_core.news.supabase_repo import SupabaseNewsRepository


CORE_REALTIME_SYMBOLS = ("BTCUSDT", "SOLUSDT", "XRPUSDT", "ETHUSDT")


def _env_int(name: str, default: int, *, minimum: int, maximum: int) -> int:
    raw = os.getenv(name)
    value = default if raw is None else int(raw)
    return max(minimum, min(maximum, value))


def _env_float(name: str, default: float, *, minimum: float, maximum: float) -> float:
    raw = os.getenv(name)
    value = default if raw is None else float(raw)
    return max(minimum, min(maximum, value))


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _select_realtime_symbols(candidates, realtime_symbol_limit: int) -> list[str]:
    symbols = [candidate.symbol for candidate in candidates[:realtime_symbol_limit]]
    for symbol in CORE_REALTIME_SYMBOLS:
        if symbol not in symbols:
            symbols.append(symbol)
    return symbols


async def run_realtime_cycle(
    *,
    scanner,
    repo,
    realtime,
    timeframe: str,
    universe_limit: int,
    candidate_limit: int,
    realtime_symbol_limit: int,
    realtime_seconds: float,
    flush_interval_seconds: float,
) -> MarketScanResult:
    result = await scanner.scan(
        timeframe=timeframe,
        universe_limit=universe_limit,
        candidate_limit=candidate_limit,
    )
    await repo.persist_scan(result)

    symbols = _select_realtime_symbols(result.candidates, realtime_symbol_limit)
    if not symbols:
        return result

    aggregator = LiveMarketAggregator()
    last_flush = time.monotonic()
    async for event in realtime.events(symbols, timeframe, run_seconds=realtime_seconds):
        closed_candle = aggregator.apply(event)
        if closed_candle is not None:
            await repo.upsert_candle(closed_candle)

        now = time.monotonic()
        if now - last_flush >= flush_interval_seconds:
            await repo.upsert_live_states(aggregator.snapshots())
            last_flush = now

    states = aggregator.snapshots()
    if states:
        await repo.upsert_live_states(states)
    return result


async def scan_once() -> str:
    timeframe = os.getenv("SCANNER_TIMEFRAME", "15m")
    universe_limit = _env_int("SCANNER_UNIVERSE_LIMIT", 30, minimum=1, maximum=200)
    candidate_limit = _env_int("SCANNER_CANDIDATE_LIMIT", 10, minimum=1, maximum=universe_limit)
    concurrency = _env_int("SCANNER_CONCURRENCY", 5, minimum=1, maximum=20)

    async with BinanceUsdMClient() as client:
        scanner = BinanceOpportunityScanner(client=client, concurrency=concurrency)
        result = await scanner.scan(
            timeframe=timeframe,
            universe_limit=universe_limit,
            candidate_limit=candidate_limit,
        )
    return result.model_dump_json(indent=2)


async def run_forever() -> None:
    supabase_url = os.getenv("SUPABASE_URL", "").strip()
    service_role_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    if not supabase_url or not service_role_key:
        raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required for realtime worker mode")

    timeframe = os.getenv("SCANNER_TIMEFRAME", "15m")
    universe_limit = _env_int("SCANNER_UNIVERSE_LIMIT", 30, minimum=1, maximum=200)
    candidate_limit = _env_int("SCANNER_CANDIDATE_LIMIT", 10, minimum=1, maximum=universe_limit)
    concurrency = _env_int("SCANNER_CONCURRENCY", 5, minimum=1, maximum=20)
    realtime_symbol_limit = _env_int("REALTIME_SYMBOL_LIMIT", 10, minimum=1, maximum=candidate_limit)
    realtime_seconds = _env_float("SCANNER_INTERVAL_SECONDS", 300.0, minimum=30.0, maximum=3600.0)
    flush_interval = _env_float("REALTIME_FLUSH_SECONDS", 3.0, minimum=1.0, maximum=60.0)
    retry_delay = _env_float("WORKER_RETRY_SECONDS", 10.0, minimum=1.0, maximum=300.0)
    news_enrichment_enabled = _env_flag("NEWS_ENRICHMENT_V1_ENABLED", False)

    async with AsyncExitStack() as stack:
        client = await stack.enter_async_context(BinanceUsdMClient())
        repo = await stack.enter_async_context(
            SupabaseMarketRepository(
                supabase_url=supabase_url,
                api_key=service_role_key,
            )
        )

        news_score_provider = None
        if news_enrichment_enabled:
            news_repo = await stack.enter_async_context(
                SupabaseNewsRepository(
                    supabase_url=supabase_url,
                    api_key=service_role_key,
                )
            )
            news_score_provider = RecentNewsScoreProvider(repo=news_repo)

        scanner = BinanceOpportunityScanner(
            client=client,
            concurrency=concurrency,
            news_score_provider=news_score_provider,
        )
        realtime = BinanceUsdMRealtimeClient()
        while True:
            try:
                result = await run_realtime_cycle(
                    scanner=scanner,
                    repo=repo,
                    realtime=realtime,
                    timeframe=timeframe,
                    universe_limit=universe_limit,
                    candidate_limit=candidate_limit,
                    realtime_symbol_limit=realtime_symbol_limit,
                    realtime_seconds=realtime_seconds,
                    flush_interval_seconds=flush_interval,
                )
                print(
                    f"scanner cycle complete timeframe={result.timeframe} "
                    f"universe={result.universe_size} candidates={len(result.candidates)} "
                    f"failures={len(result.failures)} enrichment={result.enrichment_status}"
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                print(f"market worker cycle failed: {exc}")
                await asyncio.sleep(retry_delay)


def main() -> None:
    mode = os.getenv("MARKET_WORKER_MODE", "realtime").strip().lower()
    if mode == "once":
        print(asyncio.run(scan_once()))
        return
    asyncio.run(run_forever())


if __name__ == "__main__":
    main()
