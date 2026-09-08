from datetime import datetime, timezone

from btc_core.market.realtime import (
    LiveMarketAggregator,
    build_usdm_stream_urls,
    parse_realtime_message,
)


def test_build_usdm_stream_urls_uses_2026_split_market_and_public_paths():
    urls = build_usdm_stream_urls(["BTCUSDT", "solusdt"], "15m")

    assert urls.market.startswith("wss://fstream.binance.com/market/stream?streams=")
    assert "btcusdt@markPrice@1s" in urls.market
    assert "btcusdt@kline_15m" in urls.market
    assert "solusdt@markPrice@1s" in urls.market
    assert urls.public.startswith("wss://fstream.binance.com/public/stream?streams=")
    assert "btcusdt@bookTicker" in urls.public
    assert "solusdt@bookTicker" in urls.public


def test_parse_mark_price_combined_message():
    event = parse_realtime_message(
        {
            "stream": "btcusdt@markPrice@1s",
            "data": {
                "e": "markPriceUpdate",
                "E": 1_725_000_000_000,
                "s": "BTCUSDT",
                "p": "62000.50",
                "i": "61980.25",
                "r": "0.0001",
            },
        }
    )

    assert event.kind == "MARK_PRICE"
    assert event.symbol == "BTCUSDT"
    assert event.mark_price == 62000.50
    assert event.index_price == 61980.25
    assert event.funding_rate == 0.0001
    assert event.event_time.tzinfo == timezone.utc


def test_parse_book_ticker_and_closed_kline_then_aggregate_state():
    aggregator = LiveMarketAggregator()
    mark = parse_realtime_message(
        {
            "stream": "solusdt@markPrice@1s",
            "data": {"e": "markPriceUpdate", "E": 1_725_000_000_000, "s": "SOLUSDT", "p": "150", "i": "149.8", "r": "0.0002"},
        }
    )
    book = parse_realtime_message(
        {
            "stream": "solusdt@bookTicker",
            "data": {"e": "bookTicker", "E": 1_725_000_000_500, "s": "SOLUSDT", "b": "149.90", "a": "150.10"},
        }
    )
    kline = parse_realtime_message(
        {
            "stream": "solusdt@kline_15m",
            "data": {
                "e": "kline",
                "E": 1_725_000_001_000,
                "s": "SOLUSDT",
                "k": {
                    "t": 1_724_999_100_000,
                    "T": 1_725_000_000_000,
                    "i": "15m",
                    "o": "148",
                    "h": "151",
                    "l": "147",
                    "c": "150",
                    "v": "1234",
                    "q": "185000",
                    "n": 321,
                    "V": "700",
                    "Q": "105000",
                    "x": True,
                },
            },
        }
    )

    assert aggregator.apply(mark) is None
    assert aggregator.apply(book) is None
    closed_candle = aggregator.apply(kline)
    state = aggregator.snapshot("SOLUSDT")

    assert state.mark_price == 150
    assert state.best_bid == 149.9
    assert state.best_ask == 150.1
    assert round(state.spread_percent, 6) == round((0.2 / 150) * 100, 6)
    assert state.candle_close == 150
    assert state.candle_timeframe == "15m"
    assert closed_candle is not None
    assert closed_candle.symbol == "SOLUSDT"
    assert closed_candle.timeframe == "15m"


def test_parse_unknown_control_message_returns_none():
    assert parse_realtime_message({"result": None, "id": 1}) is None
