import pytest

from btc_core.ai.models import AIProvider
from btc_core.ai.providers.base import AIProviderError, AIProviderRuntimeConfig
from btc_core.ai.providers.claude import ClaudeProviderClient
from btc_core.ai.providers.factory import build_provider_client
from btc_core.ai.providers.gemini import GeminiProviderClient
from btc_core.ai.providers.openai_compatible import OpenAICompatibleProviderClient


def make_config(provider: AIProvider, base_url: str = "https://example.test/v1"):
    return AIProviderRuntimeConfig(
        provider=provider,
        model="test-model",
        api_key="secret",
        base_url=base_url,
    )


@pytest.mark.parametrize(
    ("provider", "expected_type"),
    [
        (AIProvider.GEMINI, GeminiProviderClient),
        (AIProvider.CLAUDE, ClaudeProviderClient),
        (AIProvider.OPENAI_COMPATIBLE, OpenAICompatibleProviderClient),
        (AIProvider.DEEPSEEK, OpenAICompatibleProviderClient),
        (AIProvider.OPENROUTER, OpenAICompatibleProviderClient),
    ],
)
def test_factory_maps_all_supported_providers(provider, expected_type):
    client = build_provider_client(make_config(provider))
    assert isinstance(client, expected_type)


def test_factory_requires_base_url_for_openai_compatible_runtime():
    with pytest.raises(AIProviderError) as exc_info:
        build_provider_client(make_config(AIProvider.OPENAI_COMPATIBLE, base_url="   "))
    assert exc_info.value.code == "INVALID_CONFIG"
