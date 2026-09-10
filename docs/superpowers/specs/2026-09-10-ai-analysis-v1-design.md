# AI Analysis V1 — Design Specification

Date: 2026-09-10
Status: Approved design, pending user review of written spec
Branch: `feature/ai-analysis-v1-design`

## 1. Goal

Add AI-assisted analysis to the existing `market-worker` without adding a new service. The AI layer enriches scanner candidates with structured trading analysis while preserving the current safety model:

- `TRADING_MODE=SIMULATION`
- `DIRECT_AI_ORDER_ENABLED=false`
- AI never sends orders in V1
- deterministic risk checks remain authoritative
- scanner and realtime market ingestion must continue even when AI is unavailable

Each analyzed candidate must produce:

- direction: `LONG`, `SHORT`, or `WAIT`
- confidence, 0–100
- entry range (`entry_min`, `entry_max`)
- stop loss
- up to three take-profit targets
- risk/reward ratio
- concise reason summary

The existing `btc_core.ai.models.AIDecision` contract is the canonical validation contract and must be reused rather than duplicated.

## 2. Architectural Decision

### Selected approach

Run AI Analysis V1 inside the existing `services.market_worker` process.

The scanner remains the source of candidate discovery and ranking. After a scan is persisted, AI analysis is launched as an asynchronous side task while realtime WebSocket ingestion starts immediately.

```text
Binance USD-M
    |
    v
Market Scanner
    |
    +--> News Enrichment V1
    |
    v
persist_scan()
    |
    +--> async AI Analysis task (Top N)
    |
    +--> realtime WebSocket ingestion continues immediately

AI Analysis
    |
    v
AIDecision validation
    |
    v
Price-geometry validation
    |
    v
Deterministic risk precheck
    |
    v
market_ai_analyses
```

AI work must never sit on the critical path between scan persistence and realtime stream startup. At the end of each realtime cycle, the worker must await completed AI work or cancel/cleanup unfinished AI work before starting another scan so tasks cannot accumulate across cycles.

## 3. Candidate Selection

V1 analyzes only the highest-ranked scanner candidates.

Defaults:

- `AI_ANALYSIS_CANDIDATE_LIMIT=3`
- `AI_ANALYSIS_CONCURRENCY=2`
- `AI_MIN_OPPORTUNITY_SCORE=65`

Initial production canary uses `AI_ANALYSIS_CANDIDATE_LIMIT=1` and `AI_ANALYSIS_CONCURRENCY=1`.

AI does not replace scanner ranking. Scanner output remains independently usable if AI is disabled, skipped, or fails.

## 4. AI Input Snapshot

Each AI analysis receives a compact deterministic snapshot rather than unbounded raw market history.

The snapshot contains:

- symbol
- current scanner timeframe and scanner direction
- opportunity score and component scores
- latest mark/last price
- funding rate
- open-interest change
- long/short ratio
- spread/liquidity metrics
- recent News Enrichment score
- relevant recent tagged-news summary when available
- multi-timeframe technical context for `4h`, `1h`, and `15m`

Multi-timeframe context should be assembled from deterministic market features already used by the project, or equivalent compact summaries derived from Binance market data. The provider prompt must not send a large raw candle dump when bounded feature values can represent the same context.

The persisted audit snapshot must be sanitized and must never contain API keys, authorization headers, or secret values.

## 5. Provider Architecture

### Supported providers

The existing provider enum remains authoritative:

- `GEMINI`
- `CLAUDE`
- `OPENAI_COMPATIBLE`
- `DEEPSEEK`
- `OPENROUTER`

### Common interface

All providers implement one internal interface conceptually equivalent to:

```python
analyze(snapshot) -> AIDecision
```

Provider-specific request/response formatting belongs behind adapters. The market worker and analysis orchestration must not depend on individual provider payload formats.

V1 should use the project's existing `httpx` dependency instead of adding multiple vendor SDKs unless a provider cannot be implemented reliably with HTTP.

Provider layout:

- Gemini: Gemini-specific adapter
- Claude: Claude-specific adapter
- OpenAI-compatible API, DeepSeek, OpenRouter: shared OpenAI-compatible transport/parser where practical, with provider-specific defaults only where required

All adapters return only validated `AIDecision` objects to the orchestration layer.

## 6. Server-Side Configuration and Secrets

V1 uses Railway server-side variables only.

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

Rules:

- `AI_API_KEY` is server-only
- browser code never receives the key
- Supabase never stores the plaintext API key
- logs never print the key or authorization header
- `AI_BASE_URL` is optional and used only when needed
- model name is configurable and not hard-coded into business logic

The existing `ai_provider_configs.secret_ref` concept may be used later for authenticated per-user settings, but V1 runtime configuration comes from Railway.

## 7. Settings UI Scope

The current Settings page is not an authenticated secret-management surface.

For V1:

- UI may display selected Provider and Model
- UI may display `Configured` / `Not configured` for the API key
- the real key is never returned to the browser
- UI cannot write or replace production AI secrets

Authenticated provider/key management is a later milestone.

## 8. Timeout, Retry, and Concurrency

Defaults:

- timeout per request: 20 seconds
- retry count: 1
- AI concurrency: 2

Retry only for transient conditions:

- network failure
- timeout
- HTTP 429
- HTTP 5xx

Do not repeatedly retry:

- authentication/authorization errors
- invalid provider/model configuration
- malformed structured response
- schema validation failure

Retries use bounded backoff and never block scanner/realtime startup.

## 9. Structured Output and Validation

Every successful provider response must validate against `AIDecision`. No partially parsed or loosely structured result can become a valid signal.

Allowed directions for a new scanner candidate are:

- `LONG`
- `SHORT`
- `WAIT`

`EXIT` remains part of the shared model for future position-management workflows but is not produced for a new scanner candidate in V1.

### Exact price geometry

The existing model already requires:

```text
entry_min <= entry_max
```

For `LONG`, actionable geometry requires:

```text
stop_loss < entry_min <= entry_max < every take_profit
```

For `SHORT`, actionable geometry requires:

```text
every take_profit < entry_min <= entry_max < stop_loss
```

Take-profit list values must all be positive. Ordering inside the TP list is presentation-only; geometry validation checks every TP against the entry range.

For `WAIT`, the existing contract still requires positive Entry/SL/TP values. Those values may be persisted for context, but a `WAIT` result is never interpreted as an actionable approval.

Invalid geometry produces an invalid/precheck-failed analysis and never an actionable result.

## 10. Persistence Model

The existing user-scoped `ai_decisions` table references the old `scanner_candidates` UUID table. Production market scanning now persists to system-wide `market_scanner_candidates`, whose IDs are bigint values.

AI Analysis V1 therefore uses a new system-wide table rather than linking to the obsolete user-scoped scanner schema.

### New table: `market_ai_analyses`

Recommended fields:

```text
id                         bigint identity primary key
scanner_candidate_id       bigint FK -> market_scanner_candidates(id)
run_id                      uuid FK -> market_scanner_runs(id)
symbol                      text
timeframe                   text
provider                    ai_provider
model                       text
scanner_direction           trade_direction
ai_direction                trade_direction nullable
confidence                  numeric nullable
entry_min                   numeric nullable
entry_max                   numeric nullable
stop_loss                   numeric nullable
take_profits                jsonb default []
risk_reward                 numeric nullable
reason_summary              text nullable
input_snapshot              jsonb default {}
status                      text
risk_precheck_status        text nullable
risk_precheck_reasons       text[] default {}
latency_ms                  integer nullable
attempt_count               integer not null default 0
error_code                  text nullable
error_message               text nullable
created_at                  timestamptz default now()
completed_at                timestamptz nullable
```

Duplicate protection:

```text
unique(scanner_candidate_id, provider, model)
```

Minimum status values:

- `SUCCESS`
- `SKIPPED`
- `FAILED`
- `INVALID_RESPONSE`

Stored error messages are sanitized and length-bounded.

### RLS and read/write policy

`market_ai_analyses` is system-generated market intelligence, not a user-owned secret table.

Migration requirements:

- enable RLS
- allow read-only `SELECT` to the roles used by the existing public market read path (`anon`, `authenticated`) for sanitized analysis rows
- do not grant browser/client insert, update, or delete
- writes occur only through the server-side service-role path
- API responses expose sanitized analysis fields only

The database row must never contain API keys or authorization headers.

## 11. Deterministic Risk Precheck

AI is not an approval authority.

After valid `AIDecision` parsing, V1 runs only checks available from current context:

- confidence minimum
- opportunity score minimum
- risk/reward minimum
- exact LONG/SHORT price geometry

The existing `RiskPolicy` remains the source for confidence/opportunity/RR thresholds where applicable.

Checks requiring account/portfolio context must not be fabricated:

- actual position sizing
- account risk percentage
- current daily loss
- current open-position count
- final leverage approval
- full high-impact event guard state when unavailable in the snapshot

If full account context is not available, the analysis receives:

```text
FULL_RISK_CONTEXT_PENDING
```

This means the analysis is structurally valid but is not a full trade authorization.

## 12. Failure Isolation

AI Analysis V1 is optional enrichment.

These conditions must never fail the scanner cycle or stop realtime ingestion:

- provider outage
- provider timeout
- rate limit
- malformed JSON
- schema validation failure
- invalid price geometry
- missing provider configuration
- missing API key
- persistence failure limited to the AI analysis path

On AI failure:

1. preserve the already persisted scanner result
2. preserve realtime ingestion
3. persist a sanitized AI failure row when the AI persistence path is available
4. do not synthesize replacement LONG/SHORT output
5. do not alter scanner direction or scanner score

Worker cancellation remains cooperative: `asyncio.CancelledError` propagates correctly.

## 13. Observability

AI logs may include only non-secret operational metadata:

- provider
- model
- symbol
- status
- latency
- attempt count
- normalized error code

Never log:

- `AI_API_KEY`
- Authorization header
- secret-bearing provider headers
- raw HTTP requests containing credentials

Suggested cycle summary:

```text
ai_analysis candidates=3 success=2 failed=1 skipped=0 provider=...
```

## 14. API / Web Read Path

V1 exposes latest sanitized AI analysis through the backend.

Recommended endpoint:

```text
GET /api/v1/ai/latest?timeframe=15m&limit=10
```

UI may display:

- AI direction
- confidence
- entry range
- SL
- TP targets
- R:R
- reason summary
- risk precheck state
- provider/model

The scanner UI continues showing scanner data when the AI endpoint is unavailable.

## 15. Test Strategy

Implementation follows TDD where practical.

Required automated coverage:

1. valid provider response parsing
2. malformed JSON rejection
3. schema-invalid output rejection
4. timeout triggers at most one retry
5. 429/5xx retries once
6. auth/config errors do not repeatedly retry
7. concurrency limit is enforced
8. AI failure does not fail scanner persistence
9. AI failure does not prevent realtime ingestion startup
10. exact LONG price geometry
11. exact SHORT price geometry
12. WAIT is never actionable
13. confidence/opportunity/RR precheck
14. incomplete portfolio context returns `FULL_RISK_CONTEXT_PENDING`
15. persistence contains no API key or Authorization header
16. duplicate candidate/provider/model protection
17. RLS/read policy allows sanitized reads and no client writes
18. existing market scanner tests remain green
19. existing News Enrichment tests remain green
20. existing market-worker secret-hardening regression remains green
21. web/API build/tests remain green

CI never makes paid external AI requests. Provider HTTP calls are mocked/faked.

## 16. Rollout Plan

### Phase 1 — deployed disabled

```text
AI_ANALYSIS_V1_ENABLED=false
TRADING_MODE=SIMULATION
DIRECT_AI_ORDER_ENABLED=false
```

Apply migration and deploy code without AI calls. Verify scanner persistence, realtime ingestion, and existing behavior are unchanged.

### Phase 2 — canary

Configure provider/model/key server-side, then:

```text
AI_ANALYSIS_V1_ENABLED=true
AI_ANALYSIS_CANDIDATE_LIMIT=1
AI_ANALYSIS_CONCURRENCY=1
```

Verify:

- one intended analysis per scanner cycle
- valid structured response
- bounded latency
- correct sanitized persistence
- no secret in logs/database
- healthy scanner/realtime timing

### Phase 3 — Top 3

After canary stability:

```text
AI_ANALYSIS_CANDIDATE_LIMIT=3
AI_ANALYSIS_CONCURRENCY=2
```

Keep:

```text
TRADING_MODE=SIMULATION
DIRECT_AI_ORDER_ENABLED=false
```

No live execution is introduced by this milestone.

## 17. Out of Scope

AI Analysis V1 does not include:

- direct AI order execution
- live trading
- authenticated browser secret write/update
- multi-provider ensemble voting
- automatic provider failover between vendors
- AI self-modification of scanner weights
- automatic promotion of learned rules to production
- real-money position sizing
- final account-level risk approval

Those require separate design approval.

## 18. Success Criteria

AI Analysis V1 succeeds when:

1. market worker continues scanning and ingesting realtime data when AI is disabled or broken
2. selected candidates receive valid structured AI analyses
3. bounded 4H + 1H + 15m context, futures metrics, scanner scores, and available news context are included
4. successful results pass `AIDecision` and exact deterministic price-geometry validation
5. deterministic risk precheck cannot be bypassed by AI output
6. incomplete account context is marked pending rather than fabricated
7. analyses link to `market_scanner_candidates`, not the obsolete user-scoped scanner table
8. secrets stay server-side and do not appear in browser responses, logs, or persisted payloads
9. RLS preserves sanitized read-only access and server-only writes
10. CI passes using mocked provider requests
11. production rollout begins disabled, canaries one candidate, then expands to Top 3 only after verification
