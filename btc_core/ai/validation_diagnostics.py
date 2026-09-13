from __future__ import annotations

from pydantic import ValidationError

from btc_core.ai.providers.base import AIProviderError


_GEOMETRY_FIELDS = frozenset(
    {
        "entry_min",
        "entry_max",
        "stop_loss",
        "take_profits",
        "risk_reward",
    }
)


def safe_provider_error_code(exc: AIProviderError) -> str:
    """Return a bounded diagnostic code without inspecting or persisting raw AI output."""
    if exc.code != "INVALID_SCHEMA":
        return exc.code

    cause = exc.__cause__
    if not isinstance(cause, ValidationError):
        return exc.code

    top_level_fields: set[str] = set()
    has_model_level_error = False
    for error in cause.errors(
        include_url=False,
        include_context=False,
        include_input=False,
    ):
        location = error.get("loc", ())
        if not location:
            has_model_level_error = True
            continue
        top_level_fields.add(str(location[0]))

    if has_model_level_error or top_level_fields.intersection(_GEOMETRY_FIELDS):
        return "INVALID_SCHEMA_GEOMETRY"
    if "direction" in top_level_fields:
        return "INVALID_SCHEMA_DIRECTION"
    return "INVALID_SCHEMA_FIELD"
