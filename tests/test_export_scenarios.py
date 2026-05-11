from __future__ import annotations

import json

import pytest

from ropeway_skip_stop_optimization.export_scenarios import (
    export_three_station_greedy_all_stop_passenger_replay,
    export_three_station_greedy_all_stop_replay_metrics,
    export_three_station_greedy_all_stop_movement_plan,
    export_three_station_milp_v0_movement_plan,
)


def test_exports_greedy_all_stop_movement_plan_json(tmp_path) -> None:
    output_path = export_three_station_greedy_all_stop_movement_plan(tmp_path)
    payload = json.loads(output_path.read_text(encoding="utf-8"))

    assert output_path.name == "three_station_v0__dt_0p5__greedy_all_stop_movement_plan.json"
    assert payload["discrete_scenario_id"] == "three_station_v0__dt_0p5"
    assert payload["horizon_steps"] == 2400
    assert len(payload["trajectories"]) == 23
    assert len(payload["trajectories"][0]["positions"]) == 2401
    assert payload["paths"][0]["id"] == "all_stop_cycle"
    assert "M_lr_skip_bypass" not in payload["paths"][0]["source_segment_ids"]
    assert "M_rl_skip_bypass" not in payload["paths"][0]["source_segment_ids"]


def test_exports_greedy_all_stop_passenger_replay_json(tmp_path) -> None:
    output_path = export_three_station_greedy_all_stop_passenger_replay(tmp_path)
    payload = json.loads(output_path.read_text(encoding="utf-8"))

    assert output_path.name == "three_station_v0__dt_0p5__greedy_all_stop_passenger_replay.json"
    assert payload["discrete_scenario_id"] == "three_station_v0__dt_0p5"
    assert payload["movement_plan_horizon_steps"] == 2400
    assert payload["boarding_policy"] == "greedy_fifo_next_compatible_cabin"
    assert payload["summary"]["arrived_passengers"] == 3480
    assert payload["summary"]["boarded_passengers"] == 3480
    assert payload["summary"]["served_passengers"] == 3480
    assert payload["summary"]["unserved_passengers"] == 0
    assert len(payload["steps"]) == 2401
    assert payload["steps"][0]["queue_states"][0]["waiting_count"] == 580
    assert payload["boarding_events"][0]["station_id"] == "M"
    assert payload["boarding_events"][0]["destination"] == "L"
    assert payload["boarding_events"][0]["count"] == 8
    assert payload["final_queue_states"] == []


def test_exports_greedy_all_stop_replay_metrics_json(tmp_path) -> None:
    output_path = export_three_station_greedy_all_stop_replay_metrics(tmp_path)
    payload = json.loads(output_path.read_text(encoding="utf-8"))

    assert output_path.name == "three_station_v0__dt_0p5__greedy_all_stop_replay_metrics.json"
    assert payload["discrete_scenario_id"] == "three_station_v0__dt_0p5"
    assert payload["movement_plan_horizon_steps"] == 2400
    assert payload["delta_seconds"] == 0.5
    assert len(payload["steps"]) == 2401
    assert payload["steps"][0]["arrivals_count"] == 3480
    assert payload["steps"][0]["waiting_count"] == 3480
    assert payload["steps"][0]["cumulative_waiting_passenger_hours"] == pytest.approx(1740.0 / 3600)
    assert payload["steps"][0]["waiting_by_station"] == [
        {"count": 1160, "station_id": "L"},
        {"count": 1160, "station_id": "M"},
        {"count": 1160, "station_id": "R"},
    ]
    assert payload["steps"][6]["boarding_count"] == 8
    assert payload["steps"][6]["onboard_count"] == 8
    assert payload["steps"][-1]["waiting_count"] == 0
    assert payload["steps"][-1]["onboard_count"] == 0


def test_exports_milp_v0_movement_plan_json(tmp_path) -> None:
    pytest.importorskip("gurobipy")

    output_path = export_three_station_milp_v0_movement_plan(tmp_path, horizon_steps=2, cabin_count=2)
    payload = json.loads(output_path.read_text(encoding="utf-8"))

    assert output_path.name == "three_station_v0__dt_0p5__milp_v0_movement_plan_c2_h2.json"
    assert payload["movement_plan"]["discrete_scenario_id"] == "three_station_v0__dt_0p5"
    assert payload["movement_plan"]["horizon_steps"] == 2
    assert len(payload["movement_plan"]["trajectories"]) == 2
    assert len(payload["movement_plan"]["trajectories"][0]["positions"]) == 3
    assert payload["metadata"]["status"] == "optimal"
    assert len(payload["metadata"]["selected_arc_ids_by_cabin"]["0"]) == 2
