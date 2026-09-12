"""Pure, deterministic paper-trade matching and account reconciliation."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from math import isfinite
from uuid import UUID


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
    analysis_id: int | None
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
    multi_agent_run_id: str | None = None

    def __post_init__(self) -> None:
        analysis_valid = type(self.analysis_id) is int and self.analysis_id > 0
        run_valid = False
        if isinstance(self.multi_agent_run_id, str) and self.multi_agent_run_id.strip():
            try:
                UUID(self.multi_agent_run_id.strip())
                run_valid = True
            except ValueError:
                run_valid = False
        if analysis_valid == run_valid:
            raise ValueError("exactly one analysis source is required")
        if self.analysis_id is not None and not analysis_valid:
            raise ValueError("analysis_id must be a positive integer")
        if self.multi_agent_run_id is not None and not run_valid:
            raise ValueError("multi_agent_run_id must be a UUID")

    @property
    def source_key(self):
        if self.analysis_id is not None:
            return self.analysis_id
        return f"multi-agent:{self.multi_agent_run_id}"


@dataclass
class AccountState:
    balance: float = 1000.0
    equity: float | None = None
    realized_pnl: float = 0.0
    gross_realized_pnl: float = 0.0
    max_equity: float | None = None
    max_drawdown_percent: float = 0.0

    def __post_init__(self):
        if self.balance <= 0 or not isfinite(self.balance):
            raise ValueError("balance must be positive")
        self.equity = self.balance if self.equity is None else self.equity
        self.max_equity = self.equity if self.max_equity is None else max(self.max_equity, self.equity)

    def reconcile(self, pnl: float, *, gross_pnl: float = 0.0) -> None:
        self.realized_pnl += pnl
        self.gross_realized_pnl += gross_pnl
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
    gross_realized_pnl: float = 0.0
    fills: int = 0
    opened_at: datetime | None = None
    closed_at: datetime | None = None
    expired_at: datetime | None = None
    accounted_costs: float = 0.0
    accounted_funding: float = 0.0
    accounted_gross: float = 0.0
    funding_timestamps: set[datetime] = field(default_factory=set)

    def __post_init__(self): self.remaining_quantity = self.setup.quantity
    @property
    def signal_created_at(self): return self.setup.signal_created_at
    @property
    def analysis_id(self): return self.setup.analysis_id
    @property
    def multi_agent_run_id(self): return self.setup.multi_agent_run_id


class PaperTradeEngine:
    FEE_RATE = 0.0005
    SLIPPAGE_RATE = 0.0002
    ENTRY_WINDOW = timedelta(minutes=60)

    def __init__(self, account: AccountState):
        self.account, self.trades = account, {}

    def create_pending(self, setup: TradeSetup) -> PaperTrade:
        source_key = setup.source_key
        if source_key in self.trades: return self.trades[source_key]
        if not setup.full_risk_approved or setup.side not in ("LONG", "SHORT"):
            raise ValueError("trade setup is not simulation eligible")
        if setup.quantity <= 0 or setup.leverage <= 0 or setup.leverage > 5 or setup.entry_min <= 0 or setup.entry_max < setup.entry_min:
            raise ValueError("invalid trade geometry")
        trade = PaperTrade(setup); self.trades[source_key] = trade; return trade

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
                self._funding(trade, funding, candle.timestamp)
                sl_hit = candle.low <= setup.stop_loss if long else candle.high >= setup.stop_loss
                tps = sorted(set(setup.take_profits), reverse=not long)
                tp_hit = next((i + 1 for i, tp in enumerate(tps) if (candle.high >= tp if long else candle.low <= tp) and i + 1 > trade.highest_tp_reached), None)
                if sl_hit: self._exit(trade, setup.stop_loss, trade.remaining_quantity, TradeStatus.SL_EXIT, candle.timestamp); return
                if tp_hit:
                    for level in range(trade.highest_tp_reached, len(tps)):
                        touched = candle.high >= tps[level] if long else candle.low <= tps[level]
                        if not touched:
                            break
                        qty = min(setup.quantity / len(tps), trade.remaining_quantity)
                        self._exit(trade, tps[level], qty, TradeStatus.TP_EXIT if level == len(tps) - 1 else TradeStatus.OPEN, candle.timestamp)
                        trade.highest_tp_reached = level + 1
                        if trade.remaining_quantity <= 1e-12: return

    def _fill_cost(self, trade, price, qty):
        notional = price * qty; trade.fees_paid += notional * self.FEE_RATE; trade.slippage_cost += notional * self.SLIPPAGE_RATE; trade.fills += 1

    def _funding(self, trade, observations, at):
        if trade.opened_at is None: return
        obs = [o for o in observations if trade.opened_at < o.timestamp <= at and o.timestamp not in trade.funding_timestamps]
        if not obs:
            if not any(o.timestamp > trade.opened_at for o in observations): trade.funding_quality = "PARTIAL"
            return
        direction = 1 if trade.setup.side == "LONG" else -1
        for observation in obs:
            trade.funding_paid += trade.simulated_entry_price * trade.remaining_quantity * observation.rate * direction
            trade.funding_timestamps.add(observation.timestamp)
        trade.funding_quality = "FULL"

    def _exit(self, trade, price, qty, status, at):
        long = trade.setup.side == "LONG"; effective = price * (1 - self.SLIPPAGE_RATE if long else 1 + self.SLIPPAGE_RATE)
        gross = (effective - trade.simulated_entry_price) * qty * (1 if long else -1)
        self._fill_cost(trade, effective, qty)
        trade.gross_realized_pnl += gross
        trade.remaining_quantity -= qty; trade.status = status; trade.closed_at = at
        costs = trade.fees_paid + trade.slippage_cost
        net = (trade.gross_realized_pnl - trade.accounted_gross) - (costs - trade.accounted_costs) - (trade.funding_paid - trade.accounted_funding)
        trade.realized_pnl += net
        trade.accounted_costs, trade.accounted_funding, trade.accounted_gross = costs, trade.funding_paid, trade.gross_realized_pnl
        self.account.reconcile(net, gross_pnl=gross)