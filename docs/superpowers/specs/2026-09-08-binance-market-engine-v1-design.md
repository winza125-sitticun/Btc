# Binance USD-M Market Engine V1 Design

## Scope
This milestone adds a read-only Binance USDⓈ-M perpetual futures market adapter and a market-only opportunity scanner. It never authenticates to Binance and cannot place, cancel, or modify orders.

## Data sources
- `GET /fapi/v1/exchangeInfo` for the tradable USDT perpetual universe.
- `GET /fapi/v1/ticker/24hr` for liquidity/volume ranking.
- `GET /fapi/v1/klines` for OHLCV, quote volume, trade count, and taker-buy quote volume.
- `GET /fapi/v1/premiumIndex` for mark price, index price, and latest funding rate.
- `GET /futures/data/openInterestHist` for short-term OI change.
- `GET /futures/data/globalLongShortAccountRatio` for market positioning context.
- `GET /fapi/v1/ticker/bookTicker` for best bid/ask and spread.

## Components
1. `btc_core.market.models` defines normalized immutable Pydantic records.
2. `btc_core.market.binance_usdm` owns public REST transport, validation, normalization, timeout/error mapping, and rate-limit-safe request boundaries.
3. `btc_core.market.features` turns normalized snapshots into deterministic market feature scores and a LONG/SHORT/WAIT market direction.
4. `btc_core.market.scanner` ranks the top-volume perpetual contracts and returns market-only scanner candidates.
5. `services.market_worker` provides a one-shot worker entry point. Continuous WebSocket ingestion is the next sub-milestone.

## Scanner behavior
The scanner first selects the highest 24h quote-volume USDT perpetual symbols, then limits concurrency while collecting deeper metrics. It never sends every listed pair to an AI provider. Feature scores feed the existing weighted `OpportunityInputs` contract. News, macro, and risk/reward are set to neutral 50 in this market-only milestone and are explicitly marked as not yet enriched.

## Safety and reliability
- Public market endpoints only; no API key fields exist in the client.
- Every request has a finite timeout and Binance error responses raise typed errors.
- Symbol/timeframe inputs are normalized and validated.
- Scanner concurrency is bounded.
- A failure on one symbol does not abort the entire scan; failed symbols are reported separately.
- Default trading mode remains SIMULATION and this milestone does not alter execution code.

## Verification
Unit tests use `httpx.MockTransport`, not the Binance network. Tests cover universe filtering, kline normalization, snapshot assembly, LONG/SHORT feature direction, volume selection, bounded ranking, and per-symbol failure isolation. Existing backend tests and the web build must remain green in GitHub Actions.
