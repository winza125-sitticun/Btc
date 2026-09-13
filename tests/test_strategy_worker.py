import asyncio

from btc_core.ai.multi_agent.models import RolloutMode
from services.strategy_worker.app.main import StrategyWorker, load_worker_config


class FakeRepository:
    def __init__(self, events, failures=()):
        self.events = events
        self.failures = set(failures)

    async def finalize_due_outcomes(self, market_client):
        self.events.append("finalize_due_outcomes")
        if "finalize_due_outcomes" in self.failures:
            raise RuntimeError("outcome failure")

    async def expire_stale_entries(self):
        self.events.append("expire_stale_entries")

    async def evaluate_new_analyses(self):
        self.events.append("evaluate_new_analyses")

    async def update_trades(self, market_client):
        self.events.append("update_trades")
        if "update_trades" in self.failures:
            raise RuntimeError("trade failure")

    async def reconcile_account(self):
        self.events.append("reconcile_account")


def test_enabled_cycle_runs_stages_in_order_and_is_independent():
    events = []
    worker = StrategyWorker(
        repository=FakeRepository(events), market_client=object(), enabled=True,
        outcome_evaluation_enabled=True, simulation_engine_enabled=True,
    )

    result = asyncio.run(worker.run_cycle())

    assert result.errors == ()
    assert result.stages == (
        "finalize_due_outcomes", "expire_stale_entries", "evaluate_new_analyses",
        "update_trades", "reconcile_account",
    )
    assert events == list(result.stages)


def test_stage_failure_is_recorded_and_later_stages_still_run():
    events = []
    worker = StrategyWorker(
        repository=FakeRepository(events, {"update_trades"}), market_client=object(), enabled=True,
        outcome_evaluation_enabled=True, simulation_engine_enabled=True,
    )

    result = asyncio.run(worker.run_cycle())

    assert result.errors == (("update_trades", "RuntimeError"),)
    assert events[-1] == "reconcile_account"


def test_disabled_worker_does_not_touch_repository():
    events = []
    result = asyncio.run(StrategyWorker(
        repository=FakeRepository(events), market_client=object(), enabled=False,
    ).run_cycle())
    assert result.skipped is True
    assert events == []


def test_worker_defaults_are_safe(monkeypatch):
    for key in (
        "STRATEGY_WORKER_ENABLED", "OUTCOME_EVALUATION_ENABLED", "SIMULATION_ENGINE_ENABLED",
        "LIVE_ORDER_EXECUTION_ENABLED", "AI_MULTI_AGENT_ENABLED", "AI_MULTI_AGENT_MODE",
    ):
        monkeypatch.delenv(key, raising=False)
    config = load_worker_config()
    assert config.enabled is False
    assert config.outcome_evaluation_enabled is False
    assert config.simulation_engine_enabled is False
    assert config.live_order_execution_enabled is False
    assert config.multi_agent_mode is RolloutMode.OFF
    assert config.cycle_seconds == 60


def test_cycle_seconds_rejects_invalid_or_out_of_range_values(monkeypatch):
    import pytest
    for value in ("not-an-int", "29", "301"):
        monkeypatch.setenv("STRATEGY_CYCLE_SECONDS", value)
        with pytest.raises(ValueError):
            load_worker_config()


def test_enabled_missing_stage_is_an_explicit_error_and_later_stages_run():
    class PartialRepository:
        async def reconcile_account(self):
            events.append("reconcile_account")

    events = []
    result = asyncio.run(StrategyWorker(
        repository=PartialRepository(), market_client=object(), enabled=True,
        outcome_evaluation_enabled=True, simulation_engine_enabled=True,
    ).run_cycle())
    assert ("finalize_due_outcomes", "NotImplementedError") in result.errors
    assert events == ["reconcile_account"]
