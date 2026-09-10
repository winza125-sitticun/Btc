# AI Analysis V1 — Design Specification

Date: 2026-09-10
Status: Approved design, pending implementation plan
Branch: `feature/ai-analysis-v1-design`

## 1. Goal

Add AI-assisted analysis to the existing `market-worker` without adding a new service. The AI layer enriches scanner candidates with a structured trading analysis while preserving the current safety model:

- `TRADING_MODE=SIMULATION`
- `DIRECT_AI_ORDER_ENABLED=false`
- AI never sends orders in V1
- deterministic risk checks remain authoritative
- scanner and realtime market ingestion must continue even when AI is unavailable

The AI output for each analyzed candidate must include:

- direction: `LONG`, `SHORT`, or `WAIT`
- confidence, 0–100
- entry range (`entry_min`, `entry_max`)
- stop loss
- up to three take-profit targets
- risk/reward ratio
- concise reason summary

The existing `btc_core.ai.models.AIDecision` contract is the canonical validation contract and should be reused rather than duplicated.

## 2. Architectural Decision

### Selected approach

Run AI Analysis V1 inside the existing `services.market_worker` process.

The scanner remains the source of candidate discovery and ranking. After a scan is persisted, AI analysis is launched as an asynchronous side task while the realtime WebSocket ingestion starts immediately.

Data flow:

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

### Why this approach

This avoids a second deployment/service while preserving the existing scanner and realtime flow. AI work must never sit on the critical path between scan persistence and realtime stream startup.

At the end of each realtime cycle, the worker must await or cancel/cleanup the AI task before starting a new scan so tasks cannot accumulate across cycles.

## 3. Candidate Selection

V1 analyzes only the highest-ranked scanner candidates.

Defaults:

- `AI_ANALYSIS_CANDIDATE_LIMIT=3`
- `AI_ANALYSIS_CONCURRENCY=2`

Initial production canary uses `AI_ANALYSIS_CANDIDATE_LIMIT=1`.

Candidates may be filtered by a minimum scanner opportunity score before an AI request is created. The initial default threshold should be conservative and configurable, with a default of 65.

AI does not replace scanner ranking. Scanner output remains independently usable if AI is disabled or fails.

## 4. AI Input Snapshot

Each AI analysis receives a compact, deterministic snapshot rather than raw unbounded market history.

The snapshot should contain:

- symbol
- current scanner timeframe and scanner direction
- opportunity score and component scores
- latest mark/last price
- funding rate
- open-interest change
- long/short ratio
- spread/liquidity metrics
- recent News Enrichment score and relevant recent tagged news summary when available
- multi-timeframe technical context for `4h`, `1h`, and `15m`

Multi-timeframe context should be assembled from deterministic market features already used by the project, or equivalent compact summaries derived from Binance market data. The prompt should not send a large raw candle dump when the same information can be represented by bounded feature values.

The AI input snapshot stored for audit must be sanitized and must never contain API keys, authorization headers, or secret values.

## 5. Provider Architecture

### Supported providers

The existing provider enum remains authoritative:

- `GEMINI`
- `CLAUDE`
- `OPENAI_COMPATIBLE`
- `DEEPSEEK`
- `OPENROUTER`

### Common interface

All providers implement a single internal interface conceptually equivalent to:

```python
analyze(snapshot) -> AIDecision
```

Provider-specific request/response formatting belongs behind adapters. The market worker and analysis orchestration must not depend on individual provider payload formats.

V1 should use the project's existing `httpx` dependency instead of adding multiple vendor SDKs unless a provider cannot be implemented reliably with HTTP.

### Provider grouping

Where practical:

- Gemini uses a Gemini-specific adapter
- Claude uses a Claude-specific adapter
- OpenAI-compatible API, DeepSeek, and OpenRouter share an OpenAI-compatible transport/parser layer with provider-specific base URL/default headers only where required

All adapters must return only validated `AIDecision` objects to the orchestration layer.

## 6. Server-Side Configuration and Secrets

V1 uses Railway server-side variables only.

Required/optional variables:

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
- browser code must never receive the key
- Supabase must never store the plaintext API key
- logs must never print the key or authorization header
- `AI_BASE_URL` is optional and used only when needed by the selected provider/configuration
- model name remains configurable and is not hard-coded into business logic

The existing `ai_provider_configs.secret_ref` concept may be used later for authenticated per-user settings, but V1 runtime configuration comes from Railway.

## 7. Settings UI Scope

The current Settings page is a presentation shell and is not yet an authenticated secret-management surface.

For V1:

- the UI may display selected Provider and Model
- the UI may display `Configured` / `Not configured` for the API key
- the real key must never be returned to the browser
- the UI does not write or replace production AI secrets

Authenticated provider/key management is a later milestone.

## 8. Request Timeout, Retry, and Concurrency

Defaults:

- timeout per request: 20 seconds
- retry count: 1
- AI concurrency: 2

Retry only for transient conditions such as:

- network failures
- timeout
- HTTP 429
- HTTP 5xx

Do not repeatedly retry:

- authentication/authorization errors
- invalid provider/model configuration
- malformed structured response
- schema validation failure

Retries must use bounded backoff and must never block the scanner/realtime task.

## 9. Structured Output and Validation

Every successful provider response must validate against `AIDecision`.

No partially parsed or loosely structured result may be treated as a valid signal.

Allowed AI directions for candidate analysis are:

- `LONG`
- `SHORT`
- `WAIT`

`EXIT` remains part of the shared model for future position-management workflows but is not produced for a new scanner candidate in V1.

### Price geometry

After schema validation, the system performs deterministic price-structure checks.

For `LONG`:

```text
stop_loss < entry range < take profit targets
```

For `SHORT`:

```text
take profit targets < entry range < stop_loss
```

For `WAIT`, entry/SL/TP values may still be returned by the provider contract, but the result must not be interpreted as an actionable trade approval.

Malformed geometry produces an invalid/precheck-failed analysis and never an actionable result.

## 10. Persistence Model

The existing user-scoped `ai_decisions` table references the old `scanner_candidates` UUID table. Production market scanning now persists to system-wide `market_scanner_candidates`, whose IDs are bigint values.

AI Analysis V1 therefore uses a new system-wide table rather than incorrectly linking to the old user-scoped schema.

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

Suggested unique protection:

```text
unique(scanner_candidate_id, provider, model)
```

This prevents duplicate analysis for the same candidate/provider/model within a persisted scanner result.

### Status values

At minimum:

- `SUCCESS`
- `SKIPPED`
- `FAILED`
- `INVALID_RESPONSE`

Error messages stored in the table must be sanitized and bounded in length.

## 11. Deterministic Risk Precheck

AI is not an approval authority.

After a valid `AIDecision`, V1 runs only the deterministic checks that can be evaluated from currently available context:

- confidence minimum
- opportunity score minimum
- risk/reward minimum
- valid LONG/SHORT price geometry

The existing `RiskPolicy` remains the source for confidence/opportunity/RR thresholds where applicable.

Checks requiring account/portfolio context must not be fabricated. In V1, these include:

- actual position sizing
- account risk percentage
- current daily loss
- current number of open positions
- final leverage approval
- full high-impact event guard state if not available in the analysis snapshot

If these are not available, the analysis gets:

```text
FULL_RISK_CONTEXT_PENDING
```

This means the result is analytically valid but is not a full trade authorization.

## 12. Failure Isolation

AI Analysis V1 is optional enrichment.

The following must never fail the scanner cycle or stop realtime market ingestion:

- provider outage
- provider timeout
- rate limit
- malformed JSON
- schema validation failure
- invalid price geometry
- missing provider configuration
- missing API key
- persistence failure limited to the AI analysis path

Behavior on AI failure:

1. preserve the already persisted scanner result
2. preserve realtime ingestion
3. store a sanitized AI failure record when persistence is available
4. do not synthesize a replacement LONG/SHORT decision
5. do not alter scanner direction or scanner score

Cancellation of the market worker itself remains cooperative: `asyncio.CancelledError` must propagate correctly.

## 13. Observability

AI logging should include only non-secret operational metadata:

- provider
- model
- candidate symbol
- status
- latency
- attempt count
- normalized error code

Never log:

- `AI_API_KEY`
- Authorization header
- provider secret-bearing request headers
- full raw HTTP request containing credentials

Suggested cycle summary:

```text
ai_analysis candidates=3 success=2 failed=1 skipped=0 provider=...
```

## 14. API / Web Read Path

V1 should expose the latest AI analysis through the backend without exposing secrets.

Recommended read API:

```text
GET /api/v1/ai/latest?timeframe=15m&limit=10
```

The response should contain only sanitized analysis fields required for the UI.

The scanner UI may display:

- AI direction
- confidence
- entry range
- SL
- TP targets
- R:R
- reason summary
- risk precheck state
- provider/model

The UI must continue showing scanner data if the AI endpoint is unavailable.

## 15. Test Strategy

Implementation follows TDD where practical.

Required automated coverage:

1. provider adapter parses a valid structured response
2. malformed JSON is rejected
3. schema-invalid output is rejected
4. timeout triggers at most one retry
5. 429/5xx transient failure retries once
6. auth/config errors do not retry repeatedly
7. concurrency limit is enforced
8. AI task failure does not fail scanner persistence
9. AI task failure does not prevent realtime ingestion from starting
10. LONG price geometry validation
11. SHORT price geometry validation
12. WAIT is never considered an actionable approval
13. deterministic confidence/opportunity/RR precheck
14. incomplete portfolio context returns `FULL_RISK_CONTEXT_PENDING`
15. persistence stores no API key or Authorization header
16. duplicate candidate/provider/model protection works
17. existing market scanner tests remain green
18. existing News Enrichment tests remain green
19. existing market-worker secret-hardening regression remains green
20. web/API build/tests remain green

No test should make a paid external AI request in CI. Provider HTTP calls must be mocked/faked.

## 16. Rollout Plan

### Phase 1 — code/migration deployed disabled

Deploy with:

```text
AI_ANALYSIS_V1_ENABLED=false
TRADING_MODE=SIMULATION
DIRECT_AI_ORDER_ENABLED=false
```

Apply the migration and deploy code without calling AI.

Verify:

- scanner still persists normally
- realtime ingestion remains healthy
- existing production behavior is unchanged

### Phase 2 — canary

Configure provider/model/key server-side and set:

```text
AI_ANALYSIS_V1_ENABLED=true
AI_ANALYSIS_CANDIDATE_LIMIT=1
AI_ANALYSIS_CONCURRENCY=1
```

Verify:

- one analysis per intended scanner cycle
- response validates
- latency is bounded
- sanitized persistence is correct
- no secret appears in logs or database
- scanner/realtime timing remains healthy

### Phase 3 — Top 3

After the canary is stable:

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
- automatic provider failover between different vendors
- AI self-modification of scanner weights
- automatic promotion of learned rules to production
- real-money position sizing
- final account-level risk approval

Those require separate design approval.

## 18. Success Criteria

AI Analysis V1 is considered successful when:

1. the current market worker continues scanning and ingesting realtime data even if AI is disabled or broken
2. selected candidates receive valid structured AI analyses
3. 4H + 1H + 15m context, futures metrics, scanner scores, and available news context are included in the bounded AI snapshot
4. every successful result passes `AIDecision` validation and deterministic price-geometry checks
5. deterministic risk precheck cannot be bypassed by AI output
6. incomplete account context is marked pending rather than fabricated
7. results are stored against `market_scanner_candidates`, not the obsolete user-scoped scanner table
8. secrets stay server-side and do not appear in browser responses, logs, or persisted analysis payloads
9. CI passes with mocked provider requests
10. production rollout begins disabled, then canaries one candidate, then expands to Top 3 only after verification
