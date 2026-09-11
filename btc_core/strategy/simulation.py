"""Pure, deterministic paper-trade matching and account reconciliation."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from math import isfinite


class TradeStatus(StrEnum):
    PENDING_ENTRY = "PENDING_ENTRY"
    OPEN = "OPEN"
    TP_EXIT = "TP_EXIT"
    SL_EXIT = "SL_EXIT"
    EXPIRED = "EXPIRED"
    CLOSED = "CLOSED"


@dataclass(frozen=True)
class Bar:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float


@dataclass(frozen=True)
class FundingObservation:
    timestamp: datetime
    rate: float


@dataclass(frozen=True)
class TradeSetup:
    analysis_id: int
    symbol: str
    side: str
    timeframe: str
    signal_created_at: datetime
    entry_min: float
    entry_max: float
    stop_loss: float
    take_profits: tuple[float, ...] = ()
    quantity: float = 0
    leverage: float = 1
    risk_amount: float = 0
    full_risk_approved: bool = False
    scanner_candidate_id: int | None = None
    full_risk_reasons: tuple[str, ...] = ()


@dataclass
class AccountState:
    balance: float = 1000.0
    equity: float | None = None
    realized_pnl: float = 0.0
    max_equity: float | None = None
    max_drawdown_percent: float = 0.0

    def __post_init__(self):
        if self.balance <= 0 or not isfinite(self.balance):
            raise ValueError("balance must be positive")
        self.equity = self.balance if self.equity is None else self.equity
        self.max_equity = self.equity if self.max_equity is None else max(self.max_equity, self.equity)

    def reconcile(self, pnl: float) -> None:
        self.realized_pnl += pnl
        self.balance += pnl
        self.equity = self.balance
        self.max_equity = max(self.max_equity or self.equity, self.equity)
        self.max_drawdown_percent = max(self.max_drawdown_percent, (self.max_equity - self.equity) / self.max_equity * 100)


@dataclass
class PaperTrade:
    setup: TradeSetup
    status: TradeStatus = TradeStatus.PENDING_ENTRY
    simulated_entry_price: float | None = None
    highest_tp_reached: int = 0
    remaining_quantity: float = field(init=False)
    fees_paid: float = 0.0
    slippage_cost: float = 0.0
    funding_paid: float = 0.0
    funding_quality: str = "MISSING"
    realized_pnl: float = 0.0
    fills: int = 0
    opened_at: datetime | None = None
    closed_at: datetime | None = None
    expired_at: datetime | None = None

    def __post_init__(self): self.remaining_quantity = self.setup.quantity
    @property
    def signal_created_at(self): return self.setup.signal_created_at
    @property
    def analysis_id(self): return self.setup.analysis_id


class PaperTradeEngine:
    FEE_RATE = 0.0005
    SLIPPAGE_RATE = 0.0002
    ENTRY_WINDOW = timedelta(minutes=60)

    def __init__(self, account: AccountState):
        self.account, self.trades = account, {}

    def create_pending(self, setup: TradeSetup) -> PaperTrade:
        if setup.analysis_id in self.trades: return self.trades[setup.analysis_id]
        if not setup.full_risk_approved or setup.side not in ("LONG", "SHORT"):
            raise ValueError("trade setup is not simulation eligible")
        if setup.quantity <= 0 or setup.leverage <= 0 or setup.leverage > 5 or setup.entry_min <= 0 or setup.entry_max < setup.entry_min:
            raise ValueError("invalid trade geometry")
        trade = PaperTrade(setup); self.trades[setup.analysis_id] = trade; return trade

    def process(self, bars: list[Bar], *, funding: list[FundingObservation] | None = None) -> None:
        funding = funding or []
        for trade in self.trades.values():
            if trade.status in (TradeStatus.PENDING_ENTRY, TradeStatus.OPEN):
                self._process_trade(trade, sorted(bars, key=lambda b: b.timestamp), funding)

    def _process_trade(self, trade, bars, funding):
        setup, long = trade.setup, trade.setup.side == "LONG"
        end = setup.signal_created_at + self.ENTRY_WINDOW
        for candle in bars:
            if candle.timestamp < setup.signal_created_at: continue
            if trade.status is TradeStatus.PENDING_ENTRY:
                if candle.timestamp > end:
                    trade.status, trade.expired_at = TradeStatus.EXPIRED, candle.timestamp; return
                if candle.low <= setup.entry_max and candle.high >= setup.entry_min:
                    raw = setup.entry_min if long else setup.entry_max
                    trade.simulated_entry_price = raw * (1 + self.SLIPPAGE_RATE if long else 1 - self.SLIPPAGE_RATE)
                    trade.opened_at, trade.status = candle.timestamp, TradeStatus.OPEN
                    self._fill_cost(trade, trade.simulated_entry_price, setup.quantity)
                    self._funding(trade, funding, candle.timestamp)
            if trade.status is TradeStatus.OPEN:
                sl_hit = candle.low <= setup.stop_loss if long else candle.high >= setup.stop_loss
                tps = sorted(set(setup.take_profits), reverse=not long)
                tp_hit = next((i + 1 for i, tp in enumerate(tps) if (candle.high >= tp if long else candle.low <= tp) and i + 1 > trade.highest_tp_reached), None)
                if sl_hit: self._exit(trade, setup.stop_loss, trade.remaining_quantity, TradeStatus.SL_EXIT, candle.timestamp); return
                if tp_hit:
                    qty = setup.quantity / len(tps)
                    self._exit(trade, tps[tp_hit - 1], min(qty, trade.remaining_quantity), TradeStatus.TP_EXIT if tp_hit == len(tps) else TradeStatus.OPEN, candle.timestamp)
                    trade.highest_tp_reached = tp_hit
                    if trade.remaining_quantity <= 1e-12: trade.status = TradeStatus.TP_EXIT; return

    def _fill_cost(self, trade, price, qty):
        notional = price * qty; trade.fees_paid += notional * self.FEE_RATE; trade.slippage_cost += notional * self.SLIPPAGE_RATE; trade.fills += 1

    def _funding(self, trade, observations, at):
        obs = [o for o in observations if o.timestamp <= at]
        if not obs: trade.funding_quality = "PARTIAL"; return
        rate = obs[-1].rate; direction = 1 if trade.setup.side == "LONG" else -1
        trade.funding_paid += trade.simulated_entry_price * trade.setup.quantity * rate * direction; trade.funding_quality = "FULL"

    def _exit(self, trade, price, qty, status, at):
        long = trade.setup.side == "LONG"; effective = price * (1 - self.SLIPPAGE_RATE if long else 1 + self.SLIPPAGE_RATE)
        gross = (effective - trade.simulated_entry_price) * qty * (1 if long else -1)
        self._fill_cost(trade, effective, qty); fee = effective * qty * self.FEE_RATE
        trade.realized_pnl += gross - fee - effective * qty * self.SLIPPAGE_RATE
        trade.remaining_quantity -= qty; trade.status = status; trade.closed_at = at
        if trade.remaining_quantity <= 1e-12:
            trade.realized_pnl -= trade.funding_paid; self.account.reconcile(trade.realized_pnl)
