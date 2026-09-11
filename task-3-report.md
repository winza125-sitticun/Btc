# Task 3 report — Signal outcome evaluator

## Files

- `btc_core/strategy/outcomes.py` — immutable OHLC/spec/outcome models and pure bounded evaluator.
- `btc_core/strategy/repository.py` — bounded Supabase analysis/outcome/candle methods and public fallback callback boundary.
- `tests/test_signal_outcomes.py` — LONG/SHORT/WAIT/no-fill, stop-first, missing-data and signed excursion coverage.
- `tests/test_strategy_repository.py` — idempotent upsert and exact candle query/fallback coverage.

## Verification

- RED attempt: `python -m pytest tests/test_signal_outcomes.py -q` could not start because no Python executable is on the default PATH.
- Focused GREEN: `C:\Users\q739\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m pytest tests/test_signal_outcomes.py tests/test_strategy_repository.py -q` → `6 passed`.
- Full suite: same bundled Python with `-m pytest -q` → `140 passed, 2 warnings` (pre-existing dependency deprecation warnings).

## Safety and concerns

The evaluator performs no network or repository I/O and returns frozen Pydantic models. Repository writes target only `market_ai_signal_outcomes` with `(ai_analysis_id,horizon)` conflict resolution. Candle reads are symbol/time-window bounded to 1,500 rows; fallback is an injected callback intended for public Binance klines and is never used for private exchange calls. Missing paths return `MISSING`/`PENDING` rather than fabricating WIN or LOSS. Partial paths remain `PARTIAL`.

## Commit

Commit: `feat: evaluate AI signal outcomes`
