from __future__ import annotations

from datetime import datetime, timezone

import httpx
import pytest

from btc_core.strategy.multi_agent_order_runtime import create_multi_agent_order_intents

RUN_ID = "11111111-1111-4111-8111-111111111111"
NOW = datetime(2026, 9, 13, 6, 0, tzinfo=timezone.utc)


class ContractMismatchRepo:
    def __init__(self, *, rollout_mode: str, status: str):
        self.rollout_mode = rollout_mode
        self.status = status
        self.calls: list[str] = []

    async def _request(self, method, path, **kwargs):
        self.calls.append(path)
        if method == "GET" and path == "/ai_multi_agent_runs":
            return httpx.Response(200, json=[{
                "id": RUN_ID,
                "scanner_candidate_id": 42,
                "symbol": "BTCUSDT",
                "timeframe": "15m",
                "started_at": NOW.isoformat(),
                "completed_at": NOW.isoformat(),
                "status": self.status,
                "rollout_mode": self.rollout_mode,
            }])
        raise AssertionError("persisted run contract mismatch must fail closed before downstream reads")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("rollout_mode", "status"),
    [("SHADOW", "COMPLETED"), ("PRIMARY", "RUNNING")],
)
async def test_primary_runtime_revalidates_persisted_run_contract(rollout_mode, status):
    repo = ContractMismatchRepo(rollout_mode=rollout_mode, status=status)

    assert await create_multi_agent_order_intents(repo, "PRIMARY") == []
    assert repo.calls == ["/ai_multi_agent_runs"]
