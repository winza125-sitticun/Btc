# Task 7 implementation report

Implemented strategy metrics and simulation-only experiment registry.

- Added `btc_core/strategy/metrics.py` with bounded rolling `24H`, `7D`, `30D`, and `ALL` aggregation, quality-aware outcome statistics, drawdown, TP/SL rates, and provider latency/success metrics.
- Added `btc_core/strategy/experiments.py` with an immutable lifecycle (`DRAFT -> SIMULATION -> PROMOTABLE|REJECTED -> ARCHIVED`) and an explicit guard against production configuration mutation.
- Added repository upsert/read methods for sanitized metrics and experiment records.
- Added focused contract tests in `tests/test_strategy_metrics.py` and `tests/test_strategy_experiments.py`.

Verification: bundled Python focused tests passed: `10 passed` for `tests/test_strategy_metrics.py`, `tests/test_strategy_experiments.py`, and `tests/test_strategy_repository.py`; `git diff --check` passed.

Implementation commit SHA: `9a9e34a0001ab815eb1717c53d38edc56046fe83`.
Review-fix commit SHA: `a85a7157a496a8fc8203ddd5ba32f5fb8a03bfd5`.
