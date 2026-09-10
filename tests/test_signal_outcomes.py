from datetime import datetime, timedelta, timezone

from btc_core.strategy.outcomes import OHLCBar, SignalSpec, evaluate_signal_outcome


def bar(at, *, high, low, close, open=None):
    return OHLCBar(timestamp=at, open=open or close, high=high, low=low, close=close)


def test_long_entry_then_tp1_is_a_win_with_signed_excursions():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    result = evaluate_signal_outcome(
        SignalSpec(direction="LONG", entry_min=100, entry_max=102, stop=95,
                   take_profits=(105, 110), signal_timestamp=start, horizon="1H"),
        (bar(start + timedelta(minutes=5), high=103, low=99, close=101),
         bar(start + timedelta(minutes=15), high=106, low=100, close=105)),
    )
    assert result.entry_touched is True
    assert result.highest_tp_hit == 1
    assert result.outcome == "WIN"
    assert result.mfe_percent == 4.95049505
    assert result.mae_percent == -1.98019802


def test_short_entry_then_stop_is_a_loss():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    result = evaluate_signal_outcome(
        SignalSpec(direction="SHORT", entry_min=100, entry_max=102, stop=106,
                   take_profits=(95,), signal_timestamp=start, horizon="1H"),
        (bar(start + timedelta(minutes=5), high=101, low=99, close=100),
         bar(start + timedelta(minutes=15), high=107, low=100, close=106)),
    )
    assert result.stop_touched is True
    assert result.outcome == "LOSS"
    assert result.final_return_percent == -4.95049505


def test_no_entry_is_no_fill_and_wait_has_no_position():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    bars = (bar(start + timedelta(minutes=5), high=99, low=98, close=98),)
    no_fill = evaluate_signal_outcome(SignalSpec(direction="LONG", entry_min=100, entry_max=102,
        stop=95, take_profits=(105,), signal_timestamp=start, horizon="1H"), bars)
    wait = evaluate_signal_outcome(SignalSpec(direction="WAIT", entry_min=100, entry_max=102,
        stop=95, take_profits=(105,), signal_timestamp=start, horizon="1H"), bars)
    assert no_fill.outcome == "NO_FILL"
    assert wait.outcome == "NEUTRAL" and wait.entry_touched is False


def test_same_candle_stop_wins_over_tp_and_missing_data_is_not_a_win():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    spec = SignalSpec(direction="LONG", entry_min=100, entry_max=100, stop=95,
                      take_profits=(105,), signal_timestamp=start, horizon="1H")
    result = evaluate_signal_outcome(spec, (bar(start + timedelta(minutes=5), high=106, low=94, close=100),))
    missing = evaluate_signal_outcome(spec, ())
    assert result.outcome == "LOSS" and result.stop_touched is True and result.highest_tp_hit == 0
    assert missing.data_quality == "MISSING" and missing.outcome not in {"WIN", "LOSS"}

def test_out_of_horizon_candle_does_not_change_return_or_mfe():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    result = evaluate_signal_outcome(SignalSpec(direction="LONG", entry_min=100, entry_max=100, stop=95, take_profits=(105,), signal_timestamp=start, horizon="1H"), (bar(start + timedelta(minutes=5), high=101, low=99, close=101), bar(start + timedelta(hours=2), high=200, low=200, close=200)))
    assert result.final_return_percent == 1 and result.mfe_percent == 1

def test_short_signed_excursions_and_long_horizons():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    result = evaluate_signal_outcome(SignalSpec(direction="SHORT", entry_min=100, entry_max=100, stop=110, take_profits=(90,), signal_timestamp=start, horizon="4H"), (bar(start + timedelta(hours=1), high=105, low=95, close=100), bar(start + timedelta(hours=4), high=102, low=90, close=92)))
    assert result.mfe_percent == 10 and result.mae_percent == -5 and result.highest_tp_hit == 1

def test_wait_and_exit_report_partial_or_missing_quality():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    wait = SignalSpec(direction="WAIT", entry_min=100, entry_max=100, stop=95, signal_timestamp=start, horizon="24H")
    exit_spec = wait.model_copy(update={"direction": "EXIT", "horizon": "4H"})
    assert evaluate_signal_outcome(wait, (bar(start + timedelta(hours=1), high=101, low=99, close=100),)).data_quality == "PARTIAL"
    assert evaluate_signal_outcome(exit_spec, ()).data_quality == "MISSING"
