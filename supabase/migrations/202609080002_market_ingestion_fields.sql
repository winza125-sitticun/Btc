-- Market-ingestion fields required by the Binance USD-M public-data adapter.
alter table public.market_candles
  add column if not exists taker_buy_base_volume numeric,
  add column if not exists taker_buy_quote_volume numeric;

comment on column public.market_candles.taker_buy_base_volume is
  'Base-asset volume bought by takers in the candle.';
comment on column public.market_candles.taker_buy_quote_volume is
  'Quote-asset volume bought by takers in the candle.';
