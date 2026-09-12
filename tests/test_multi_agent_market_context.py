from datetime import datetime, timezone

import pytest

from btc_core.ai.analysis import AINewsContext, AIAnalysisSnapshot, TimeframeTechnicalContext
from btc_core.ai.models import Direction
from btc_core.ai.multi_agent.market_context import derive_market_context
from btc_core.ai.multi_agent.models import FrozenSnapshotEnvelope
from btc_core.scanner.scoring import OpportunityInputs


def _envelope() -> FrozenSnapshotEnvelope:
    technical = {
        "4h": TimeframeTechnicalContext(timeframe="4h", close=100, trend_percent=0.5, momentum_percent=1.0, recent_high=110, recent_low=90, recent_volume_ratio=1.2, direction=Direction.LONG),
        "1h": TimeframeTechnicalContext(timeframe="1h", close=100, trend_percent=-0.25, momentum_percent=-0.5, recent_high=105, recent_low=95, recent_volume_ratio=1.0, direction=Direction.SHORT),
        "15m": TimeframeTechnicalContext(timeframe="15m", close=100, trend_percent=0.125, momentum_percent=0.25, recent_high=102, recent_low=98, recent_volume_ratio=0.8, direction=Direction.LONG),
    }
    snapshot = AIAnalysisSnapshot(
        symbol="BTCUSDT", timeframe="15m", scanner_direction=Direction.LONG,
        opportunity_score=70,
        components=OpportunityInputs(technical=80, momentum=70, volume=60, order_flow=50, open_interest=40, funding=50, liquidity=90, news=50, macro=50, risk_reward=50),
        last_price=100, funding_rate=0.0001, open_interest_change_percent=1.0,
        long_short_ratio=1.5, spread_percent=0.05,
        technical_by_timeframe=technical, news=AINewsContext(score=50, stories=()),
    )
    return FrozenSnapshotEnvelope(snapshot_ref="snap-ctx", observed_at=datetime(2026, 9, 12, 8, 0, tzinfo=timezone.utc), snapshot=snapshot)


def test_market_context_uses_exact_normalized_vortex_mapping():
    result = derive_market_context(_envelope())

    assert result.trend_strength == pytest.approx(0.7)
    assert result.volatility == pytest.approx(1.0)
    assert result.momentum == pytest.approx(0.2)
    assert result.order_flow_imbalance == pytest.approx(0.4)
    assert result.liquidity == pytest.approx(0.75)
    assert result.snapshot_ref == "snap-ctx"
    assert result.observed_at == datetime(2026, 9, 12, 8, 0, tzinfo=timezone.utc)
    assert result.mapping_version == "vortex-input-v1"


def test_market_context_values_are_quantized_to_six_decimals():
    dumped = derive_market_context(_envelope()).model_dump()
    for key in ("trend_strength", "volatility", "momentum", "order_flow_imbalance", "liquidity"):
        assert dumped[key] == round(dumped[key], 6)
