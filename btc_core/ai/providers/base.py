from __future__ import annotations

import asyncio
from typing import Any, Protocol

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from btc_core.ai.analysis import AIAnalysisSnapshot
from btc_core.ai.models import AIDecision, AIProvider


class AIProviderRuntimeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: AIProvider
    model: str = Field(min_length=1, max_length=120)
    api_key: str = Field(min_length=1, repr=False)
    base_url: str = Field(min_length=8, max_length=500)
    timeout_seconds: float = Field(default=20.0, gt=0, le=120)
    max_retries: int = Field(default=1, ge=0, le=1)

    @field_validator("model", "api_key", "base_url")
    @classmethod
    def strip_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("value must not be blank")
        return stripped


class AIProviderError(RuntimeError):
    def __init__(self, message: str, *, code: str, status_code: int | None = None):
        super().__init__(message)
        self.code = code
        self.status_code = status_code


class AIProviderClientProtocol(Protocol):
    async def analyze(self, snapshot: AIAnalysisSnapshot) -> AIDecision: ...


async def request_with_retry(
    client: httpx.AsyncClient,
    method: str,
    path: str,
    *,
    max_retries: int,
    json: dict[str, Any],
) -> httpx.Response:
    attempts = max_retries + 1
    for attempt in range(attempts):
        try:
            response = await client.request(method, path, json=json)
        except httpx.TimeoutException as exc:
            if attempt < max_retries:
                await asyncio.sleep(0)
                continue
            raise AIProviderError("AI provider request timed out", code="TIMEOUT") from exc
        except httpx.RequestError as exc:
            if attempt < max_retries:
                await asyncio.sleep(0)
                continue
            raise AIProviderError("AI provider network request failed", code="NETWORK") from exc

        if response.status_code == 429:
            if attempt < max_retries:
                await asyncio.sleep(0)
                continue
            raise AIProviderError(
                "AI provider rate limit reached",
                code="RATE_LIMIT",
                status_code=response.status_code,
            )
        if 500 <= response.status_code <= 599:
            if attempt < max_retries:
                await asyncio.sleep(0)
                continue
            raise AIProviderError(
                "AI provider upstream server error",
                code="UPSTREAM_5XX",
                status_code=response.status_code,
            )
        if response.status_code in {401, 403}:
            raise AIProviderError(
                "AI provider authentication failed",
                code="AUTH",
                status_code=response.status_code,
            )
        if response.is_error:
            raise AIProviderError(
                "AI provider request configuration was rejected",
                code="INVALID_CONFIG",
                status_code=response.status_code,
            )
        return response

    raise AIProviderError("AI provider request failed", code="NETWORK")
