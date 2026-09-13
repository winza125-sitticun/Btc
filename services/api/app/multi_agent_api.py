from __future__ import annotations

import os
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query

from btc_core.ai.models import AIProvider
from btc_core.ai.multi_agent.config import freeze_multi_agent_config, load_multi_agent_config
from btc_core.ai.multi_agent.models import AgentRole
from btc_core.ai.multi_agent.prompts import role_prompt
from btc_core.ai.multi_agent.read_repository import MultiAgentReadRepository
from services.api.app.config import (
    DashboardEventSummary,
    MultiAgentConfigSummary,
    MultiAgentRunDetail,
    MultiAgentRunSummary,
    PerformanceSummaryResponse,
)


router = APIRouter(prefix="/api/v1/multi-agent", tags=["multi-agent"])

_PROVIDER_SECRET_ENV = {
    AIProvider.GEMINI: "GEMINI_API_KEY",
    AIProvider.CLAUDE: "ANTHROPIC_API_KEY",
    AIProvider.OPENAI_COMPATIBLE: "OPENAI_COMPATIBLE_API_KEY",
    AIProvider.DEEPSEEK: "DEEPSEEK_API_KEY",
    AIProvider.OPENROUTER: "OPENROUTER_API_KEY",
}
_PRIVATE_EXACT = {
    "input_snapshot",
    "raw_provider_body",
    "provider_body",
    "prompt_text",
    "role_prompt_bundle",
    "api_key",
    "apikey",
    "api-key",
    "access_token",
    "token",
    "secret",
    "password",
    "authorization",
    "auth_header",
    "credential",
    "credentials",
    "webhook_url",
    "webhook",
}
_PRIVATE_PARTS = ("password", "authorization", "credential")


def _is_private_key(key: Any) -> bool:
    normalized = str(key).strip().lower()
    if normalized == "secret_configured":
        return False
    if normalized in _PRIVATE_EXACT:
        return True
    if any(part in normalized for part in _PRIVATE_PARTS):
        return True
    return normalized.endswith(("_api_key", "_access_token", "_auth_token", "_secret"))


def sanitize_multi_agent_public(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): sanitize_multi_agent_public(item)
            for key, item in value.items()
            if not _is_private_key(key)
        }
    if isinstance(value, (list, tuple)):
        return [sanitize_multi_agent_public(item) for item in value]
    return value


async def get_multi_agent_reader():
    url = os.getenv("SUPABASE_URL", "").strip()
    key = os.getenv("SUPABASE_ANON_KEY", "").strip()
    if not url or not key:
        raise RuntimeError("SUPABASE_URL and SUPABASE_ANON_KEY are required")
    repo = MultiAgentReadRepository(supabase_url=url, api_key=key)
    try:
        yield repo
    finally:
        await repo.aclose()


def _configured_role_summary(role: AgentRole, frozen, env: dict[str, str]) -> dict[str, Any]:
    assignment = next((item for item in frozen.assignments if item.role is role), None)
    prefix = f"AI_ROLE_{role.value}_"
    if assignment is not None:
        provider = assignment.provider
        model = assignment.model
        base_weight = assignment.base_weight
        prompt_version = assignment.prompt_version
        prompt_digest = assignment.prompt_digest
        enabled = True
    else:
        provider_raw = (env.get(prefix + "PROVIDER") or "").strip().upper()
        try:
            provider = AIProvider(provider_raw) if provider_raw else None
        except ValueError:
            provider = None
        model = (env.get(prefix + "MODEL") or "").strip()
        try:
            base_weight = float(env.get(prefix + "BASE_WEIGHT", "1.0"))
        except ValueError:
            base_weight = 1.0
        prompt_version = (env.get(prefix + "PROMPT_VERSION") or "v1").strip() or "v1"
        try:
            prompt = role_prompt(role, prompt_version)
        except ValueError:
            prompt = role_prompt(role, "v1")
            prompt_version = prompt.version
        prompt_digest = prompt.digest
        enabled = False
    secret_name = _PROVIDER_SECRET_ENV.get(provider) if provider is not None else None
    return {
        "role": role.value,
        "enabled": enabled,
        "provider": provider.value if provider is not None else "",
        "model": model,
        "base_weight": base_weight,
        "prompt_version": prompt_version,
        "prompt_digest": prompt_digest,
        "secret_configured": bool(secret_name and (env.get(secret_name) or "").strip()),
    }


@router.get("/config", response_model=MultiAgentConfigSummary)
def multi_agent_config() -> dict[str, Any]:
    try:
        env = dict(os.environ)
        config = load_multi_agent_config(env)
        frozen = freeze_multi_agent_config(config)
        payload = {
            "config_version": frozen.config_version,
            "rollout_mode": frozen.mode.value,
            "min_valid_roles": frozen.min_valid_roles,
            "min_coverage": frozen.min_coverage,
            "min_agreement": frozen.min_agreement,
            "min_signed_score": frozen.min_signed_score,
            "decision_contract_version": frozen.decision_contract_version,
            "consensus_algorithm_version": frozen.consensus_version,
            "hesitation_algorithm_version": frozen.hesitation_version,
            "performance_algorithm_version": frozen.performance_version,
            "roles": [_configured_role_summary(role, frozen, env) for role in AgentRole],
        }
        return sanitize_multi_agent_public(payload)
    except ValueError as exc:
        raise HTTPException(status_code=503, detail="Multi-agent configuration is invalid") from exc


@router.get("/latest", response_model=list[MultiAgentRunSummary])
async def multi_agent_latest(
    reader: Annotated[MultiAgentReadRepository, Depends(get_multi_agent_reader)],
    timeframe: str = Query(default="15m", min_length=2, max_length=8),
    limit: int = Query(default=10, ge=1, le=50),
):
    try:
        return sanitize_multi_agent_public(
            await reader.latest_runs(timeframe=timeframe.strip(), limit=limit)
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/runs/{run_id}", response_model=MultiAgentRunDetail)
async def multi_agent_run(
    run_id: str,
    reader: Annotated[MultiAgentReadRepository, Depends(get_multi_agent_reader)],
):
    item = await reader.run_detail(run_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Multi-agent run not found")
    return sanitize_multi_agent_public(item)


@router.get("/events", response_model=list[DashboardEventSummary])
async def multi_agent_events(
    reader: Annotated[MultiAgentReadRepository, Depends(get_multi_agent_reader)],
    run_id: str = Query(min_length=1, max_length=100),
    limit: int = Query(default=100, ge=1, le=500),
):
    try:
        return sanitize_multi_agent_public(
            await reader.dashboard_events(run_id=run_id, limit=limit)
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/performance", response_model=list[PerformanceSummaryResponse])
async def multi_agent_performance(
    reader: Annotated[MultiAgentReadRepository, Depends(get_multi_agent_reader)],
    role: str | None = Query(default=None),
    symbol: str | None = Query(default=None, max_length=30),
    horizon: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
):
    try:
        return sanitize_multi_agent_public(
            await reader.performance_summaries(
                role=role,
                symbol=symbol,
                horizon=horizon,
                limit=limit,
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
