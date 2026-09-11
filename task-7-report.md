# Task 7 implementation report

Implemented strategy metrics and simulation-only experiment registry.

- Added `btc_core/strategy/metrics.py` with bounded rolling `24H`, `7D`, `30D`, and `ALL` aggregation, quality-aware outcome statistics, drawdown, TP/SL rates, and provider latency/success metrics.
- Added `btc_core/strategy/experiments.py` with an immutable lifecycle (`DRAFT -> SIMULATION -> PROMOTABLE|REJECTED -> ARCHIVED`) and an explicit guard against production configuration mutation.
- Added repository upsert/read methods for sanitized metrics and experiment records.
- Added focused contract tests in `tests/test_strategy_metrics.py` and `tests/test_strategy_experiments.py`.

Verification: `git diff --check` passed. The workspace has no Python interpreter/pytest executable available, so the focused test command could not be run locally; CI should run `pytest tests/test_strategy_metrics.py tests/test_strategy_experiments.py tests/test_strategy_repository.py -q`.

Commit SHA: to be filled after commit.
