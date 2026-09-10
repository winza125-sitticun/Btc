from __future__ import annotations

import json
from typing import Any

import httpx
from pydantic import ValidationError

from btc_core.ai.analysis import AIAnalysisSnapshot
from btc_core.ai.models import AIDecision
from btc_core.ai.providers.base import AIProviderError, AIProviderRuntimeConfig, request_with_retry


class GeminiProviderClient:
    def __init__(
        self,
        config: AIProviderRuntimeConfig,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not config.base_url:
            raise AIProviderError("Gemini base URL is required", code="INVALID_CONFIG")
        self.config = config
        self._client = httpx.AsyncClient(
            base_url=f"{config.base_url.rstrip('/')}/",
            timeout=httpx.Timeout(config.timeout_seconds),
            transport=transport,
            headers={
                "x-goog-api-key": config.api_key,
                "Content-Type": "application/json",
            },
        )

    async def __aenter__(self) -> "GeminiProviderClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    def _request_payload(self, snapshot: AIAnalysisSnapshot) -> dict[str, Any]:
        return {
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {
                            "text": (
                                "Analyze this bounded crypto futures snapshot. "
                                "Return one JSON object matching the response schema. "
                                "Direction must be LONG, SHORT, or WAIT; never claim an order was executed.\n"
                                + snapshot.model_dump_json()
                            )
                        }
                    ],
                }
            ],
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseJsonSchema": AIDecision.model_json_schema(),
            },
        }

    def _parse_response(self, response: httpx.Response) -> AIDecision:
        try:
            envelope = response.json()
            parts = envelope["candidates"][0]["content"]["parts"]
            text_parts = [item["text"] for item in parts if isinstance(item, dict) and isinstance(item.get("text"), str)]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise AIProviderError("Gemini response did not contain usable text", code="INVALID_SCHEMA") from exc
        if len(text_parts) != 1 or not text_parts[0].strip():
            raise AIProviderError("Gemini response must contain one JSON text part", code="INVALID_SCHEMA")
        try:
            data = json.loads(text_parts[0])
        except ValueError as exc:
            raise AIProviderError("Gemini returned invalid JSON content", code="INVALID_JSON") from exc
        if not isinstance(data, dict):
            raise AIProviderError("Gemini JSON content must be an object", code="INVALID_SCHEMA")
        data = dict(data)
        data["provider"] = self.config.provider.value
        data["model"] = self.config.model
        try:
            return AIDecision.model_validate(data)
        except ValidationError as exc:
            raise AIProviderError("Gemini decision failed schema validation", code="INVALID_SCHEMA") from exc

    async def analyze(self, snapshot: AIAnalysisSnapshot) -> AIDecision:
        response = await request_with_retry(
            self._client,
            "POST",
            f"models/{self.config.model}:generateContent",
            max_retries=self.config.max_retries,
            json=self._request_payload(snapshot),
        )
        return self._parse_response(response)
