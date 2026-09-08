from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class _MarketModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MarketSymbol(_MarketModel):
    symbol: str
    pair: str
    base_asset: str
    quote_asset: str
    status: str
    contract_type: str
    price_precision: int = Field(ge=0)
    quantity_precision: int = Field(ge=0)

    @field_validator("symbol", "pair", "base_asset", "quote_asset", "status", "contract_type")
    @classmethod
    def normalize_upper(cls, value: str) -> str:
        return value.strip().upper()


class Ticker24h(_MarketModel):
    symbol: str
    last_price: float = Field(gt=0)
    price_change_percent: float
    quote_volume: float = Field(ge=0)
    observed_at: datetime

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        return value.strip().upper()


class Candle(_MarketModel):
    symbol: str
    timeframe: str
    open_time: datetime
    close_time: datetime
    open: float = Field(gt=0)
    high: float = Field(gt=0)
    low: float = Field(gt=0)
    close: float = Field(gt=0)
    volume: float = Field(ge=0)
    quote_volume: float = Field(ge=0)
    trade_count: int = Field(ge=0)
    taker_buy_base_volume: float = Field(ge=0)
    taker_buy_quote_volume: float = Field(ge=0)

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        return value.strip().upper()


class MarketSnapshot(_MarketModel):
    symbol: str
    timeframe: str
    candles: list[Candle] = Field(min_length=6)
    mark_price: float = Field(gt=0)
    index_price: float = Field(gt=0)
    funding_rate: float
    open_interest: float = Field(ge=0)
    open_interest_value: float = Field(ge=0)
    open_interest_change_percent: float
    long_short_ratio: float = Field(gt=0)
    best_bid: float = Field(gt=0)
    best_ask: float = Field(gt=0)
    spread_percent: float = Field(ge=0)
    observed_at: datetime

    @field_validator("symbol")
    @classmethod
    def normalize_snapshot_symbol(cls, value: str) -> str:
        return value.strip().upper()
