from __future__ import annotations

import hashlib
import json

from btc_core.ai.multi_agent.models import AgentRole, RolePrompt


ROLE_INSTRUCTIONS_V1: dict[AgentRole, str] = {
    AgentRole.TECHNICAL: (
        "Analyze only the supplied multi-timeframe price/technical context. "
        "Focus on trend structure, support/resistance, price geometry and technical invalidation. "
        "Return the strict AIDecision schema; do not invent market data or place/authorize orders."
    ),
    AgentRole.MOMENTUM: (
        "Analyze only the supplied momentum, volume and volatility context. "
        "Focus on acceleration/deceleration, participation, breakout versus mean-reversion risk and momentum invalidation. "
        "Return the strict AIDecision schema; do not invent data or place/authorize orders."
    ),
    AgentRole.ORDER_FLOW: (
        "Analyze only supplied derivatives/order-flow evidence: funding, open-interest change, long/short positioning, spread/liquidity and related bounded context. "
        "Explain whether flows confirm, contradict or fail to confirm the setup. "
        "Return the strict AIDecision schema; do not invent order-book data or place/authorize orders."
    ),
    AgentRole.NEWS: (
        "Analyze only the sanitized news/macro items supplied in the snapshot and their relevance to this symbol/setup. "
        "If news is absent or stale, explicitly reduce confidence or WAIT; never invent headlines, events or sources. "
        "Return the strict AIDecision schema; do not place/authorize orders."
    ),
    AgentRole.CONTRARIAN: (
        "Act as a skeptical counter-thesis reviewer. Challenge the apparent setup, identify opposing evidence, failure modes and invalidation conditions, "
        "then return LONG, SHORT, WAIT or EXIT using the same strict AIDecision schema. Do not place/authorize orders."
    ),
    AgentRole.RISK_REVIEW: (
        "Review qualitative setup risk only: conflicting timeframes, crowded positioning, event/news risk, weak geometry and uncertainty. "
        "Your output is advisory analysis only and can never approve, size, submit or authorize a trade. Return the strict AIDecision schema."
    ),
}


_REQUIRED_FOCUS: dict[AgentRole, tuple[str, ...]] = {
    AgentRole.TECHNICAL: ("multi-timeframe structure", "support/resistance", "technical invalidation"),
    AgentRole.MOMENTUM: ("momentum", "volume participation", "volatility"),
    AgentRole.ORDER_FLOW: ("funding", "open interest", "positioning and liquidity"),
    AgentRole.NEWS: ("sanitized news", "macro relevance", "freshness uncertainty"),
    AgentRole.CONTRARIAN: ("counter-thesis", "failure modes", "invalidation"),
    AgentRole.RISK_REVIEW: ("qualitative setup risk", "conflicts", "uncertainty"),
}


_SAFETY_CONSTRAINTS: tuple[str, ...] = (
    "Use only supplied bounded context.",
    "Return the strict AIDecision schema.",
    "Never place, size, submit or authorize an order.",
)


def _normalized(text: str) -> str:
    return " ".join(text.split())


def _prompt_digest(role: AgentRole, version: str, instruction: str) -> str:
    canonical = json.dumps(
        {
            "role": role.value,
            "version": version,
            "instruction": _normalized(instruction),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def role_prompt(role: AgentRole, version: str = "v1") -> RolePrompt:
    if version != "v1":
        raise ValueError(f"unsupported prompt version for {role.value}: {version}")
    instruction = ROLE_INSTRUCTIONS_V1[role]
    return RolePrompt(
        role=role,
        version=version,
        instruction=instruction,
        required_focus=_REQUIRED_FOCUS[role],
        safety_constraints=_SAFETY_CONSTRAINTS,
        digest=_prompt_digest(role, version, instruction),
    )
