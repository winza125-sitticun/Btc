import pytest

from btc_core.simulation.models import PositionSide, SimulationPosition


def test_long_position_unrealized_pnl_subtracts_costs():
    position = SimulationPosition(
        symbol="SOLUSDT",
        side=PositionSide.LONG,
        entry_price=100,
        quantity=2,
        leverage=5,
        fees_paid=0.2,
        funding_paid=0.1,
        slippage_cost=0.1,
    )
    assert position.unrealized_pnl(105) == pytest.approx(9.6)


def test_short_position_profit_when_mark_price_falls():
    position = SimulationPosition(
        symbol="BTCUSDT",
        side=PositionSide.SHORT,
        entry_price=100,
        quantity=2,
        leverage=3,
    )
    assert position.unrealized_pnl(95) == pytest.approx(10)
