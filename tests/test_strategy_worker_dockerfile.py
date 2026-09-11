from pathlib import Path


def test_strategy_worker_deployment_contract_is_worker_and_safe():
    dockerfile = Path(__file__).resolve().parents[1] / "Dockerfile.strategy-worker"
    railway = Path(__file__).resolve().parents[1] / "railway.strategy-worker.toml"
    env_example = Path(__file__).resolve().parents[1] / ".env.example"
    assert dockerfile.exists()
    assert railway.exists()
    assert "services.strategy_worker.app.main" in dockerfile.read_text(encoding="utf-8")
    text = railway.read_text(encoding="utf-8")
    assert "[envs]" not in text
    assert 'builder = "RAILPACK"' in text
    assert 'startCommand = "python -m services.strategy_worker.app.main"' in text
    assert "LIVE_ORDER_EXECUTION_ENABLED=false" in env_example.read_text(encoding="utf-8")
    assert "true" not in text.lower().split("live_order_execution_enabled", 1)[-1].split("\n", 1)[0]
