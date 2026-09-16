# REZ Analysis Layer V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the approved deterministic REZ Analysis Layer V1 to Scanner V6 as a HYBRID context/timing gate, preserving all existing V6 safety rules and keeping live/testnet order execution absent.

**Architecture:** Add three focused modules: a pure deterministic analysis module, a SQLite watch-state module, and a REZ calibration/report module. Integrate the analysis layer after the existing structure trade plan and before the unchanged Setup Score, with `PASS`, `WAIT`, and `REJECT` states. Persist `WAIT` watches in the existing Shadow SQLite database without altering existing Shadow snapshot/outcome semantics, and call Astra only after REZ `PASS` plus Setup Score `>=75`.

**Tech Stack:** Python 3.13 runtime, stdlib `unittest`, SQLite, existing `requests`, `tradingview-ta`, `google-genai`; no new dependency.

**Spec:** `docs/superpowers/specs/2026-09-16-rez-analysis-layer-v1-design.md`

## Global Constraints

- `REZ_ANALYSIS_ENABLED=false` must preserve current V6 behavior.
- Approved runtime behavior when enabled is HYBRID only.
- `SETUP_MIN_SCORE=75` remains unchanged.
- Existing minimum structure R:R remains unchanged.
- Existing market-provider lock and provider fallback remain unchanged.
- Use closed provider candles only for REZ structure and trigger confirmation.
- Do not mix Binance and Bybit candles inside one candidate evaluation.
- Astra remains Devil's Advocate only and cannot change LONG/SHORT direction.
- AI failure remains fail-closed.
- Telegram remains final-output only after REZ PASS, score gate, Astra approval, and cooldown.
- Decision-support only; no live or testnet order execution code.
- REZ V1 must not modify `setup_score_v6.py` scoring weights.
- Reuse `STRUCTURE_SWING_WINDOW`, `STRUCTURE_ATR_PERIOD`, and `STRUCTURE_ATR_BUFFER_MULT`.
- Default `REZ_WATCH_TTL_HOURS=12`.
- Default `REZ_ANALYSIS_VERSION=REZ_V1`.
- Keep the 80-symbol Railway runtime universe unchanged.
- Tests use stdlib `unittest`; external market, Telegram, and Gemini calls are mocked/faked.

---

## File Map

**Create**
- `scanner_v6/rez_analysis_v1.py` — pure deterministic 1H structure, 15m trigger, and HYBRID decision logic.
- `scanner_v6/rez_watch_v1.py` — SQLite watch state and append-only REZ analysis events in the existing Shadow DB file.
- `scanner_v6/rez_report_v1.py` — REZ-specific calibration joins/metrics and a small CLI report.
- `scanner_v6/tests/test_rez_analysis_v1.py` — structure, trigger, closed-candle, and HYBRID matrix tests.
- `scanner_v6/tests/test_rez_watch_v1.py` — watch identity, dedupe, promotion, invalidation, expiry, and snapshot-link tests.
- `scanner_v6/tests/test_rez_report_v1.py` — calibration aggregation tests.
- `scanner_v6/tests/test_rez_scanner_integration.py` — disabled-path preservation and scanner gate/Astra/Telegram orchestration tests.

**Modify**
- `scanner_v6/auto_scanner_v6.part00` — imports, REZ env configuration, lazy watch-store bootstrap.
- `scanner_v6/auto_scanner_v6.part02` — extend `analyze_with_ai(...)` with deterministic REZ metadata only.
- `scanner_v6/auto_scanner_v6.part03` — fetch 15m closed provider candles, invoke REZ after structure plan, persist WAIT/REJECT/PASS event, and gate Setup Score.
- `scanner_v6/auto_scanner_v6.part04` — link PASS event to Shadow snapshot and add REZ fields to Telegram output.
- `scanner_v6/requirements.txt` — no package additions; touch only if a task accidentally introduces a dependency, which is prohibited by this plan.

**Do not modify unless a regression proves necessary**
- `scanner_v6/setup_score_v6.py`
- `scanner_v6/shadow_eval_v6.part00`
- `scanner_v6/shadow_eval_v6.part01`
- `scanner_v6/shadow_eval_v6.part02`
- `scanner_v6/market_data_v6.py`

---

### Task 1: Deterministic REZ Analysis Core

**Files:**
- Create: `scanner_v6/rez_analysis_v1.py`
- Create: `scanner_v6/tests/test_rez_analysis_v1.py`

**Interfaces:**
- Consumes: provider candle dictionaries with keys `open_time`, `open`, `high`, `low`, `close`, `volume`, `close_time`; side `LONG|SHORT`; existing structure config values.
- Produces:
  - `RezAnalysisResult`
  - `analyze_rez_candidate(...) -> RezAnalysisResult`
  - `calculate_atr(candles, period) -> Optional[float]`
  - `find_confirmed_swings(candles, window) -> dict[str, list[dict]]`

Define the result contract exactly:

```python
from dataclasses import dataclass
from typing import Optional

@dataclass(frozen=True)
class RezAnalysisResult:
    analysis_version: str
    state: str                 # PASS | WAIT | REJECT
    structure_1h: str          # CONTINUATION | PULLBACK | REVERSAL | RANGE | UNKNOWN
    trigger_15m: str           # BREAKOUT | RETEST | RECLAIM | REJECTION | NO_TRIGGER
    supporting_triggers: tuple[str, ...]
    reason: str
    protected_swing_timestamp: Optional[int]
    protected_swing_price: Optional[float]
    trigger_level_kind: Optional[str]
    trigger_level_price: Optional[float]
    closed_1h_at_ms: Optional[int]
    closed_15m_at_ms: Optional[int]
```

For RANGE watch identity, set `protected_swing_timestamp` and `protected_swing_price` to the confirmed 1H range boundary used as the current trigger reference. This gives RANGE a deterministic anchor without treating it as directional protected structure.

- [ ] **Step 1: Write failing ATR/swing/BOS tests**

Add tests that construct closed candle dictionaries directly and verify: ATR rejects insufficient data, swings exclude edges, LONG/SHORT BOS require close plus ATR buffer, and wick-only breach is not BOS.

```python
import unittest
from rez_analysis_v1 import analyze_rez_candidate


def c(ts, o, h, l, close):
    return {
        "open_time": ts,
        "open": float(o), "high": float(h), "low": float(l), "close": float(close),
        "volume": 1.0,
        "close_time": ts + 3_599_999,
    }


class RezAnalysisCoreTests(unittest.TestCase):
    def test_wick_only_breach_does_not_confirm_long_bos(self):
        candles_1h = [
            c(0, 100, 102, 99, 101),
            c(1, 101, 105, 100, 103),
            c(2, 103, 110, 102, 104),
            c(3, 104, 106, 101, 102),
            c(4, 102, 111, 101, 104),  # wick through prior high, close does not clear buffer
            c(5, 104, 106, 103, 105),
        ]
        result = analyze_rez_candidate(
            side="LONG",
            candles_1h=candles_1h,
            candles_15m=[],
            atr_period=2,
            atr_buffer_mult=0.25,
            swing_window=1,
            analysis_version="REZ_V1",
        )
        self.assertNotEqual(result.structure_1h, "CONTINUATION")
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```bash
cd scanner_v6
python -m unittest tests.test_rez_analysis_v1 -v
```

Expected: import failure because `rez_analysis_v1.py` does not exist.

- [ ] **Step 3: Implement candle validation, ATR, confirmed swings, and BOS helpers**

Implement private helpers with no network or database access:

```python
def _valid_closed_candle(candle):
    try:
        o = float(candle["open"]); h = float(candle["high"])
        l = float(candle["low"]); close = float(candle["close"])
        open_time = int(candle["open_time"]); close_time = int(candle["close_time"])
    except (KeyError, TypeError, ValueError):
        return False
    return open_time < close_time and h >= max(o, close) and l <= min(o, close)


def calculate_atr(candles, period):
    if period <= 0 or len(candles) < period + 1:
        return None
    if not all(_valid_closed_candle(c) for c in candles[-(period + 1):]):
        return None
    ranges = []
    for i in range(len(candles) - period, len(candles)):
        cur, prev = candles[i], candles[i - 1]
        h, l, pc = float(cur["high"]), float(cur["low"]), float(prev["close"])
        ranges.append(max(h - l, abs(h - pc), abs(l - pc)))
    return sum(ranges) / period if ranges else None
```

`find_confirmed_swings(...)` must include both `price` and `timestamp=int(candle['close_time'])` in each returned swing object.

- [ ] **Step 4: Add failing 1H classification tests**

Cover these exact cases:

```python
def test_continuation_requires_same_side_bos_and_intact_protected_swing(): ...
def test_pullback_keeps_protected_swing_intact(): ...
def test_reversal_requires_invalidation_then_new_same_side_bos(): ...
def test_single_choch_without_new_bos_is_not_reversal(): ...
def test_overlapping_swings_classify_range(): ...
def test_missing_history_classifies_unknown_and_rejects(): ...
```

Each test must assert `state`, `structure_1h`, `protected_swing_timestamp`, and `trigger_level_price` where applicable.

- [ ] **Step 5: Implement 1H classification minimally**

Use these internal signatures:

```python
def _classify_1h_structure(
    *, side: str, candles: list[dict], atr_period: int,
    atr_buffer_mult: float, swing_window: int,
) -> dict:
    """Return structure, protected swing, trigger level, reason, closed timestamp."""
```

The returned dictionary must contain:

```python
{
    "structure": "CONTINUATION|PULLBACK|REVERSAL|RANGE|UNKNOWN",
    "protected_swing_timestamp": int | None,
    "protected_swing_price": float | None,
    "trigger_level_kind": str | None,
    "trigger_level_price": float | None,
    "closed_1h_at_ms": int | None,
    "invalidated": bool,
    "reason": str,
}
```

Use close-confirmed BOS with `buffer = ATR(1H) * atr_buffer_mult`; never classify wick-only breaks as BOS.

- [ ] **Step 6: Add failing 15m trigger tests**

Cover exact behavior:

```python
def test_breakout_requires_closed_close_beyond_level_plus_15m_buffer(): ...
def test_retest_requires_prior_breakout_then_return_to_zone(): ...
def test_reclaim_requires_close_back_on_valid_side(): ...
def test_liquidity_sweep_is_supporting_only(): ...
def test_rejection_requires_zone_touch_wick_at_least_body_and_valid_close(): ...
def test_opposite_breakout_returns_reject(): ...
def test_no_trigger_returns_wait_for_continuation_or_pullback(): ...
```

Represent 15m close times explicitly and assert the newest closed candle timestamp is carried to `closed_15m_at_ms`.

- [ ] **Step 7: Implement 15m trigger and HYBRID matrix**

Use these helpers:

```python
def _classify_15m_trigger(
    *, side: str, candles: list[dict], trigger_level: float,
    atr_period: int, atr_buffer_mult: float, swing_window: int,
) -> dict: ...


def _hybrid_state(structure: str, trigger: str, opposite_trigger: bool) -> tuple[str, str]: ...
```

The matrix must be literal and auditable:

```python
PASS = {
    "CONTINUATION": {"BREAKOUT", "RETEST", "REJECTION"},
    "PULLBACK": {"RETEST", "REJECTION", "RECLAIM"},
    "REVERSAL": {"RECLAIM", "BREAKOUT"},
}
```

If `opposite_trigger` is true, return `REJECT`; `RANGE` returns `WAIT`; `UNKNOWN` returns `REJECT`; `LIQUIDITY_SWEEP` stays in `supporting_triggers` and never becomes the primary PASS trigger by itself.

- [ ] **Step 8: Implement `analyze_rez_candidate(...)`**

Exact signature:

```python
def analyze_rez_candidate(
    *,
    side: str,
    candles_1h: list[dict],
    candles_15m: list[dict],
    atr_period: int,
    atr_buffer_mult: float,
    swing_window: int,
    analysis_version: str = "REZ_V1",
) -> RezAnalysisResult:
    ...
```

It must validate side/config, classify 1H first, fail closed on UNKNOWN/invalid data, then classify 15m only when a deterministic trigger level exists.

- [ ] **Step 9: Run all REZ analysis tests and verify GREEN**

Run:

```bash
cd scanner_v6
python -m unittest tests.test_rez_analysis_v1 -v
```

Expected: all tests PASS.

- [ ] **Step 10: Commit Task 1**

```bash
git add scanner_v6/rez_analysis_v1.py scanner_v6/tests/test_rez_analysis_v1.py
git commit -m "feat(scanner-v6): add deterministic REZ analysis core"
```

---

### Task 2: Persistent REZ Watch State

**Files:**
- Create: `scanner_v6/rez_watch_v1.py`
- Create: `scanner_v6/tests/test_rez_watch_v1.py`

**Interfaces:**
- Consumes: existing `SHADOW_DB_PATH`, `RezAnalysisResult`, current symbol/side/provider timestamps.
- Produces:
  - `RezWatchStore(db_path: str)`
  - `build_watch_key(...) -> str`
  - `record_analysis(...) -> tuple[int, bool]`
  - `link_event_snapshot(event_id: int, snapshot_id: str) -> None`
  - `expire_due(now_ms: int) -> int`

- [ ] **Step 1: Write failing schema and dedupe tests**

Use `tempfile.TemporaryDirectory()` and a real SQLite file. Verify initialization creates `rez_watch_state` and `rez_analysis_events`, and the same watch key does not create duplicate watch rows.

```python
class RezWatchStoreTests(unittest.TestCase):
    def test_same_watch_key_reuses_watch_row(self):
        store = RezWatchStore(self.db_path)
        event1, inserted1 = store.record_analysis(...)
        event2, inserted2 = store.record_analysis(...same closed_15m_at_ms...)
        self.assertTrue(inserted1)
        self.assertFalse(inserted2)
```

- [ ] **Step 2: Run focused tests and verify RED**

```bash
cd scanner_v6
python -m unittest tests.test_rez_watch_v1 -v
```

Expected: import failure.

- [ ] **Step 3: Implement schema and deterministic watch key**

Create tables exactly as approved, with foreign key from event `watch_id` to watch state and nullable `shadow_snapshot_id`.

```python
def build_watch_key(symbol, side, anchor_timestamp, trigger_level_kind, analysis_version):
    raw = f"{symbol.upper()}|{side.upper()}|{int(anchor_timestamp)}|{trigger_level_kind}|{analysis_version}"
    return raw
```

Reject empty symbol, invalid side, missing anchor timestamp, missing trigger kind, or empty version with `ValueError` so enabled REZ can fail closed.

- [ ] **Step 4: Add failing transition tests**

Cover:

```python
def test_unchanged_closed_15m_timestamp_does_not_append_duplicate_event(): ...
def test_newer_closed_15m_timestamp_appends_event(): ...
def test_wait_can_promote_to_pass(): ...
def test_reject_marks_watch_invalidated(): ...
def test_expire_due_marks_older_wait_expired(): ...
def test_pass_event_can_link_shadow_snapshot_once(): ...
def test_second_different_snapshot_link_is_rejected(): ...
```

- [ ] **Step 5: Implement transition methods**

Exact public method:

```python
def record_analysis(
    self, *, symbol: str, side: str, provider: str,
    result: RezAnalysisResult, now_ms: int, ttl_hours: int,
) -> tuple[int, bool]:
    """Return (event_id, event_inserted). Reuse watch row; dedupe same 15m close."""
```

State mapping:

```python
PASS -> ANALYSIS_PASS
WAIT -> ANALYSIS_WAIT
REJECT -> REJECT_ANALYSIS
```

`expires_at_ms = first_seen_at_ms + ttl_hours * 3_600_000`. A REJECT event sets `invalidated_at_ms=now_ms`. `expire_due` only changes active `ANALYSIS_WAIT` rows.

- [ ] **Step 6: Implement one-time snapshot link**

```python
def link_event_snapshot(self, event_id: int, snapshot_id: str) -> None:
    # UPDATE only WHERE shadow_snapshot_id IS NULL.
    # If row is missing or already linked to another id, raise ValueError.
```

Do not add REZ columns to existing Shadow tables.

- [ ] **Step 7: Run watch tests and verify GREEN**

```bash
cd scanner_v6
python -m unittest tests.test_rez_watch_v1 -v
```

- [ ] **Step 8: Commit Task 2**

```bash
git add scanner_v6/rez_watch_v1.py scanner_v6/tests/test_rez_watch_v1.py
git commit -m "feat(scanner-v6): persist REZ watch states"
```

---

### Task 3: REZ Calibration Report

**Files:**
- Create: `scanner_v6/rez_report_v1.py`
- Create: `scanner_v6/tests/test_rez_report_v1.py`

**Interfaces:**
- Consumes: `rez_analysis_events`, `rez_watch_state`, and existing `setup_snapshots/setup_outcomes` by `shadow_snapshot_id`.
- Produces: `build_rez_report(rows: list[dict]) -> dict`, `generate_report(db_path: str) -> dict`, CLI `python rez_report_v1.py --db ... [--json]`.

- [ ] **Step 1: Write failing metric tests**

Create deterministic synthetic joined rows and assert:

```python
report["wait_to_pass_rate_pct"]
report["pass_to_score_gate_rate_pct"]
report["pass_to_astra_approved_rate_pct"]
report["expiry_rate_pct"]
report["invalidation_rate_pct"]
report["by_structure"]["PULLBACK"]["sample_count"]
report["by_trigger"]["RETEST"]["tp1_hit_rate_pct"]
```

Also assert median/average MFE and MAE use only rows with linked Shadow outcomes.

- [ ] **Step 2: Verify RED**

```bash
cd scanner_v6
python -m unittest tests.test_rez_report_v1 -v
```

- [ ] **Step 3: Implement report aggregation**

Use stdlib `statistics.mean` and `statistics.median`; division by zero returns `None`, never zero by fabrication.

`generate_report(db_path)` must query REZ events and left join existing Shadow data:

```sql
SELECT e.*, w.symbol, w.side, w.analysis_version,
       s.score_total, s.astra_verdict,
       o.status AS outcome_status, o.mfe_r, o.mae_r
FROM rez_analysis_events e
JOIN rez_watch_state w ON w.id = e.watch_id
LEFT JOIN setup_snapshots s ON s.id = e.shadow_snapshot_id
LEFT JOIN setup_outcomes o ON o.snapshot_id = s.id
ORDER BY e.created_at_ms ASC
```

- [ ] **Step 4: Add CLI rendering test**

Assert text report contains `REZ V1 Calibration Report`, `WAIT->PASS`, structure breakdown, trigger breakdown, and `Automatic tuning: DISABLED`.

- [ ] **Step 5: Run tests and verify GREEN**

```bash
cd scanner_v6
python -m unittest tests.test_rez_report_v1 -v
```

- [ ] **Step 6: Commit Task 3**

```bash
git add scanner_v6/rez_report_v1.py scanner_v6/tests/test_rez_report_v1.py
git commit -m "feat(scanner-v6): add REZ calibration reporting"
```

---

### Task 4: Scanner Configuration and Disabled-Path Preservation

**Files:**
- Modify: `scanner_v6/auto_scanner_v6.part00` imports/config/store bootstrap near current imports and `SHADOW_*` config.
- Create: `scanner_v6/tests/test_rez_scanner_integration.py`

**Interfaces:**
- Consumes: `RezWatchStore`, `analyze_rez_candidate`.
- Produces config constants and `get_rez_watch_store() -> Optional[RezWatchStore]`.

- [ ] **Step 1: Write failing config/default tests**

Load the assembled scanner module in a subprocess with env overrides and assert defaults:

```python
self.assertEqual(scanner.REZ_ANALYSIS_ENABLED, False)
self.assertEqual(scanner.REZ_ANALYSIS_VERSION, "REZ_V1")
self.assertEqual(scanner.REZ_WATCH_TTL_HOURS, 12)
```

Also assert disabling REZ does not initialize `RezWatchStore` and does not require 15m provider klines beyond current behavior.

- [ ] **Step 2: Verify RED**

Run after assembling runtime files locally:

```bash
cd scanner_v6
cat shadow_eval_v6.part* > shadow_eval_v6.py
cat auto_scanner_v6.part* > auto_scanner_v6.py
python -m unittest tests.test_rez_scanner_integration.RezScannerIntegrationTests.test_rez_disabled_defaults -v
```

Expected: missing REZ constants.

- [ ] **Step 3: Add imports and env config**

Add in `auto_scanner_v6.part00`:

```python
from rez_analysis_v1 import RezAnalysisResult, analyze_rez_candidate
from rez_watch_v1 import RezWatchStore

REZ_ANALYSIS_ENABLED = os.getenv("REZ_ANALYSIS_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}
REZ_ANALYSIS_VERSION = os.getenv("REZ_ANALYSIS_VERSION", "REZ_V1").strip() or "REZ_V1"
REZ_WATCH_TTL_HOURS = int(os.getenv("REZ_WATCH_TTL_HOURS", "12"))

_REZ_WATCH_STORE = None
_REZ_WATCH_STORE_FAILED = False
```

Implement `get_rez_watch_store()` exactly like `get_shadow_store()` but only call it when `REZ_ANALYSIS_ENABLED` is true; any initialization failure returns `None` and becomes sticky/fail-closed for REZ-enabled scans.

- [ ] **Step 4: Verify disabled-path tests GREEN**

Run:

```bash
cd scanner_v6
cat shadow_eval_v6.part* > shadow_eval_v6.py
cat auto_scanner_v6.part* > auto_scanner_v6.py
python -m unittest tests.test_rez_scanner_integration.RezScannerIntegrationTests.test_rez_disabled_defaults -v
```

- [ ] **Step 5: Commit Task 4**

```bash
git add scanner_v6/auto_scanner_v6.part00 scanner_v6/tests/test_rez_scanner_integration.py
git commit -m "feat(scanner-v6): add REZ feature configuration"
```

---

### Task 5: Insert HYBRID Gate Into Scanner Flow

**Files:**
- Modify: `scanner_v6/auto_scanner_v6.part03` around `build_structure_trade_plan(...)` and before `score_setup(...)`.
- Modify: `scanner_v6/auto_scanner_v6.part04` immediately after `shadow_store.record_snapshot(...)` data is available.
- Modify: `scanner_v6/tests/test_rez_scanner_integration.py`

**Interfaces:**
- Consumes: current `side`, `plan`, 1H provider candles, provider session, and REZ config.
- Produces: `rez_result`, `rez_event_id`, final states `WAIT_ANALYSIS` and `REJECT_ANALYSIS`; only PASS reaches score calculation.

- [ ] **Step 1: Write failing orchestration tests**

Mock `analyze_rez_candidate`, `score_setup`, Astra, Telegram, provider klines, and stores. Cover:

```python
def test_rez_wait_skips_score_astra_and_telegram(): ...
def test_rez_reject_skips_score_astra_and_telegram(): ...
def test_rez_pass_calls_score(): ...
def test_rez_pass_score_below_75_skips_astra(): ...
def test_rez_pass_score_75_or_more_can_reach_astra(): ...
def test_rez_db_failure_when_enabled_fails_closed(): ...
def test_rez_disabled_uses_existing_v6_path(): ...
```

- [ ] **Step 2: Verify RED**

```bash
cd scanner_v6
cat shadow_eval_v6.part* > shadow_eval_v6.py
cat auto_scanner_v6.part* > auto_scanner_v6.py
python -m unittest tests.test_rez_scanner_integration -v
```

- [ ] **Step 3: Fetch closed 15m candles only after existing structure plan succeeds**

In `part03`, after `plan` succeeds:

```python
rez_result = None
rez_event_id = None
if REZ_ANALYSIS_ENABLED:
    rez_store = get_rez_watch_store()
    if rez_store is None:
        print(f"  [x] {symbol}: REZ persistence unavailable -> REJECT")
        continue
    candles_15m = market_session.provider.get_klines(symbol, "15m", STRUCTURE_KLINE_LIMIT)
    rez_result = analyze_rez_candidate(
        side=side,
        candles_1h=candles_1h,
        candles_15m=candles_15m,
        atr_period=STRUCTURE_ATR_PERIOD,
        atr_buffer_mult=STRUCTURE_ATR_BUFFER_MULT,
        swing_window=STRUCTURE_SWING_WINDOW,
        analysis_version=REZ_ANALYSIS_VERSION,
    )
```

Do not fetch REZ 15m candles when REZ is disabled.

- [ ] **Step 4: Persist state before score and enforce HYBRID gate**

```python
rez_event_id, _ = rez_store.record_analysis(
    symbol=symbol, side=side, provider=provider_name,
    result=rez_result, now_ms=int(time.time() * 1000),
    ttl_hours=REZ_WATCH_TTL_HOURS,
)
if rez_result.state == "WAIT":
    print(f"  ⏳ {symbol}: REZ 1H={rez_result.structure_1h} 15m={rez_result.trigger_15m} -> WAIT_ANALYSIS")
    continue
if rez_result.state != "PASS":
    print(f"  [x] {symbol}: REZ {rez_result.reason} -> REJECT_ANALYSIS")
    continue
```

Call `rez_store.expire_due(now_ms)` once per scan cycle, not once per symbol, and include count in cycle summary.

- [ ] **Step 5: Carry REZ metadata into qualified setup**

When appending a qualified setup, add:

```python
"rez_result": rez_result,
"rez_event_id": rez_event_id,
```

When REZ is disabled, both remain `None` so current V6 behavior is unchanged.

- [ ] **Step 6: Link PASS event to Shadow snapshot after `record_snapshot`**

Immediately after obtaining `shadow_snapshot_id`:

```python
if REZ_ANALYSIS_ENABLED and rez_event_id is not None:
    rez_store.link_event_snapshot(rez_event_id, shadow_snapshot_id)
```

Any link failure is fail-closed for that candidate before Astra/Telegram.

- [ ] **Step 7: Add compact cycle counters**

Initialize:

```python
rez_counts = {"pass": 0, "wait": 0, "reject": 0, "expired": 0, "promoted": 0}
```

Print once per enabled scan:

```text
[*] REZ: pass=N wait=N reject=N expired=N promoted=N
```

`promoted` increments only when the store reports a prior `ANALYSIS_WAIT` watch changed to `ANALYSIS_PASS`; expose this boolean from `record_analysis` as metadata or a tiny `get_watch_state` helper rather than inferring from logs.

- [ ] **Step 8: Run integration tests and verify GREEN**

```bash
cd scanner_v6
cat shadow_eval_v6.part* > shadow_eval_v6.py
cat auto_scanner_v6.part* > auto_scanner_v6.py
python -m unittest tests.test_rez_scanner_integration -v
```

- [ ] **Step 9: Commit Task 5**

```bash
git add scanner_v6/auto_scanner_v6.part03 scanner_v6/auto_scanner_v6.part04 scanner_v6/tests/test_rez_scanner_integration.py
git commit -m "feat(scanner-v6): gate setups through REZ hybrid analysis"
```

---

### Task 6: Astra Context and Telegram Presentation

**Files:**
- Modify: `scanner_v6/auto_scanner_v6.part02` `analyze_with_ai(...)`.
- Modify: `scanner_v6/auto_scanner_v6.part04` Astra call and Telegram message.
- Modify: `scanner_v6/tests/test_rez_scanner_integration.py`.

**Interfaces:**
- Consumes: optional `RezAnalysisResult` from Task 5.
- Produces: deterministic REZ context in Astra prompt and Telegram final signal only.

- [ ] **Step 1: Write failing prompt tests**

Patch Gemini client and capture `contents`. For enabled PASS metadata assert prompt contains:

```text
REZ Analysis: REZ_V1
1H Structure: PULLBACK
15m Trigger: RETEST
Supporting Triggers: LIQUIDITY_SWEEP
```

Also assert Astra still receives the original side and cannot return an alternate direction because response schema remains only confidence/verdict/reason/risk.

- [ ] **Step 2: Extend `analyze_with_ai` signature**

Exact extension:

```python
def analyze_with_ai(..., setup_score=None, rez_result: Optional[RezAnalysisResult] = None) -> Dict[str, Any]:
```

Build `rez_text` only from deterministic fields; never send raw candle arrays.

- [ ] **Step 3: Add failing Telegram-format test**

Capture `send_telegram_alert(message)` for an approved candidate and assert:

```text
📐 *1H Structure:* `PULLBACK`
⚡ *15m Trigger:* `RETEST + LIQUIDITY_SWEEP`
🧪 *Analysis:* `REZ_V1`
```

When REZ is disabled, these lines must be absent and existing V6 message fields remain present.

- [ ] **Step 4: Implement Telegram REZ lines**

Construct supporting tags deterministically and append three lines only when `item['rez_result'] is not None`.

Do not send Telegram for `WAIT_ANALYSIS`, `REJECT_ANALYSIS`, `WAIT_SCORE`, or `WAIT_ASTRA`; those paths must never enter the final delivery loop.

- [ ] **Step 5: Run integration tests GREEN**

```bash
cd scanner_v6
cat shadow_eval_v6.part* > shadow_eval_v6.py
cat auto_scanner_v6.part* > auto_scanner_v6.py
python -m unittest tests.test_rez_scanner_integration -v
```

- [ ] **Step 6: Commit Task 6**

```bash
git add scanner_v6/auto_scanner_v6.part02 scanner_v6/auto_scanner_v6.part04 scanner_v6/tests/test_rez_scanner_integration.py
git commit -m "feat(scanner-v6): add REZ context to Astra and alerts"
```

---

### Task 7: Full Regression and Build Verification

**Files:**
- No new production files unless a failing test identifies a specific defect.
- Verify all files from Tasks 1–6.

**Interfaces:**
- Produces fresh evidence that generated runtime files compile and the full discovered test suite passes.

- [ ] **Step 1: Assemble generated files exactly like Railway**

```bash
cd scanner_v6
cat shadow_eval_v6.part* > shadow_eval_v6.py
cat auto_scanner_v6.part* > auto_scanner_v6.py
```

- [ ] **Step 2: Compile all runtime modules**

```bash
python -m py_compile \
  market_data_v6.py setup_score_v6.py shadow_eval_v6.py shadow_report_v6.py \
  rez_analysis_v1.py rez_watch_v1.py rez_report_v1.py auto_scanner_v6.py
```

Expected: exit code 0 and no output.

- [ ] **Step 3: Run the full discovered test suite**

```bash
python -m unittest discover -s tests -v
```

Expected: exit code 0, zero failures, zero errors.

- [ ] **Step 4: Verify scoring code is byte-for-byte unchanged from pre-REZ commit**

```bash
git diff 7331c56a88dffe87d21d6ba7bfddf1847c4dbcfe -- scanner_v6/setup_score_v6.py
```

Expected: no diff.

- [ ] **Step 5: Verify no order execution code was introduced**

```bash
grep -RniE "create_order|place_order|new_order|futures_create_order|/order" \
  rez_analysis_v1.py rez_watch_v1.py rez_report_v1.py auto_scanner_v6.py
```

Expected: no executable order API path. If a test fixture contains the word, inspect it and keep production code clean.

- [ ] **Step 6: Commit only if verification required a fix**

If no fix was required, make no empty commit. If a defect was fixed, rerun Steps 1–5 and commit the exact fix with a narrow message.

---

### Task 8: Railway Phase A Rollout, Disabled by Default

**Files/Config:**
- Railway service: `scanner-v6-shadow`
- Source branch: `deploy/v6-shadow`
- Do not modify service `api`.

**Interfaces:**
- Produces deployed code with REZ disabled, preserving the 80-symbol runtime and current safety state.

- [ ] **Step 1: Confirm current scanner service config before changing anything**

Verify start command still contains:

```text
python -u auto_scanner_v6.py --interval 5 --limit 80
```

and volume mount remains `/data`.

- [ ] **Step 2: Set Phase A variables without enabling REZ**

Set:

```text
REZ_ANALYSIS_ENABLED=false
REZ_ANALYSIS_VERSION=REZ_V1
REZ_WATCH_TTL_HOURS=12
```

Do not change `SETUP_MIN_SCORE`, structure/R:R values, `TRADING_MODE`, or `DIRECT_AI_ORDER_ENABLED`.

- [ ] **Step 3: Deploy scanner service only**

Deploy `scanner-v6-shadow`; do not touch `api`.

- [ ] **Step 4: Verify fresh deployment state and runtime logs**

Require evidence for all:

```text
deployment = SUCCESS
start command = --limit 80
market provider locks normally
scan cycles continue
no REZ WAIT/PASS/REJECT gating appears while disabled
Shadow evaluation continues
volume /data remains mounted
```

- [ ] **Step 5: Run external connectivity healthcheck**

Inside deployed scanner environment:

```bash
python external_healthcheck.py
```

Require:

```text
GEMINI=OK
TELEGRAM_AUTH=OK
TELEGRAM_CHAT=OK
HEALTHCHECK=OK
```

`TELEGRAM_SEND=SKIPPED` is acceptable for this non-delivery check.

- [ ] **Step 6: Record Phase A evidence**

Capture deployment id, test count/result, first successful scan timestamp, and healthcheck output in the implementation handoff/PR description. Do not claim Phase A complete without this fresh evidence.

---

### Task 9: Railway Phase B HYBRID Canary

**Files/Config:**
- Railway service: `scanner-v6-shadow` only.

**Interfaces:**
- Enables approved HYBRID behavior after Phase A verification; no scoring changes.

- [ ] **Step 1: Enable only the REZ feature flag**

Set:

```text
REZ_ANALYSIS_ENABLED=true
```

Keep:

```text
SETUP_MIN_SCORE=75
TRADING_MODE=SIMULATION
DIRECT_AI_ORDER_ENABLED=false
```

- [ ] **Step 2: Deploy scanner service and verify SUCCESS**

Do not infer success from config write alone; confirm a fresh deployment reaches `SUCCESS`.

- [ ] **Step 3: Inspect at least two fresh scan cycles**

Require logs to show the compact summary:

```text
REZ: pass=N wait=N reject=N expired=N promoted=N
```

and candidate transitions such as:

```text
SYMBOL: 1H=PULLBACK 15m=NO_TRIGGER -> WAIT_ANALYSIS
```

No requirement exists for an immediate PASS signal; absence of a signal is valid if deterministic gates do not pass.

- [ ] **Step 4: Verify WAIT does not invoke Astra**

For at least one logged WAIT candidate, confirm there is no following `Requesting Devil's Advocate AI review` for that candidate in the same cycle.

- [ ] **Step 5: Verify PASS behavior when naturally observed**

If a PASS setup occurs during observation, verify score gate still runs after REZ. If no PASS occurs, do not manufacture a production trade; use automated integration tests as the functional evidence and continue collecting Shadow/REZ watches.

- [ ] **Step 6: Generate initial REZ report without tuning**

```bash
python rez_report_v1.py --db /data/shadow_eval_v6.sqlite3
```

Confirm report renders even with insufficient samples and states automatic tuning is disabled.

- [ ] **Step 7: Stop at calibration boundary**

Do not alter score weights, score threshold, TTL, trigger sensitivity, R:R minimum, or provider behavior from early canary observations. Further tuning requires accumulated evidence and separate review.

---

## Final Verification Checklist

Before declaring REZ V1 implemented or deployed, verify all of the following with fresh evidence:

- [ ] `python -m unittest discover -s tests -v` exits 0.
- [ ] Runtime modules compile after part-file assembly.
- [ ] `setup_score_v6.py` remains unchanged.
- [ ] Disabled REZ path preserves existing V6 behavior.
- [ ] Enabled REZ WAIT/REJECT never reaches Astra or Telegram.
- [ ] REZ PASS still requires Setup Score `>=75` before Astra.
- [ ] AI failure remains fail-closed.
- [ ] Telegram is only final output after all gates.
- [ ] Watch dedupe uses stable identity and closed-15m timestamp dedupe.
- [ ] WAIT can promote to PASS; invalidated/expired watches stop re-evaluating.
- [ ] REZ event can link to an existing Shadow snapshot without modifying Shadow tables.
- [ ] Calibration report groups by structure and trigger and never auto-tunes.
- [ ] Railway scanner remains `--limit 80` with `/data` volume.
- [ ] `api` service is untouched.
- [ ] Decision-support-only safety remains intact; no live/testnet order execution exists.
