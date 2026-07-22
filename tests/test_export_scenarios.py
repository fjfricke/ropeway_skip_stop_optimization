from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from ropeway_skip_stop_optimization.examples.base import ScenarioExample, ScenarioExampleMetadata
from ropeway_skip_stop_optimization.examples.registry import get_example
from ropeway_skip_stop_optimization.examples.three_station import (
    ThreeStationExample,
    ThreeStationOptimizedInitialPlacementExample,
    build_three_station_scenario,
)
from ropeway_skip_stop_optimization.examples.three_station_ean import (
    build_three_station_ean_config,
)
from ropeway_skip_stop_optimization.exports.artifacts import (
    ArtifactSet,
    DiscreteScenarioArtifactBuilder,
    ExportContext,
    PhysicalScenarioArtifactBuilder,
)
from ropeway_skip_stop_optimization.exports.json_codec import to_jsonable
from ropeway_skip_stop_optimization.exports.runner import build_artifact_set, export_artifact_set
from ropeway_skip_stop_optimization.exports.runner import _latest_ean_checkpoint_path
from ropeway_skip_stop_optimization.exports.runner import run_artifact_set
from ropeway_skip_stop_optimization.exports.manifest import load_manifest
from ropeway_skip_stop_optimization.optimization.discrete_time import MilpV0VariableStrategy
from ropeway_skip_stop_optimization.optimization.ean import (
    DeterministicPhysicalNodeToSwitchStartBuilder,
    EanConfig,
    EanFleetMode,
    EanMipStartStrategy,
    EanModelBuildMetrics,
    EanOptimizationMetadata,
    EanOptimizationProblemKind,
    EanOptimizationConfig,
    EanOptimizationResult,
    EanPassengerObjective,
    GurobiSolverPolicy,
    RingEanBuildArtifactBuilder,
    StationEanConfig,
    StationWaitingMode,
)
from ropeway_skip_stop_optimization.progress import ProgressReporter


def test_json_codec_sorts_sets_deterministically() -> None:
    assert to_jsonable(frozenset(("z", "a", "m"))) == ["a", "m", "z"]


def test_ean_build_only_exports_profile_without_solution_artifacts(
    tmp_path: Path,
) -> None:
    pytest.importorskip("gurobipy")

    result = export_artifact_set(
        example_id="three_station_v0",
        artifact_set_id="ean_passenger_journey_time",
        output_root=tmp_path,
        ean_build_only=True,
    )

    profile_path = tmp_path / "three_station_v0" / "ean_model_build_profile.json"
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    assert result.artifact_set_id == "ean_passenger_journey_time_build_only"
    assert profile_path in result.artifact_paths
    assert profile["status"] == "build_only"
    assert profile["model"]["variable_count"] > 0
    assert profile["model"]["constraint_count"] > 0
    assert profile["model"]["build_metrics"]["headway_constraints_seconds"] > 0
    assert profile["artifact"]["build_metrics"]["pair_count"] > 0
    assert profile["serialization_seconds_by_path"]
    assert not (
        tmp_path
        / "three_station_v0"
        / "ean_passenger_service_journey_time_movement_plan.json"
    ).exists()


def test_exports_greedy_all_stop_manifest_and_movement_plan_json(tmp_path: Path) -> None:
    result = export_artifact_set(output_root=tmp_path, artifact_set_id="greedy_all_stop")
    output_path = tmp_path / "three_station_v0" / "greedy_all_stop_movement_plan.json"
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))

    assert output_path in result.artifact_paths
    variant = _manifest_variant(manifest, "three_station_ring", "half_cabins_skip_wait")
    assert variant["default_artifact_set"] == "greedy_all_stop"
    artifact_set = _manifest_artifact_set(
        manifest,
        "three_station_ring",
        "half_cabins_skip_wait",
        "greedy_all_stop",
    )
    assert artifact_set["backend"] == "discrete"
    assert artifact_set["artifacts"]["movement_plan"] == (
        "three_station_v0/greedy_all_stop_movement_plan.json"
    )
    assert payload["discrete_scenario_id"] == "three_station_v0__dt_0p5"
    assert payload["horizon_steps"] == 2400
    assert len(payload["trajectories"]) == 28
    assert len(payload["trajectories"][0]["positions"]) == 2401
    assert payload["paths"][0]["id"] == "all_stop_cycle"
    assert "M_lr_skip_bypass" not in payload["paths"][0]["source_segment_ids"]
    assert "M_rl_skip_bypass" not in payload["paths"][0]["source_segment_ids"]


def test_exports_greedy_all_stop_passenger_replay_json(tmp_path: Path) -> None:
    export_artifact_set(output_root=tmp_path, artifact_set_id="greedy_all_stop")
    output_path = tmp_path / "three_station_v0" / "greedy_all_stop_passenger_replay.json"
    payload = json.loads(output_path.read_text(encoding="utf-8"))

    assert payload["discrete_scenario_id"] == "three_station_v0__dt_0p5"
    assert payload["movement_plan_horizon_steps"] == 2400
    assert payload["boarding_policy"] == "greedy_fifo_next_compatible_cabin"
    assert payload["summary"]["arrived_passengers"] == 3480
    assert payload["summary"]["boarded_passengers"] == 3464
    assert payload["summary"]["served_passengers"] == 3464
    assert payload["summary"]["unserved_passengers"] == 16
    assert len(payload["steps"]) == 2401
    assert payload["steps"][0]["queue_states"][0]["waiting_count"] == 580
    assert payload["boarding_events"][0]["station_id"] == "M"
    assert payload["boarding_events"][0]["destination"] == "R"
    assert payload["boarding_events"][0]["count"] == 8
    assert payload["final_queue_states"] == [
        {"destination": "R", "station_id": "L", "time_step": 2400, "waiting_count": 16}
    ]


def test_exports_greedy_all_stop_replay_metrics_json(tmp_path: Path) -> None:
    export_artifact_set(output_root=tmp_path, artifact_set_id="greedy_all_stop")
    output_path = tmp_path / "three_station_v0" / "greedy_all_stop_replay_metrics.json"
    payload = json.loads(output_path.read_text(encoding="utf-8"))

    assert payload["discrete_scenario_id"] == "three_station_v0__dt_0p5"
    assert payload["movement_plan_horizon_steps"] == 2400
    assert payload["delta_seconds"] == 0.5
    assert len(payload["steps"]) == 2401
    assert payload["steps"][0]["arrivals_count"] == 3480
    assert payload["steps"][0]["waiting_count"] == 3472
    assert payload["steps"][0]["cumulative_waiting_passenger_hours"] == pytest.approx(0.4822222222222222)
    assert payload["steps"][0]["waiting_by_station"] == [
        {"count": 1160, "station_id": "L"},
        {"count": 1152, "station_id": "M"},
        {"count": 1160, "station_id": "R"},
    ]
    assert payload["steps"][6]["boarding_count"] == 8
    assert payload["steps"][6]["onboard_count"] == 24
    assert payload["steps"][-1]["waiting_count"] == 16
    assert payload["steps"][-1]["onboard_count"] == 0


def test_exports_ean_all_stop_baseline_json(tmp_path: Path) -> None:
    result = export_artifact_set(output_root=tmp_path, artifact_set_id="ean_all_stop_baseline")
    artifact_path = tmp_path / "three_station_v0" / "ean_build_artifact.json"
    plan_path = tmp_path / "three_station_v0" / "ean_all_stop_movement_plan.json"
    replay_path = tmp_path / "three_station_v0" / "ean_physical_replay.json"
    artifact_payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    plan_payload = json.loads(plan_path.read_text(encoding="utf-8"))
    replay_payload = json.loads(replay_path.read_text(encoding="utf-8"))
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))

    assert artifact_path in result.artifact_paths
    assert plan_path in result.artifact_paths
    assert replay_path in result.artifact_paths
    artifact_set = _manifest_artifact_set(
        manifest,
        "three_station_ring",
        "half_cabins_skip_wait",
        "ean_all_stop_baseline",
    )
    assert artifact_set["backend"] == "ean"
    assert artifact_set["artifacts"] == {
        "scenario": "three_station_v0/scenario.json",
        "ean_input": "three_station_v0/ean_build_artifact.json",
        "ean_result": "three_station_v0/ean_all_stop_movement_plan.json",
        "ean_replay": "three_station_v0/ean_physical_replay.json",
    }

    timings_by_switch = {timing["switch_id"]: timing for timing in artifact_payload["timings"]}
    assert artifact_payload["scenario_id"] == "three_station_v0"
    assert len(artifact_payload["cabin_starts"]) == 15
    assert len(timings_by_switch) == 4
    assert timings_by_switch["M_entry_lr"]["skip_allowed"] is True
    assert timings_by_switch["M_entry_rl"]["skip_allowed"] is True
    assert timings_by_switch["L_entry_rl"]["skip_allowed"] is False
    assert timings_by_switch["R_entry_lr"]["skip_allowed"] is False

    assert plan_payload["scenario_id"] == "three_station_v0"
    assert len(plan_payload["trajectories"]) == 15
    assert {
        visit["decision"]
        for trajectory in plan_payload["trajectories"]
        for visit in trajectory["visits"]
    } == {"stop"}
    assert replay_payload["scenario_id"] == "three_station_v0"
    assert replay_payload["events"]
    assert len({event["cabin_id"] for event in replay_payload["events"]}) == 15
    assert replay_payload["events"][0]["physical_node_id"] in timings_by_switch


def test_exports_ean_skip_stop_feasibility_json(tmp_path: Path) -> None:
    pytest.importorskip("gurobipy")
    result = run_artifact_set(
        _TinyThreeStationSkipNoWaitEanExample(),
        build_artifact_set("ean_skip_stop_feasibility"),
        output_root=tmp_path,
        progress=ProgressReporter(enabled=False),
    )
    plan_path = tmp_path / "three_station_skip_no_wait_test" / "ean_skip_stop_movement_plan.json"
    replay_path = tmp_path / "three_station_skip_no_wait_test" / "ean_skip_stop_physical_replay.json"
    plan_payload = json.loads(plan_path.read_text(encoding="utf-8"))
    replay_payload = json.loads(replay_path.read_text(encoding="utf-8"))
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))

    artifact_set = _manifest_artifact_set(
        manifest,
        "three_station_ring",
        "skip_no_wait_test",
        "ean_skip_stop_feasibility",
    )
    assert artifact_set["artifacts"] == {
        "scenario": "three_station_skip_no_wait_test/scenario.json",
        "ean_input": "three_station_skip_no_wait_test/ean_build_artifact.json",
        "ean_result": "three_station_skip_no_wait_test/ean_skip_stop_movement_plan.json",
        "ean_replay": "three_station_skip_no_wait_test/ean_skip_stop_physical_replay.json",
    }
    decisions = {
        visit["decision"]
        for trajectory in plan_payload["trajectories"]
        for visit in trajectory["visits"]
    }
    assert decisions == {"skip", "stop"}
    assert len(plan_payload["trajectories"]) == 4
    assert replay_payload["events"]


def test_exports_initial_placement_tail_passenger_result_without_fixed_start_mip_start(
    tmp_path: Path,
) -> None:
    pytest.importorskip("gurobipy")

    result = run_artifact_set(
        _TinyThreeStationInitialPlacementTailExample(),
        build_artifact_set("ean_passenger_waiting_time"),
        output_root=tmp_path,
        ean_solver_policy=GurobiSolverPolicy(time_limit_seconds=10.0),
        ean_mip_start_strategy=EanMipStartStrategy.OPTIMIZED_ALL_STOP,
        progress=ProgressReporter(enabled=False),
    )

    result_path = (
        tmp_path
        / "three_station_initial_placement_tail_test"
        / "ean_passenger_service_waiting_time.json"
    )
    replay_path = (
        tmp_path
        / "three_station_initial_placement_tail_test"
        / "ean_passenger_service_physical_replay.json"
    )
    payload = json.loads(result_path.read_text(encoding="utf-8"))
    replay_payload = json.loads(replay_path.read_text(encoding="utf-8"))

    assert result_path in result.artifact_paths
    assert payload["movement_plan"]["model_end_seconds"] == 1500.0
    assert payload["fleet_plan"]["mode"] == EanFleetMode.OPTIMIZED_INITIAL_PLACEMENT.value
    assert payload["fleet_plan"]["available_fleet_count"] == 4
    assert len(payload["fleet_plan"]["initial_states"]) == 1
    assert sum(payload["passenger_plan"]["unserved_counts_by_demand_group_id"].values()) == 0
    assert replay_payload["model_end_seconds"] == 1500.0


def test_export_context_auto_injects_per_objective_ean_progress_recorders(monkeypatch: pytest.MonkeyPatch) -> None:
    captured_recorders: dict[EanPassengerObjective, object] = {}

    def fake_solve(self: object, problem: object) -> EanOptimizationResult:
        objective = problem.objective
        captured_recorders[objective] = self.config.progress_recorder
        return _fake_ean_passenger_service_result(objective)

    monkeypatch.setattr(
        "ropeway_skip_stop_optimization.exports.artifacts.EanOptimizer.solve",
        fake_solve,
    )
    context = ExportContext(
        example=ThreeStationExample(),
        progress=ProgressReporter(enabled=False),
    )
    context._scenario = build_three_station_scenario()
    context._ean_artifact = SimpleNamespace(fleet_mode=EanFleetMode.FIXED_STARTS)

    context.ean_passenger_service_result(EanPassengerObjective.WAITING_TIME)
    context.ean_passenger_service_result(EanPassengerObjective.JOURNEY_TIME)

    assert captured_recorders[EanPassengerObjective.WAITING_TIME] is not None
    assert captured_recorders[EanPassengerObjective.JOURNEY_TIME] is not None
    assert (
        captured_recorders[EanPassengerObjective.WAITING_TIME]
        is not captured_recorders[EanPassengerObjective.JOURNEY_TIME]
    )


def test_unified_passenger_metadata_adapter_preserves_export_contract() -> None:
    result = _fake_ean_passenger_service_result(
        EanPassengerObjective.JOURNEY_TIME
    )

    assert set(result.metadata.passenger_export_dict()) == {
        "status",
        "solver_status",
        "objective_kind",
        "objective_value_seconds",
        "objective_passenger_hours",
        "best_bound",
        "mip_gap",
        "runtime_seconds",
        "node_count",
        "solution_count",
        "mip_gap_target",
        "time_limit_seconds",
        "demand_group_count",
        "ride_candidate_count",
        "slot_variable_count",
        "served_passenger_count",
        "unserved_passenger_count",
        "variable_count",
        "constraint_count",
        "model_nonzero_count",
        "model_setup_runtime_seconds",
        "skipped_visit_count",
        "visible_skipped_visit_count",
        "checkpoint_read_path",
        "checkpoint_solution_file_prefix",
        "checkpoint_final_solution_path",
        "resolved_mip_start_strategy",
        "mip_start_active_cabin_count",
        "mip_start_unserved_passenger_count",
        "mip_start_passenger_objective_seconds",
        "mip_start_generation_seconds",
        "optimization_config",
        "progress_samples",
    }


def test_discrete_export_requires_discrete_example_capability(tmp_path: Path) -> None:
    artifact_set = ArtifactSet(
        id="discrete_only",
        label="Discrete only",
        builders=(DiscreteScenarioArtifactBuilder(),),
    )

    with pytest.raises(ValueError, match="does not support discrete exports"):
        run_artifact_set(
            _PhysicalOnlyExample(),
            artifact_set,
            output_root=tmp_path,
            progress=ProgressReporter(enabled=False),
        )


def test_manifest_merges_new_variant_without_rebuilding_family(tmp_path: Path) -> None:
    run_artifact_set(
        _ManifestVariantExample("manifest_variant_a", "variant_a", "Variant A"),
        _physical_artifact_set("physical_one"),
        output_root=tmp_path,
        progress=ProgressReporter(enabled=False),
    )
    result = run_artifact_set(
        _ManifestVariantExample("manifest_variant_b", "variant_b", "Variant B"),
        _physical_artifact_set("physical_one"),
        output_root=tmp_path,
        progress=ProgressReporter(enabled=False),
    )
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))

    family = _manifest_family(manifest, "manifest_family")
    assert {variant["id"] for variant in family["variants"]} == {"variant_a", "variant_b"}
    assert _manifest_variant(manifest, "manifest_family", "variant_a")["example_id"] == "manifest_variant_a"
    assert _manifest_variant(manifest, "manifest_family", "variant_b")["example_id"] == "manifest_variant_b"


def test_manifest_clean_removes_only_selected_variant_artifact_sets(tmp_path: Path) -> None:
    variant_a = _ManifestVariantExample("manifest_variant_a", "variant_a", "Variant A")
    variant_b = _ManifestVariantExample("manifest_variant_b", "variant_b", "Variant B")
    run_artifact_set(
        variant_a,
        _physical_artifact_set("physical_one"),
        output_root=tmp_path,
        progress=ProgressReporter(enabled=False),
    )
    run_artifact_set(
        variant_a,
        _physical_artifact_set("physical_two"),
        output_root=tmp_path,
        progress=ProgressReporter(enabled=False),
    )
    run_artifact_set(
        variant_b,
        _physical_artifact_set("physical_one"),
        output_root=tmp_path,
        progress=ProgressReporter(enabled=False),
    )

    result = run_artifact_set(
        variant_a,
        _physical_artifact_set("physical_one"),
        output_root=tmp_path,
        progress=ProgressReporter(enabled=False),
        clean=True,
    )
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))

    selected = _manifest_variant(manifest, "manifest_family", "variant_a")
    sibling = _manifest_variant(manifest, "manifest_family", "variant_b")
    assert {artifact_set["id"] for artifact_set in selected["artifact_sets"]} == {"physical_one"}
    assert {artifact_set["id"] for artifact_set in sibling["artifact_sets"]} == {"physical_one"}


def test_legacy_three_station_no_skip_manifest_maps_to_full_cabins_variant(tmp_path: Path) -> None:
    (tmp_path / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "generated_at": None,
                "examples": [
                    {
                        "id": "three_station_no_skip_no_wait_v0",
                        "label": "Three station ring no_skip+no_wait",
                        "description": "",
                        "tags": [],
                        "default_artifact_set": "physical_only",
                        "artifact_sets": [
                            {
                                "id": "physical_only",
                                "label": "Physical scenario",
                                "artifacts": {"scenario": "three_station_no_skip_no_wait_v0/scenario.json"},
                            }
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    manifest = load_manifest(tmp_path)

    variant = _manifest_variant(manifest, "three_station_ring", "full_cabins_no_skip_no_wait")
    assert variant["example_id"] == "three_station_no_skip_no_wait_v0"


def test_latest_ean_checkpoint_uses_selected_example_and_artifact_set(tmp_path: Path) -> None:
    older = tmp_path / "three_station_v0__ean_passenger_journey_time__incumbent_0.sol"
    newer = tmp_path / "three_station_v0__ean_passenger_journey_time__incumbent.final.sol"
    other = tmp_path / "three_station_v0__ean_passenger_waiting_time__incumbent_9.sol"
    older.write_text("old", encoding="utf-8")
    newer.write_text("new", encoding="utf-8")
    other.write_text("other", encoding="utf-8")
    os.utime(older, (1, 1))
    os.utime(newer, (2, 2))
    os.utime(other, (3, 3))

    assert _latest_ean_checkpoint_path(
        tmp_path,
        example_id="three_station_v0",
        artifact_set_id="ean_passenger_journey_time",
    ) == newer


def test_three_station_family_exports_three_named_variants(tmp_path: Path) -> None:
    for example_id in (
        "three_station_full_no_skip_no_wait_v0",
        "three_station_half_no_skip_no_wait_v0",
        "three_station_v0",
    ):
        result = run_artifact_set(
            get_example(example_id),
            build_artifact_set("physical_only"),
            output_root=tmp_path,
            progress=ProgressReporter(enabled=False),
        )

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    family = _manifest_family(manifest, "three_station_ring")

    assert {variant["id"] for variant in family["variants"]} == {
        "full_cabins_no_skip_no_wait",
        "half_cabins_no_skip_no_wait",
        "half_cabins_skip_wait",
    }


def test_exports_milp_v0_movement_plan_json(tmp_path: Path) -> None:
    pytest.importorskip("gurobipy")

    export_artifact_set(
        output_root=tmp_path,
        artifact_set_id="milp_v0_feasibility",
        milp_horizon_steps=2,
        milp_cabin_count=2,
    )
    output_path = tmp_path / "three_station_v0" / "milp_v0_dense_movement_plan_c2_h2.json"
    payload = json.loads(output_path.read_text(encoding="utf-8"))

    assert payload["movement_plan"]["discrete_scenario_id"] == "three_station_v0__dt_0p5"
    assert payload["movement_plan"]["horizon_steps"] == 2
    assert len(payload["movement_plan"]["trajectories"]) == 2
    assert len(payload["movement_plan"]["trajectories"][0]["positions"]) == 3
    assert payload["metadata"]["status"] == "optimal"
    assert len(payload["metadata"]["selected_arc_ids_by_cabin"]["0"]) == 2


def test_exports_sparse_milp_v0_movement_plan_json(tmp_path: Path) -> None:
    pytest.importorskip("gurobipy")

    export_artifact_set(
        output_root=tmp_path,
        artifact_set_id="milp_v0_feasibility",
        milp_horizon_steps=2,
        milp_cabin_count=2,
        milp_variable_strategy=MilpV0VariableStrategy.SPARSE_REACHABILITY,
    )
    output_path = tmp_path / "three_station_v0" / "milp_v0_sparse_movement_plan_c2_h2.json"
    payload = json.loads(output_path.read_text(encoding="utf-8"))

    assert payload["movement_plan"]["discrete_scenario_id"] == "three_station_v0__dt_0p5"
    assert payload["movement_plan"]["horizon_steps"] == 2
    assert len(payload["movement_plan"]["trajectories"]) == 2
    assert payload["metadata"]["status"] == "optimal"
    assert payload["metadata"]["variable_count"] < 2 * 3 * 406 + 2 * 2 * 410


def test_exports_sparse_milp_v1_passenger_waiting_plan_json(tmp_path: Path) -> None:
    pytest.importorskip("gurobipy")

    export_artifact_set(
        output_root=tmp_path,
        artifact_set_id="milp_v1_passenger_feasibility",
        milp_horizon_steps=2,
        milp_cabin_count=2,
        milp_variable_strategy=MilpV0VariableStrategy.SPARSE_REACHABILITY,
    )
    output_path = tmp_path / "three_station_v0" / "milp_v1_passenger_waiting_feasibility_sparse_movement_plan_c2_h2.json"
    payload = json.loads(output_path.read_text(encoding="utf-8"))

    assert payload["movement_plan"]["discrete_scenario_id"] == "three_station_v0__dt_0p5"
    assert payload["movement_plan"]["horizon_steps"] == 2
    assert payload["metadata"]["status"] == "optimal"
    assert payload["metadata"]["passenger_variable_count"] > 0
    assert payload["metadata"]["total_onboard_at_horizon"] == 0


def test_cli_can_export_milp_v1_passenger_mode_without_milp_v0(tmp_path: Path) -> None:
    pytest.importorskip("gurobipy")

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ropeway_skip_stop_optimization.exports.cli",
            "--output-root",
            str(tmp_path),
            "--artifact-set",
            "milp_v1_passenger_feasibility",
            "--milp-horizon",
            "2",
            "--milp-cabin-count",
            "2",
            "--milp-variable-strategy",
            MilpV0VariableStrategy.SPARSE_REACHABILITY.value,
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    output_names = {line.rsplit("/", 1)[-1] for line in result.stdout.splitlines()}
    assert "milp_v1_passenger_waiting_feasibility_sparse_movement_plan_c2_h2.json" in output_names
    assert "milp_v0_sparse_movement_plan_c2_h2.json" not in output_names
    assert not (tmp_path / "three_station_v0" / "milp_v0_sparse_movement_plan_c2_h2.json").exists()


def test_cli_help_includes_ean_optimization_selection() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ropeway_skip_stop_optimization.exports.cli",
            "--help",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert "--ean-optimizations" in result.stdout
    assert "tight_big_m_bounds" in result.stdout
    assert "slot_activation_first_slot" in result.stdout
    assert "board_time_projected_journey_time" in result.stdout


def test_cli_can_export_milp_v1_waiting_time_objective(tmp_path: Path) -> None:
    pytest.importorskip("gurobipy")

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ropeway_skip_stop_optimization.exports.cli",
            "--output-root",
            str(tmp_path),
            "--artifact-set",
            "milp_v1_waiting_time",
            "--milp-horizon",
            "2",
            "--milp-cabin-count",
            "2",
            "--milp-variable-strategy",
            MilpV0VariableStrategy.SPARSE_REACHABILITY.value,
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    output_names = {line.rsplit("/", 1)[-1] for line in result.stdout.splitlines()}
    assert "milp_v1_passenger_waiting_waiting_time_sparse_movement_plan_c2_h2.json" in output_names


def _manifest_family(manifest: dict, family_id: str) -> dict:
    return next(family for family in manifest["families"] if family["id"] == family_id)


def _manifest_variant(manifest: dict, family_id: str, variant_id: str) -> dict:
    family = _manifest_family(manifest, family_id)
    return next(variant for variant in family["variants"] if variant["id"] == variant_id)


def _manifest_artifact_set(manifest: dict, family_id: str, variant_id: str, artifact_set_id: str) -> dict:
    variant = _manifest_variant(manifest, family_id, variant_id)
    return next(artifact_set for artifact_set in variant["artifact_sets"] if artifact_set["id"] == artifact_set_id)


def _fake_ean_passenger_service_result(objective: EanPassengerObjective) -> EanOptimizationResult:
    return EanOptimizationResult(
        problem_kind=EanOptimizationProblemKind.PASSENGER_SERVICE,
        movement_plan=object(),
        passenger_plan=object(),
        metadata=EanOptimizationMetadata(
            problem_kind=EanOptimizationProblemKind.PASSENGER_SERVICE,
            status="optimal",
            solver_status="OPTIMAL",
            objective_kind=objective,
            objective_value_seconds=1.0,
            objective_passenger_hours=1.0 / 3600.0,
            best_bound=1.0,
            mip_gap=0.0,
            runtime_seconds=0.1,
            node_count=0.0,
            solution_count=1,
            mip_gap_target=0.0,
            time_limit_seconds=None,
            demand_group_count=0,
            ride_candidate_count=0,
            slot_variable_count=0,
            served_passenger_count=0,
            unserved_passenger_count=0,
            variable_count=0,
            constraint_count=0,
            model_nonzero_count=0,
            model_setup_runtime_seconds=0.0,
            movement_variable_count=0,
            movement_constraint_count=0,
            movement_nonzero_count=0,
            headway_pair_count=0,
            headway_order_variable_count=0,
            fixed_movement=False,
            build_metrics=EanModelBuildMetrics(
                passenger_candidate_generation_seconds=0.0,
                movement_model_seconds=0.0,
                movement_fixing_seconds=0.0,
                passenger_model_seconds=0.0,
                mip_start_seconds=0.0,
                mip_start_objective_value_seconds=None,
                gurobi_setup_total_seconds=0.0,
            ),
            solve_phase_metrics=None,
            skipped_visit_count=0,
            visible_skipped_visit_count=0,
            checkpoint_read_path=None,
            checkpoint_solution_file_prefix=None,
            checkpoint_final_solution_path=None,
            optimization_config=EanOptimizationConfig(),
        ),
    )


class _PhysicalOnlyExample(ScenarioExample):
    metadata = ScenarioExampleMetadata(
        id="physical_only_test",
        label="Physical only test",
        description="Test example without discrete export capability.",
    )

    def build_scenario(self):
        return build_three_station_scenario()


class _TinyThreeStationSkipNoWaitEanExample(ThreeStationExample):
    metadata = ScenarioExampleMetadata(
        id="three_station_skip_no_wait_test",
        label="Three station skip/no-wait test",
        description="Small three-station EAN skip/stop solver smoke test with no station waiting.",
        tags=("ring", "skip-stop", "no-waiting", "test"),
        family_id="three_station_ring",
        family_label="Three station ring",
        variant_id="skip_no_wait_test",
        variant_label="Skip/no-wait test",
    )

    def build_scenario(self):
        scenario = build_three_station_scenario()
        return scenario.__class__(id=self.metadata.id, **{key: value for key, value in scenario.__dict__.items() if key != "id"})

    def build_ean_config(self, scenario) -> EanConfig:
        base_config = super().build_ean_config(scenario)
        return EanConfig(
            horizon_seconds=base_config.horizon_seconds,
            tail_seconds=base_config.tail_seconds,
            cabin_capacity=base_config.cabin_capacity,
            station_configs=tuple(
                StationEanConfig(station_id=config.station_id, waiting_mode=StationWaitingMode.NO_WAITING)
                for config in base_config.station_configs
            ),
        )

    def build_ean_artifact_builder(self, scenario, config):
        from ropeway_skip_stop_optimization.examples.three_station_ean import build_three_station_ean_ring_switch_order

        switch_cycle = build_three_station_ean_ring_switch_order(scenario)
        return RingEanBuildArtifactBuilder(
            switch_cycle=switch_cycle,
            start_builder=DeterministicPhysicalNodeToSwitchStartBuilder(),
        )


class _TinyThreeStationInitialPlacementTailExample(
    ThreeStationOptimizedInitialPlacementExample
):
    metadata = ScenarioExampleMetadata(
        id="three_station_initial_placement_tail_test",
        label="Three station initial placement tail test",
        description="Small optimized-initial-placement export test with a certification tail.",
        tags=("ring", "optimized-initial-placement", "tail", "test"),
        family_id="three_station_ring",
        family_label="Three station ring",
        variant_id="initial_placement_tail_test",
        variant_label="Initial placement tail test",
    )

    def build_scenario(self):
        scenario = super().build_scenario()
        return replace(
            scenario,
            id=self.metadata.id,
            demands=(replace(scenario.demands[0], count=1),),
        )

    def build_ean_config(self, scenario) -> EanConfig:
        return build_three_station_ean_config(scenario, tail_seconds=300.0)


class _ManifestVariantExample(ScenarioExample):
    def __init__(self, example_id: str, variant_id: str, variant_label: str) -> None:
        self.metadata = ScenarioExampleMetadata(
            id=example_id,
            label=variant_label,
            description=f"{variant_label} test variant.",
            family_id="manifest_family",
            family_label="Manifest family",
            variant_id=variant_id,
            variant_label=variant_label,
        )

    def build_scenario(self):
        scenario = build_three_station_scenario()
        return scenario.__class__(id=self.metadata.id, **{key: value for key, value in scenario.__dict__.items() if key != "id"})


def _physical_artifact_set(artifact_set_id: str) -> ArtifactSet:
    return ArtifactSet(
        id=artifact_set_id,
        label=artifact_set_id.replace("_", " ").title(),
        builders=(PhysicalScenarioArtifactBuilder(),),
    )
