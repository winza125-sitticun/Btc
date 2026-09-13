from __future__ import annotations

import asyncio
from pathlib import Path
import runpy


def test_market_worker_module_execution_starts_realtime_loop(monkeypatch) -> None:
    calls: list[str] = []

    def fake_asyncio_run(coroutine):
        calls.append(coroutine.cr_code.co_name)
        coroutine.close()
        return None

    monkeypatch.setattr(asyncio, "run", fake_asyncio_run)
    monkeypatch.setenv("MARKET_WORKER_MODE", "realtime")

    module_path = Path("services/market_worker/app/main.py")
    runpy.run_path(str(module_path), run_name="__main__")

    assert calls == ["run_forever"]
