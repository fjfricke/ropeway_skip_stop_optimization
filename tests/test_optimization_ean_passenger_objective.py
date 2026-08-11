import pytest

from ropeway_skip_stop_optimization.optimization.ean import (
    EanPassengerObjective,
    EanPassengerObjectiveEvent,
    ean_passenger_objective_definition,
)
from ropeway_skip_stop_optimization.optimization.ean.optimizers.passenger_model import (
    EanPassengerObjective as LegacyPassengerObjectiveImport,
)


@pytest.mark.parametrize(
    ("objective", "event", "expected_cost"),
    (
        (
            EanPassengerObjective.WAITING_TIME,
            EanPassengerObjectiveEvent.BOARDING,
            7.0,
        ),
        (
            EanPassengerObjective.JOURNEY_TIME,
            EanPassengerObjectiveEvent.ALIGHTING,
            25.0,
        ),
    ),
)
def test_objective_definition_preserves_exact_ean_costs(
    objective: EanPassengerObjective,
    event: EanPassengerObjectiveEvent,
    expected_cost: float,
) -> None:
    definition = ean_passenger_objective_definition(objective)

    assert definition.event is event
    assert definition.served_cost_seconds(
        release_time_seconds=3.0,
        boarding_time_seconds=10.0,
        alighting_time_seconds=28.0,
    ) == pytest.approx(expected_cost)
    assert definition.unserved_cost_seconds(
        release_time_seconds=3.0,
        horizon_seconds=100.0,
    ) == pytest.approx(97.0)


@pytest.mark.parametrize(
    "objective",
    tuple(EanPassengerObjective),
)
def test_optimistic_objective_cost_is_a_lower_bound(
    objective: EanPassengerObjective,
) -> None:
    definition = ean_passenger_objective_definition(objective)
    lower_bound = definition.optimistic_served_cost_lower_bound_seconds(
        release_time_seconds=10.0,
        earliest_boarding_time_seconds=5.0,
        earliest_alighting_time_seconds=12.0,
    )
    exact = definition.served_cost_seconds(
        release_time_seconds=10.0,
        boarding_time_seconds=14.0,
        alighting_time_seconds=30.0,
    )

    assert 0.0 <= lower_bound <= exact


def test_legacy_passenger_model_import_keeps_the_public_enum_identity() -> None:
    assert LegacyPassengerObjectiveImport is EanPassengerObjective


def test_exact_objective_rejects_temporally_invalid_ride() -> None:
    definition = ean_passenger_objective_definition(EanPassengerObjective.JOURNEY_TIME)

    with pytest.raises(ValueError, match="before release"):
        definition.served_cost_seconds(
            release_time_seconds=10.0,
            boarding_time_seconds=9.0,
            alighting_time_seconds=20.0,
        )
