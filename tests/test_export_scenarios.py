from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from ropeway_skip_stop_optimization.examples.base import ScenarioExample, ScenarioExampleMetadata
from ropeway_skip_stop_optimization.examples.three_station import build_three_station_scenario
from ropeway_skip_stop_optimization.exports.artifacts import ArtifactSet, DiscreteScenarioArtifactBuilder
from ropeway_skip_stop_optimization.exports.runner import export_artifact_set
from ropeway_skip_stop_optimization.exports.runner import run_artifact_set
from ropeway_skip_stop_optimization.optimization.discrete_time import MilpV0VariableStrategy
from ropeway_skip_stop_optimization.progress import ProgressReporter


def test_exports_greedy_all_stop_manifest_and_movement_plan_json(tmp_path: Path) -> None:
    result = export_artifact_set(output_root=tmp_path, artifact_set_id="greedy_all_stop")
    output_path = tmp_path / "three_station_v0" / "greedy_all_stop_movement_plan.json"
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))

    assert output_path in result.artifact_paths
    assert manifest["examples"][0]["default_artifact_set"] == "greedy_all_stop"
    assert manifest["examples"][0]["artifact_sets"][0]["artifacts"]["movement_plan"] == (
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
    artifact_set = _manifest_artifact_set(manifest, "three_station_v0", "ean_all_stop_baseline")
    assert artifact_set["artifacts"] == {
        "scenario": "three_station_v0/scenario.json",
        "ean_input": "three_station_v0/ean_build_artifact.json",
        "ean_result": "three_station_v0/ean_all_stop_movement_plan.json",
        "ean_replay": "three_station_v0/ean_physical_replay.json",
    }

    timings_by_switch = {timing["switch_id"]: timing for timing in artifact_payload["timings"]}
    assert artifact_payload["scenario_id"] == "three_station_v0"
    assert len(artifact_payload["cabin_starts"]) == 30
    assert len(timings_by_switch) == 4
    assert timings_by_switch["M_entry_lr"]["skip_allowed"] is True
    assert timings_by_switch["M_entry_rl"]["skip_allowed"] is True
    assert timings_by_switch["L_entry_rl"]["skip_allowed"] is False
    assert timings_by_switch["R_entry_lr"]["skip_allowed"] is False

    assert plan_payload["scenario_id"] == "three_station_v0"
    assert len(plan_payload["trajectories"]) == 30
    assert {
        visit["decision"]
        for trajectory in plan_payload["trajectories"]
        for visit in trajectory["visits"]
    } == {"stop"}
    assert replay_payload["scenario_id"] == "three_station_v0"
    assert replay_payload["events"]
    assert len({event["cabin_id"] for event in replay_payload["events"]}) == 30
    assert replay_payload["events"][0]["physical_node_id"] in timings_by_switch


def test_exports_ean_skip_stop_feasibility_json(tmp_path: Path) -> None:
    pytest.importorskip("gurobipy")
    result = export_artifact_set(output_root=tmp_path, artifact_set_id="ean_skip_stop_feasibility")
    plan_path = tmp_path / "three_station_v0" / "ean_skip_stop_movement_plan.json"
    replay_path = tmp_path / "three_station_v0" / "ean_skip_stop_physical_replay.json"
    plan_payload = json.loads(plan_path.read_text(encoding="utf-8"))
    replay_payload = json.loads(replay_path.read_text(encoding="utf-8"))
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))

    artifact_set = _manifest_artifact_set(manifest, "three_station_v0", "ean_skip_stop_feasibility")
    assert artifact_set["artifacts"] == {
        "scenario": "three_station_v0/scenario.json",
        "ean_input": "three_station_v0/ean_build_artifact.json",
        "ean_result": "three_station_v0/ean_skip_stop_movement_plan.json",
        "ean_replay": "three_station_v0/ean_skip_stop_physical_replay.json",
    }
    decisions = {
        visit["decision"]
        for trajectory in plan_payload["trajectories"]
        for visit in trajectory["visits"]
    }
    assert decisions == {"skip", "stop"}
    assert len(plan_payload["trajectories"]) == 30
    assert replay_payload["events"]


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


def _manifest_artifact_set(manifest: dict, example_id: str, artifact_set_id: str) -> dict:
    example = next(example for example in manifest["examples"] if example["id"] == example_id)
    return next(artifact_set for artifact_set in example["artifact_sets"] if artifact_set["id"] == artifact_set_id)


class _PhysicalOnlyExample(ScenarioExample):
    metadata = ScenarioExampleMetadata(
        id="physical_only_test",
        label="Physical only test",
        description="Test example without discrete export capability.",
    )

    def build_scenario(self):
        return build_three_station_scenario()
