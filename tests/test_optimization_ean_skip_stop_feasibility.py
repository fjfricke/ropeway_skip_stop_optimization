from __future__ import annotations

from pathlib import Path

import pytest

from ropeway_skip_stop_optimization.examples.three_station import ThreeStationExample
from ropeway_skip_stop_optimization.optimization.ean import (
    EanBuildProgressKind,
    EanBuildStage,
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
from ropeway_skip_stop_optimization.optimization.ean.optimizers import solver as solver_module
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


def test_build_only_materializes_model_without_calling_optimize(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("gurobipy")
    example = ThreeStationExample()
    scenario = example.build_scenario()
    config = example.build_ean_config(scenario)
    artifact = example.build_ean_artifact_builder(scenario, config).build(
        scenario,
        config,
    )
    events = []

    def fail_optimize(**_kwargs):
        raise AssertionError("build-only mode called optimize")

    monkeypatch.setattr(solver_module, "_optimize", fail_optimize)
    result = EanOptimizer(
        EanSolveConfig(
            build_only=True,
            build_progress_callback=events.append,
        )
    ).solve(EanMovementFeasibilityProblem(artifact))

    assert result.metadata.status == "build_only"
    assert result.metadata.solver_status == "NOT_STARTED"
    assert result.metadata.runtime_seconds is None
    assert result.movement_plan is None
    assert result.metadata.variable_count > 0
    assert result.metadata.constraint_count > 0
    assert result.metadata.build_metrics.artifact == artifact.build_metrics
    assert result.metadata.build_metrics.headway_constraints_seconds > 0
    assert {
        event.stage
        for event in events
        if event.kind is EanBuildProgressKind.FINISHED
    } >= {
        EanBuildStage.MOVEMENT_VARIABLES,
        EanBuildStage.HEADWAY_CONSTRAINTS,
        EanBuildStage.FINAL_MODEL_UPDATE,
    }


def test_fixed_start_headway_precedence_reduces_three_station_model() -> None:
    pytest.importorskip("gurobipy")
    example = ThreeStationExample()
    scenario = example.build_scenario()
    config = example.build_ean_config(scenario)
    artifact = example.build_ean_artifact_builder(scenario, config).build(
        scenario,
        config,
    )

    legacy = EanOptimizer(EanSolveConfig(build_only=True)).solve(
        EanMovementFeasibilityProblem(artifact)
    )
    classified = EanOptimizer(
        EanSolveConfig(
            optimization_config=EanOptimizationConfig(
                enable_fixed_start_headway_precedence=True
            ),
        )
    ).solve(EanMovementFeasibilityProblem(artifact))

    assert legacy.metadata.headway_order_variable_count == len(
        artifact.headway_pairs
    )
    assert classified.metadata.build_metrics.fixed_headway_pair_count > 0
    assert classified.metadata.build_metrics.redundant_headway_pair_count == 0
    assert (
        classified.metadata.build_metrics.disjunctive_headway_pair_count
        + classified.metadata.build_metrics.fixed_headway_pair_count
        == len(artifact.headway_pairs)
    )
    assert classified.metadata.headway_order_variable_count < (
        legacy.metadata.headway_order_variable_count
    )
    assert classified.metadata.constraint_count < legacy.metadata.constraint_count
    assert classified.metadata.status == "optimal"
    assert classified.movement_plan is not None
    validate_ean_movement_plan_against_artifact(
        artifact,
        classified.movement_plan,
    ).raise_for_errors()


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
