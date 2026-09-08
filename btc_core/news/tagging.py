from __future__ import annotations

import re

from btc_core.news.models import NormalizedArticle


FULL_ALIASES: dict[str, tuple[str, ...]] = {
    "BTCUSDT": ("bitcoin",),
    "SOLUSDT": ("solana",),
    "XRPUSDT": ("xrp", "ripple", "xrpl"),
    "ETHUSDT": ("ethereum", "ether"),
}

TICKERS: dict[str, str] = {
    "BTCUSDT": "BTC",
    "SOLUSDT": "SOL",
    "XRPUSDT": "XRP",
    "ETHUSDT": "ETH",
}

SYMBOL_ORDER = ("BTCUSDT", "SOLUSDT", "XRPUSDT", "ETHUSDT")


def _contains_alias(text: str, alias: str) -> bool:
    return re.search(rf"(?<![\w]){re.escape(alias)}(?![\w])", text, re.IGNORECASE) is not None


def _contains_upper_ticker(text: str, ticker: str) -> bool:
    return re.search(rf"(?<![A-Za-z0-9_]){re.escape(ticker)}(?![A-Za-z0-9_])", text) is not None


def tag_text(text: str) -> tuple[str, ...]:
    tagged: list[str] = []
    for symbol in SYMBOL_ORDER:
        aliases = FULL_ALIASES[symbol]
        if any(_contains_alias(text, alias) for alias in aliases) or _contains_upper_ticker(
            text, TICKERS[symbol]
        ):
            tagged.append(symbol)
    return tuple(tagged)


def tag_core_assets(article: NormalizedArticle) -> tuple[str, ...]:
    text = article.title if not article.summary else f"{article.title}\n{article.summary}"
    return tag_text(text)
