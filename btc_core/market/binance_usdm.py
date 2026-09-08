from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

import httpx

from btc_core.market.models import Candle, MarketSnapshot, MarketSymbol, Ticker24h


BINANCE_USDM_BASE_URL = "https://fapi.binance.com"
SUPPORTED_RATIO_PERIODS = {"5m", "15m", "30m", "1h", "2h", "4h", "6h", "12h", "1d"}


class BinanceMarketDataError(RuntimeError):
    def __init__(self, message: str, *, code: int | None = None, status_code: int | None = None):
        super().__init__(message)
        self.code = code
        self.status_code = status_code


def _utc_from_ms(value: int | float) -> datetime:
    return datetime.fromtimestamp(float(value) / 1000.0, tz=timezone.utc)


def _ratio_period(timeframe: str) -> str:
    normalized = timeframe.strip()
    if normalized in SUPPORTED_RATIO_PERIODS:
        return normalized
    if normalized in {"1m", "3m"}:
        return "5m"
    raise ValueError(f"unsupported derivatives statistics timeframe: {timeframe}")


class BinanceUsdMClient:
    """Read-only client for Binance USDⓈ-M public market endpoints."""

    def __init__(
        self,
        *,
        base_url: str = BINANCE_USDM_BASE_URL,
        timeout_seconds: float = 10.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=httpx.Timeout(timeout_seconds),
            transport=transport,
            headers={"User-Agent": "btc-ai-futures-trader/0.1"},
        )

    async def __aenter__(self) -> "BinanceUsdMClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _get(self, path: str, *, params: dict[str, Any] | None = None) -> Any:
        try:
            response = await self._client.get(path, params=params)
        except httpx.HTTPError as exc:
            raise BinanceMarketDataError(f"Binance market request failed: {exc}") from exc

        if response.is_error:
            code: int | None = None
            message = f"Binance market request failed with HTTP {response.status_code}"
            try:
                payload = response.json()
                if isinstance(payload, dict):
                    raw_code = payload.get("code")
                    code = int(raw_code) if raw_code is not None else None
                    message = str(payload.get("msg") or message)
            except (ValueError, TypeError):
                pass
            raise BinanceMarketDataError(message, code=code, status_code=response.status_code)

        try:
            return response.json()
        except ValueError as exc:
            raise BinanceMarketDataError("Binance returned invalid JSON", status_code=response.status_code) from exc

    async def list_usdt_perpetuals(self) -> list[MarketSymbol]:
        payload = await self._get("/fapi/v1/exchangeInfo")
        symbols: list[MarketSymbol] = []
        for item in payload.get("symbols", []):
            if item.get("quoteAsset") != "USDT":
                continue
            if item.get("contractType") != "PERPETUAL":
                continue
            if item.get("status") != "TRADING":
                continue
            symbols.append(
                MarketSymbol(
                    symbol=item["symbol"],
                    pair=item.get("pair", item["symbol"]),
                    base_asset=item["baseAsset"],
                    quote_asset=item["quoteAsset"],
                    status=item["status"],
                    contract_type=item["contractType"],
                    price_precision=int(item.get("pricePrecision", 8)),
                    quantity_precision=int(item.get("quantityPrecision", 8)),
                )
            )
        return symbols

    async def ticker_24h(self) -> list[Ticker24h]:
        payload = await self._get("/fapi/v1/ticker/24hr")
        items = payload if isinstance(payload, list) else [payload]
        now = datetime.now(timezone.utc)
        tickers: list[Ticker24h] = []
        for item in items:
            last_price = float(item.get("lastPrice", 0) or 0)
            if last_price <= 0:
                continue
            observed = _utc_from_ms(item["closeTime"]) if item.get("closeTime") else now
            tickers.append(
                Ticker24h(
                    symbol=item["symbol"],
                    last_price=last_price,
                    price_change_percent=float(item.get("priceChangePercent", 0) or 0),
                    quote_volume=float(item.get("quoteVolume", 0) or 0),
                    observed_at=observed,
                )
            )
        return tickers

    async def klines(self, symbol: str, timeframe: str, *, limit: int = 60) -> list[Candle]:
        if not 1 <= limit <= 1500:
            raise ValueError("kline limit must be between 1 and 1500")
        normalized_symbol = symbol.strip().upper()
        payload = await self._get(
            "/fapi/v1/klines",
            params={"symbol": normalized_symbol, "interval": timeframe, "limit": limit},
        )
        candles: list[Candle] = []
        for row in payload:
            candles.append(
                Candle(
                    symbol=normalized_symbol,
                    timeframe=timeframe,
                    open_time=_utc_from_ms(row[0]),
                    open=float(row[1]),
                    high=float(row[2]),
                    low=float(row[3]),
                    close=float(row[4]),
                    volume=float(row[5]),
                    close_time=_utc_from_ms(row[6]),
                    quote_volume=float(row[7]),
                    trade_count=int(row[8]),
                    taker_buy_base_volume=float(row[9]),
                    taker_buy_quote_volume=float(row[10]),
                )
            )
        return candles

    async def premium_index(self, symbol: str) -> dict[str, Any]:
        payload = await self._get("/fapi/v1/premiumIndex", params={"symbol": symbol.strip().upper()})
        if not isinstance(payload, dict):
            raise BinanceMarketDataError("Unexpected premium index payload")
        return payload

    async def open_interest_history(self, symbol: str, timeframe: str, *, limit: int = 2) -> list[dict[str, Any]]:
        return await self._get(
            "/futures/data/openInterestHist",
            params={"symbol": symbol.strip().upper(), "period": _ratio_period(timeframe), "limit": limit},
        )

    async def global_long_short_ratio(self, symbol: str, timeframe: str, *, limit: int = 1) -> list[dict[str, Any]]:
        return await self._get(
            "/futures/data/globalLongShortAccountRatio",
            params={"symbol": symbol.strip().upper(), "period": _ratio_period(timeframe), "limit": limit},
        )

    async def book_ticker(self, symbol: str) -> dict[str, Any]:
        payload = await self._get("/fapi/v1/ticker/bookTicker", params={"symbol": symbol.strip().upper()})
        if not isinstance(payload, dict):
            raise BinanceMarketDataError("Unexpected book ticker payload")
        return payload

    async def market_snapshot(self, symbol: str, timeframe: str, *, candle_limit: int = 60) -> MarketSnapshot:
        normalized_symbol = symbol.strip().upper()
        candles, premium, oi_history, ratios, book = await asyncio.gather(
            self.klines(normalized_symbol, timeframe, limit=candle_limit),
            self.premium_index(normalized_symbol),
            self.open_interest_history(normalized_symbol, timeframe, limit=2),
            self.global_long_short_ratio(normalized_symbol, timeframe, limit=1),
            self.book_ticker(normalized_symbol),
        )

        if len(oi_history) < 2:
            raise BinanceMarketDataError(f"Not enough open-interest history for {normalized_symbol}")
        if not ratios:
            raise BinanceMarketDataError(f"No long/short ratio data for {normalized_symbol}")

        previous_oi = float(oi_history[0]["sumOpenInterest"])
        current_oi = float(oi_history[-1]["sumOpenInterest"])
        oi_change = 0.0 if previous_oi == 0 else ((current_oi / previous_oi) - 1.0) * 100.0

        best_bid = float(book["bidPrice"])
        best_ask = float(book["askPrice"])
        midpoint = (best_bid + best_ask) / 2.0
        spread_percent = 0.0 if midpoint <= 0 else ((best_ask - best_bid) / midpoint) * 100.0

        observed_ms = premium.get("time") or book.get("time") or int(datetime.now(timezone.utc).timestamp() * 1000)
        return MarketSnapshot(
            symbol=normalized_symbol,
            timeframe=timeframe,
            candles=candles,
            mark_price=float(premium["markPrice"]),
            index_price=float(premium["indexPrice"]),
            funding_rate=float(premium.get("lastFundingRate", 0) or 0),
            open_interest=current_oi,
            open_interest_value=float(oi_history[-1].get("sumOpenInterestValue", 0) or 0),
            open_interest_change_percent=oi_change,
            long_short_ratio=float(ratios[-1]["longShortRatio"]),
            best_bid=best_bid,
            best_ask=best_ask,
            spread_percent=max(spread_percent, 0.0),
            observed_at=_utc_from_ms(observed_ms),
        )
