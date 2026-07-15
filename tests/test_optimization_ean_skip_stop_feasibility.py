from __future__ import annotations

import pytest

from ropeway_skip_stop_optimization.examples.three_station import ThreeStationExample
from ropeway_skip_stop_optimization.optimization.ean import (
    EanFormulationConfig,
    EanHorizonFormulation,
    EanOptimizationConfig,
    EanRouteDecision,
    EanSkipStopFeasibilityConfig,
    EanStopSkipTimingFormulation,
    EanTimeBoundFormulation,
    solve_ean_skip_stop_feasibility,
    validate_ean_movement_plan_against_artifact,
)


@pytest.mark.parametrize(
    "timing_formulation",
    (
        EanStopSkipTimingFormulation.BIG_M,
        EanStopSkipTimingFormulation.AFFINE,
    ),
)
def test_ean_skip_stop_feasibility_finds_valid_three_station_plan(
    timing_formulation: EanStopSkipTimingFormulation,
) -> None:
    pytest.importorskip("gurobipy")
    example = ThreeStationExample()
    scenario = example.build_scenario()
    config = example.build_ean_config(scenario)
    artifact = example.build_ean_artifact_builder(scenario, config).build(scenario, config)

    result = solve_ean_skip_stop_feasibility(
        artifact,
        EanSkipStopFeasibilityConfig(
            optimization_config=EanOptimizationConfig(
                formulation=EanFormulationConfig(
                    stop_skip_timing=timing_formulation,
                )
            )
        ),
    )

    assert result.metadata.status == "optimal"
    assert result.movement_plan is not None
    validate_ean_movement_plan_against_artifact(artifact, result.movement_plan).raise_for_errors()
    assert len(result.movement_plan.trajectories) == len(artifact.cabin_starts)
    assert result.metadata.skipped_visit_count > 0
    assert {
        visit.decision
        for trajectory in result.movement_plan.trajectories
        for visit in trajectory.visits
    } <= {EanRouteDecision.STOP, EanRouteDecision.SKIP}


@pytest.mark.parametrize(
    "timing_formulation",
    (
        EanStopSkipTimingFormulation.BIG_M,
        EanStopSkipTimingFormulation.AFFINE,
    ),
)
def test_exact_horizon_activation_extracts_valid_three_station_prefixes(
    timing_formulation: EanStopSkipTimingFormulation,
) -> None:
    pytest.importorskip("gurobipy")
    example = ThreeStationExample()
    scenario = example.build_scenario()
    config = example.build_ean_config(scenario)
    artifact = example.build_ean_artifact_builder(scenario, config).build(
        scenario,
        config,
    )

    result = solve_ean_skip_stop_feasibility(
        artifact,
        EanSkipStopFeasibilityConfig(
            optimization_config=EanOptimizationConfig(
                formulation=EanFormulationConfig(
                    horizon=EanHorizonFormulation.EXACT_TIME_ACTIVATION,
                    time_bounds=EanTimeBoundFormulation.DERIVED_VISIT_BOUNDS,
                    stop_skip_timing=timing_formulation,
                )
            )
        ),
    )

    assert result.metadata.status == "optimal"
    assert result.movement_plan is not None
    assert sum(
        len(trajectory.visits)
        for trajectory in result.movement_plan.trajectories
    ) < len(artifact.switch_visits)
    validate_ean_movement_plan_against_artifact(
        artifact,
        result.movement_plan,
        tolerance_seconds=1e-5,
    ).raise_for_errors()
