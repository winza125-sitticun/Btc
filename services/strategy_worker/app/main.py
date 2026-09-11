from __future__ import annotations

import asyncio
import inspect
import os
from dataclasses import dataclass

from btc_core.strategy.repository import PublicBinanceKlinesFetcher, SupabaseStrategyRepository


def _flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    return default if raw is None else raw.strip().lower() in {"1", "true", "yes", "on"}


def _seconds(name: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(name, str(default))))
    except ValueError:
        return default


def _cycle_seconds() -> int:
    raw = os.getenv("STRATEGY_CYCLE_SECONDS", "60")
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError("STRATEGY_CYCLE_SECONDS must be an integer") from exc
    if not 30 <= value <= 300:
        raise ValueError("STRATEGY_CYCLE_SECONDS must be between 30 and 300")
    return value


@dataclass(frozen=True)
class WorkerConfig:
    enabled: bool = False
    outcome_evaluation_enabled: bool = False
    simulation_engine_enabled: bool = False
    cycle_seconds: int = 60
    target_risk_percent: float = 0.5
    taker_fee_bps: float = 5
    slippage_bps: float = 2
    entry_validity_minutes_15m: int = 60
    live_order_execution_enabled: bool = False


def load_worker_config() -> WorkerConfig:
    return WorkerConfig(
        enabled=_flag("STRATEGY_WORKER_ENABLED"),
        outcome_evaluation_enabled=_flag("OUTCOME_EVALUATION_ENABLED"),
        simulation_engine_enabled=_flag("SIMULATION_ENGINE_ENABLED"),
        cycle_seconds=_cycle_seconds(),
        target_risk_percent=float(os.getenv("SIM_TARGET_RISK_PERCENT", "0.5")),
        taker_fee_bps=float(os.getenv("SIM_TAKER_FEE_BPS", "5")),
        slippage_bps=float(os.getenv("SIM_SLIPPAGE_BPS", "2")),
        entry_validity_minutes_15m=_seconds("SIM_ENTRY_VALIDITY_MINUTES_15M", 60),
        live_order_execution_enabled=_flag("LIVE_ORDER_EXECUTION_ENABLED"),
    )


@dataclass(frozen=True)
class CycleResult:
    stages: tuple[str, ...] = ()
    errors: tuple[tuple[str, str], ...] = ()
    skipped: bool = False


class StrategyWorker:
    """Runs strategy bookkeeping independently from the market worker.

    Repository methods are intentionally optional while the worker is being
    rolled out; this keeps each stage independently deployable and testable.
    """

    def __init__(self, *, repository, market_client, enabled: bool = False,
                 outcome_evaluation_enabled: bool = False,
                 simulation_engine_enabled: bool = False,
                 live_order_execution_enabled: bool = False) -> None:
        if live_order_execution_enabled:
            raise ValueError("live order execution is prohibited for strategy worker")
        self.repository = repository
        self.market_client = market_client
        self.enabled = enabled
        self.outcome_evaluation_enabled = outcome_evaluation_enabled
        self.simulation_engine_enabled = simulation_engine_enabled

    async def _call(self, name: str, *args):
        method = getattr(self.repository, name, None)
        if method is None:
            raise NotImplementedError(f"repository stage is not implemented: {name}")
        value = method(*args)
        return await value if inspect.isawaitable(value) else value

    async def run_cycle(self) -> CycleResult:
        if not self.enabled:
            return CycleResult(skipped=True)
        stages = (
            ("finalize_due_outcomes", (self.market_client,), self.outcome_evaluation_enabled),
            ("expire_stale_entries", (), self.simulation_engine_enabled),
            ("evaluate_new_analyses", (), self.simulation_engine_enabled),
            ("update_trades", (self.market_client,), self.simulation_engine_enabled),
            ("reconcile_account", (), self.simulation_engine_enabled),
        )
        completed: list[str] = []
        errors: list[tuple[str, str]] = []
        for name, args, enabled in stages:
            if not enabled:
                continue
            try:
                await self._call(name, *args)
                completed.append(name)
            except Exception as exc:  # isolate one stage from the rest of the cycle
                errors.append((name, type(exc).__name__))
        return CycleResult(tuple(completed), tuple(errors))


async def run_forever() -> None:
    config = load_worker_config()
    if not config.enabled:
        print("strategy worker disabled; no strategy state writes")
        return
    if config.live_order_execution_enabled:
        raise RuntimeError("LIVE_ORDER_EXECUTION_ENABLED must remain false")
    url, key = os.getenv("SUPABASE_URL", "").strip(), os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    if not url or not key:
        raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required")
    async with SupabaseStrategyRepository(supabase_url=url, api_key=key) as repository:
        fetcher = PublicBinanceKlinesFetcher()
        worker = StrategyWorker(repository=repository, market_client=fetcher,
                                 enabled=True,
                                 outcome_evaluation_enabled=config.outcome_evaluation_enabled,
                                 simulation_engine_enabled=config.simulation_engine_enabled)
        try:
            while True:
                result = await worker.run_cycle()
                print(f"strategy cycle complete stages={len(result.stages)} errors={len(result.errors)}")
                await asyncio.sleep(config.cycle_seconds)
        finally:
            await fetcher.aclose()


def main() -> None:
    asyncio.run(run_forever())


if __name__ == "__main__":
    main()
