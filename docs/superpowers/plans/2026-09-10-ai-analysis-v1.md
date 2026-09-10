# AI Analysis V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add structured AI analysis for the highest-ranked market-scanner candidates inside the existing `market-worker`, persist sanitized analysis results, expose them read-only through the API/UI, and preserve SIMULATION-only safety and realtime failure isolation.

**Architecture:** `market-worker` persists each scanner run first, then launches an asynchronous AI-analysis task while realtime WebSocket ingestion starts immediately. AI input is a bounded 4h/1h/15m snapshot plus scanner/futures/news context; provider-specific HTTP adapters return the existing `AIDecision` model, which then passes deterministic price geometry and risk precheck before persistence in `market_ai_analyses`.

**Tech Stack:** Python 3.12, asyncio, httpx, Pydantic 2, FastAPI, PostgreSQL/Supabase PostgREST + RLS, React 19 + TypeScript + Vite, pytest/pytest-asyncio, Railway, Cloudflare static assets.

**Spec:** `docs/superpowers/specs/2026-09-10-ai-analysis-v1-design.md`

## Global Constraints

- `TRADING_MODE=SIMULATION` throughout this milestone.
- `DIRECT_AI_ORDER_ENABLED=false`; AI never sends an order in V1.
- `AI_ANALYSIS_V1_ENABLED=false` is the default and initial deployment state.
- AI failure must never invalidate a persisted scanner run or prevent realtime ingestion from starting.
- Provider output must validate through the existing `btc_core.ai.models.AIDecision`; do not create a duplicate decision schema.
- New-candidate AI directions are limited to `LONG`, `SHORT`, `WAIT`; `EXIT` is rejected in this workflow.
- Default timeout is 20 seconds, maximum retry count is 1, candidate limit is 3, AI concurrency is 2, minimum scanner score is 65.
- Initial production canary is one candidate with concurrency 1.
- `AI_API_KEY` remains server-side; never return, log, or persist it or an Authorization header.
- No paid/external AI call is made by CI; provider requests use `httpx.MockTransport` or fake clients.
- `market_ai_analyses` is publicly readable only through sanitized columns/policies and writable only by the service-role path.
- Existing scanner, News Enrichment V1, realtime, and Docker secret-hardening tests must remain green.

---

## File Structure

Create focused AI modules rather than expanding `services/market_worker/app/main.py` into provider business logic:

- `btc_core/ai/analysis.py` — bounded input models, price-geometry validation, deterministic AI risk precheck.
- `btc_core/ai/snapshot.py` — build 4h/1h/15m deterministic technical/news input snapshots.
- `btc_core/ai/providers/base.py` — provider protocol, runtime config, retry/error taxonomy, shared JSON parsing helpers.
- `btc_core/ai/providers/openai_compatible.py` — OpenAI-compatible, DeepSeek, OpenRouter request/response adapter.
- `btc_core/ai/providers/gemini.py` — Gemini generateContent adapter.
- `btc_core/ai/providers/claude.py` — Claude Messages adapter.
- `btc_core/ai/providers/factory.py` — select the adapter from `AIProvider`.
- `btc_core/ai/orchestrator.py` — candidate filtering, bounded concurrency, provider call, validation, persistence summary.
- `btc_core/ai/supabase_repo.py` — write/read `market_ai_analyses` through PostgREST.
- `supabase/migrations/202609100001_market_ai_analysis_v1.sql` — table, indexes, duplicate protection, RLS/read grants.
- Existing `btc_core/market/supabase_repo.py` — return persisted scanner-candidate IDs without changing scanner semantics.
- Existing `btc_core/news/supabase_repo.py` — add bounded recent tagged-news context query.
- Existing `services/market_worker/app/main.py` — environment wiring and async task lifecycle only.
- Existing `services/api/app/main.py`, `services/api/app/config.py` — sanitized AI read/config endpoints.
- Existing `apps/web/src/api.ts`, `App.tsx`, `styles.css` — display analysis and read-only provider state.

---

### Task 1: Pure AI Analysis Contracts and Deterministic Precheck

**Files:**
- Create: `btc_core/ai/analysis.py`
- Create: `tests/test_ai_analysis.py`
- Modify: `tests/test_ai_models.py`

**Interfaces:**
- Consumes: `btc_core.ai.models.AIDecision`, `AIProvider`, `Direction`; `btc_core.risk.engine.RiskPolicy`; `btc_core.scanner.scoring.OpportunityInputs`.
- Produces: `TimeframeTechnicalContext`, `AINewsContext`, `AIAnalysisSnapshot`, `AIAnalysisPrecheck`, `validate_price_geometry(decision)`, `precheck_ai_decision(decision, *, opportunity_score, policy)`.

- [ ] **Step 1: Write failing geometry and risk-precheck tests**

```python
from btc_core.ai.analysis import precheck_ai_decision, validate_price_geometry
from btc_core.ai.models import AIDecision, AIProvider, Direction
from btc_core.risk.engine import RiskPolicy


def make_long(**updates):
    data = dict(
        provider=AIProvider.GEMINI,
        model="test-model",
        symbol="BTCUSDT",
        timeframe="15m",
        direction=Direction.LONG,
        confidence=82,
        entry_min=100,
        entry_max=101,
        stop_loss=97,
        take_profits=[104, 108],
        risk_reward=2.4,
        reason_summary="Structured test decision.",
    )
    data.update(updates)
    return AIDecision(**data)


def test_long_geometry_requires_sl_below_full_entry_range_and_all_tps_above():
    assert validate_price_geometry(make_long()).valid is True
    invalid = make_long(stop_loss=100.5)
    assert validate_price_geometry(invalid).valid is False


def test_short_geometry_requires_all_tps_below_entry_and_sl_above():
    decision = make_long(
        direction=Direction.SHORT,
        entry_min=100,
        entry_max=101,
        stop_loss=104,
        take_profits=[98, 95],
    )
    assert validate_price_geometry(decision).valid is True


def test_wait_is_never_actionable():
    result = precheck_ai_decision(
        make_long(direction=Direction.WAIT),
        opportunity_score=90,
        policy=RiskPolicy(),
    )
    assert result.actionable is False
    assert "wait_direction" in result.reasons


def test_structurally_valid_signal_still_requires_full_risk_context():
    result = precheck_ai_decision(
        make_long(), opportunity_score=84, policy=RiskPolicy()
    )
    assert result.status == "FULL_RISK_CONTEXT_PENDING"
```

- [ ] **Step 2: Run the focused tests and confirm RED**

Run: `pytest tests/test_ai_analysis.py -q`

Expected: collection/import failure because `btc_core.ai.analysis` does not exist.

- [ ] **Step 3: Implement the minimal pure models and checks**

Core shape:

```python
class PriceGeometryResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    valid: bool
    reasons: tuple[str, ...] = ()


class AIAnalysisPrecheck(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    actionable: bool = False
    status: str
    reasons: tuple[str, ...] = ()


def validate_price_geometry(decision: AIDecision) -> PriceGeometryResult:
    if decision.direction is Direction.LONG:
        valid = (
            decision.stop_loss < decision.entry_min <= decision.entry_max
            and all(tp > decision.entry_max for tp in decision.take_profits)
        )
    elif decision.direction is Direction.SHORT:
        valid = (
            all(tp < decision.entry_min for tp in decision.take_profits)
            and decision.entry_min <= decision.entry_max < decision.stop_loss
        )
    elif decision.direction is Direction.WAIT:
        return PriceGeometryResult(valid=True)
    else:
        return PriceGeometryResult(valid=False, reasons=("exit_not_allowed",))
    return PriceGeometryResult(valid=valid, reasons=() if valid else ("invalid_price_structure",))
```

`precheck_ai_decision()` must check confidence, scanner opportunity score, R:R and geometry using `RiskPolicy`; it must return `FULL_RISK_CONTEXT_PENDING` for a valid LONG/SHORT because account-level sizing/daily-loss/open-position/event context is intentionally absent.

- [ ] **Step 4: Run focused model/precheck tests**

Run: `pytest tests/test_ai_analysis.py tests/test_ai_models.py tests/test_risk_engine.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add btc_core/ai/analysis.py tests/test_ai_analysis.py tests/test_ai_models.py
git commit -m "feat: add deterministic AI analysis precheck"
```

---

### Task 2: Bounded Multi-Timeframe and News Snapshot Builder

**Files:**
- Create: `btc_core/ai/snapshot.py`
- Create: `tests/test_ai_snapshot.py`
- Modify: `btc_core/news/supabase_repo.py`
- Modify: `tests/test_news_enrichment.py`

**Interfaces:**
- Consumes: `MarketScannerCandidate`; a market-data object exposing `klines(symbol, timeframe, *, limit)`; `SupabaseNewsRepository`.
- Produces: `build_ai_snapshot(candidate, *, market_client, news_repo) -> AIAnalysisSnapshot`.

- [ ] **Step 1: Add failing tests proving exactly 4h/1h/15m bounded market context**

```python
@pytest.mark.asyncio
async def test_snapshot_fetches_only_required_timeframes_and_no_unbounded_history():
    client = FakeKlineClient()
    snapshot = await build_ai_snapshot(
        make_candidate("BTCUSDT", "15m"),
        market_client=client,
        news_repo=FakeNewsRepo(),
    )
    assert [call[:2] for call in client.calls] == [
        ("BTCUSDT", "4h"), ("BTCUSDT", "1h"), ("BTCUSDT", "15m")
    ]
    assert all(call[2] == 60 for call in client.calls)
    assert set(snapshot.technical_by_timeframe) == {"4h", "1h", "15m"}
```

Add a news test asserting the repository query selects only `title,summary,published_at,impact_level,credibility_score` joined to the exact symbol and a closed 24-hour window.

- [ ] **Step 2: Run RED**

Run: `pytest tests/test_ai_snapshot.py tests/test_news_enrichment.py -q`

Expected: missing builder/repository method failures.

- [ ] **Step 3: Add a bounded news-context model/query**

Add `recent_asset_context(symbol, since, until, limit=5)` to `SupabaseNewsRepository`. Return a small immutable model containing title, optional summary, timestamp, impact and credibility. Do not include source secrets or raw_data.

- [ ] **Step 4: Implement deterministic technical summaries from candles**

Use candle-only calculations for each timeframe so AI snapshot assembly does not repeat premium-index/OI/ratio/book requests. Include close, trend percent, momentum percent, recent high/low, recent volume ratio, and a normalized direction label. Reuse the same EMA/momentum concepts already present in `btc_core.market.features`; do not send raw 60-candle arrays to the provider.

Representative interface:

```python
async def build_ai_snapshot(
    candidate: MarketScannerCandidate,
    *,
    market_client: KlineClientProtocol,
    news_repo: NewsContextRepositoryProtocol | None,
    now: datetime | None = None,
) -> AIAnalysisSnapshot:
    ...
```

- [ ] **Step 5: Run snapshot/news tests**

Run: `pytest tests/test_ai_snapshot.py tests/test_news_enrichment.py tests/test_market_features.py -q`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add btc_core/ai/snapshot.py btc_core/news/supabase_repo.py tests/test_ai_snapshot.py tests/test_news_enrichment.py
git commit -m "feat: build bounded AI market snapshots"
```

---

### Task 3: Shared Provider Runtime, Retry Policy, and OpenAI-Compatible Adapter

**Files:**
- Create: `btc_core/ai/providers/__init__.py`
- Create: `btc_core/ai/providers/base.py`
- Create: `btc_core/ai/providers/openai_compatible.py`
- Create: `tests/test_ai_provider_openai_compatible.py`

**Interfaces:**
- Produces `AIProviderRuntimeConfig`, `AIProviderError`, `AIProviderClientProtocol.analyze(snapshot) -> AIDecision`, `OpenAICompatibleProviderClient`.
- Runtime config fields: provider, model, api_key, base_url, timeout_seconds=20, max_retries=1.

- [ ] **Step 1: Write HTTP parsing/retry tests with `httpx.MockTransport`**

Cover valid JSON, malformed JSON, schema-invalid JSON, timeout/network error, HTTP 429, HTTP 500, HTTP 401. Assert transient failures make at most 2 total attempts and auth/schema failures make exactly 1 attempt.

Representative assertion:

```python
assert request_count == 2  # first transient failure + one retry
assert decision.provider is AIProvider.DEEPSEEK
assert decision.symbol == "BTCUSDT"
```

- [ ] **Step 2: Run RED**

Run: `pytest tests/test_ai_provider_openai_compatible.py -q`

- [ ] **Step 3: Implement common transport/error taxonomy**

Use normalized codes such as `TIMEOUT`, `NETWORK`, `RATE_LIMIT`, `UPSTREAM_5XX`, `AUTH`, `INVALID_CONFIG`, `INVALID_JSON`, `INVALID_SCHEMA`. `AIProviderError` must store only sanitized metadata; never copy request headers or API key into exception text.

- [ ] **Step 4: Implement OpenAI-compatible request/response parsing**

Use `POST {base_url}/chat/completions`, bearer auth, model, system/user messages, and JSON mode when supported. The prompt must explicitly request JSON and include the `AIDecision` field names. Parse `choices[0].message.content` with `json.loads`, inject/verify configured `provider` and `model`, then construct `AIDecision`.

DeepSeek currently documents `/chat/completions` with `response_format={"type":"json_object"}`; OpenRouter is OpenAI-compatible but model capabilities vary, so Pydantic validation remains mandatory even when provider-native structured output is requested.

- [ ] **Step 5: Run focused provider tests**

Run: `pytest tests/test_ai_provider_openai_compatible.py tests/test_ai_models.py -q`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add btc_core/ai/providers tests/test_ai_provider_openai_compatible.py
git commit -m "feat: add OpenAI compatible AI provider adapter"
```

---

### Task 4: Gemini, Claude, and Provider Factory

**Files:**
- Create: `btc_core/ai/providers/gemini.py`
- Create: `btc_core/ai/providers/claude.py`
- Create: `btc_core/ai/providers/factory.py`
- Create: `tests/test_ai_provider_gemini.py`
- Create: `tests/test_ai_provider_claude.py`
- Create: `tests/test_ai_provider_factory.py`

**Interfaces:**
- `build_provider_client(config, *, transport=None) -> AIProviderClientProtocol`.

- [ ] **Step 1: Write provider-specific RED tests**

Gemini test asserts use of configured model and JSON response mode/schema and parses candidate text. Claude test asserts `/v1/messages`, `x-api-key`, an Anthropic version header, configured model, bounded max tokens, and JSON extraction from text content. Factory test maps all five enum values to the correct adapter family.

- [ ] **Step 2: Run RED**

Run: `pytest tests/test_ai_provider_gemini.py tests/test_ai_provider_claude.py tests/test_ai_provider_factory.py -q`

- [ ] **Step 3: Implement Gemini adapter**

Use `generateContent`; request `application/json` structured output and still validate the returned JSON through `AIDecision`. Do not hard-code a model name.

- [ ] **Step 4: Implement Claude adapter**

Use the Messages API with configured model and server-side key. Instruct Claude to return one JSON object matching the canonical fields and parse only text output; reject missing/multiple unusable content blocks rather than guessing.

- [ ] **Step 5: Implement factory mapping**

```python
if config.provider is AIProvider.GEMINI:
    return GeminiProviderClient(...)
if config.provider is AIProvider.CLAUDE:
    return ClaudeProviderClient(...)
if config.provider in {
    AIProvider.OPENAI_COMPATIBLE,
    AIProvider.DEEPSEEK,
    AIProvider.OPENROUTER,
}:
    return OpenAICompatibleProviderClient(...)
raise AIProviderError("unsupported provider", code="INVALID_CONFIG")
```

Provider-specific default base URLs belong in the factory/config helper, while `OPENAI_COMPATIBLE` requires `AI_BASE_URL`.

- [ ] **Step 6: Run provider suite**

Run: `pytest tests/test_ai_provider_*.py -q`

Expected: PASS, with no external network calls.

- [ ] **Step 7: Commit**

```bash
git add btc_core/ai/providers tests/test_ai_provider_gemini.py tests/test_ai_provider_claude.py tests/test_ai_provider_factory.py
git commit -m "feat: add Gemini and Claude AI adapters"
```

---

### Task 5: Persistence Schema, Candidate Linkage, and Sanitized AI Repository

**Files:**
- Create: `supabase/migrations/202609100001_market_ai_analysis_v1.sql`
- Create: `btc_core/ai/supabase_repo.py`
- Create: `tests/test_ai_supabase_repo.py`
- Create: `tests/test_ai_migration.py`
- Modify: `btc_core/market/supabase_repo.py`
- Create: `tests/test_market_supabase_repo.py`

**Interfaces:**
- `PersistedCandidateRef(id: int, rank: int, symbol: str)`
- `PersistedScanRef(run_id: str, candidates: tuple[PersistedCandidateRef, ...])`
- `SupabaseMarketRepository.persist_scan(result) -> PersistedScanRef`
- `SupabaseAIAnalysisRepository.persist(record) -> None`
- `SupabaseAIAnalysisRepository.latest(timeframe, limit) -> list[dict[str, Any]]`

- [ ] **Step 1: Write migration/security RED tests**

Read the SQL file and assert it contains: FK to `market_scanner_candidates(id)`, unique candidate/provider/model, RLS enable, SELECT policy for `anon, authenticated`, SELECT grant only, no insert/update/delete grant to browser roles.

- [ ] **Step 2: Write repository RED tests**

Use `httpx.MockTransport`. `persist_scan()` must request `Prefer: return=representation` for candidate insertion and return real candidate IDs from the response. AI persistence test must recursively inspect the submitted JSON and assert neither a known API key string nor `authorization` key appears anywhere.

- [ ] **Step 3: Create migration**

SQL must define bounded/checkable statuses and nullable AI fields for failure rows, an index on `(timeframe, created_at desc)` plus candidate/run lookups, and RLS/read-only policy matching the spec. Example core:

```sql
create table if not exists public.market_ai_analyses (
  id bigint generated always as identity primary key,
  scanner_candidate_id bigint not null references public.market_scanner_candidates(id) on delete cascade,
  run_id uuid not null references public.market_scanner_runs(id) on delete cascade,
  symbol text not null,
  timeframe text not null,
  provider public.ai_provider not null,
  model text not null,
  scanner_direction public.trade_direction not null,
  ai_direction public.trade_direction,
  confidence numeric(5,2) check (confidence between 0 and 100),
  entry_min numeric,
  entry_max numeric,
  stop_loss numeric,
  take_profits jsonb not null default '[]'::jsonb,
  risk_reward numeric,
  reason_summary text,
  input_snapshot jsonb not null default '{}'::jsonb,
  status text not null check (status in ('SUCCESS','SKIPPED','FAILED','INVALID_RESPONSE')),
  risk_precheck_status text,
  risk_precheck_reasons text[] not null default '{}',
  latency_ms integer,
  attempt_count integer not null default 0,
  error_code text,
  error_message text,
  created_at timestamptz not null default now(),
  completed_at timestamptz,
  unique(scanner_candidate_id, provider, model)
);
```

- [ ] **Step 4: Return inserted candidate IDs from market persistence**

Keep the existing scan payload/weights unchanged. Change the candidate insert to `Prefer: return=representation`, parse `id/rank/symbol`, and return `PersistedScanRef`. Update fake repositories/tests accordingly.

- [ ] **Step 5: Implement AI repository**

`persist()` receives an already-sanitized domain record, truncates error text to a fixed bound (e.g. 500 chars), and uses upsert/duplicate-safe behavior on `(scanner_candidate_id, provider, model)`. `latest()` selects only UI-safe columns; never use `select=*` for the public read path.

- [ ] **Step 6: Run persistence/migration tests**

Run: `pytest tests/test_ai_migration.py tests/test_ai_supabase_repo.py tests/test_market_supabase_repo.py tests/test_market_worker.py -q`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add supabase/migrations/202609100001_market_ai_analysis_v1.sql btc_core/ai/supabase_repo.py btc_core/market/supabase_repo.py tests/test_ai_migration.py tests/test_ai_supabase_repo.py tests/test_market_supabase_repo.py tests/test_market_worker.py
git commit -m "feat: persist system market AI analyses"
```

---

### Task 6: AI Orchestrator and Non-Blocking Market-Worker Integration

**Files:**
- Create: `btc_core/ai/orchestrator.py`
- Create: `tests/test_ai_orchestrator.py`
- Modify: `services/market_worker/app/main.py`
- Modify: `tests/test_market_worker.py`
- Modify: `.env.example`

**Interfaces:**
- `AIAnalysisRunner.analyze_scan(result, persisted_scan) -> AIAnalysisRunSummary`
- `run_realtime_cycle(..., ai_runner=None) -> MarketScanResult`

- [ ] **Step 1: Write orchestrator RED tests for filtering/concurrency/failure isolation**

Tests must prove:

1. candidates below `AI_MIN_OPPORTUNITY_SCORE` are skipped without provider calls;
2. only top N eligible candidates are analyzed;
3. active provider calls never exceed configured semaphore size;
4. provider failure produces sanitized failure persistence and continues other candidates;
5. `asyncio.CancelledError` propagates rather than becoming a failure row.

- [ ] **Step 2: Write worker RED test proving realtime starts before slow AI finishes**

Use an `asyncio.Event` in a fake AI runner and realtime client:

```python
@pytest.mark.asyncio
async def test_realtime_starts_without_waiting_for_ai_analysis():
    ai_started = asyncio.Event()
    allow_ai_finish = asyncio.Event()
    realtime_started = asyncio.Event()
    # fake AI waits on allow_ai_finish; fake realtime sets realtime_started immediately
    task = asyncio.create_task(run_realtime_cycle(..., ai_runner=fake_ai))
    await ai_started.wait()
    await asyncio.wait_for(realtime_started.wait(), timeout=0.2)
    allow_ai_finish.set()
    await task
```

- [ ] **Step 3: Implement orchestrator**

For each selected persisted candidate: build snapshot, call provider, validate `AIDecision`, reject provider/model/symbol/timeframe mismatches, run geometry/precheck, persist `SUCCESS` or normalized failure. Return counts for success/failed/skipped. No scanner score/direction mutation.

- [ ] **Step 4: Integrate async lifecycle into `run_realtime_cycle()`**

Sequence must be exactly:

```python
result = await scanner.scan(...)
persisted = await repo.persist_scan(result)
ai_task = None
if ai_runner is not None:
    ai_task = asyncio.create_task(ai_runner.analyze_scan(result, persisted))
# start realtime loop immediately
...
# at cycle end, await bounded AI task; on worker cancellation cancel/await then re-raise
```

AI exceptions escaping the runner are caught/logged at the AI boundary and must not turn into `market worker cycle failed` unless the entire worker itself is being cancelled.

- [ ] **Step 5: Wire environment configuration**

Add to `.env.example`:

```text
AI_ANALYSIS_V1_ENABLED=false
AI_PROVIDER=
AI_MODEL=
AI_API_KEY=
AI_BASE_URL=
AI_TIMEOUT_SECONDS=20
AI_MAX_RETRIES=1
AI_ANALYSIS_CANDIDATE_LIMIT=3
AI_ANALYSIS_CONCURRENCY=2
AI_MIN_OPPORTUNITY_SCORE=65
```

`run_forever()` creates provider/snapshot/news/AI repositories only when enabled. Missing provider/model/key while enabled must disable/skip AI with a sanitized configuration message rather than crash the market scanner.

- [ ] **Step 6: Run worker/orchestrator/regression tests**

Run: `pytest tests/test_ai_orchestrator.py tests/test_market_worker.py tests/test_binance_market_scanner.py tests/test_news_enrichment.py tests/test_market_worker_dockerfile.py -q`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add btc_core/ai/orchestrator.py services/market_worker/app/main.py .env.example tests/test_ai_orchestrator.py tests/test_market_worker.py
git commit -m "feat: run AI analysis alongside realtime market ingestion"
```

---

### Task 7: Sanitized API Read Path and Provider Status

**Files:**
- Modify: `services/api/app/config.py`
- Modify: `services/api/app/main.py`
- Modify: `tests/test_api.py`
- Modify: `tests/test_api_market.py`

**Interfaces:**
- `GET /api/v1/ai/latest?timeframe=15m&limit=10`
- Extended `/api/v1/config/public` adds `ai_analysis_enabled`, `ai_provider`, `ai_model`, `ai_api_key_configured` only.

- [ ] **Step 1: Write RED API tests**

Assert `ai/latest` normalizes timeframe/limit and returns safe fields. Public config test sets `AI_API_KEY=super-secret-value` and asserts serialized response contains `ai_api_key_configured: true` but does not contain the secret string, `api_key`, or Authorization metadata.

- [ ] **Step 2: Implement public config from environment**

Do not expose the key itself:

```python
class PublicConfig(BaseModel):
    trading_mode: TradingMode = TradingMode.SIMULATION
    direct_ai_order_enabled: bool = False
    min_confidence: float = 75.0
    min_opportunity_score: float = 75.0
    max_leverage: float = 5.0
    ai_analysis_enabled: bool = False
    ai_provider: str | None = None
    ai_model: str | None = None
    ai_api_key_configured: bool = False
```

Build values from env inside the endpoint or a pure helper that can be unit-tested.

- [ ] **Step 3: Add AI repository dependency/read endpoint**

Use `SUPABASE_ANON_KEY`, never fall back to the service-role key. Return only explicit safe columns from `SupabaseAIAnalysisRepository.latest()`.

- [ ] **Step 4: Run API tests**

Run: `pytest tests/test_api.py tests/test_api_market.py tests/test_ai_supabase_repo.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add services/api/app/config.py services/api/app/main.py tests/test_api.py tests/test_api_market.py
git commit -m "feat: expose sanitized AI analysis API"
```

---

### Task 8: Web Scanner AI Cards and Read-Only Settings State

**Files:**
- Modify: `apps/web/src/api.ts`
- Modify: `apps/web/src/App.tsx`
- Modify: `apps/web/src/styles.css`

**Interfaces:**
- `AIAnalysis` TypeScript type matching safe API fields.
- `fetchLatestAIAnalyses(timeframe, limit)` and `fetchPublicConfig()`.

- [ ] **Step 1: Add API types/functions first**

Representative type:

```ts
export type AIAnalysis = {
  scanner_candidate_id: number
  symbol: string
  timeframe: string
  provider: string
  model: string
  scanner_direction: 'LONG' | 'SHORT' | 'WAIT' | 'EXIT'
  ai_direction: 'LONG' | 'SHORT' | 'WAIT' | null
  confidence: number | null
  entry_min: number | null
  entry_max: number | null
  stop_loss: number | null
  take_profits: number[]
  risk_reward: number | null
  reason_summary: string | null
  status: string
  risk_precheck_status: string | null
  risk_precheck_reasons: string[]
  created_at: string
}
```

- [ ] **Step 2: Integrate resilient polling**

Poll AI analyses on the same scanner timeframe. Keep AI errors separate from scanner errors; if the AI endpoint is unavailable, scanner candidate rows/live prices continue rendering unchanged.

- [ ] **Step 3: Render analysis detail without implying order approval**

Show AI direction/confidence, Entry, SL, TP, R:R, provider/model and risk-precheck status. `FULL_RISK_CONTEXT_PENDING` must be displayed as pending/not trade-authorized, not as an approval badge.

Settings reads `PublicConfig`: provider/model are display-only in V1; provider select/model input should be disabled or clearly read-only, and API key displays `Configured` / `Not configured` only.

- [ ] **Step 4: Update styles for mobile cards**

Add compact `.ai-analysis`, `.ai-grid`, `.risk-pending` rules and preserve the existing <=560px single-column behavior. Do not introduce a new UI framework.

- [ ] **Step 5: Build web**

Run:

```bash
cd apps/web
npm install
npm run build
```

Expected: TypeScript and Vite build PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/web/src/api.ts apps/web/src/App.tsx apps/web/src/styles.css
git commit -m "feat: display AI scanner analysis in web app"
```

---

### Task 9: Documentation, Full Verification, PR, and Production Canary

**Files:**
- Modify: `README.md`
- Verify: `.github/workflows/ci.yml`
- Verify: `Dockerfile.market-worker`

**Interfaces:** Operational rollout only; no live execution.

- [ ] **Step 1: Update README to reflect implemented milestone**

Document AI Analysis V1 data flow, server-only Railway variables, read endpoint, `FULL_RISK_CONTEXT_PENDING`, and the explicit statement that AI does not place orders.

- [ ] **Step 2: Run complete local/CI-equivalent backend suite**

Run:

```bash
python -m pip install -e '.[dev]'
pytest -q
```

Expected: all tests PASS; no provider test reaches the public internet.

- [ ] **Step 3: Run complete web build**

Run:

```bash
cd apps/web
npm install
npm run build
```

Expected: PASS.

- [ ] **Step 4: Run explicit safety regression checks**

Run:

```bash
pytest tests/test_market_worker_dockerfile.py tests/test_market_worker.py tests/test_news_enrichment.py tests/test_binance_market_scanner.py -q
```

Check that neither `Dockerfile.market-worker` nor committed config contains a real AI/Supabase secret. Confirm defaults remain `SIMULATION`, direct AI order false, AI analysis false.

- [ ] **Step 5: Commit documentation/verification changes**

```bash
git add README.md
git commit -m "docs: document AI Analysis V1 rollout"
```

- [ ] **Step 6: Open PR and require green CI before merge**

PR body must state: migration added, AI disabled by default, no live orders, provider HTTP mocked in CI, candidate limit/concurrency defaults, secret handling, and rollback method (`AI_ANALYSIS_V1_ENABLED=false`).

- [ ] **Step 7: Deploy Phase 1 with AI disabled**

Apply `202609100001_market_ai_analysis_v1.sql`, deploy code, and keep:

```text
AI_ANALYSIS_V1_ENABLED=false
TRADING_MODE=SIMULATION
DIRECT_AI_ORDER_ENABLED=false
```

Verify a fresh scanner run persists and realtime market state continues updating before configuring an AI key.

- [ ] **Step 8: Configure server-only provider variables and canary one candidate**

Set `AI_PROVIDER`, `AI_MODEL`, `AI_API_KEY` and optional `AI_BASE_URL`; then:

```text
AI_ANALYSIS_V1_ENABLED=true
AI_ANALYSIS_CANDIDATE_LIMIT=1
AI_ANALYSIS_CONCURRENCY=1
```

Verify exactly one intended analysis per cycle, bounded latency, correct candidate FK, no secrets in logs/database/API, and scanner/realtime health.

- [ ] **Step 9: Expand to Top 3 only after canary verification**

Set:

```text
AI_ANALYSIS_CANDIDATE_LIMIT=3
AI_ANALYSIS_CONCURRENCY=2
```

Keep simulation/direct-order safety values unchanged. If latency/error rate or worker health regresses, disable `AI_ANALYSIS_V1_ENABLED` immediately; scanner/news/realtime must continue without code rollback.

---

## Plan Self-Review Checklist

Before implementation begins, confirm:

- Every success criterion in the design spec maps to Tasks 1–9.
- No task requires live-order code, browser secret writes, ensemble voting, vendor failover, self-modifying weights, or account-level position sizing.
- Provider names and `AIDecision` field names match existing code exactly.
- Persistence links to `market_scanner_candidates.id` (`bigint`), never the obsolete user-scoped `scanner_candidates` UUID table.
- Exact geometry is `LONG: SL < entry_min <= entry_max < every TP`; `SHORT: every TP < entry_min <= entry_max < SL`.
- `WAIT` is valid structured analysis but never actionable.
- AI work starts after scanner persistence and runs concurrently with realtime startup.
- Account context is never fabricated; valid analysis remains `FULL_RISK_CONTEXT_PENDING` until a future full risk milestone.
- Public API and UI never reveal the API key.
- Production rollout is disabled -> one-candidate canary -> Top 3, with SIMULATION and direct-order-off throughout.
