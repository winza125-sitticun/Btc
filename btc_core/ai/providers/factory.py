from __future__ import annotations

import httpx

from btc_core.ai.models import AIProvider
from btc_core.ai.providers.base import AIProviderClientProtocol, AIProviderError, AIProviderRuntimeConfig
from btc_core.ai.providers.claude import ClaudeProviderClient
from btc_core.ai.providers.gemini import GeminiProviderClient
from btc_core.ai.providers.openai_compatible import OpenAICompatibleProviderClient


_DEFAULT_BASE_URLS: dict[AIProvider, str] = {
    AIProvider.GEMINI: "https://generativelanguage.googleapis.com/v1beta",
    AIProvider.CLAUDE: "https://api.anthropic.com",
    AIProvider.DEEPSEEK: "https://api.deepseek.com",
    AIProvider.OPENROUTER: "https://openrouter.ai/api/v1",
}


def _resolve_config(config: AIProviderRuntimeConfig) -> AIProviderRuntimeConfig:
    if config.base_url:
        return config
    if config.provider is AIProvider.OPENAI_COMPATIBLE:
        raise AIProviderError("AI_BASE_URL is required for OPENAI_COMPATIBLE", code="INVALID_CONFIG")
    default = _DEFAULT_BASE_URLS.get(config.provider)
    if not default:
        raise AIProviderError("Unsupported AI provider", code="INVALID_CONFIG")
    return config.model_copy(update={"base_url": default})


def build_provider_client(
    config: AIProviderRuntimeConfig,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> AIProviderClientProtocol:
    resolved = _resolve_config(config)
    if resolved.provider is AIProvider.GEMINI:
        return GeminiProviderClient(resolved, transport=transport)
    if resolved.provider is AIProvider.CLAUDE:
        return ClaudeProviderClient(resolved, transport=transport)
    if resolved.provider in {
        AIProvider.OPENAI_COMPATIBLE,
        AIProvider.DEEPSEEK,
        AIProvider.OPENROUTER,
    }:
        return OpenAICompatibleProviderClient(resolved, transport=transport)
    raise AIProviderError("Unsupported AI provider", code="INVALID_CONFIG")
