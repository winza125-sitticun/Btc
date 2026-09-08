from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from websockets.asyncio.client import connect

from btc_core.market.models import Candle


BINANCE_USDM_MARKET_WS_BASE = "wss://fstream.binance.com/market"
BINANCE_USDM_PUBLIC_WS_BASE = "wss://fstream.binance.com/public"


def _utc_from_ms(value: int | float) -> datetime:
    return datetime.fromtimestamp(float(value) / 1000.0, tz=timezone.utc)


class UsdmStreamUrls(BaseModel):
    model_config = ConfigDict(extra="forbid")
    market: str
    public: str


class RealtimeMarketEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["MARK_PRICE", "BOOK_TICKER", "KLINE"]
    symbol: str
    event_time: datetime
    mark_price: float | None = Field(default=None, gt=0)
    index_price: float | None = Field(default=None, gt=0)
    funding_rate: float | None = None
    best_bid: float | None = Field(default=None, gt=0)
    best_ask: float | None = Field(default=None, gt=0)
    candle: Candle | None = None
    candle_closed: bool = False

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        return value.strip().upper()


class LiveMarketState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str
    mark_price: float | None = Field(default=None, gt=0)
    index_price: float | None = Field(default=None, gt=0)
    funding_rate: float | None = None
    best_bid: float | None = Field(default=None, gt=0)
    best_ask: float | None = Field(default=None, gt=0)
    spread_percent: float | None = Field(default=None, ge=0)
    candle_timeframe: str | None = None
    candle_open: float | None = Field(default=None, gt=0)
    candle_high: float | None = Field(default=None, gt=0)
    candle_low: float | None = Field(default=None, gt=0)
    candle_close: float | None = Field(default=None, gt=0)
    candle_volume: float | None = Field(default=None, ge=0)
    event_time: datetime | None = None

    @field_validator("symbol")
    @classmethod
    def normalize_state_symbol(cls, value: str) -> str:
        return value.strip().upper()


def build_usdm_stream_urls(symbols: list[str], timeframe: str) -> UsdmStreamUrls:
    normalized = sorted({item.strip().lower() for item in symbols if item.strip()})
    if not normalized:
        raise ValueError("at least one symbol is required")
    if len(normalized) > 500:
        raise ValueError("a realtime connection may track at most 500 symbols")

    market_streams: list[str] = []
    public_streams: list[str] = []
    for symbol in normalized:
        market_streams.extend((f"{symbol}@markPrice@1s", f"{symbol}@kline_{timeframe}"))
        public_streams.append(f"{symbol}@bookTicker")

    return UsdmStreamUrls(
        market=f"{BINANCE_USDM_MARKET_WS_BASE}/stream?streams={'/'.join(market_streams)}",
        public=f"{BINANCE_USDM_PUBLIC_WS_BASE}/stream?streams={'/'.join(public_streams)}",
    )


def parse_realtime_message(payload: dict[str, Any]) -> RealtimeMarketEvent | None:
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    event_type = data.get("e")
    if not event_type:
        return None

    event_time_ms = data.get("E") or data.get("T") or int(datetime.now(timezone.utc).timestamp() * 1000)
    event_time = _utc_from_ms(event_time_ms)
    symbol = str(data.get("s") or "").upper()
    if not symbol:
        return None

    if event_type == "markPriceUpdate":
        return RealtimeMarketEvent(
            kind="MARK_PRICE",
            symbol=symbol,
            event_time=event_time,
            mark_price=float(data["p"]),
            index_price=float(data["i"]),
            funding_rate=float(data.get("r", 0) or 0),
        )

    if event_type == "bookTicker":
        return RealtimeMarketEvent(
            kind="BOOK_TICKER",
            symbol=symbol,
            event_time=event_time,
            best_bid=float(data["b"]),
            best_ask=float(data["a"]),
        )

    if event_type == "kline" and isinstance(data.get("k"), dict):
        row = data["k"]
        candle = Candle(
            symbol=symbol,
            timeframe=str(row["i"]),
            open_time=_utc_from_ms(row["t"]),
            close_time=_utc_from_ms(row["T"]),
            open=float(row["o"]),
            high=float(row["h"]),
            low=float(row["l"]),
            close=float(row["c"]),
            volume=float(row["v"]),
            quote_volume=float(row.get("q", 0) or 0),
            trade_count=int(row.get("n", 0) or 0),
            taker_buy_base_volume=float(row.get("V", 0) or 0),
            taker_buy_quote_volume=float(row.get("Q", 0) or 0),
        )
        return RealtimeMarketEvent(
            kind="KLINE",
            symbol=symbol,
            event_time=event_time,
            candle=candle,
            candle_closed=bool(row.get("x", False)),
        )

    return None


class LiveMarketAggregator:
    def __init__(self) -> None:
        self._states: dict[str, LiveMarketState] = {}

    def apply(self, event: RealtimeMarketEvent | None) -> Candle | None:
        if event is None:
            return None
        current = self._states.get(event.symbol, LiveMarketState(symbol=event.symbol))
        updates: dict[str, Any] = {"event_time": event.event_time}

        if event.kind == "MARK_PRICE":
            updates.update(
                mark_price=event.mark_price,
                index_price=event.index_price,
                funding_rate=event.funding_rate,
            )
        elif event.kind == "BOOK_TICKER":
            bid = event.best_bid
            ask = event.best_ask
            midpoint = ((bid or 0) + (ask or 0)) / 2.0
            spread = 0.0 if midpoint <= 0 or bid is None or ask is None else max(((ask - bid) / midpoint) * 100.0, 0.0)
            updates.update(best_bid=bid, best_ask=ask, spread_percent=spread)
        elif event.kind == "KLINE" and event.candle is not None:
            candle = event.candle
            updates.update(
                candle_timeframe=candle.timeframe,
                candle_open=candle.open,
                candle_high=candle.high,
                candle_low=candle.low,
                candle_close=candle.close,
                candle_volume=candle.volume,
            )
            self._states[event.symbol] = current.model_copy(update=updates)
            return candle if event.candle_closed else None

        self._states[event.symbol] = current.model_copy(update=updates)
        return None

    def snapshot(self, symbol: str) -> LiveMarketState:
        normalized = symbol.strip().upper()
        if normalized not in self._states:
            raise KeyError(normalized)
        return self._states[normalized].model_copy(deep=True)

    def snapshots(self) -> list[LiveMarketState]:
        return [self._states[symbol].model_copy(deep=True) for symbol in sorted(self._states)]


class BinanceUsdMRealtimeClient:
    """Read-only Binance USDⓈ-M realtime market stream client.

    Binance split USD-M market streams in 2026: high-frequency book data uses
    /public while mark price and kline data use /market. This client keeps those
    connections separate and merges their events through an asyncio queue.
    """

    def __init__(self, *, open_timeout: float = 10.0, close_timeout: float = 5.0) -> None:
        self._open_timeout = open_timeout
        self._close_timeout = close_timeout

    async def _consume(self, url: str, queue: asyncio.Queue[RealtimeMarketEvent | Exception]) -> None:
        try:
            async with connect(
                url,
                open_timeout=self._open_timeout,
                close_timeout=self._close_timeout,
                ping_interval=None,
                max_queue=1024,
            ) as websocket:
                async for raw in websocket:
                    try:
                        payload = json.loads(raw)
                        if isinstance(payload, dict):
                            event = parse_realtime_message(payload)
                            if event is not None:
                                await queue.put(event)
                    except (ValueError, TypeError, KeyError):
                        continue
        except Exception as exc:  # surfaced through the merged iterator
            await queue.put(exc)

    async def events(self, symbols: list[str], timeframe: str, *, run_seconds: float) -> AsyncIterator[RealtimeMarketEvent]:
        if run_seconds <= 0:
            raise ValueError("run_seconds must be positive")
        urls = build_usdm_stream_urls(symbols, timeframe)
        queue: asyncio.Queue[RealtimeMarketEvent | Exception] = asyncio.Queue(maxsize=4096)
        tasks = [
            asyncio.create_task(self._consume(urls.market, queue)),
            asyncio.create_task(self._consume(urls.public, queue)),
        ]
        loop = asyncio.get_running_loop()
        deadline = loop.time() + run_seconds
        try:
            while True:
                remaining = deadline - loop.time()
                if remaining <= 0:
                    return
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=min(1.0, remaining))
                except TimeoutError:
                    if all(task.done() for task in tasks):
                        return
                    continue
                if isinstance(item, Exception):
                    raise item
                yield item
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
