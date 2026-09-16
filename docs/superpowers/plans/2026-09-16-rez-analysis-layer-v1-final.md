# REZ Analysis Layer V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the approved deterministic REZ Analysis Layer V1 to Scanner V6 as a HYBRID context/timing gate without weakening any existing V6 safety rule.

**Architecture:** Create a pure deterministic analysis module, a persistent REZ watch store in the same Shadow SQLite file, and a REZ calibration report. Insert the REZ gate after the existing Structure Trade Plan and before the unchanged Setup Score. REZ WAIT/REJECT cannot reach Astra or Telegram; REZ PASS still needs Setup Score `>=75` before Astra.

**Tech Stack:** Python 3.13, stdlib `unittest`, SQLite, existing project dependencies only.

**Spec:** `docs/superpowers/specs/2026-09-16-rez-analysis-layer-v1-design.md`

## Global Constraints

- Default `REZ_ANALYSIS_ENABLED=false`.
- Enabled behavior is HYBRID only.
- `SETUP_MIN_SCORE=75` remains unchanged.
- Existing minimum structure R:R remains unchanged.
- Existing market-provider lock/fallback remains unchanged.
- Use only closed candles from the provider locked for the current scan cycle.
- Never mix Binance and Bybit candles inside one candidate evaluation.
- Reuse `STRUCTURE_SWING_WINDOW`, `STRUCTURE_ATR_PERIOD`, `STRUCTURE_ATR_BUFFER_MULT`.
- `REZ_ANALYSIS_VERSION=REZ_V1` by default.
- `REZ_WATCH_TTL_HOURS=12` by default.
- Astra remains Devil's Advocate only and cannot change side.
- AI failure remains fail-closed.
- Telegram remains final-output only after all deterministic gates, Astra approval, and cooldown.
- No live/testnet order execution.
- No new Python dependency.
- Keep Railway scanner universe at `--limit 80`.
- Do not modify `api` Railway service.

---

## File Map

Create:
- `scanner_v6/rez_analysis_v1.py`
- `scanner_v6/rez_watch_v1.py`
- `scanner_v6/rez_report_v1.py`
- `scanner_v6/tests/test_rez_analysis_v1.py`
- `scanner_v6/tests/test_rez_watch_v1.py`
- `scanner_v6/tests/test_rez_report_v1.py`
- `scanner_v6/tests/test_rez_scanner_integration.py`

Modify:
- `scanner_v6/auto_scanner_v6.part00`
- `scanner_v6/auto_scanner_v6.part02`
- `scanner_v6/auto_scanner_v6.part03`
- `scanner_v6/auto_scanner_v6.part04`

Do not modify unless a failing regression proves a specific need:
- `scanner_v6/setup_score_v6.py`
- `scanner_v6/shadow_eval_v6.part00`
- `scanner_v6/shadow_eval_v6.part01`
- `scanner_v6/shadow_eval_v6.part02`
- `scanner_v6/market_data_v6.py`
- `scanner_v6/requirements.txt`

---

### Task 1: Deterministic REZ Analysis Core

**Files:**
- Create `scanner_v6/rez_analysis_v1.py`
- Create `scanner_v6/tests/test_rez_analysis_v1.py`

**Produces:**

```python
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

- [ ] **Step 1: Write RED test for missing history**

```python
class RezAnalysisTests(unittest.TestCase):
    def test_missing_history_fails_closed(self):
        result = analyze_rez_candidate(
            side="LONG", candles_1h=[], candles_15m=[],
            atr_period=14, atr_buffer_mult=0.25,
            swing_window=2, analysis_version="REZ_V1",
        )
        self.assertEqual(result.structure_1h, "UNKNOWN")
        self.assertEqual(result.state, "REJECT")
```

- [ ] **Step 2: Verify RED**

```bash
cd scanner_v6
python -m unittest tests.test_rez_analysis_v1 -v
```

- [ ] **Step 3: Implement candle validation, ATR, confirmed swings**

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
    if not all(_valid_closed_candle(row) for row in window):
        return None
    values = []
    for index in range(1, len(window)):
        current = window[index]
        previous = window[index - 1]
        high = float(current["high"])
        low = float(current["low"])
        previous_close = float(previous["close"])
        values.append(max(high - low, abs(high - previous_close), abs(low - previous_close)))
    return sum(values) / period
```

`find_confirmed_swings` returns `{"highs": list, "lows": list}`. Every swing dict contains exactly `index`, `price`, `timestamp`. Edge candles are excluded.

- [ ] **Step 4: Add RED/GREEN structure classification tests**

Tests must assert these outcomes from explicit closed-candle fixtures:

```python
self.assertEqual(continuation.structure_1h, "CONTINUATION")
self.assertEqual(pullback.structure_1h, "PULLBACK")
self.assertEqual(reversal.structure_1h, "REVERSAL")
self.assertNotEqual(invalidation_without_new_bos.structure_1h, "REVERSAL")
self.assertEqual(ranging.structure_1h, "RANGE")
self.assertNotEqual(wick_only_break.structure_1h, "CONTINUATION")
```

Classification algorithm order is fixed: calculate ATR1H; find confirmed swings; find chronological same-side BOS only when candle close exceeds swing by `ATR1H*buffer_mult`; assign latest opposite swing as protected swing; detect later protected-swing invalidation by close plus buffer; classify REVERSAL only when a new same-side BOS occurs after invalidation; otherwise classify intact same-side BOS as CONTINUATION or PULLBACK based on retrace into BOS zone; classify no directional BOS with usable boundaries as RANGE; insufficient deterministic anchors as UNKNOWN.

- [ ] **Step 5: Add RED/GREEN 15m trigger tests**

Tests must assert:

```python
self.assertEqual(breakout.trigger_15m, "BREAKOUT")
self.assertEqual(retest.trigger_15m, "RETEST")
self.assertEqual(reclaim.trigger_15m, "RECLAIM")
self.assertEqual(rejection.trigger_15m, "REJECTION")
self.assertIn("LIQUIDITY_SWEEP", sweep.supporting_triggers)
self.assertNotEqual(sweep.trigger_15m, "LIQUIDITY_SWEEP")
self.assertEqual(opposite_break.state, "REJECT")
self.assertEqual(no_trigger.trigger_15m, "NO_TRIGGER")
```

Rules are exact: BREAKOUT uses closed 15m close beyond `trigger_level ± ATR15m*buffer_mult`; RETEST requires an earlier breakout then later zone touch and valid-side close; RECLAIM requires trade through level then close back to valid side; REJECTION requires zone touch, valid-side close, nonzero body, zone-facing wick at least body size; LIQUIDITY_SWEEP uses latest confirmed opposite 15m swing and is supporting-only; opposite close-confirmed breakout rejects.

- [ ] **Step 6: Implement literal HYBRID matrix**

```python
PASS_MATRIX = {
    "CONTINUATION": {"BREAKOUT", "RETEST", "REJECTION"},
    "PULLBACK": {"RETEST", "REJECTION", "RECLAIM"},
    "REVERSAL": {"RECLAIM", "BREAKOUT"},
}


def hybrid_state(structure, trigger, opposite_trigger):
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

- [ ] **Step 7: Implement public analyzer and GREEN verification**

Exact signature:

```python
def analyze_rez_candidate(
    *, side, candles_1h, candles_15m, atr_period,
    atr_buffer_mult, swing_window, analysis_version="REZ_V1",
):
```

WAIT/PASS must always contain `protected_swing_timestamp`, `trigger_level_kind`, `trigger_level_price`, and closed 1H/15m timestamps. UNKNOWN REJECT may leave anchor fields null.

Run:

```bash
python -m unittest tests.test_rez_analysis_v1 -v
```

- [ ] **Step 8: Commit Task 1**

```bash
git add rez_analysis_v1.py tests/test_rez_analysis_v1.py
git commit -m "feat(scanner-v6): add deterministic REZ analysis core"
```

---

### Task 2: Persistent REZ Watch State

**Files:**
- Create `scanner_v6/rez_watch_v1.py`
- Create `scanner_v6/tests/test_rez_watch_v1.py`

**Produces:**

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

- [ ] **Step 1: Write RED schema test with temporary SQLite file**

```python
class RezWatchStoreTests(unittest.TestCase):
    def test_initialization_creates_tables(self):
        store = RezWatchStore(self.db_path)
        names = store.table_names()
        self.assertIn("rez_watch_state", names)
        self.assertIn("rez_analysis_events", names)
```

- [ ] **Step 2: Implement approved schema and stable key**

```python
def build_watch_key(symbol, side, anchor_timestamp, trigger_level_kind, analysis_version):
    symbol = str(symbol).strip().upper()
    side = str(side).strip().upper()
    kind = str(trigger_level_kind).strip().upper()
    version = str(analysis_version).strip().upper()
    if not symbol or side not in {"LONG", "SHORT"} or anchor_timestamp is None or not kind or not version:
        raise ValueError("invalid REZ watch identity")
    return f"{symbol}|{side}|{int(anchor_timestamp)}|{kind}|{version}"
```

Create approved `rez_watch_state` and `rez_analysis_events` columns. `watch_key` is unique. Event uniqueness is `(watch_id, closed_15m_at_ms, analysis_state, trigger_15m)`.

- [ ] **Step 3: Add state-transition tests**

Use real SQLite and verify: repeated same WAIT/closed-15m is deduped; newer closed 15m creates event; WAIT then PASS returns `promoted=True`; anchored REJECT sets `invalidated_at_ms`; `expire_due` changes only active WAIT rows after fixed 12-hour TTL.

- [ ] **Step 4: Implement state mapping**

```python
STATE_MAP = {
    "PASS": "ANALYSIS_PASS",
    "WAIT": "ANALYSIS_WAIT",
    "REJECT": "REJECT_ANALYSIS",
}


def is_promotion(previous_state, current_state):
    return previous_state == "ANALYSIS_WAIT" and current_state == "ANALYSIS_PASS"
```

`record_analysis` preserves original `first_seen_at_ms`; expiry never slides forward; returns `RezRecordResult`.

- [ ] **Step 5: Implement Shadow snapshot link tests and method**

```python
def validate_snapshot_link(current, requested):
    if current is None:
        return "SET"
    if str(current) == str(requested):
        return "NOOP"
    raise ValueError("REZ event already linked to another Shadow snapshot")
```

`link_event_snapshot` updates null link once, treats same link as idempotent, rejects another snapshot id, and never changes existing Shadow tables.

- [ ] **Step 6: Run GREEN and commit**

```bash
python -m unittest tests.test_rez_watch_v1 -v
git add rez_watch_v1.py tests/test_rez_watch_v1.py
git commit -m "feat(scanner-v6): persist REZ watch states"
```

---

### Task 3: REZ Calibration Report

**Files:**
- Create `scanner_v6/rez_report_v1.py`
- Create `scanner_v6/tests/test_rez_report_v1.py`

- [ ] **Step 1: Write RED aggregation test**

Use one watch with WAIT then PASS/RETEST, score 82, Astra APPROVED, TP1, MFE 1.8R, MAE -0.4R. Assert WAIT-to-PASS, PASS-to-score>=75, PASS-to-Astra-approved are 100%, and PULLBACK/RETEST sample counts are one.

- [ ] **Step 2: Implement database join**

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

- [ ] **Step 3: Implement metrics**

Use stdlib mean/median. Zero denominator returns `None`. Include WAIT-to-PASS, PASS-to-score>=75, PASS-to-Astra-approved, expiry, invalidation, TP1/TP2/TP3/SL rates, average/median MFE/MAE, by structure, by trigger, and analysis version. Never auto-tune.

- [ ] **Step 4: Add CLI and GREEN test**

```bash
python rez_report_v1.py --db shadow_eval_v6.sqlite3
python rez_report_v1.py --db shadow_eval_v6.sqlite3 --json
python -m unittest tests.test_rez_report_v1 -v
```

Text must state `Automatic tuning: DISABLED`.

- [ ] **Step 5: Commit Task 3**

```bash
git add rez_report_v1.py tests/test_rez_report_v1.py
git commit -m "feat(scanner-v6): add REZ calibration reporting"
```

---

### Task 4: Scanner Config and Disabled-Path Preservation

**Files:**
- Modify `scanner_v6/auto_scanner_v6.part00`
- Create `scanner_v6/tests/test_rez_scanner_integration.py`

- [ ] **Step 1: Write RED default-config test**

Assert with REZ env vars unset:

```python
self.assertFalse(scanner.REZ_ANALYSIS_ENABLED)
self.assertEqual(scanner.REZ_ANALYSIS_VERSION, "REZ_V1")
self.assertEqual(scanner.REZ_WATCH_TTL_HOURS, 12)
```

Assert disabled flow does not construct `RezWatchStore`.

- [ ] **Step 2: Add config/imports**

```python
from rez_analysis_v1 import RezAnalysisResult, analyze_rez_candidate
from rez_watch_v1 import RezWatchStore

REZ_ANALYSIS_ENABLED = os.getenv("REZ_ANALYSIS_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}
REZ_ANALYSIS_VERSION = os.getenv("REZ_ANALYSIS_VERSION", "REZ_V1").strip() or "REZ_V1"
REZ_WATCH_TTL_HOURS = int(os.getenv("REZ_WATCH_TTL_HOURS", "12"))
```

Add lazy `get_rez_watch_store` using `SHADOW_DB_PATH` and the same sticky fail-closed pattern as `get_shadow_store`.

- [ ] **Step 3: Assemble and GREEN**

```bash
cat shadow_eval_v6.part* > shadow_eval_v6.py
cat auto_scanner_v6.part* > auto_scanner_v6.py
python -m unittest tests.test_rez_scanner_integration -v
```

- [ ] **Step 4: Commit Task 4**

```bash
git add auto_scanner_v6.part00 tests/test_rez_scanner_integration.py
git commit -m "feat(scanner-v6): add REZ feature configuration"
```

---

### Task 5: HYBRID Gate Integration

**Files:**
- Modify `scanner_v6/auto_scanner_v6.part03`
- Modify `scanner_v6/auto_scanner_v6.part04`
- Modify `scanner_v6/tests/test_rez_scanner_integration.py`

- [ ] **Step 1: Write RED orchestration tests**

Required assertions:

```python
score_setup.assert_not_called()            # REZ WAIT or REJECT
analyze_with_ai.assert_not_called()        # WAIT, REJECT, PASS score 74
send_telegram_alert.assert_not_called()    # WAIT, REJECT, PASS score 74
analyze_with_ai.assert_called_once()       # PASS score >=75
analyze_rez_candidate.assert_not_called()  # feature disabled
```

Also test REZ persistence failure stops candidate before Astra.

- [ ] **Step 2: Invoke REZ after successful existing Structure Plan**

```python
rez_result = analyze_rez_candidate(
    side=side,
    candles_1h=candles_1h,
    candles_15m=market_session.provider.get_klines(symbol, "15m", STRUCTURE_KLINE_LIMIT),
    atr_period=STRUCTURE_ATR_PERIOD,
    atr_buffer_mult=STRUCTURE_ATR_BUFFER_MULT,
    swing_window=STRUCTURE_SWING_WINDOW,
    analysis_version=REZ_ANALYSIS_VERSION,
)
```

Do not make this extra 15m provider call while feature is disabled.

- [ ] **Step 3: Apply anchor/persistence rule exactly**

```python
has_watch_anchor = (
    rez_result.protected_swing_timestamp is not None
    and rez_result.trigger_level_kind is not None
    and rez_result.trigger_level_price is not None
)

if rez_result.state == "REJECT" and not has_watch_anchor:
    rez_counts["reject"] += 1
    print(f"  [x] {symbol}: REZ {rez_result.reason} -> REJECT_ANALYSIS")
    continue

if not has_watch_anchor:
    rez_counts["reject"] += 1
    print(f"  [x] {symbol}: REZ missing deterministic watch anchor -> REJECT_ANALYSIS")
    continue

rez_record = rez_store.record_analysis(
    symbol=symbol,
    side=side,
    provider=provider_name,
    result=rez_result,
    now_ms=int(time.time() * 1000),
    ttl_hours=REZ_WATCH_TTL_HOURS,
)
```

Anchored REJECT is persisted then rejected. WAIT/PASS without an anchor is fail-closed. UNKNOWN/data-insufficient REJECT without anchor is rejected/logged but does not create an invalid watch key.

- [ ] **Step 4: Gate downstream flow**

```python
if rez_result.state == "WAIT":
    rez_counts["wait"] += 1
    continue
if rez_result.state != "PASS":
    rez_counts["reject"] += 1
    continue
rez_counts["pass"] += 1
if rez_record.promoted:
    rez_counts["promoted"] += 1
```

Only PASS reaches existing `score_setup`.

- [ ] **Step 5: Expire once per scan and link PASS event to Shadow snapshot**

Call `expire_due(now_ms)` once per enabled scan. After existing `shadow_store.record_snapshot` returns:

```python
rez_store.link_event_snapshot(rez_record.event_id, shadow_snapshot_id)
```

Any link failure stops that candidate before Astra/Telegram. Add REZ result/event id to the qualified item. Print one summary:

```text
[*] REZ: pass=N wait=N reject=N expired=N promoted=N
```

- [ ] **Step 6: Assemble, GREEN, commit**

```bash
cat shadow_eval_v6.part* > shadow_eval_v6.py
cat auto_scanner_v6.part* > auto_scanner_v6.py
python -m unittest tests.test_rez_scanner_integration -v
git add auto_scanner_v6.part03 auto_scanner_v6.part04 tests/test_rez_scanner_integration.py
git commit -m "feat(scanner-v6): gate setups through REZ hybrid analysis"
```

---

### Task 6: Astra Context and Telegram Output

**Files:**
- Modify `scanner_v6/auto_scanner_v6.part02`
- Modify `scanner_v6/auto_scanner_v6.part04`
- Modify integration tests.

- [ ] **Step 1: Write RED Astra prompt test**

A PULLBACK/RETEST with LIQUIDITY_SWEEP supporting tag must include four deterministic lines: analysis version, 1H structure, 15m primary trigger, supporting triggers.

- [ ] **Step 2: Implement compact prompt helper**

```python
def rez_prompt_text(rez_result):
    if rez_result is None:
        return "REZ Analysis: DISABLED"
    support = ",".join(sorted(rez_result.supporting_triggers)) or "NONE"
    return "\n".join([
        f"REZ Analysis: {rez_result.analysis_version}",
        f"1H Structure: {rez_result.structure_1h}",
        f"15m Trigger: {rez_result.trigger_15m}",
        f"Supporting Triggers: {support}",
        f"REZ Reason: {rez_result.reason}",
    ])
```

Extend `analyze_with_ai` with optional `rez_result`. Never send raw candles. Existing Astra response schema remains unchanged.

- [ ] **Step 3: Write RED Telegram-format test and implement**

Enabled final signal includes:

```text
📐 *1H Structure:* `PULLBACK`
⚡ *15m Trigger:* `RETEST + LIQUIDITY_SWEEP`
🧪 *Analysis:* `REZ_V1`
```

Disabled flow omits these three lines but preserves existing alert fields. WAIT_ANALYSIS, REJECT_ANALYSIS, WAIT_SCORE, WAIT_ASTRA never enter final delivery.

- [ ] **Step 4: GREEN and commit**

```bash
cat shadow_eval_v6.part* > shadow_eval_v6.py
cat auto_scanner_v6.part* > auto_scanner_v6.py
python -m unittest tests.test_rez_scanner_integration -v
git add auto_scanner_v6.part02 auto_scanner_v6.part04 tests/test_rez_scanner_integration.py
git commit -m "feat(scanner-v6): add REZ context to Astra and alerts"
```

---

### Task 7: Full Regression and Build Verification

- [ ] **Step 1: Assemble runtime files**

```bash
cd scanner_v6
cat shadow_eval_v6.part* > shadow_eval_v6.py
cat auto_scanner_v6.part* > auto_scanner_v6.py
```

- [ ] **Step 2: Compile**

```bash
python -m py_compile market_data_v6.py setup_score_v6.py shadow_eval_v6.py shadow_report_v6.py rez_analysis_v1.py rez_watch_v1.py rez_report_v1.py auto_scanner_v6.py
```

- [ ] **Step 3: Run full tests**

```bash
python -m unittest discover -s tests -v
```

Require exit 0, zero failures/errors.

- [ ] **Step 4: Prove score module unchanged**

```bash
git diff 7331c56a88dffe87d21d6ba7bfddf1847c4dbcfe -- scanner_v6/setup_score_v6.py
```

Require no diff.

- [ ] **Step 5: Prove no order execution path added**

```bash
grep -RniE "create_order|place_order|new_order|futures_create_order|/order" rez_analysis_v1.py rez_watch_v1.py rez_report_v1.py auto_scanner_v6.py
```

Require no executable order API path.

---

### Task 8: Railway Phase A, Deployed Disabled

Target only `scanner-v6-shadow`.

- [ ] Confirm start command stays `python -u auto_scanner_v6.py --interval 5 --limit 80` and `/data` volume exists.
- [ ] Set `REZ_ANALYSIS_ENABLED=false`, `REZ_ANALYSIS_VERSION=REZ_V1`, `REZ_WATCH_TTL_HOURS=12`.
- [ ] Do not change score threshold, R:R, trading mode, direct-order flag, provider behavior, or `api` service.
- [ ] Deploy and require fresh `SUCCESS`.
- [ ] Verify scan cycles/provider lock/Shadow evaluation continue and REZ gating does not appear while disabled.
- [ ] Run `python external_healthcheck.py` and require `GEMINI=OK`, `TELEGRAM_AUTH=OK`, `TELEGRAM_CHAT=OK`, `HEALTHCHECK=OK`.
- [ ] Record deployment id, full test result, first successful scan timestamp, healthcheck output.

---

### Task 9: Railway Phase B, HYBRID Canary

- [ ] Set only `REZ_ANALYSIS_ENABLED=true`; keep `SETUP_MIN_SCORE=75`, `TRADING_MODE=SIMULATION`, `DIRECT_AI_ORDER_ENABLED=false`.
- [ ] Deploy scanner and require fresh `SUCCESS`.
- [ ] Observe at least two scan cycles and require `REZ: pass=N wait=N reject=N expired=N promoted=N`.
- [ ] Confirm at least one WAIT candidate does not invoke Astra in the same cycle.
- [ ] If a natural PASS occurs, verify score gate follows REZ and Astra runs only at score `>=75`. Do not manufacture a production trade if no PASS occurs.
- [ ] Run `python rez_report_v1.py --db /data/shadow_eval_v6.sqlite3`; it must render even with low sample count and state `Automatic tuning: DISABLED`.
- [ ] Stop at calibration boundary. No tuning of scores, threshold, TTL, trigger sensitivity, R:R, or provider behavior without separate evidence/review.

---

## Final Verification Checklist

- [ ] Full `unittest` discovery exits 0.
- [ ] Runtime modules compile after part-file assembly.
- [ ] `setup_score_v6.py` unchanged.
- [ ] Disabled REZ preserves V6 behavior.
- [ ] WAIT/REJECT never reaches Astra or Telegram.
- [ ] PASS still needs score `>=75` before Astra.
- [ ] AI failure remains fail-closed.
- [ ] Watch identity/dedupe deterministic; WAIT can promote to PASS.
- [ ] Unanchored UNKNOWN/REJECT does not create invalid watch keys.
- [ ] Invalidated/expired watches stop re-evaluating.
- [ ] REZ events link to Shadow snapshots without changing existing Shadow tables.
- [ ] Calibration reporting never auto-tunes.
- [ ] Railway remains `--limit 80` with `/data` volume.
- [ ] `api` service untouched.
- [ ] No live/testnet order execution code exists.
