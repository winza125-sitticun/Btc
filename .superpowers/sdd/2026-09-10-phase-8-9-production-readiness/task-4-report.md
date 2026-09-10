# Task 4 report — Full simulation risk and position sizing

Implemented immutable `FullRiskContext` and `PositionSize` plus pure
`evaluate_full_risk(...)` and `size_position(...)` in
`btc_core/strategy/risk.py`. Existing `RiskPolicy` defaults were not changed;
no live execution or exchange submission path was added.

## TDD evidence

- RED: `python -m pytest tests/test_full_risk_context.py tests/test_risk_engine.py -q`
  initially failed because the new module did not exist.
- GREEN: `C:\Users\q739\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m pytest tests/test_full_risk_context.py tests/test_risk_engine.py -q`
  — `23 passed in 0.18s` (including non-finite/non-numeric rejection tests).
- Initial implementation commit SHA: `0540236ae804ae31261682e88c6d47c9417efb52`.
- Review fix commit SHA: `50135f16d9f54e07eb6e5026fc908c6933746e69`.

## Safety/concerns

- Position sizing owns risk percentage and leverage caps; callers cannot pass a
  quantity or override policy leverage.
- Default target risk is 0.5%, capped at the policy's 1%; notional is capped at
  balance × policy max leverage (5x).
- Invalid account, entry, stop, or stop distance fails closed.
- Non-finite, non-numeric, out-of-range, and invalid-count risk context fails
  closed with `risk_context_invalid`.
- Event context can be required for readiness-sensitive evaluation; missing
  context is rejected with `event_context_missing`.
- Full repository verification was not run in this task; the focused risk
  suite and existing risk-engine suite passed.
