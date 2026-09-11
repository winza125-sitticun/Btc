from pathlib import Path


def test_source_has_no_private_order_submission_and_defaults_are_safe():
    root = Path(__file__).parents[1]
    source = "\n".join(p.read_text(encoding="utf-8") for p in root.rglob("*.py") if "tests" not in p.parts)
    assert "/fapi/v1/order" not in source.lower()
    assert "post order" not in source.lower()
    env = (root / ".env.example").read_text(encoding="utf-8")
    for line in ("TRADING_MODE=SIMULATION", "DIRECT_AI_ORDER_ENABLED=false", "LIVE_ORDER_EXECUTION_ENABLED=false", "ORDER_INTENT_DRY_RUN_ENABLED=false"):
        assert line in env
