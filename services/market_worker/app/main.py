from __future__ import annotations

import asyncio
import os

from btc_core.market.binance_usdm import BinanceUsdMClient
from btc_core.market.scanner import BinanceOpportunityScanner


def _env_int(name: str, default: int, *, minimum: int, maximum: int) -> int:
    raw = os.getenv(name)
    value = default if raw is None else int(raw)
    return max(minimum, min(maximum, value))


async def scan_once() -> str:
    timeframe = os.getenv("SCANNER_TIMEFRAME", "15m")
    universe_limit = _env_int("SCANNER_UNIVERSE_LIMIT", 30, minimum=1, maximum=200)
    candidate_limit = _env_int("SCANNER_CANDIDATE_LIMIT", 10, minimum=1, maximum=universe_limit)
    concurrency = _env_int("SCANNER_CONCURRENCY", 5, minimum=1, maximum=20)

    async with BinanceUsdMClient() as client:
        scanner = BinanceOpportunityScanner(client=client, concurrency=concurrency)
        result = await scanner.scan(
            timeframe=timeframe,
            universe_limit=universe_limit,
            candidate_limit=candidate_limit,
        )
    return result.model_dump_json(indent=2)


def main() -> None:
    print(asyncio.run(scan_once()))


if __name__ == "__main__":
    main()
