import pytest

from btc_core.strategy.experiments import ExperimentStatus, create_experiment, transition_experiment


def test_experiment_lifecycle_is_simulation_only():
    experiment = create_experiment("rsi-v2", "test variant", "baseline-v1", {"threshold": 80})
    assert experiment.status is ExperimentStatus.DRAFT
    experiment = transition_experiment(experiment, ExperimentStatus.SIMULATION)
    experiment = transition_experiment(experiment, ExperimentStatus.PROMOTABLE, sample_count=20, decision_reason="evidence")
    archived = transition_experiment(experiment, ExperimentStatus.ARCHIVED)
    assert archived.status is ExperimentStatus.ARCHIVED
    assert archived.variant_configuration == {"threshold": 80}


def test_experiment_rejects_invalid_transitions_and_production_mutation():
    experiment = create_experiment("x", "x", "base", {})
    with pytest.raises(ValueError):
        transition_experiment(experiment, ExperimentStatus.PROMOTABLE)
    with pytest.raises(ValueError):
        transition_experiment(experiment, ExperimentStatus.SIMULATION, railway_variables={"X": "Y"})

