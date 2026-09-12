from __future__ import annotations

import json
from typing import Any

import httpx
from pydantic import ValidationError

from btc_core.ai.analysis import AIAnalysisSnapshot
from btc_core.ai.models import AIDecision
from btc_core.ai.providers.base import AIProviderError, AIProviderRuntimeConfig, request_with_retry


class ClaudeProviderClient:
    def __init__(self, config: AIProviderRuntimeConfig, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        if not config.base_url:
            raise AIProviderError("Claude base URL is required", code="INVALID_CONFIG")
        self.config = config
        self._client = httpx.AsyncClient(
            base_url=f"{config.base_url.rstrip('/')}/",
            timeout=httpx.Timeout(config.timeout_seconds),
            transport=transport,
            headers={"x-api-key": config.api_key, "anthropic-version": "2023-06-01", "Content-Type": "application/json"},
        )

    async def __aenter__(self): return self
    async def __aexit__(self, exc_type, exc, tb): await self.aclose()
    async def aclose(self) -> None: await self._client.aclose()

    def _request_payload(self, snapshot: AIAnalysisSnapshot, *, instruction: str | None = None) -> dict[str, Any]:
        system = (
            "Analyze crypto futures candidates. Return one JSON object matching the configured schema. "
            "Direction must be LONG, SHORT, or WAIT. Never claim an order was executed."
        )
        if instruction:
            system += f" Role instruction: {instruction}"
        return {
            "model": self.config.model,
            "max_tokens": 1024,
            "system": system,
            "messages": [{"role": "user", "content": "Analyze this bounded market snapshot:\n" + snapshot.model_dump_json()}],
            "output_config": {"format": {"type": "json_schema", "schema": AIDecision.model_json_schema()}},
        }

    def _parse_response(self, response: httpx.Response) -> AIDecision:
        try:
            envelope = response.json(); content = envelope["content"]
        except (ValueError, KeyError, TypeError) as exc:
            raise AIProviderError("Claude response did not contain content", code="INVALID_SCHEMA") from exc
        if not isinstance(content, list):
            raise AIProviderError("Claude response content must be a list", code="INVALID_SCHEMA")
        text_parts = [item.get("text") for item in content if isinstance(item, dict) and item.get("type") == "text" and isinstance(item.get("text"), str)]
        text_parts = [item for item in text_parts if item and item.strip()]
        if len(text_parts) != 1:
            raise AIProviderError("Claude response must contain one usable JSON text block", code="INVALID_SCHEMA")
        try: data = json.loads(text_parts[0])
        except ValueError as exc: raise AIProviderError("Claude returned invalid JSON content", code="INVALID_JSON") from exc
        if not isinstance(data, dict): raise AIProviderError("Claude JSON content must be an object", code="INVALID_SCHEMA")
        data = dict(data); data["provider"] = self.config.provider.value; data["model"] = self.config.model
        try: return AIDecision.model_validate(data)
        except ValidationError as exc: raise AIProviderError("Claude decision failed schema validation", code="INVALID_SCHEMA") from exc

    async def analyze(self, snapshot: AIAnalysisSnapshot, *, instruction: str | None = None) -> AIDecision:
        response = await request_with_retry(self._client, "POST", "v1/messages", max_retries=self.config.max_retries, json=self._request_payload(snapshot, instruction=instruction))
        return self._parse_response(response)
