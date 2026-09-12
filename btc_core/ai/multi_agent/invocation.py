from __future__ import annotations

from collections.abc import Mapping

from btc_core.ai.models import AIDecision
from btc_core.ai.multi_agent.models import AgentRequest, AgentRole, FrozenRoleAssignment
from btc_core.ai.providers.base import AIProviderClientProtocol, AIProviderError


class RoleAwareProviderInvoker:
    """Routes one frozen role assignment to its configured provider client."""

    def __init__(self, clients: Mapping[AgentRole, AIProviderClientProtocol]) -> None:
        self._clients = dict(clients)

    async def invoke(
        self,
        assignment: FrozenRoleAssignment,
        request: AgentRequest,
    ) -> AIDecision:
        if request.role is not assignment.role:
            raise AIProviderError("Role request did not match assignment", code="INVALID_CONFIG")
        client = self._clients.get(assignment.role)
        if client is None:
            raise AIProviderError(
                f"No provider client configured for role {assignment.role.value}",
                code="INVALID_CONFIG",
            )
        return await client.analyze(
            request.snapshot_envelope.snapshot,
            instruction=request.prompt.instruction,
        )
