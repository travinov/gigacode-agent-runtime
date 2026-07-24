"""Resolve plan-level permission gates before any agent subprocess starts."""

from __future__ import annotations

from dataclasses import dataclass

from .adapters.capabilities import GigaCodeCapabilities
from .approval_store import ApprovalStore
from .config import EffectiveConfig
from .domain import ExecutionPlan, PermissionMode
from .errors import AgentRuntimeError, ErrorCode


@dataclass(frozen=True, slots=True)
class PermissionDecision:
    full_access: bool
    trusted_hash: bool
    confirmed: bool
    max_parallel_full_access_agents: int


class PermissionController:
    def __init__(
        self,
        config: EffectiveConfig,
        approvals: ApprovalStore,
    ) -> None:
        self._config = config
        self._approvals = approvals

    def authorize(
        self,
        plan: ExecutionPlan,
        run_id: str,
        capabilities: GigaCodeCapabilities,
    ) -> PermissionDecision:
        capabilities.require(set(plan.capability_requirements))
        has_full_access = any(
            agent.permissions is PermissionMode.FULL_ACCESS for agent in plan.agents.values()
        )
        if not has_full_access:
            return PermissionDecision(
                full_access=False,
                trusted_hash=False,
                confirmed=False,
                max_parallel_full_access_agents=(
                    self._config.permissions.max_parallel_full_access_agents
                ),
            )
        if not self._config.permissions.allow_full_access:
            raise AgentRuntimeError(
                ErrorCode.PERMISSION_DENIED,
                "Scenario requests full_access but it is disabled globally",
                details={"scenario": plan.metadata.name, "plan_hash": plan.plan_hash},
            )

        trusted_hash = (
            self._config.permissions.trusted_scenario_hashes.get(plan.metadata.name)
            == plan.plan_hash
        )
        confirmed = self._approvals.is_approved(run_id, plan.plan_hash, "full_access")
        if (
            self._config.permissions.require_full_access_confirmation
            and not trusted_hash
            and not confirmed
        ):
            raise AgentRuntimeError(
                ErrorCode.APPROVAL_REQUIRED,
                "Full access requires approval for the exact execution plan",
                details={
                    "run_id": run_id,
                    "scenario": plan.metadata.name,
                    "plan_hash": plan.plan_hash,
                    "gate": "full_access",
                },
            )
        return PermissionDecision(
            full_access=True,
            trusted_hash=trusted_hash,
            confirmed=confirmed,
            max_parallel_full_access_agents=(
                self._config.permissions.max_parallel_full_access_agents
            ),
        )
