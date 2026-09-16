# REZ Analysis Layer V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the approved deterministic REZ Analysis Layer V1 to Scanner V6 as a HYBRID context/timing gate while preserving all V6 safety rules and keeping live/testnet order execution absent.

**Architecture:** Add three focused modules: deterministic analysis, persistent watch state, and REZ calibration reporting. Insert REZ after the existing Structure Trade Plan and before the unchanged Setup Score. Persist WAIT watches in the same Shadow SQLite database without changing existing Shadow snapshot/outcome semantics. Astra runs only after REZ PASS and Setup Score `>=75`.

**Tech Stack:** Python 3.13 runtime, stdlib `unittest`, SQLite, existing `requests`, `tradingview-ta`, `google-genai`; no new dependency.

**Spec:** `docs/superpowers/specs/2026-09-16-rez-analysis-layer-v1-design.md`

## Global Constraints

- `REZ_ANALYSIS_ENABLED=false` must preserve current V6 behavior.
- Enabled behavior is the approved HYBRID mode only.
- `SETUP_MIN_SCORE=75` remains unchanged.
- Existing minimum structure R:R remains unchanged.
- Existing market-provider lock/fallback remains unchanged.
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
- Keep Railway runtime universe at 80 symbols.
- Tests use stdlib `unittest`; market, Telegram, and Gemini calls are mocked/faked.

---

## File Map

**Create**
- `scanner_v6/rez_analysis_v1.py` — 1H structure, 15m trigger, HYBRID decision logic.
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
- Produces `RezAnalysisResult` and `analyze_rez_candidate`.

Use this public contract:

```python
from dataclasses import dataclass
from typing import Optional

@dataclass(frozen=True)
class RezAnalysisResult:
    analysis_version: str
    state: str
    structure_1h: str
    trigger_15m: str
    supporting_triggers: tuple
    reason: str
    protected_swing_timestamp: Optional[int]
    protected_swing_price: Optional[float]
    trigger_level_kind: Optional[str]
    trigger_level_price: Optional[float]
    closed_1h_at_ms: Optional[int]
    closed_15m_at_ms: Optional[int]
```

For `RANGE`, use the confirmed 1H range boundary chosen as trigger reference for `protected_swing_timestamp` and `protected_swing_price`; it is only a stable watch anchor.

- [ ] **Step 1: Write first failing core test**

```python
import unittest
from rez_analysis_v1 import analyze_rez_candidate

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

- [ ] **Step 3: Implement candle validation, ATR, and confirmed swings**

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
    for index in range(1, len(window)):
        current, previous = window[index], window[index - 1]
        high = float(current["high"])
        low = float(current["low"])
        prev_close = float(previous["close"])
        true_ranges.append(max(high - low, abs(high - prev_close), abs(low - prev_close)))
    return sum(true_ranges) / period
```

`find_confirmed_swings(candles, window)` must return `{"highs": [...], "lows": [...]}` where each swing contains `index`, `price`, and `timestamp=int(close_time)`. Edge candles are never confirmed swings.

- [ ] **Step 4: Add concrete 1H classification tests**

Use closed-candle fixtures for these exact assertions:

```python
self.assertEqual(continuation.structure_1h, "CONTINUATION")
self.assertEqual(pullback.structure_1h, "PULLBACK")
self.assertEqual(reversal.structure_1h, "REVERSAL")
self.assertNotEqual(invalidation_without_new_bos.structure_1h, "REVERSAL")
self.assertEqual(ranging.structure_1h, "RANGE")
self.assertEqual(insufficient.structure_1h, "UNKNOWN")
self.assertEqual(insufficient.state, "REJECT")
self.assertNotEqual(wick_only_break.structure_1h, "CONTINUATION")
```

The wick-only fixture must breach a swing with `high`/`low` but keep close inside the ATR-buffer confirmation boundary.

- [ ] **Step 5: Implement 1H classifier with an explicit return schema**

```python
STRUCTURES = {"CONTINUATION", "PULLBACK", "REVERSAL", "RANGE", "UNKNOWN"}


def _structure_result(structure, protected, trigger_kind, trigger_price, closed_at, invalidated, reason):
    return {
        "structure": structure,
        "protected_swing_timestamp": None if protected is None else int(protected["timestamp"]),
        "protected_swing_price": None if protected is None else float(protected["price"]),
        "trigger_level_kind": trigger_kind,
        "trigger_level_price": None if trigger_price is None else float(trigger_price),
        "closed_1h_at_ms": closed_at,
        "invalidated": bool(invalidated),
        "reason": reason,
    }
```

Algorithm order is fixed: validate ATR/swings; find latest chronological same-side BOS using close beyond swing plus `ATR1H*buffer_mult`; assign latest opposite confirmed swing before/at that BOS as protected swing; test protected-swing invalidation by a later 1H close beyond buffer; classify REVERSAL only if invalidation is followed by a new same-side BOS; otherwise classify CONTINUATION when latest same-side BOS is intact, PULLBACK when intact structure has retraced into the BOS zone, RANGE when no directional BOS is confirmed but usable boundaries exist, UNKNOWN when deterministic anchors are missing.

- [ ] **Step 6: Add concrete 15m trigger tests**

Assert these exact outcomes from closed fixtures:

```python
self.assertEqual(breakout.trigger_15m, "BREAKOUT")
self.assertEqual(retest.trigger_15m, "RETEST")
self.assertEqual(reclaim.trigger_15m, "RECLAIM")
self.assertEqual(rejection.trigger_15m, "REJECTION")
self.assertIn("LIQUIDITY_SWEEP", sweep.supporting_triggers)
self.assertNotEqual(sweep.trigger_15m, "LIQUIDITY_SWEEP")
self.assertEqual(opposite_break.state, "REJECT")
self.assertEqual(no_trigger.trigger_15m, "NO_TRIGGER")
self.assertEqual(no_trigger.state, "WAIT")
```

- [ ] **Step 7: Implement literal HYBRID matrix and trigger rules**

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

Trigger rules are exact: 15m BREAKOUT requires close beyond `trigger_level ± ATR15m*buffer_mult`; RETEST requires an earlier confirmed breakout then a later zone touch and valid-side close; RECLAIM requires trade through level then valid-side close; REJECTION requires zone touch, valid-side close, and zone-facing wick `>= abs(close-open)` with nonzero body; LIQUIDITY_SWEEP uses latest confirmed 15m opposite swing and is supporting-only; explicit opposite breakout beyond opposite confirmed 15m swing plus buffer sets `opposite_trigger=True`.

- [ ] **Step 8: Implement public analyzer**

```python
def analyze_rez_candidate(
    *, side, candles_1h, candles_15m, atr_period,
    atr_buffer_mult, swing_window, analysis_version="REZ_V1",
):
    side = str(side).upper()
    if side not in {"LONG", "SHORT"} or atr_period <= 0 or atr_buffer_mult < 0 or swing_window < 1:
        return RezAnalysisResult(
            analysis_version=analysis_version,
            state="REJECT",
            structure_1h="UNKNOWN",
            trigger_15m="NO_TRIGGER",
            supporting_triggers=(),
            reason="INVALID_INPUT",
            protected_swing_timestamp=None,
            protected_swing_price=None,
            trigger_level_kind=None,
            trigger_level_price=None,
            closed_1h_at_ms=None,
            closed_15m_at_ms=None,
        )
```

After input validation, call `_classify_1h_structure`; convert UNKNOWN to REJECT; otherwise require a deterministic trigger level, classify 15m, call `_hybrid_state`, then construct a fully populated `RezAnalysisResult` with no missing required metadata for WAIT/PASS watches.

- [ ] **Step 9: Run GREEN**

```bash
cd scanner_v6
python -m unittest tests.test_rez_analysis_v1 -v
```

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

- [ ] **Step 1: Write failing schema test**

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

- [ ] **Step 3: Implement schema and stable identity**

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

Create all approved columns in `rez_watch_state` and `rez_analysis_events`. Add `UNIQUE(watch_key)` and event uniqueness on `(watch_id, closed_15m_at_ms, analysis_state, trigger_15m)`.

- [ ] **Step 4: Add transition tests**

Use real SQLite and assert: identical WAIT on identical closed 15m timestamp returns `event_inserted=False`; a newer closed 15m candle appends an event; WAIT then PASS returns `promoted=True`; REJECT sets `invalidated_at_ms`; `expire_due` changes only active WAIT rows past fixed 12-hour expiry.

- [ ] **Step 5: Implement state mapping and promotion result**

```python
STATE_MAP = {
    "PASS": "ANALYSIS_PASS",
    "WAIT": "ANALYSIS_WAIT",
    "REJECT": "REJECT_ANALYSIS",
}


def _is_promotion(previous_state, current_state):
    return previous_state == "ANALYSIS_WAIT" and current_state == "ANALYSIS_PASS"
```

`record_analysis` must: build key; fetch/create watch; preserve original `first_seen_at_ms`; compute fixed `expires_at_ms=first_seen_at_ms + ttl_hours*3_600_000`; update current metadata; insert one deduped event; set invalidation timestamp on REJECT; return all `RezRecordResult` fields including `promoted` from `_is_promotion`.

- [ ] **Step 6: Implement one-time Shadow snapshot link with tests**

```python
def _validate_snapshot_link(current, requested):
    if current is None:
        return "SET"
    if str(current) == str(requested):
        return "NOOP"
    raise ValueError("REZ event already linked to another Shadow snapshot")
```

`link_event_snapshot(event_id, snapshot_id)` must read current value, apply this rule, update only when action is `SET`, and raise on missing event or empty requested ID. Do not alter existing Shadow tables.

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
- Produces `build_rez_report(rows)`, `generate_report(db_path)`, text renderer, and CLI.

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

Use `statistics.mean` and `statistics.median`; zero denominators return `None`. Report keys must include WAIT-to-PASS, PASS-to-score-gate, PASS-to-Astra-approved, expiry, invalidation, structure/trigger breakdowns, TP/SL rates, average/median MFE R, and average/median MAE R.

- [ ] **Step 4: Add CLI test and implementation**

Text must contain `REZ V1 Calibration Report`, `WAIT->PASS`, structure/trigger sections, and `Automatic tuning: DISABLED`. Support:

```bash
python rez_report_v1.py --db shadow_eval_v6.sqlite3
python rez_report_v1.py --db shadow_eval_v6.sqlite3 --json
```

- [ ] **Step 5: Run GREEN and commit**

```bash
cd scanner_v6
python -m unittest tests.test_rez_report_v1 -v
git add rez_report_v1.py tests/test_rez_report_v1.py
git commit -m "feat(scanner-v6): add REZ calibration reporting"
```

---

### Task 4: Scanner Configuration and Disabled-Path Preservation

**Files:**
- Modify: `scanner_v6/auto_scanner_v6.part00`
- Create: `scanner_v6/tests/test_rez_scanner_integration.py`

**Interfaces:**
- Produces `REZ_ANALYSIS_ENABLED`, `REZ_ANALYSIS_VERSION`, `REZ_WATCH_TTL_HOURS`, and `get_rez_watch_store`.

- [ ] **Step 1: Write failing config/default test**

After assembling generated files, import scanner with REZ env vars unset and assert:

```python
self.assertFalse(scanner.REZ_ANALYSIS_ENABLED)
self.assertEqual(scanner.REZ_ANALYSIS_VERSION, "REZ_V1")
self.assertEqual(scanner.REZ_WATCH_TTL_HOURS, 12)
```

Patch `RezWatchStore` and assert it is not constructed while REZ is disabled.

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

`get_rez_watch_store` must follow the existing `get_shadow_store` sticky fail-closed pattern and use `SHADOW_DB_PATH`. The scanner must call it only when REZ is enabled.

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
- Only REZ PASS reaches `score_setup` when enabled.

- [ ] **Step 1: Add failing orchestration tests**

Use mocks with these exact call assertions:

```python
score_setup.assert_not_called()          # REZ WAIT and REZ REJECT
analyze_with_ai.assert_not_called()      # WAIT, REJECT, and PASS score 74
send_telegram_alert.assert_not_called()  # WAIT, REJECT, and PASS score 74
analyze_with_ai.assert_called_once()     # PASS score 75 or higher
analyze_rez_candidate.assert_not_called()  # REZ disabled legacy path
```

Also make a REZ-store failure test and assert candidate never reaches Astra.

- [ ] **Step 2: Run RED**

```bash
cd scanner_v6
cat shadow_eval_v6.part* > shadow_eval_v6.py
cat auto_scanner_v6.part* > auto_scanner_v6.py
python -m unittest tests.test_rez_scanner_integration -v
```

- [ ] **Step 3: Invoke REZ after existing Structure Plan**

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
        symbol=symbol,
        side=side,
        provider=provider_name,
        result=rez_result,
        now_ms=int(time.time() * 1000),
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

```python
rez_counts = {"pass": 0, "wait": 0, "reject": 0, "expired": 0, "promoted": 0}
```

Call `expire_due(now_ms)` once per enabled scan. Increment `promoted` only from `rez_record.promoted`. Print once per enabled scan:

```text
[*] REZ: pass=N wait=N reject=N expired=N promoted=N
```

- [ ] **Step 5: Carry REZ metadata and link Shadow snapshot**

Add to qualified item:

```python
"rez_result": rez_result,
"rez_event_id": None if rez_record is None else rez_record.event_id,
```

After `shadow_store.record_snapshot` returns:

```python
if REZ_ANALYSIS_ENABLED and rez_record is not None:
    rez_store.link_event_snapshot(rez_record.event_id, shadow_snapshot_id)
```

Any link failure stops that candidate before Astra/Telegram.

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

**Interface:** `analyze_with_ai` gains optional `rez_result: Optional[RezAnalysisResult] = None`.

- [ ] **Step 1: Write failing Astra prompt test**

Capture Gemini `contents` and assert a PULLBACK/RETEST result with sweep tag contains exactly:

```text
REZ Analysis: REZ_V1
1H Structure: PULLBACK
15m Trigger: RETEST
Supporting Triggers: LIQUIDITY_SWEEP
```

- [ ] **Step 2: Extend Astra input without changing output contract**

```python
def _rez_prompt_text(rez_result):
    if rez_result is None:
        return "REZ Analysis: DISABLED"
    support = ",".join(sorted(rez_result.supporting_triggers)) or "NONE"
    return (
        f"REZ Analysis: {rez_result.analysis_version}\n"
        f"1H Structure: {rez_result.structure_1h}\n"
        f"15m Trigger: {rez_result.trigger_15m}\n"
        f"Supporting Triggers: {support}\n"
        f"REZ Reason: {rez_result.reason}"
    )
```

Append this compact text to the current Astra prompt; never send raw candles. Keep the existing response JSON contract: confidence, verdict, reason, risk.

- [ ] **Step 3: Write failing Telegram-format test**

Capture final message and assert enabled REZ adds:

```text
📐 *1H Structure:* `PULLBACK`
⚡ *15m Trigger:* `RETEST + LIQUIDITY_SWEEP`
🧪 *Analysis:* `REZ_V1`
```

Assert these lines are absent when REZ metadata is `None`, while existing Entry/SL/TP/score/Astra/BTC/provider/invalidation lines remain.

- [ ] **Step 4: Implement final-output formatting**

Primary trigger is first; supporting triggers are sorted and appended with ` + `. WAIT_ANALYSIS, REJECT_ANALYSIS, WAIT_SCORE, and WAIT_ASTRA must never enter final delivery.

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

- [ ] **Step 3: Run full test suite**

```bash
python -m unittest discover -s tests -v
```

Expected: exit 0, zero failures, zero errors.

- [ ] **Step 4: Prove Setup Score code is unchanged**

```bash
git diff 7331c56a88dffe87d21d6ba7bfddf1847c4dbcfe -- scanner_v6/setup_score_v6.py
```

Expected: no diff.

- [ ] **Step 5: Prove no order-execution path was introduced**

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

- [ ] **Step 1: Confirm runtime config**

Require:

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

Do not change score, structure/R:R, trading mode, or direct-order flags.

- [ ] **Step 3: Deploy scanner only and verify SUCCESS**

A config write is not proof; confirm a fresh deployment reaches `SUCCESS`.

- [ ] **Step 4: Verify fresh runtime evidence**

Require: `--limit 80`; provider lock healthy; scan cycles continue; no REZ gating while disabled; Shadow evaluation continues; `/data` mounted.

- [ ] **Step 5: Run external healthcheck**

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

`TELEGRAM_SEND=SKIPPED` is acceptable.

- [ ] **Step 6: Record evidence**

Record deployment id, full test result, first successful scan timestamp, and healthcheck output. Do not claim Phase A complete without this fresh evidence.

---

### Task 9: Railway Phase B HYBRID Canary

**Target:** Railway service `scanner-v6-shadow` only.

- [ ] **Step 1: Enable only REZ**

```text
REZ_ANALYSIS_ENABLED=true
SETUP_MIN_SCORE=75
TRADING_MODE=SIMULATION
DIRECT_AI_ORDER_ENABLED=false
```

- [ ] **Step 2: Deploy and verify SUCCESS**

Confirm a fresh scanner deployment reaches `SUCCESS`.

- [ ] **Step 3: Inspect at least two fresh scan cycles**

Require:

```text
REZ: pass=N wait=N reject=N expired=N promoted=N
```

and deterministic state logs such as:

```text
REZUSDT: 1H=PULLBACK 15m=NO_TRIGGER -> WAIT_ANALYSIS
```

Zero immediate signals is valid if gates do not pass.

- [ ] **Step 4: Verify WAIT does not invoke Astra**

For at least one WAIT candidate, confirm there is no subsequent `Requesting Devil's Advocate AI review` for that candidate in the same cycle.

- [ ] **Step 5: Verify PASS behavior only when naturally observed**

If PASS occurs, verify Setup Score runs after REZ and Astra only at score `>=75`. If no PASS occurs, use automated integration tests as path evidence and keep collecting watches; do not manufacture a production trade.

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
