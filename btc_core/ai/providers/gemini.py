from __future__ import annotations

import json
from typing import Any

import httpx
from pydantic import ValidationError

from btc_core.ai.analysis import AIAnalysisSnapshot
from btc_core.ai.models import AIDecision
from btc_core.ai.providers.base import AIProviderError, AIProviderRuntimeConfig, request_with_retry


_GEMINI_JSON_SCHEMA_KEYS = {
    "$id",
    "$defs",
    "$ref",
    "$anchor",
    "type",
    "format",
    "title",
    "description",
    "enum",
    "items",
    "prefixItems",
    "minItems",
    "maxItems",
    "minimum",
    "maximum",
    "anyOf",
    "oneOf",
    "properties",
    "additionalProperties",
    "required",
}


def _normalize_gemini_json_schema(value: Any) -> Any:
    if isinstance(value, list):
        return [_normalize_gemini_json_schema(item) for item in value]
    if not isinstance(value, dict):
        return value

    normalized: dict[str, Any] = {}
    for key, item in value.items():
        if key == "exclusiveMinimum":
            normalized.setdefault("minimum", item)
            continue
        if key == "exclusiveMaximum":
            normalized.setdefault("maximum", item)
            continue
        if key not in _GEMINI_JSON_SCHEMA_KEYS:
            continue

        if key in {"properties", "$defs"} and isinstance(item, dict):
            normalized[key] = {
                name: _normalize_gemini_json_schema(schema)
                for name, schema in item.items()
            }
        else:
            normalized[key] = _normalize_gemini_json_schema(item)
    return normalized


def _decode_gemini_json_text(text: str) -> Any:
    stripped = text.strip()
    try:
        return json.loads(stripped)
    except ValueError as initial_exc:
        if stripped.count("```") != 2:
            raise initial_exc
        if stripped.startswith("```json\n") and stripped.endswith("\n```"):
            inner = stripped[len("```json\n") : -len("\n```")]
        elif stripped.startswith("```\n") and stripped.endswith("\n```"):
            inner = stripped[len("```\n") : -len("\n```")]
        else:
            raise initial_exc
        return json.loads(inner.strip())


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

    def _request_payload(
        self,
        snapshot: AIAnalysisSnapshot,
        *,
        include_schema: bool = True,
        include_response_format: bool = True,
    ) -> dict[str, Any]:
        if include_schema:
            output_instruction = "Return one JSON object matching the response schema. "
        else:
            output_instruction = (
                "Return exactly one JSON object with keys symbol, timeframe, direction, confidence, "
                "entry_min, entry_max, stop_loss, take_profits, risk_reward, and reason_summary. "
            )

        payload: dict[str, Any] = {
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {
                            "text": (
                                "Analyze this bounded crypto futures snapshot. "
                                + output_instruction
                                + "Direction must be LONG, SHORT, or WAIT; never claim an order was executed.\n"
                                + snapshot.model_dump_json()
                            )
                        }
                    ],
                }
            ],
        }
        if not include_response_format:
            return payload

        response_text: dict[str, Any] = {"mimeType": "application/json"}
        if include_schema:
            response_text["schema"] = _normalize_gemini_json_schema(AIDecision.model_json_schema())
        payload["generationConfig"] = {
            "responseFormat": {
                "text": response_text,
            }
        }
        return payload

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
            data = _decode_gemini_json_text(text_parts[0])
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

    @staticmethod
    def _is_bad_request(exc: AIProviderError) -> bool:
        return exc.code == "INVALID_CONFIG" and exc.status_code == 400

    async def analyze(self, snapshot: AIAnalysisSnapshot) -> AIDecision:
        path = f"models/{self.config.model}:generateContent"
        if self.config.model.startswith("gemini-3.8-"):
            response = await request_with_retry(
                self._client,
                "POST",
                path,
                max_retries=self.config.max_retries,
                json=self._request_payload(
                    snapshot,
                    include_schema=False,
                    include_response_format=False,
                ),
            )
            return self._parse_response(response)

        try:
            response = await request_with_retry(
                self._client,
                "POST",
                path,
                max_retries=self.config.max_retries,
                json=self._request_payload(snapshot),
            )
        except AIProviderError as structured_exc:
            if not self._is_bad_request(structured_exc):
                raise
            try:
                response = await request_with_retry(
                    self._client,
                    "POST",
                    path,
                    max_retries=self.config.max_retries,
                    json=self._request_payload(snapshot, include_schema=False),
                )
            except AIProviderError as mime_exc:
                if not self._is_bad_request(mime_exc):
                    raise
                response = await request_with_retry(
                    self._client,
                    "POST",
                    path,
                    max_retries=self.config.max_retries,
                    json=self._request_payload(
                        snapshot,
                        include_schema=False,
                        include_response_format=False,
                    ),
                )
        return self._parse_response(response)
