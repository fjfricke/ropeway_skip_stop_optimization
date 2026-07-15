from __future__ import annotations

from pathlib import Path

import pytest

from ropeway_skip_stop_optimization.examples.three_station import ThreeStationExample
from ropeway_skip_stop_optimization.optimization.ean import (
    EanFormulationConfig,
    EanHorizonFormulation,
    EanMovementFeasibilityProblem,
    EanOptimizationConfig,
    EanOptimizationProblemKind,
    EanOptimizer,
    EanRouteDecision,
    EanSolveConfig,
    EanStopSkipTimingFormulation,
    EanTimeBoundFormulation,
    GurobiCheckpointConfig,
    validate_ean_movement_plan_against_artifact,
)
from ropeway_skip_stop_optimization.optimization.solver_progress import (
    GurobiMipProgressRecorder,
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

    result = EanOptimizer(
        EanSolveConfig(
            optimization_config=EanOptimizationConfig(
                formulation=EanFormulationConfig(
                    stop_skip_timing=timing_formulation,
                )
            )
        )
    ).solve(EanMovementFeasibilityProblem(artifact))

    assert result.metadata.status == "optimal"
    assert result.problem_kind is EanOptimizationProblemKind.MOVEMENT_FEASIBILITY
    assert result.metadata.objective_kind is None
    assert result.metadata.demand_group_count is None
    assert result.movement_plan is not None
    assert result.passenger_plan is None
    validate_ean_movement_plan_against_artifact(artifact, result.movement_plan).raise_for_errors()
    assert len(result.movement_plan.trajectories) == len(artifact.cabin_starts)
    assert result.metadata.skipped_visit_count > 0
    assert {
        visit.decision
        for trajectory in result.movement_plan.trajectories
        for visit in trajectory.visits
    } <= {EanRouteDecision.STOP, EanRouteDecision.SKIP}


def test_movement_feasibility_supports_tight_bounds_progress_and_checkpoints(
    tmp_path: Path,
) -> None:
    pytest.importorskip("gurobipy")
    example = ThreeStationExample()
    scenario = example.build_scenario()
    config = example.build_ean_config(scenario)
    artifact = example.build_ean_artifact_builder(scenario, config).build(
        scenario,
        config,
    )
    checkpoint_path = tmp_path / "movement.sol"
    recorder = GurobiMipProgressRecorder()
    optimization_config = EanOptimizationConfig(
        enable_tight_big_m_bounds=True
    )

    result = EanOptimizer(
        EanSolveConfig(
            optimization_config=optimization_config,
            checkpoint=GurobiCheckpointConfig(
                final_solution_path=checkpoint_path
            ),
            progress_recorder=recorder,
        )
    ).solve(EanMovementFeasibilityProblem(artifact))

    assert result.metadata.status == "optimal"
    assert result.metadata.optimization_config.enable_tight_big_m_bounds
    assert result.metadata.progress_samples
    assert result.metadata.progress_samples[-1].event == "final"
    assert checkpoint_path.is_file()

    resumed = EanOptimizer(
        EanSolveConfig(
            optimization_config=optimization_config,
            checkpoint=GurobiCheckpointConfig(
                read_solution_path=checkpoint_path
            ),
        )
    ).solve(EanMovementFeasibilityProblem(artifact))

    assert resumed.metadata.status == "optimal"
    assert resumed.metadata.checkpoint_read_path == checkpoint_path.as_posix()
    assert resumed.movement_plan is not None


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

    result = EanOptimizer(
        EanSolveConfig(
            optimization_config=EanOptimizationConfig(
                formulation=EanFormulationConfig(
                    horizon=EanHorizonFormulation.EXACT_TIME_ACTIVATION,
                    time_bounds=EanTimeBoundFormulation.DERIVED_VISIT_BOUNDS,
                    stop_skip_timing=timing_formulation,
                )
            )
        )
    ).solve(EanMovementFeasibilityProblem(artifact))

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
