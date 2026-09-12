from __future__ import annotations

import json
from typing import Any

import httpx
from pydantic import ValidationError

from btc_core.ai.analysis import AIAnalysisSnapshot
from btc_core.ai.models import AIDecision
from btc_core.ai.providers.base import AIProviderError, AIProviderRuntimeConfig, request_with_retry


_SYSTEM_PROMPT = """You analyze crypto futures candidates. Return exactly one JSON object and no markdown.\nUse these exact fields: provider, model, symbol, timeframe, direction, confidence, entry_min, entry_max, stop_loss, take_profits, risk_reward, reason_summary.\ndirection must be LONG, SHORT, or WAIT. Do not claim an order was executed."""


class OpenAICompatibleProviderClient:
    def __init__(self, config: AIProviderRuntimeConfig, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.config = config
        self._client = httpx.AsyncClient(base_url=f"{config.base_url.rstrip('/')}/", timeout=httpx.Timeout(config.timeout_seconds), transport=transport, headers={"Authorization": f"Bearer {config.api_key}", "Content-Type": "application/json"})

    async def __aenter__(self): return self
    async def __aexit__(self, exc_type, exc, tb): await self.aclose()
    async def aclose(self) -> None: await self._client.aclose()

    def _request_payload(self, snapshot: AIAnalysisSnapshot, *, instruction: str | None = None) -> dict[str, Any]:
        system = _SYSTEM_PROMPT if not instruction else f"{_SYSTEM_PROMPT}\nRole instruction: {instruction}"
        return {"model": self.config.model, "messages": [{"role": "system", "content": system}, {"role": "user", "content": "Analyze this bounded market snapshot and return JSON:\n" + snapshot.model_dump_json()}], "response_format": {"type": "json_object"}}

    def _parse_response(self, response: httpx.Response) -> AIDecision:
        try: envelope = response.json()
        except ValueError as exc: raise AIProviderError("AI provider returned invalid JSON envelope", code="INVALID_JSON") from exc
        try: content = envelope["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc: raise AIProviderError("AI provider response did not contain message content", code="INVALID_SCHEMA") from exc
        if not isinstance(content, str) or not content.strip(): raise AIProviderError("AI provider response content was empty", code="INVALID_SCHEMA")
        try: data = json.loads(content)
        except (TypeError, ValueError) as exc: raise AIProviderError("AI provider returned invalid JSON content", code="INVALID_JSON") from exc
        if not isinstance(data, dict): raise AIProviderError("AI provider JSON content must be an object", code="INVALID_SCHEMA")
        data = dict(data); data["provider"] = self.config.provider.value; data["model"] = self.config.model
        try: return AIDecision.model_validate(data)
        except ValidationError as exc: raise AIProviderError("AI provider decision failed schema validation", code="INVALID_SCHEMA") from exc

    async def analyze(self, snapshot: AIAnalysisSnapshot, *, instruction: str | None = None) -> AIDecision:
        response = await request_with_retry(self._client, "POST", "chat/completions", max_retries=self.config.max_retries, json=self._request_payload(snapshot, instruction=instruction))
        return self._parse_response(response)
