from datetime import datetime, timedelta, timezone

import pytest

from btc_core.strategy.simulation import (
    AccountState,
    Bar,
    FundingObservation,
    PaperTradeEngine,
    TradeSetup,
    TradeStatus,
)


def setup(**kwargs):
    base = dict(analysis_id=11, symbol="BTCUSDT", side="LONG", timeframe="15m",
                signal_created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                entry_min=100, entry_max=102, stop_loss=95, take_profits=(105, 110, 115),
                quantity=1, leverage=2, risk_amount=5, full_risk_approved=True)
    base.update(kwargs)
    return TradeSetup(**base)


def bar(at, low, high, close=None):
    return Bar(timestamp=at, open=close or low, high=high, low=low, close=close or low)


def test_eligible_analysis_creates_one_pending_trade_and_replay_is_idempotent():
    engine = PaperTradeEngine(AccountState(balance=1000))
    trade = engine.create_pending(setup())
    assert trade.status is TradeStatus.PENDING_ENTRY
    assert engine.create_pending(setup()) is trade
    assert len(engine.trades) == 1


def test_entry_expires_after_60_minutes_without_chasing():
    engine = PaperTradeEngine(AccountState(balance=1000))
    trade = engine.create_pending(setup())
    t0 = trade.signal_created_at
    engine.process([bar(t0 + timedelta(minutes=61), 103, 104)])
    assert trade.status is TradeStatus.EXPIRED
    assert trade.simulated_entry_price is None


def test_entry_fee_slippage_and_equal_tp_ladder_then_sl():
    engine = PaperTradeEngine(AccountState(balance=1000))
    trade = engine.create_pending(setup())
    t0 = trade.signal_created_at
    engine.process([bar(t0 + timedelta(minutes=15), 101, 101),
                    bar(t0 + timedelta(minutes=30), 104, 106),
                    bar(t0 + timedelta(minutes=45), 109, 111),
                    bar(t0 + timedelta(minutes=60), 90, 116)])
    assert trade.status is TradeStatus.SL_EXIT
    assert trade.highest_tp_reached == 2
    assert trade.fills == 4
    assert trade.fees_paid == pytest.approx(0.10166633333333333)


def test_same_candle_tp_and_sl_chooses_sl_and_missing_funding_is_partial():
    engine = PaperTradeEngine(AccountState(balance=1000))
    trade = engine.create_pending(setup())
    t0 = trade.signal_created_at
    engine.process([bar(t0 + timedelta(minutes=15), 95, 106)])
    assert trade.status is TradeStatus.SL_EXIT
    assert trade.highest_tp_reached == 0
    assert trade.funding_quality == "PARTIAL"


def test_funding_and_reconciliation_updates_balance_equity_and_drawdown():
    account = AccountState(balance=1000)
    engine = PaperTradeEngine(account)
    trade = engine.create_pending(setup())
    t0 = trade.signal_created_at
    engine.process([bar(t0 + timedelta(minutes=15), 100, 101), bar(t0 + timedelta(minutes=30), 94, 96)],
                   funding=[FundingObservation(t0 + timedelta(minutes=15), .001)])
    assert account.balance < 1000
    assert account.equity == pytest.approx(account.balance)
    assert account.max_drawdown_percent >= 0
