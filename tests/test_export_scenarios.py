from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from ropeway_skip_stop_optimization.examples.base import ScenarioExample, ScenarioExampleMetadata
from ropeway_skip_stop_optimization.examples.registry import get_example
from ropeway_skip_stop_optimization.examples.three_station import ThreeStationExample, build_three_station_scenario
from ropeway_skip_stop_optimization.exports.artifacts import (
    ArtifactSet,
    DiscreteScenarioArtifactBuilder,
    PhysicalScenarioArtifactBuilder,
)
from ropeway_skip_stop_optimization.exports.runner import build_artifact_set, export_artifact_set
from ropeway_skip_stop_optimization.exports.runner import _latest_ean_checkpoint_path
from ropeway_skip_stop_optimization.exports.runner import run_artifact_set
from ropeway_skip_stop_optimization.exports.manifest import load_manifest
from ropeway_skip_stop_optimization.optimization.discrete_time import MilpV0VariableStrategy
from ropeway_skip_stop_optimization.optimization.ean import (
    DeterministicPhysicalNodeToSwitchStartBuilder,
    EanConfig,
    RingEanBuildArtifactBuilder,
    StationEanConfig,
    StationWaitingMode,
)
from ropeway_skip_stop_optimization.progress import ProgressReporter


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
