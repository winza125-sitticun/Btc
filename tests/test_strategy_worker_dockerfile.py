from pathlib import Path


def test_strategy_worker_deployment_contract_is_worker_and_safe():
    dockerfile = Path(__file__).resolve().parents[1] / "Dockerfile.strategy-worker"
    railway = Path(__file__).resolve().parents[1] / "railway.strategy-worker.toml"
    assert dockerfile.exists()
    assert railway.exists()
    assert "services.strategy_worker.app.main" in dockerfile.read_text(encoding="utf-8")
    text = railway.read_text(encoding="utf-8")
    assert "STRATEGY_WORKER_ENABLED" in text
    assert "LIVE_ORDER_EXECUTION_ENABLED" in text
    assert "[envs]" not in text
    assert 'builder = "NIXPACKS"' in text
    assert "true" not in text.lower().split("live_order_execution_enabled", 1)[-1].split("\n", 1)[0]
