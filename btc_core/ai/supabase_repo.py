from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field

from btc_core.ai.models import AIProvider, Direction


_SAFE_SELECT = (
    "scanner_candidate_id,run_id,symbol,timeframe,provider,model,scanner_direction,"
    "ai_direction,confidence,entry_min,entry_max,stop_loss,take_profits,risk_reward,"
    "reason_summary,status,risk_precheck_status,risk_precheck_reasons,latency_ms,"
    "attempt_count,error_code,created_at,completed_at"
)
_SECRET_KEYS = {
    "authorization",
    "api_key",
    "apikey",
    "api-key",
    "access_token",
    "secret",
    "token",
}


class SupabaseAIRepositoryError(RuntimeError):
    pass


class MarketAIAnalysisRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    scanner_candidate_id: int = Field(gt=0)
    run_id: str = Field(min_length=1)
    symbol: str = Field(min_length=1, max_length=30)
    timeframe: str = Field(min_length=1, max_length=10)
    provider: AIProvider
    model: str = Field(min_length=1, max_length=120)
    scanner_direction: Direction
    ai_direction: Direction | None = None
    confidence: float | None = Field(default=None, ge=0, le=100)
    entry_min: float | None = Field(default=None, gt=0)
    entry_max: float | None = Field(default=None, gt=0)
    stop_loss: float | None = Field(default=None, gt=0)
    take_profits: tuple[float, ...] = ()
    risk_reward: float | None = Field(default=None, gt=0)
    reason_summary: str | None = Field(default=None, max_length=1000)
    input_snapshot: dict[str, Any] = Field(default_factory=dict)
    status: Literal["SUCCESS", "SKIPPED", "FAILED", "INVALID_RESPONSE"]
    risk_precheck_status: str | None = Field(default=None, max_length=100)
    risk_precheck_reasons: tuple[str, ...] = ()
    latency_ms: int | None = Field(default=None, ge=0)
    attempt_count: int = Field(default=0, ge=0)
    error_code: str | None = Field(default=None, max_length=100)
    error_message: str | None = None
    completed_at: datetime | None = None


def _sanitize(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _sanitize(item)
            for key, item in value.items()
            if str(key).strip().lower() not in _SECRET_KEYS
        }
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    if isinstance(value, tuple):
        return [_sanitize(item) for item in value]
    return value


class SupabaseAIAnalysisRepository:
    def __init__(
        self,
        *,
        supabase_url: str,
        api_key: str,
        timeout_seconds: float = 10.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not supabase_url.strip() or not api_key.strip():
            raise ValueError("Supabase URL and API key are required")
        self._client = httpx.AsyncClient(
            base_url=f"{supabase_url.rstrip('/')}/rest/v1",
            timeout=httpx.Timeout(timeout_seconds),
            transport=transport,
            headers={
                "apikey": api_key,
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
        )

    async def __aenter__(self) -> "SupabaseAIAnalysisRepository":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        try:
            response = await self._client.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise SupabaseAIRepositoryError("Supabase AI repository request failed") from exc
        if response.is_error:
            raise SupabaseAIRepositoryError(
                f"Supabase AI repository returned HTTP {response.status_code}"
            )
        return response

    async def persist(self, record: MarketAIAnalysisRecord) -> None:
        payload = record.model_dump(mode="json", exclude_none=True)
        payload["input_snapshot"] = _sanitize(payload.get("input_snapshot", {}))
        if payload.get("error_message") is not None:
            payload["error_message"] = str(payload["error_message"])[:500]
        await self._request(
            "POST",
            "/market_ai_analyses",
            params={"on_conflict": "scanner_candidate_id,provider,model"},
            headers={"Prefer": "resolution=merge-duplicates,return=minimal"},
            json=payload,
        )

    async def latest(self, timeframe: str, limit: int) -> list[dict[str, Any]]:
        normalized = timeframe.strip()
        if not normalized:
            return []
        if not 1 <= limit <= 50:
            raise ValueError("limit must be between 1 and 50")
        response = await self._request(
            "GET",
            "/market_ai_analyses",
            params={
                "select": _SAFE_SELECT,
                "timeframe": f"eq.{normalized}",
                "order": "created_at.desc",
                "limit": str(limit),
            },
        )
        rows = response.json()
        return rows if isinstance(rows, list) else []
