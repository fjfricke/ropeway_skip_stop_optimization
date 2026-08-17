from dataclasses import replace
import json

import pytest

from ropeway_skip_stop_optimization.benchmarking.ddd_scaling import (
    build_initial_ddd_network_problem,
)
from ropeway_skip_stop_optimization.examples.registry import get_example
from ropeway_skip_stop_optimization.exports.ddd_root_cg import (
    export_ddd_root_cg_checkpoint_to_frontend,
)
from ropeway_skip_stop_optimization.optimization.ddd import (
    DddTrajectoryExactRootColumnGenerationSolver,
    EanArtifactToDddMovementProblemAdapter,
    read_ddd_trajectory_root_cg_checkpoint,
    write_ddd_trajectory_root_cg_checkpoint,
)
from ropeway_skip_stop_optimization.optimization.ean import (
    EanPassengerCandidateBuilder,
    EanPassengerObjective,
    NetworkEanBuildArtifactBuilder,
    SparseHeadwayPairBuilder,
)


def test_ddd_root_checkpoint_frontend_export_recovers_legacy_passenger_values(
    tmp_path,
) -> None:
    example_id = "three_station_half_no_skip_no_wait_v0"
    example = get_example(example_id)
    scenario = example.build_scenario()
    config = example.build_ean_config(scenario)
    base_builder = example.build_ean_artifact_builder(scenario, config)
    assert isinstance(base_builder, NetworkEanBuildArtifactBuilder)
    artifact = replace(
        base_builder,
        headway_pair_builder=SparseHeadwayPairBuilder(),
    ).build(scenario, config)
    movement = EanArtifactToDddMovementProblemAdapter().build(artifact)
    problem = build_initial_ddd_network_problem(movement)
    passenger_build = EanPassengerCandidateBuilder().build(scenario, artifact)
    states = []
    result = DddTrajectoryExactRootColumnGenerationSolver(
        max_iterations=5,
        pricing_time_limit_seconds=5.0,
    ).solve(
        problem=problem,
        artifact=artifact,
        passenger_build=passenger_build,
        objective=EanPassengerObjective.JOURNEY_TIME,
        checkpoint_callback=states.append,
    )
    assert result.root_lp_certified
    assert states[-1].incumbent_ride_values_by_id

    checkpoint_path = tmp_path / "legacy.checkpoint.json"
    write_ddd_trajectory_root_cg_checkpoint(
        checkpoint_path,
        replace(states[-1], incumbent_ride_values_by_id={}),
    )
    output_root = tmp_path / "frontend"
    exported = export_ddd_root_cg_checkpoint_to_frontend(
        example_id=example_id,
        checkpoint_path=checkpoint_path,
        output_root=output_root,
    )
    assert exported.passenger_assignment_recovered
    restored = read_ddd_trajectory_root_cg_checkpoint(checkpoint_path)
    assert restored.incumbent_ride_values_by_id
    assert exported.objective_value_seconds == pytest.approx(result.best_upper_bound)

    repeated = export_ddd_root_cg_checkpoint_to_frontend(
        example_id=example_id,
        checkpoint_path=checkpoint_path,
        output_root=output_root,
    )
    assert not repeated.passenger_assignment_recovered
    manifest = json.loads(repeated.manifest_path.read_text(encoding="utf-8"))
    variant = next(
        variant
        for family in manifest["families"]
        for variant in family["variants"]
        if variant["example_id"] == example_id
    )
    assert variant["default_artifact_set"] == "ddd_root_cg_journey_time"
    result_path = output_root / example_id / "ddd_root_cg_journey_time.json"
    payload = json.loads(result_path.read_text(encoding="utf-8"))
    assert payload["metadata"]["root_lp_certified"] is True
    assert payload["metadata"]["mip_gap"] == pytest.approx(result.relative_gap)
    assert payload["passenger_plan"]["served_rides"]
