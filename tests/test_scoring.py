import pytest

from btc_core.scanner.scoring import OpportunityInputs, calculate_opportunity_score


def test_opportunity_score_uses_declared_weighted_components():
    inputs = OpportunityInputs(
        technical=80,
        momentum=70,
        volume=90,
        order_flow=60,
        open_interest=75,
        funding=50,
        liquidity=100,
        news=65,
        macro=40,
        risk_reward=85,
    )
    assert calculate_opportunity_score(inputs) == pytest.approx(73.65, abs=0.01)


def test_opportunity_score_rejects_component_above_100():
    with pytest.raises(ValueError):
        OpportunityInputs(
            technical=101,
            momentum=70,
            volume=90,
            order_flow=60,
            open_interest=75,
            funding=50,
            liquidity=100,
            news=65,
            macro=40,
            risk_reward=85,
        )
