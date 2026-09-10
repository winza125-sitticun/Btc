# Task 3 review round report

Review fixes: horizon-bounded final close/return; partial persisted candle coverage now invokes the bounded fallback; missing-outcome discovery scopes `SUCCESS` analyses and all supported directions; WAIT/EXIT now preserve FULL/PARTIAL/MISSING quality; added 4H/24H and signed SHORT regression coverage; private-named fallback callbacks are rejected and fallback remains explicitly bounded to 1,500 rows.

Verification: bundled Python focused suite `11 passed`; full suite `145 passed, 2 warnings`.

Fix commit SHA: `26bdf34a095b1f6ba0b787bcdfa3efe258e8b93c`.

Round 3 concrete-adapter fix SHA: `a19d9a865d38a6e1d35422b796a02747cbdfc2d7`.
The adapter owns the fixed `https://fapi.binance.com/fapi/v1/klines` request and accepts only injected HTTP transport; arbitrary callbacks cannot be supplied or invoked.

Round 4 subclass-bypass fix SHA: `c7d72fc0087845b426f936ec49f155157fe338cd`. `candles` now requires the exact concrete adapter type, with regression coverage proving overridden `__call__` is neither accepted nor invoked. Focused suite: `12 passed`.
