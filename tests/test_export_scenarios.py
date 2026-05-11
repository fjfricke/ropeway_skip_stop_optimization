from __future__ import annotations

import json

from ropeway_skip_stop_optimization.export_scenarios import (
    export_three_station_greedy_all_stop_passenger_replay,
    export_three_station_greedy_all_stop_movement_plan,
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
    assert payload["summary"]["arrived_passengers"] == 52
    assert payload["summary"]["boarded_passengers"] == 52
    assert payload["summary"]["served_passengers"] == 52
    assert payload["summary"]["unserved_passengers"] == 0
    assert len(payload["steps"]) == 2401
    assert payload["steps"][120]["boarding_events"][0]["station_id"] == "L"
    assert payload["steps"][120]["boarding_events"][0]["destination"] == "R"
    assert payload["steps"][120]["boarding_events"][0]["count"] == 8
    assert payload["steps"][120]["queue_states"][0]["waiting_count"] == 4
