from pathlib import Path


def test_phase_8_9_defaults_are_simulation_only():
    root = Path(__file__).parents[1]
    env = (root / ".env.example").read_text(encoding="utf-8")
    for line in (
        "TRADING_MODE=SIMULATION", "DIRECT_AI_ORDER_ENABLED=false",
        "LIVE_ORDER_EXECUTION_ENABLED=false", "OUTCOME_EVALUATION_ENABLED=false",
        "SIMULATION_ENGINE_ENABLED=false", "ALERTS_V1_ENABLED=false",
        "READINESS_V1_ENABLED=false", "ORDER_INTENT_DRY_RUN_ENABLED=false",
    ):
        assert line in env
    source = "\n".join(p.read_text(encoding="utf-8") for p in root.rglob("*.py") if "tests" not in p.parts)
    assert "/fapi/v1/order" not in source.lower()
