# REZ Analysis Layer V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the approved deterministic REZ Analysis Layer V1 to Scanner V6 as a HYBRID context/timing gate, preserving all existing V6 safety rules and keeping live/testnet order execution absent.

**Architecture:** Add three focused modules: a pure deterministic analysis module, a SQLite watch-state module, and a REZ calibration/report module. Integrate REZ after the existing Structure Trade Plan and before the unchanged Setup Score. Persist `WAIT` watches in the same Shadow SQLite database without altering existing Shadow snapshot/outcome semantics, and call Astra only after REZ `PASS` plus Setup Score `>=75`.

**Tech Stack:** Python 3.13 runtime, stdlib `unittest`, SQLite, existing `requests`, `tradingview-ta`, `google-genai`; no new dependency.

**Spec:** `docs/superpowers/specs/2026-09-16-rez-analysis-layer-v1-design.md`

## Global Constraints

- `REZ_ANALYSIS_ENABLED=false` must preserve current V6 behavior.
- Enabled behavior is the approved HYBRID mode only.
- `SETUP_MIN_SCORE=75` remains unchanged.
- Existing minimum structure R:R remains unchanged.
- Existing market-provider lock and provider fallback remain unchanged.
- REZ uses closed candles from the provider already locked for the scan cycle.
- Never mix Binance and Bybit candles inside one candidate evaluation.
- Astra remains Devil's Advocate only and cannot change LONG/SHORT direction.
- AI failure remains fail-closed.
- Telegram remains final-output only after REZ PASS, score gate, Astra approval, and cooldown.
- Decision-support only; no live or testnet order execution code.
- `setup_score_v6.py` weights remain unchanged.
- Reuse `STRUCTURE_SWING_WINDOW`, `STRUCTURE_ATR_PERIOD`, and `STRUCTURE_ATR_BUFFER_MULT`.
- `REZ_WATCH_TTL_HOURS=12` by default.
- `REZ_ANALYSIS_VERSION=REZ_V1` by default.
- Keep the Railway runtime universe at 80 symbols.
- Tests use stdlib `unittest`; market, Telegram, and Gemini calls are mocked/faked.

---

## File Map

**Create**
- `scanner_v6/rez_analysis_v1.py` — pure 1H structure, 15m trigger, HYBRID decision logic.
- `scanner_v6/rez_watch_v1.py` — SQLite watch state and REZ analysis events.
- `scanner_v6/rez_report_v1.py` — REZ calibration joins/metrics and CLI report.
- `scanner_v6/tests/test_rez_analysis_v1.py`
- `scanner_v6/tests/test_rez_watch_v1.py`
- `scanner_v6/tests/test_rez_report_v1.py`
- `scanner_v6/tests/test_rez_scanner_integration.py`

**Modify**
- `scanner_v6/auto_scanner_v6.part00` — imports, env config, lazy REZ store.
- `scanner_v6/auto_scanner_v6.part02` — Astra prompt accepts REZ metadata.
- `scanner_v6/auto_scanner_v6.part03` — invoke/persist/gate REZ after Structure Plan.
- `scanner_v6/auto_scanner_v6.part04` — link REZ event to Shadow snapshot and render Telegram context.

**Do not modify unless a regression proves it necessary**
- `scanner_v6/setup_score_v6.py`
- `scanner_v6/shadow_eval_v6.part00`
- `scanner_v6/shadow_eval_v6.part01`
- `scanner_v6/shadow_eval_v6.part02`
- `scanner_v6/market_data_v6.py`
- `scanner_v6/requirements.txt`

---

### Task 1: Deterministic REZ Analysis Core

**Files:**
- Create: `scanner_v6/rez_analysis_v1.py`
- Create: `scanner_v6/tests/test_rez_analysis_v1.py`

**Interfaces:**
- Consumes candle dictionaries with `open_time`, `open`, `high`, `low`, `close`, `volume`, `close_time`.
- Produces `RezAnalysisResult` and `analyze_rez_candidate(...)`.

Use this exact public result contract:

```python
from dataclasses import dataclass
from typing import Optional

@dataclass(frozen=True)
class RezAnalysisResult:
    analysis_version: str
    state: str
    structure_1h: str
    trigger_15m: str
    supporting_triggers: tuple[str, ...]
    reason: str
    protected_swing_timestamp: Optional[int]
    protected_swing_price: Optional[float]
    trigger_level_kind: Optional[str]
    trigger_level_price: Optional[float]
    closed_1h_at_ms: Optional[int]
    closed_15m_at_ms: Optional[int]
```

For `RANGE`, use the confirmed 1H range boundary chosen as the trigger reference for `protected_swing_timestamp`/`protected_swing_price`. It is only a stable watch anchor, not directional protected structure.

- [ ] **Step 1: Write the first failing core test**

```python
import unittest
from rez_analysis_v1 import analyze_rez_candidate


def candle(ts, o, h, l, close, duration=3_600_000):
    return {
        "open_time": ts,
        "open": float(o),
        "high": float(h),
        "low": float(l),
        "close": float(close),
        "volume": 1.0,
        "close_time": ts + duration - 1,
    }


class RezAnalysisTests(unittest.TestCase):
    def test_missing_history_fails_closed(self):
        result = analyze_rez_candidate(
            side="LONG",
            candles_1h=[],
            candles_15m=[],
            atr_period=14,
            atr_buffer_mult=0.25,
            swing_window=2,
            analysis_version="REZ_V1",
        )
        self.assertEqual(result.structure_1h, "UNKNOWN")
        self.assertEqual(result.state, "REJECT")
```

- [ ] **Step 2: Run RED**

```bash
cd scanner_v6
python -m unittest tests.test_rez_analysis_v1 -v
```

Expected: import failure because `rez_analysis_v1.py` does not exist.

- [ ] **Step 3: Implement validation, ATR, and confirmed swings**

```python
def _valid_closed_candle(candle):
    try:
        o = float(candle["open"])
        h = float(candle["high"])
        l = float(candle["low"])
        close = float(candle["close"])
        open_time = int(candle["open_time"])
        close_time = int(candle["close_time"])
    except (KeyError, TypeError, ValueError):
        return False
    return open_time < close_time and h >= max(o, close) and l <= min(o, close)


def calculate_atr(candles, period):
    if period <= 0 or len(candles) < period + 1:
        return None
    window = candles[-(period + 1):]
    if not all(_valid_closed_candle(c) for c in window):
        return None
    true_ranges = []
    for i in range(1, len(window)):
        current, previous = window[i], window[i - 1]
        high = float(current["high"])
        low = float(current["low"])
        prev_close = float(previous["close"])
        true_ranges.append(max(high - low, abs(high - prev_close), abs(low - prev_close)))
    return sum(true_ranges) / period


def find_confirmed_swings(candles, window):
    if window < 1 or len(candles) < window * 2 + 1:
        return {"highs": [], "lows": []}
    if not all(_valid_closed_candle(c) for c in candles):
        return {"highs": [], "lows": []}
    highs, lows = [], []
    for index in range(window, len(candles) - window):
        current = candles[index]
        neighbors = candles[index - window:index] + candles[index + 1:index + window + 1]
        high = float(current["high"])
        low = float(current["low"])
        if all(high > float(row["high"]) for row in neighbors):
            highs.append({"index": index, "price": high, "timestamp": int(current["close_time"])})
        if all(low < float(row["low"]) for row in neighbors):
            lows.append({"index": index, "price": low, "timestamp": int(current["close_time"])})
    return {"highs": highs, "lows": lows}
```

- [ ] **Step 4: Add explicit 1H classification tests**

Add concrete fixtures for these six behaviors, each asserting both structure and state: same-side close-confirmed BOS with intact protected swing=`CONTINUATION`; retrace toward BOS without invalidation=`PULLBACK`; protected-swing invalidation followed by a new same-side BOS=`REVERSAL`; invalidation without new BOS is not reversal; overlapping/alternating swings=`RANGE`; insufficient swings=`UNKNOWN/REJECT`.

The wick-only case must include a candle whose `high` breaches the last swing high but whose `close` remains below `swing_high + ATR*buffer_mult`, and assert it is not `CONTINUATION`.

- [ ] **Step 5: Implement 1H classifier**

```python
def _classify_1h_structure(*, side, candles, atr_period, atr_buffer_mult, swing_window):
    atr = calculate_atr(candles, atr_period)
    if atr is None or atr <= 0:
        return {
            "structure": "UNKNOWN", "protected_swing_timestamp": None,
            "protected_swing_price": None, "trigger_level_kind": None,
            "trigger_level_price": None, "closed_1h_at_ms": None,
            "invalidated": False, "reason": "INVALID_1H_ATR",
        }
    swings = find_confirmed_swings(candles, swing_window)
    if not swings["highs"] or not swings["lows"]:
        return {
            "structure": "UNKNOWN", "protected_swing_timestamp": None,
            "protected_swing_price": None, "trigger_level_kind": None,
            "trigger_level_price": None, "closed_1h_at_ms": int(candles[-1]["close_time"]),
            "invalidated": False, "reason": "INSUFFICIENT_CONFIRMED_SWINGS",
        }
    # Continue with close-confirmed BOS and protected-swing rules from the approved spec.
```

The implementation after this guard must use `buffer = atr * atr_buffer_mult`, chronological swing timestamps, and closed candle prices only. It must return one of the five approved structures and a deterministic trigger level.

- [ ] **Step 6: Add explicit 15m trigger tests**

Create fixtures and assertions for: BREAKOUT requires close beyond `level ± ATR15m buffer`; RETEST requires a prior breakout plus later zone touch and valid-side close; RECLAIM requires trading through the level then closing back to the valid side; REJECTION requires zone touch, valid-side close, and zone-facing wick `>= body`; LIQUIDITY_SWEEP is only a supporting tag; explicit opposite breakout sets final state `REJECT`; no valid trigger returns `NO_TRIGGER` and `WAIT` for continuation/pullback.

- [ ] **Step 7: Implement trigger classifier and literal HYBRID matrix**

```python
PASS_MATRIX = {
    "CONTINUATION": {"BREAKOUT", "RETEST", "REJECTION"},
    "PULLBACK": {"RETEST", "REJECTION", "RECLAIM"},
    "REVERSAL": {"RECLAIM", "BREAKOUT"},
}


def _hybrid_state(structure, trigger, opposite_trigger):
    if opposite_trigger:
        return "REJECT", "OPPOSITE_15M_BREAKOUT"
    if structure == "UNKNOWN":
        return "REJECT", "UNKNOWN_STRUCTURE"
    if structure == "RANGE":
        return "WAIT", "RANGE_CONTEXT"
    if trigger in PASS_MATRIX.get(structure, set()):
        return "PASS", f"{structure}_{trigger}_CONFIRMED"
    return "WAIT", f"{structure}_NO_CONFIRMED_TRIGGER"
```

`LIQUIDITY_SWEEP` may be added only to `supporting_triggers`; it cannot become the primary trigger that makes `_hybrid_state` return PASS.

- [ ] **Step 8: Implement public analyzer**

```python
def analyze_rez_candidate(
    *, side, candles_1h, candles_15m, atr_period,
    atr_buffer_mult, swing_window, analysis_version="REZ_V1",
):
    side = str(side).upper()
    if side not in {"LONG", "SHORT"} or atr_period <= 0 or atr_buffer_mult < 0 or swing_window < 1:
        return RezAnalysisResult(
            analysis_version=analysis_version, state="REJECT", structure_1h="UNKNOWN",
            trigger_15m="NO_TRIGGER", supporting_triggers=(), reason="INVALID_INPUT",
            protected_swing_timestamp=None, protected_swing_price=None,
            trigger_level_kind=None, trigger_level_price=None,
            closed_1h_at_ms=None, closed_15m_at_ms=None,
        )
    structure = _classify_1h_structure(
        side=side, candles=candles_1h, atr_period=atr_period,
        atr_buffer_mult=atr_buffer_mult, swing_window=swing_window,
    )
    # Convert UNKNOWN to REJECT; otherwise classify 15m using the deterministic trigger level.
```

Finish the function with the exact approved matrix and populate every dataclass field; do not return partial dictionaries.

- [ ] **Step 9: Run GREEN**

```bash
cd scanner_v6
python -m unittest tests.test_rez_analysis_v1 -v
```

Expected: all REZ analysis tests pass.

- [ ] **Step 10: Commit**

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
- Consumes `SHADOW_DB_PATH` and `RezAnalysisResult`.
- Produces `RezWatchStore` and `RezRecordResult`.

Use this exact record result:

```python
@dataclass(frozen=True)
class RezRecordResult:
    event_id: int
    event_inserted: bool
    watch_id: int
    previous_state: Optional[str]
    current_state: str
    promoted: bool
```

- [ ] **Step 1: Write failing schema/dedupe test**

```python
import tempfile
import unittest
from pathlib import Path
from rez_watch_v1 import RezWatchStore


class RezWatchStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.tmp.name) / "shadow.sqlite3")

    def tearDown(self):
        self.tmp.cleanup()

    def test_initialization_creates_rez_tables(self):
        store = RezWatchStore(self.db_path)
        names = store.table_names()
        self.assertIn("rez_watch_state", names)
        self.assertIn("rez_analysis_events", names)
```

- [ ] **Step 2: Run RED**

```bash
cd scanner_v6
python -m unittest tests.test_rez_watch_v1 -v
```

- [ ] **Step 3: Implement schema and watch key**

```python
def build_watch_key(symbol, side, anchor_timestamp, trigger_level_kind, analysis_version):
    symbol = str(symbol).strip().upper()
    side = str(side).strip().upper()
    trigger_level_kind = str(trigger_level_kind).strip().upper()
    analysis_version = str(analysis_version).strip().upper()
    if not symbol or side not in {"LONG", "SHORT"} or anchor_timestamp is None or not trigger_level_kind or not analysis_version:
        raise ValueError("invalid REZ watch identity")
    return f"{symbol}|{side}|{int(anchor_timestamp)}|{trigger_level_kind}|{analysis_version}"
```

Create approved columns in `rez_watch_state` and `rez_analysis_events`, with `UNIQUE(watch_key)` and an event uniqueness constraint covering `(watch_id, closed_15m_at_ms, analysis_state, trigger_15m)` so the same closed candle/state cannot duplicate an event.

- [ ] **Step 4: Add transition tests**

Add concrete tests that record a WAIT event twice with the same closed 15m timestamp and assert the second returns `event_inserted=False`; record a newer 15m WAIT and assert a new event; record WAIT then PASS and assert `promoted=True`; record REJECT and assert `invalidated_at_ms` is set; advance `now_ms` beyond 12 hours and assert `expire_due()` changes only active WAIT watches to EXPIRED.

- [ ] **Step 5: Implement `record_analysis` and `expire_due`**

```python
def record_analysis(self, *, symbol, side, provider, result, now_ms, ttl_hours):
    watch_key = build_watch_key(
        symbol, side, result.protected_swing_timestamp,
        result.trigger_level_kind, result.analysis_version,
    )
    current_state = {
        "PASS": "ANALYSIS_PASS",
        "WAIT": "ANALYSIS_WAIT",
        "REJECT": "REJECT_ANALYSIS",
    }[result.state]
    # Read or create the watch, remember previous state, update timestamps/state,
    # append one event if this closed 15m state is new, and return RezRecordResult.
```

The implementation must calculate `promoted = previous_state == "ANALYSIS_WAIT" and current_state == "ANALYSIS_PASS"`. `expires_at_ms` is fixed from `first_seen_at_ms + ttl_hours*3_600_000`, not extended on every scan.

- [ ] **Step 6: Add and implement one-time Shadow snapshot link**

Test that a PASS event with `shadow_snapshot_id=NULL` can be linked once, linking the same ID again is idempotent, and linking a different ID raises `ValueError`.

```python
def link_event_snapshot(self, event_id, snapshot_id):
    snapshot_id = str(snapshot_id).strip()
    if not snapshot_id:
        raise ValueError("empty shadow snapshot id")
    # Read current value; set when NULL; accept same id; reject a different existing id.
```

Do not add columns to existing Shadow tables.

- [ ] **Step 7: Run GREEN**

```bash
cd scanner_v6
python -m unittest tests.test_rez_watch_v1 -v
```

- [ ] **Step 8: Commit**

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
- Consumes REZ events/watch rows plus existing Shadow snapshot/outcome rows via `shadow_snapshot_id`.
- Produces `build_rez_report(rows)`, `generate_report(db_path)`, and CLI output.

- [ ] **Step 1: Write failing aggregation test**

```python
import unittest
from rez_report_v1 import build_rez_report


class RezReportTests(unittest.TestCase):
    def test_report_groups_structure_trigger_and_conversion_rates(self):
        rows = [
            {"watch_id": 1, "analysis_state": "ANALYSIS_WAIT", "structure_1h": "PULLBACK", "trigger_15m": "NO_TRIGGER", "score_total": None, "astra_verdict": None, "outcome_status": None, "mfe_r": None, "mae_r": None},
            {"watch_id": 1, "analysis_state": "ANALYSIS_PASS", "structure_1h": "PULLBACK", "trigger_15m": "RETEST", "score_total": 82, "astra_verdict": "APPROVED", "outcome_status": "TP1", "mfe_r": 1.8, "mae_r": -0.4},
        ]
        report = build_rez_report(rows)
        self.assertEqual(report["wait_to_pass_rate_pct"], 100.0)
        self.assertEqual(report["pass_to_score_gate_rate_pct"], 100.0)
        self.assertEqual(report["pass_to_astra_approved_rate_pct"], 100.0)
        self.assertEqual(report["by_structure"]["PULLBACK"]["sample_count"], 1)
        self.assertEqual(report["by_trigger"]["RETEST"]["tp1_hit_rate_pct"], 100.0)
```

- [ ] **Step 2: Run RED**

```bash
cd scanner_v6
python -m unittest tests.test_rez_report_v1 -v
```

- [ ] **Step 3: Implement aggregation and database join**

Use `statistics.mean` and `statistics.median`; zero denominators return `None`.

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

Report keys must include `wait_to_pass_rate_pct`, `pass_to_score_gate_rate_pct`, `pass_to_astra_approved_rate_pct`, `expiry_rate_pct`, `invalidation_rate_pct`, `by_structure`, `by_trigger`, average/median MFE R, and average/median MAE R.

- [ ] **Step 4: Add CLI rendering test and implementation**

Test that text contains `REZ V1 Calibration Report`, `WAIT->PASS`, structure and trigger headings, and `Automatic tuning: DISABLED`. CLI:

```bash
python rez_report_v1.py --db shadow_eval_v6.sqlite3
python rez_report_v1.py --db shadow_eval_v6.sqlite3 --json
```

- [ ] **Step 5: Run GREEN**

```bash
cd scanner_v6
python -m unittest tests.test_rez_report_v1 -v
```

- [ ] **Step 6: Commit**

```bash
git add scanner_v6/rez_report_v1.py scanner_v6/tests/test_rez_report_v1.py
git commit -m "feat(scanner-v6): add REZ calibration reporting"
```

---

### Task 4: Scanner Configuration and Disabled-Path Preservation

**Files:**
- Modify: `scanner_v6/auto_scanner_v6.part00`
- Create: `scanner_v6/tests/test_rez_scanner_integration.py`

**Interfaces:**
- Produces `REZ_ANALYSIS_ENABLED`, `REZ_ANALYSIS_VERSION`, `REZ_WATCH_TTL_HOURS`, and `get_rez_watch_store()`.

- [ ] **Step 1: Write failing config/default test**

Assemble generated files in `setUpClass`, import the scanner module with REZ env vars unset, and assert:

```python
self.assertFalse(scanner.REZ_ANALYSIS_ENABLED)
self.assertEqual(scanner.REZ_ANALYSIS_VERSION, "REZ_V1")
self.assertEqual(scanner.REZ_WATCH_TTL_HOURS, 12)
```

Also patch `RezWatchStore` and assert it is not constructed when `REZ_ANALYSIS_ENABLED` is false.

- [ ] **Step 2: Run RED**

```bash
cd scanner_v6
cat shadow_eval_v6.part* > shadow_eval_v6.py
cat auto_scanner_v6.part* > auto_scanner_v6.py
python -m unittest tests.test_rez_scanner_integration -v
```

- [ ] **Step 3: Add imports/config/bootstrap**

```python
from rez_analysis_v1 import RezAnalysisResult, analyze_rez_candidate
from rez_watch_v1 import RezWatchStore

REZ_ANALYSIS_ENABLED = os.getenv("REZ_ANALYSIS_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}
REZ_ANALYSIS_VERSION = os.getenv("REZ_ANALYSIS_VERSION", "REZ_V1").strip() or "REZ_V1"
REZ_WATCH_TTL_HOURS = int(os.getenv("REZ_WATCH_TTL_HOURS", "12"))

_REZ_WATCH_STORE = None
_REZ_WATCH_STORE_FAILED = False
```

Implement `get_rez_watch_store()` with the same sticky fail-closed pattern as `get_shadow_store()`, using `SHADOW_DB_PATH`. Do not initialize it unless REZ is enabled.

- [ ] **Step 4: Run GREEN and commit**

```bash
cd scanner_v6
cat shadow_eval_v6.part* > shadow_eval_v6.py
cat auto_scanner_v6.part* > auto_scanner_v6.py
python -m unittest tests.test_rez_scanner_integration -v
git add auto_scanner_v6.part00 tests/test_rez_scanner_integration.py
git commit -m "feat(scanner-v6): add REZ feature configuration"
```

---

### Task 5: Insert HYBRID Gate Into Scanner Flow

**Files:**
- Modify: `scanner_v6/auto_scanner_v6.part03`
- Modify: `scanner_v6/auto_scanner_v6.part04`
- Modify: `scanner_v6/tests/test_rez_scanner_integration.py`

**Interfaces:**
- Uses `RezAnalysisResult` and `RezRecordResult`.
- Only REZ PASS reaches `score_setup(...)` when enabled.

- [ ] **Step 1: Add failing orchestration tests**

Write concrete mocks asserting all six paths:

```python
# WAIT: score_setup, analyze_with_ai, send_telegram_alert each assert_not_called().
# REJECT: same three functions assert_not_called().
# PASS + score 74: analyze_with_ai and send_telegram_alert assert_not_called().
# PASS + score 75: analyze_with_ai assert_called_once().
# REZ store initialization/write failure: candidate does not reach Astra.
# REZ disabled: analyze_rez_candidate assert_not_called() and legacy score path remains reachable.
```

- [ ] **Step 2: Run RED**

```bash
cd scanner_v6
cat shadow_eval_v6.part* > shadow_eval_v6.py
cat auto_scanner_v6.part* > auto_scanner_v6.py
python -m unittest tests.test_rez_scanner_integration -v
```

- [ ] **Step 3: Invoke REZ after existing Structure Plan**

In `part03`, only after `plan` is non-null:

```python
rez_result = None
rez_record = None
if REZ_ANALYSIS_ENABLED:
    rez_store = get_rez_watch_store()
    if rez_store is None:
        print(f"  [x] {symbol}: REZ persistence unavailable -> REJECT_ANALYSIS")
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
    rez_record = rez_store.record_analysis(
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

When disabled, do not fetch REZ-specific 15m klines and do not initialize REZ persistence.

- [ ] **Step 4: Add cycle counters and expiry**

Initialize only for enabled mode:

```python
rez_counts = {"pass": 0, "wait": 0, "reject": 0, "expired": 0, "promoted": 0}
```

Call `rez_store.expire_due(now_ms)` once per scan cycle. Increment `promoted` only from `rez_record.promoted`. Print once:

```text
[*] REZ: pass=N wait=N reject=N expired=N promoted=N
```

- [ ] **Step 5: Carry REZ metadata and link Shadow snapshot**

Add to qualified item:

```python
"rez_result": rez_result,
"rez_event_id": None if rez_record is None else rez_record.event_id,
```

Immediately after `shadow_store.record_snapshot(...)` returns `shadow_snapshot_id`, call:

```python
if REZ_ANALYSIS_ENABLED and rez_record is not None:
    rez_store.link_event_snapshot(rez_record.event_id, shadow_snapshot_id)
```

A link failure must stop that candidate before Astra/Telegram.

- [ ] **Step 6: Run GREEN and commit**

```bash
cd scanner_v6
cat shadow_eval_v6.part* > shadow_eval_v6.py
cat auto_scanner_v6.part* > auto_scanner_v6.py
python -m unittest tests.test_rez_scanner_integration -v
git add auto_scanner_v6.part03 auto_scanner_v6.part04 tests/test_rez_scanner_integration.py
git commit -m "feat(scanner-v6): gate setups through REZ hybrid analysis"
```

---

### Task 6: Astra Context and Telegram Presentation

**Files:**
- Modify: `scanner_v6/auto_scanner_v6.part02`
- Modify: `scanner_v6/auto_scanner_v6.part04`
- Modify: `scanner_v6/tests/test_rez_scanner_integration.py`

**Interfaces:**
- `analyze_with_ai(..., rez_result: Optional[RezAnalysisResult] = None)`.

- [ ] **Step 1: Write failing Astra prompt test**

Patch Gemini client, capture `contents`, pass a `RezAnalysisResult` with `PULLBACK`, primary `RETEST`, supporting `LIQUIDITY_SWEEP`, and assert the prompt contains exactly:

```text
REZ Analysis: REZ_V1
1H Structure: PULLBACK
15m Trigger: RETEST
Supporting Triggers: LIQUIDITY_SWEEP
```

- [ ] **Step 2: Extend Astra signature and prompt**

```python
def analyze_with_ai(
    symbol, side, price, r4, r1, r15, rsi, adx, funding, btc_trend,
    tags, plan=None, setup_score=None, rez_result: Optional[RezAnalysisResult] = None,
):
```

Build prompt text only from deterministic REZ fields; never send raw candle arrays. Keep existing output JSON contract unchanged: `confidence`, `verdict`, `reason`, `risk`.

- [ ] **Step 3: Write failing Telegram-format test**

Capture the final message and assert it contains, only when REZ metadata exists:

```text
📐 *1H Structure:* `PULLBACK`
⚡ *15m Trigger:* `RETEST + LIQUIDITY_SWEEP`
🧪 *Analysis:* `REZ_V1`
```

For REZ disabled, assert those three lines are absent while Entry, SL, TP, score, Astra, BTC bias, provider, and invalidation remain.

- [ ] **Step 4: Implement final-output formatting**

Use primary trigger first, then sorted supporting triggers. Do not send messages for `WAIT_ANALYSIS`, `REJECT_ANALYSIS`, `WAIT_SCORE`, or `WAIT_ASTRA`; those paths must never enter delivery.

- [ ] **Step 5: Run GREEN and commit**

```bash
cd scanner_v6
cat shadow_eval_v6.part* > shadow_eval_v6.py
cat auto_scanner_v6.part* > auto_scanner_v6.py
python -m unittest tests.test_rez_scanner_integration -v
git add auto_scanner_v6.part02 auto_scanner_v6.part04 tests/test_rez_scanner_integration.py
git commit -m "feat(scanner-v6): add REZ context to Astra and alerts"
```

---

### Task 7: Full Regression and Build Verification

**Files:** no production changes unless a specific failing test proves a defect.

- [ ] **Step 1: Assemble exactly like Railway**

```bash
cd scanner_v6
cat shadow_eval_v6.part* > shadow_eval_v6.py
cat auto_scanner_v6.part* > auto_scanner_v6.py
```

- [ ] **Step 2: Compile runtime modules**

```bash
python -m py_compile \
  market_data_v6.py setup_score_v6.py shadow_eval_v6.py shadow_report_v6.py \
  rez_analysis_v1.py rez_watch_v1.py rez_report_v1.py auto_scanner_v6.py
```

Expected: exit 0, no output.

- [ ] **Step 3: Run full tests**

```bash
python -m unittest discover -s tests -v
```

Expected: exit 0, zero failures, zero errors.

- [ ] **Step 4: Prove Setup Score code is unchanged**

```bash
git diff 7331c56a88dffe87d21d6ba7bfddf1847c4dbcfe -- scanner_v6/setup_score_v6.py
```

Expected: no diff.

- [ ] **Step 5: Prove no order execution path was introduced**

```bash
grep -RniE "create_order|place_order|new_order|futures_create_order|/order" \
  rez_analysis_v1.py rez_watch_v1.py rez_report_v1.py auto_scanner_v6.py
```

Expected: no executable order API path.

- [ ] **Step 6: Commit only if verification exposed a defect**

If a defect was fixed, rerun Steps 1–5 before committing the narrow fix. Do not make an empty verification commit.

---

### Task 8: Railway Phase A Rollout With REZ Disabled

**Target:** Railway service `scanner-v6-shadow` only. Do not modify `api`.

- [ ] **Step 1: Confirm current runtime config**

Require start command:

```text
python -u auto_scanner_v6.py --interval 5 --limit 80
```

and volume mount `/data`.

- [ ] **Step 2: Set Phase A variables**

```text
REZ_ANALYSIS_ENABLED=false
REZ_ANALYSIS_VERSION=REZ_V1
REZ_WATCH_TTL_HOURS=12
```

Do not change `SETUP_MIN_SCORE`, structure/R:R values, `TRADING_MODE`, or `DIRECT_AI_ORDER_ENABLED`.

- [ ] **Step 3: Deploy scanner service only**

Confirm a fresh deployment reaches `SUCCESS`; config write alone is not proof.

- [ ] **Step 4: Verify fresh runtime evidence**

Require: start command still `--limit 80`; provider locks normally; scan cycles continue; no REZ gating logs while disabled; Shadow evaluation continues; `/data` remains mounted.

- [ ] **Step 5: Run external connectivity healthcheck**

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

`TELEGRAM_SEND=SKIPPED` is acceptable here.

- [ ] **Step 6: Record Phase A evidence**

Record deployment id, full test command/result, first successful scan timestamp, and healthcheck output in the handoff/PR description. Do not claim completion without this fresh evidence.

---

### Task 9: Railway Phase B HYBRID Canary

**Target:** Railway service `scanner-v6-shadow` only.

- [ ] **Step 1: Enable only REZ**

```text
REZ_ANALYSIS_ENABLED=true
```

Keep:

```text
SETUP_MIN_SCORE=75
TRADING_MODE=SIMULATION
DIRECT_AI_ORDER_ENABLED=false
```

- [ ] **Step 2: Deploy and verify SUCCESS**

Confirm a fresh scanner deployment reaches `SUCCESS`.

- [ ] **Step 3: Inspect at least two fresh scan cycles**

Require compact summary:

```text
REZ: pass=N wait=N reject=N expired=N promoted=N
```

and deterministic candidate state logs such as:

```text
REZUSDT: 1H=PULLBACK 15m=NO_TRIGGER -> WAIT_ANALYSIS
```

No immediate PASS signal is required; zero signals is valid if deterministic gates do not pass.

- [ ] **Step 4: Verify WAIT does not invoke Astra**

For at least one WAIT candidate, confirm there is no subsequent `Requesting Devil's Advocate AI review` for the same candidate in that cycle.

- [ ] **Step 5: Verify PASS behavior only when naturally observed**

If a PASS occurs, verify Setup Score still runs after REZ and Astra only runs at score `>=75`. If no PASS occurs, rely on automated integration tests for path verification; do not manufacture a production trade.

- [ ] **Step 6: Generate initial report without tuning**

```bash
python rez_report_v1.py --db /data/shadow_eval_v6.sqlite3
```

It must render with low/zero samples and state `Automatic tuning: DISABLED`.

- [ ] **Step 7: Stop at calibration boundary**

Do not alter score weights, threshold, TTL, trigger sensitivity, R:R minimum, or provider behavior from early canary observations. Tuning requires accumulated evidence and separate review.

---

## Final Verification Checklist

- [ ] Full `unittest` discovery exits 0.
- [ ] Generated runtime files compile after part-file assembly.
- [ ] `setup_score_v6.py` is unchanged.
- [ ] Disabled REZ preserves V6 behavior.
- [ ] Enabled REZ WAIT/REJECT never reaches Astra or Telegram.
- [ ] REZ PASS still requires Setup Score `>=75` before Astra.
- [ ] AI failure remains fail-closed.
- [ ] Telegram is final-output only after all gates.
- [ ] Watch identity/dedupe is deterministic and WAIT can promote to PASS.
- [ ] Invalidated/expired watches stop re-evaluating.
- [ ] REZ events link to Shadow snapshots without altering existing Shadow tables.
- [ ] Calibration report groups by structure/trigger and never auto-tunes.
- [ ] Railway scanner stays at `--limit 80` with `/data` volume.
- [ ] `api` service remains untouched.
- [ ] No live/testnet order execution code exists.
