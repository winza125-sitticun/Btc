from datetime import datetime, timedelta, timezone

from btc_core.strategy.metrics import compute_strategy_metrics


def _row(**overrides):
    row = {
        "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
        "status": "SUCCESS", "latency_ms": 1000, "data_quality": "FULL",
        "outcome": "WIN", "final_return_percent": 4.0,
        "mfe_percent": 5.0, "mae_percent": -1.0, "highest_tp_hit": 2,
        "stop_touched": False, "eligible": True, "simulated_trade": True,
    }
    row.update(overrides)
    return row


def test_metrics_compute_quality_performance_and_operational_stats():
    rows = [_row(), _row(created_at=datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc), outcome="LOSS", final_return_percent=-2.0, highest_tp_hit=0, stop_touched=True), _row(data_quality="PARTIAL", outcome="WIN", final_return_percent=99.0)]
    result = compute_strategy_metrics(rows, now=datetime(2026, 1, 2, tzinfo=timezone.utc), window="ALL")
    assert result.analysis_count == 3
    assert result.eligible_signal_count == 3
    assert result.simulated_trade_count == 2
    assert result.win_count == 1 and result.loss_count == 1
    assert result.win_rate == 50.0
    assert result.average_net_return == 1.0
    assert result.median_net_return == 1.0
    assert result.expectancy == 1.0
    assert result.profit_factor == 2.0
    assert result.no_fill_count == 0
    assert result.partial_data_count == 1
    assert result.provider_success_rate == 100.0
    assert result.median_latency_ms == 1000 and result.p95_latency_ms == 1000


def test_metrics_windows_exclude_old_rows_and_track_no_fill_and_drawdown():
    now = datetime(2026, 1, 2, tzinfo=timezone.utc)
    rows = [_row(created_at=now - timedelta(hours=1), outcome="NO_FILL", simulated_trade=False, eligible=False, final_return_percent=None), _row(created_at=now - timedelta(days=2), final_return_percent=50.0)]
    result = compute_strategy_metrics(rows, now=now, window="24H")
    assert result.analysis_count == 1
    assert result.no_fill_count == 1
    assert result.win_count == 0
    assert result.median_net_return is None

