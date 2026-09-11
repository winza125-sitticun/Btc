from pathlib import Path


def test_phase_8_9_dashboard_contract_is_present_and_safe():
    root = Path(__file__).parents[1]
    source = "\n".join((root / "apps/web/src" / name).read_text(encoding="utf-8") for name in ("App.tsx", "api.ts"))
    for text in (
        "NOT_READY", "PAPER_READY", "LIVE_READY", "BLOCKED",
        "Live execution remains disabled. LIVE_READY means readiness checks passed; it does not submit orders.",
        "DRY RUN — NOT SUBMITTED", "Insufficient sample", "analysis/trade IDs",
    ):
        assert text in source
    assert "type=\"password\"" not in source
    assert "exchange_submission_allowed" not in source or "DRY RUN" in source
