from __future__ import annotations

import asyncio
from collections.abc import Mapping
from contextlib import AsyncExitStack
from functools import partial
import os
import time

from btc_core.ai.models import AIProvider
from btc_core.ai.multi_agent.config import load_multi_agent_config, resolve_multi_agent_mode
from btc_core.ai.multi_agent.invocation import RoleAwareProviderInvoker
from btc_core.ai.multi_agent.models import FrozenRoleAssignment, RolloutMode
from btc_core.ai.multi_agent.orchestrator import MultiAgentOrchestrator
from btc_core.ai.multi_agent.repository import SupabaseMultiAgentRepository
from btc_core.ai.multi_agent.scan_runner import MultiAgentScanRunner
from btc_core.ai.orchestrator import AIAnalysisRunner
from btc_core.ai.providers.base import AIProviderRuntimeConfig
from btc_core.ai.providers.factory import build_provider_client
from btc_core.ai.snapshot import build_ai_snapshot
from btc_core.ai.supabase_repo import SupabaseAIAnalysisRepository
from btc_core.market.binance_usdm import BinanceUsdMClient
from btc_core.market.realtime import BinanceUsdMRealtimeClient, LiveMarketAggregator
from btc_core.market.scanner import BinanceOpportunityScanner, MarketScanResult
from btc_core.market.supabase_repo import SupabaseMarketRepository
from btc_core.news.enrichment import RecentNewsScoreProvider
from btc_core.news.supabase_repo import SupabaseNewsRepository
from btc_core.risk.engine import RiskPolicy


CORE_REALTIME_SYMBOLS = ("BTCUSDT", "SOLUSDT", "XRPUSDT", "ETHUSDT")

_MULTI_AGENT_SECRET_ENV: dict[AIProvider, str] = {
    AIProvider.GEMINI: "GEMINI_API_KEY",
    AIProvider.CLAUDE: "ANTHROPIC_API_KEY",
    AIProvider.OPENAI_COMPATIBLE: "OPENAI_COMPATIBLE_API_KEY",
    AIProvider.DEEPSEEK: "DEEPSEEK_API_KEY",
    AIProvider.OPENROUTER: "OPENROUTER_API_KEY",
}


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


def _mapping_int(
    env: Mapping[str, str],
    name: str,
    default: int,
    *,
    minimum: int,
    maximum: int,
) -> int:
    raw = env.get(name)
    value = default if raw is None or not raw.strip() else int(raw)
    return max(minimum, min(maximum, value))


def _mapping_float(
    env: Mapping[str, str],
    name: str,
    default: float,
    *,
    minimum: float,
    maximum: float,
) -> float:
    raw = env.get(name)
    value = default if raw is None or not raw.strip() else float(raw)
    return max(minimum, min(maximum, value))


def _multi_agent_provider_config(
    assignment: FrozenRoleAssignment,
    env: Mapping[str, str],
) -> AIProviderRuntimeConfig:
    secret_name = _MULTI_AGENT_SECRET_ENV[assignment.provider]
    api_key = (env.get(secret_name) or "").strip()
    if not api_key:
        raise ValueError(f"{secret_name} is required for {assignment.role.value}")

    base_url = ""
    if assignment.provider is AIProvider.OPENAI_COMPATIBLE:
        base_url = (env.get("OPENAI_COMPATIBLE_BASE_URL") or "").strip()
        if not base_url:
            raise ValueError("OPENAI_COMPATIBLE_BASE_URL is required for OPENAI_COMPATIBLE")

    return AIProviderRuntimeConfig(
        provider=assignment.provider,
        model=assignment.model,
        api_key=api_key,
        base_url=base_url,
        timeout_seconds=_mapping_float(
            env,
            "AI_MULTI_AGENT_TIMEOUT_SECONDS",
            20.0,
            minimum=1.0,
            maximum=120.0,
        ),
        max_retries=_mapping_int(
            env,
            "AI_MULTI_AGENT_MAX_RETRIES",
            1,
            minimum=0,
            maximum=1,
        ),
    )


async def _build_multi_agent_runner(
    *,
    stack: AsyncExitStack,
    env: Mapping[str, str],
    supabase_url: str,
    service_role_key: str,
    market_client,
    news_repo,
):
    """Build the sidecar/primary multi-agent runtime without risking market ingestion."""
    try:
        config = load_multi_agent_config(env).to_frozen_snapshot()
        if config.mode is RolloutMode.OFF:
            return None
        if not config.assignments:
            raise ValueError("multi-agent rollout has no enabled role assignments")

        clients = {}
        for assignment in config.assignments:
            runtime_config = _multi_agent_provider_config(assignment, env)
            client = build_provider_client(runtime_config)
            clients[assignment.role] = await stack.enter_async_context(client)

        repository = await stack.enter_async_context(
            SupabaseMultiAgentRepository(
                supabase_url=supabase_url,
                api_key=service_role_key,
            )
        )
        invoker = RoleAwareProviderInvoker(clients)
        orchestrator = MultiAgentOrchestrator(
            repository=repository,
            invoker=invoker,
            max_concurrency=_mapping_int(
                env,
                "AI_MULTI_AGENT_CONCURRENCY",
                3,
                minimum=1,
                maximum=6,
            ),
        )
        snapshot_builder = partial(
            build_ai_snapshot,
            market_client=market_client,
            news_repo=news_repo,
        )
        return MultiAgentScanRunner(
            orchestrator=orchestrator,
            config=config,
            snapshot_builder=snapshot_builder,
            candidate_limit=_mapping_int(
                env,
                "AI_MULTI_AGENT_CANDIDATE_LIMIT",
                3,
                minimum=1,
                maximum=50,
            ),
            min_opportunity_score=_mapping_float(
                env,
                "AI_MULTI_AGENT_MIN_OPPORTUNITY_SCORE",
                65.0,
                minimum=0.0,
                maximum=100.0,
            ),
        )
    except Exception as exc:
        print(f"multi-agent disabled: invalid configuration type={type(exc).__name__}")
        return None


def _select_realtime_symbols(candidates, realtime_symbol_limit: int) -> list[str]:
    symbols = [candidate.symbol for candidate in candidates[:realtime_symbol_limit]]
    for symbol in CORE_REALTIME_SYMBOLS:
        if symbol not in symbols:
            symbols.append(symbol)
    return symbols


async def _cancel_ai_task(ai_task: asyncio.Task | None) -> None:
    if ai_task is None:
        return
    if not ai_task.done():
        ai_task.cancel()
    try:
        await ai_task
    except asyncio.CancelledError:
        pass
    except Exception:
        pass


async def _finish_ai_task(ai_task: asyncio.Task | None) -> None:
    if ai_task is None:
        return
    try:
        summary = await ai_task
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        print(f"ai analysis task failed type={type(exc).__name__}")
        return
    if summary is not None:
        print(
            f"ai_analysis success={summary.success} failed={summary.failed} "
            f"skipped={summary.skipped}"
        )


async def _finish_multi_agent_task(task: asyncio.Task | None) -> None:
    if task is None:
        return
    try:
        summary = await task
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        print(f"multi-agent task failed type={type(exc).__name__}")
        return
    if summary is not None:
        print(
            f"multi_agent attempted={summary.attempted} approved={summary.approved} "
            f"rejected={summary.rejected} failed={summary.failed} skipped={summary.skipped}"
        )


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
    ai_runner=None,
    multi_agent_runner=None,
) -> MarketScanResult:
    result = await scanner.scan(
        timeframe=timeframe,
        universe_limit=universe_limit,
        candidate_limit=candidate_limit,
    )
    persisted = await repo.persist_scan(result)

    ai_task = None
    if ai_runner is not None:
        ai_task = asyncio.create_task(ai_runner.analyze_scan(result, persisted))
    multi_agent_task = None
    if multi_agent_runner is not None:
        multi_agent_task = asyncio.create_task(multi_agent_runner.analyze_scan(result, persisted))

    try:
        symbols = _select_realtime_symbols(result.candidates, realtime_symbol_limit)
        if symbols:
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
    except asyncio.CancelledError:
        await _cancel_ai_task(ai_task)
        await _cancel_ai_task(multi_agent_task)
        raise
    except Exception:
        await _cancel_ai_task(ai_task)
        await _cancel_ai_task(multi_agent_task)
        raise

    try:
        await _finish_ai_task(ai_task)
        await _finish_multi_agent_task(multi_agent_task)
    except asyncio.CancelledError:
        await _cancel_ai_task(ai_task)
        await _cancel_ai_task(multi_agent_task)
        raise
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
    ai_analysis_enabled = _env_flag("AI_ANALYSIS_V1_ENABLED", False)
    multi_agent_mode = resolve_multi_agent_mode(
        os.getenv("AI_MULTI_AGENT_ENABLED"),
        os.getenv("AI_MULTI_AGENT_MODE"),
    )

    async with AsyncExitStack() as stack:
        client = await stack.enter_async_context(BinanceUsdMClient())
        repo = await stack.enter_async_context(
            SupabaseMarketRepository(
                supabase_url=supabase_url,
                api_key=service_role_key,
            )
        )

        news_repo = None
        if news_enrichment_enabled or ai_analysis_enabled or multi_agent_mode is not RolloutMode.OFF:
            news_repo = await stack.enter_async_context(
                SupabaseNewsRepository(
                    supabase_url=supabase_url,
                    api_key=service_role_key,
                )
            )

        news_score_provider = (
            RecentNewsScoreProvider(repo=news_repo)
            if news_enrichment_enabled and news_repo is not None
            else None
        )

        scanner = BinanceOpportunityScanner(
            client=client,
            concurrency=concurrency,
            news_score_provider=news_score_provider,
        )

        ai_runner = None
        if ai_analysis_enabled:
            provider_name = os.getenv("AI_PROVIDER", "").strip().upper()
            model_name = os.getenv("AI_MODEL", "").strip()
            ai_api_key = os.getenv("AI_API_KEY", "").strip()
            ai_base_url = os.getenv("AI_BASE_URL", "").strip()
            if not provider_name or not model_name or not ai_api_key:
                print("ai analysis disabled: provider/model/api key not configured")
            else:
                try:
                    provider = AIProvider(provider_name)
                    provider_config = AIProviderRuntimeConfig(
                        provider=provider,
                        model=model_name,
                        api_key=ai_api_key,
                        base_url=ai_base_url,
                        timeout_seconds=_env_float(
                            "AI_TIMEOUT_SECONDS", 20.0, minimum=1.0, maximum=120.0
                        ),
                        max_retries=_env_int(
                            "AI_MAX_RETRIES", 1, minimum=0, maximum=1
                        ),
                    )
                    provider_client = build_provider_client(provider_config)
                    provider_client = await stack.enter_async_context(provider_client)
                    ai_repo = await stack.enter_async_context(
                        SupabaseAIAnalysisRepository(
                            supabase_url=supabase_url,
                            api_key=service_role_key,
                        )
                    )
                    snapshot_builder = partial(
                        build_ai_snapshot,
                        market_client=client,
                        news_repo=news_repo,
                    )
                    ai_runner = AIAnalysisRunner(
                        provider_client=provider_client,
                        analysis_repo=ai_repo,
                        snapshot_builder=snapshot_builder,
                        provider=provider,
                        model=model_name,
                        candidate_limit=_env_int(
                            "AI_ANALYSIS_CANDIDATE_LIMIT", 3, minimum=1, maximum=50
                        ),
                        concurrency=_env_int(
                            "AI_ANALYSIS_CONCURRENCY", 2, minimum=1, maximum=20
                        ),
                        min_opportunity_score=_env_float(
                            "AI_MIN_OPPORTUNITY_SCORE", 65.0, minimum=0.0, maximum=100.0
                        ),
                        policy=RiskPolicy(),
                    )
                except Exception as exc:
                    print(f"ai analysis disabled: invalid configuration type={type(exc).__name__}")
                    ai_runner = None

        multi_agent_runner = await _build_multi_agent_runner(
            stack=stack,
            env=os.environ,
            supabase_url=supabase_url,
            service_role_key=service_role_key,
            market_client=client,
            news_repo=news_repo,
        )

        # OFF keeps the legacy path. SHADOW runs both paths. PRIMARY suppresses
        # new legacy analyses only when the multi-agent runtime is healthy;
        # configuration failure therefore falls back to legacy behavior.
        effective_ai_runner = ai_runner
        if multi_agent_runner is not None and multi_agent_mode is RolloutMode.PRIMARY:
            effective_ai_runner = None

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
                    ai_runner=effective_ai_runner,
                    multi_agent_runner=multi_agent_runner,
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
