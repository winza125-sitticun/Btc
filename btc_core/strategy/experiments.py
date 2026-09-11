"""Simulation-only experiment registry state machine."""
from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


class ExperimentStatus(StrEnum):
    DRAFT = "DRAFT"
    SIMULATION = "SIMULATION"
    PROMOTABLE = "PROMOTABLE"
    REJECTED = "REJECTED"
    ARCHIVED = "ARCHIVED"


class StrategyExperiment(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    id: str
    name: str
    description: str
    baseline_identifier: str
    variant_configuration: dict[str, Any] = Field(default_factory=dict)
    status: ExperimentStatus = ExperimentStatus.DRAFT
    started_at: datetime | None = None
    ended_at: datetime | None = None
    sample_count: int = Field(default=0, ge=0)
    metric_deltas: dict[str, Any] = Field(default_factory=dict)
    decision_reason: str | None = None


_TRANSITIONS = {
    ExperimentStatus.DRAFT: {ExperimentStatus.SIMULATION},
    ExperimentStatus.SIMULATION: {ExperimentStatus.PROMOTABLE, ExperimentStatus.REJECTED},
    ExperimentStatus.PROMOTABLE: {ExperimentStatus.ARCHIVED},
    ExperimentStatus.REJECTED: {ExperimentStatus.ARCHIVED},
    ExperimentStatus.ARCHIVED: set(),
}


def create_experiment(name: str, description: str, baseline_identifier: str, variant_configuration: dict[str, Any] | None = None) -> StrategyExperiment:
    if not name.strip() or not description.strip() or not baseline_identifier.strip():
        raise ValueError("name, description, and baseline_identifier are required")
    return StrategyExperiment(id=str(uuid4()), name=name.strip(), description=description.strip(), baseline_identifier=baseline_identifier.strip(), variant_configuration=dict(variant_configuration or {}))


def transition_experiment(experiment: StrategyExperiment, target: ExperimentStatus, *, sample_count: int | None = None, metric_deltas: dict[str, Any] | None = None, decision_reason: str | None = None, railway_variables: Any = None, **_ignored: Any) -> StrategyExperiment:
    """Return a new state; never changes deployment/configuration.

    ``railway_variables`` is explicitly rejected to prevent learning code from
    acquiring an accidental production mutation interface.
    """
    if railway_variables is not None:
        raise ValueError("experiments cannot mutate production configuration")
    if target not in _TRANSITIONS[experiment.status]:
        raise ValueError(f"invalid experiment transition {experiment.status} -> {target}")
    count = experiment.sample_count if sample_count is None else sample_count
    if count < 0: raise ValueError("sample_count must not be negative")
    if target is ExperimentStatus.PROMOTABLE and count <= 0:
        raise ValueError("promotion requires simulation evidence")
    now = datetime.now(timezone.utc)
    return experiment.model_copy(update={"status": target, "started_at": now if target is ExperimentStatus.SIMULATION else experiment.started_at, "ended_at": now if target in (ExperimentStatus.PROMOTABLE, ExperimentStatus.REJECTED, ExperimentStatus.ARCHIVED) else experiment.ended_at, "sample_count": count, "metric_deltas": dict(metric_deltas or experiment.metric_deltas), "decision_reason": decision_reason if decision_reason is not None else experiment.decision_reason})


Experiment = StrategyExperiment
