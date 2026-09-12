from __future__ import annotations

import inspect
from contextlib import AsyncExitStack

import pytest

from btc_core.ai.multi_agent.models import AgentRole, RolloutMode
from services.market_worker.app import main as market_worker


def _env(mode: str = "SHADOW") -> dict[str, str]:
    return {
        "AI_MULTI_AGENT_ENABLED": "true",
        "AI_MULTI_AGENT_MODE": mode,
        "AI_MULTI_AGENT_MIN_VALID_ROLES": "1",
        "AI_ROLE_TECHNICAL_ENABLED": "true",
        "AI_ROLE_TECHNICAL_PROVIDER": "GEMINI",
        "AI_ROLE_TECHNICAL_MODEL": "gemini-test",
        "AI_ROLE_TECHNICAL_PROMPT_VERSION": "v1",
        "GEMINI_API_KEY": "server-secret",
    }


@pytest.mark.asyncio
async def test_off_mode_fails_closed_without_requiring_provider_credentials():
    async with AsyncExitStack() as stack:
        runner = await market_worker._build_multi_agent_runner(
            stack=stack,
            env={"AI_MULTI_AGENT_ENABLED": "false", "AI_MULTI_AGENT_MODE": "PRIMARY"},
            supabase_url="https://example.supabase.co",
            service_role_key="service-key",
            market_client=object(),
            news_repo=None,
        )
    assert runner is None


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["SHADOW", "PRIMARY"])
async def test_shadow_and_primary_build_role_aware_runner(mode: str):
    async with AsyncExitStack() as stack:
        runner = await market_worker._build_multi_agent_runner(
            stack=stack,
            env=_env(mode),
            supabase_url="https://example.supabase.co",
            service_role_key="service-key",
            market_client=object(),
            news_repo=None,
        )
        assert runner is not None
        assert runner._config.mode is RolloutMode(mode)
        assert tuple(item.role for item in runner._config.assignments) == (AgentRole.TECHNICAL,)


@pytest.mark.asyncio
async def test_missing_role_credential_disables_multi_agent_without_raising():
    env = _env("PRIMARY")
    env.pop("GEMINI_API_KEY")
    async with AsyncExitStack() as stack:
        runner = await market_worker._build_multi_agent_runner(
            stack=stack,
            env=env,
            supabase_url="https://example.supabase.co",
            service_role_key="service-key",
            market_client=object(),
            news_repo=None,
        )
    assert runner is None


def test_run_forever_constructs_and_passes_multi_agent_runner_after_persistence_hook():
    source = inspect.getsource(market_worker.run_forever)
    assert "_build_multi_agent_runner(" in source
    assert "multi_agent_runner=multi_agent_runner" in source


def test_shadow_path_has_no_strategy_or_simulation_dependency():
    source = inspect.getsource(market_worker)
    assert "btc_core.strategy" not in source
    assert "btc_core.simulation" not in source
