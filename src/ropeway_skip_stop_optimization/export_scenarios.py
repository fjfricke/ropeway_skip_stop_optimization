from __future__ import annotations

import argparse
import json
from dataclasses import fields, is_dataclass
from datetime import time
from enum import Enum
from pathlib import Path
from typing import Any

from ropeway_skip_stop_optimization.baselines import build_maximal_greedy_all_stop_circulation_plan
from ropeway_skip_stop_optimization.examples import build_three_station_scenario
from ropeway_skip_stop_optimization.preprocessing.discretize import discretize_scenario
from ropeway_skip_stop_optimization.replay import build_replay_metrics, replay_passenger_boarding
from ropeway_skip_stop_optimization.validation import validate_scenario


def scenario_to_jsonable(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, time):
        return value.isoformat(timespec="minutes")
    if is_dataclass(value):
        return {field.name: scenario_to_jsonable(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, tuple | list):
        return [scenario_to_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): scenario_to_jsonable(item) for key, item in value.items()}
    return value


def export_three_station_scenario(output_dir: Path) -> Path:
    scenario = build_three_station_scenario()
    validate_scenario(scenario).raise_for_errors()

    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{scenario.id}.json"
    payload = scenario_to_jsonable(scenario)
    payload["scenario_id"] = payload.pop("id")

    output_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return output_path


def export_three_station_discrete_scenario(output_dir: Path) -> Path:
    scenario = build_three_station_scenario()
    validate_scenario(scenario).raise_for_errors()
    discrete = discretize_scenario(scenario)

    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{discrete.id}.json"
    payload = scenario_to_jsonable(discrete)

    output_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return output_path


def export_three_station_greedy_all_stop_movement_plan(output_dir: Path) -> Path:
    scenario = build_three_station_scenario()
    validate_scenario(scenario).raise_for_errors()
    discrete = discretize_scenario(scenario)
    plan = build_maximal_greedy_all_stop_circulation_plan(
        discrete,
        horizon_steps=discrete.horizon_steps,
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{discrete.id}__greedy_all_stop_movement_plan.json"
    payload = scenario_to_jsonable(plan)

    output_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return output_path


def export_three_station_greedy_all_stop_passenger_replay(output_dir: Path) -> Path:
    scenario = build_three_station_scenario()
    validate_scenario(scenario).raise_for_errors()
    discrete = discretize_scenario(scenario)
    plan = build_maximal_greedy_all_stop_circulation_plan(
        discrete,
        horizon_steps=discrete.horizon_steps,
    )
    replay = replay_passenger_boarding(discrete, plan)

    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{discrete.id}__greedy_all_stop_passenger_replay.json"
    payload = scenario_to_jsonable(replay)

    output_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return output_path


def export_three_station_greedy_all_stop_replay_metrics(output_dir: Path) -> Path:
    scenario = build_three_station_scenario()
    validate_scenario(scenario).raise_for_errors()
    discrete = discretize_scenario(scenario)
    plan = build_maximal_greedy_all_stop_circulation_plan(
        discrete,
        horizon_steps=discrete.horizon_steps,
    )
    replay = replay_passenger_boarding(discrete, plan)
    metrics = build_replay_metrics(discrete, replay)

    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{discrete.id}__greedy_all_stop_replay_metrics.json"
    payload = scenario_to_jsonable(metrics)

    output_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Export built-in ropeway scenarios as static JSON.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("frontend/public/scenarios"),
        help="Directory for exported scenario JSON files.",
    )
    args = parser.parse_args()
    output_paths = (
        export_three_station_scenario(args.output_dir),
        export_three_station_discrete_scenario(args.output_dir),
        export_three_station_greedy_all_stop_movement_plan(args.output_dir),
        export_three_station_greedy_all_stop_passenger_replay(args.output_dir),
        export_three_station_greedy_all_stop_replay_metrics(args.output_dir),
    )
    for output_path in output_paths:
        print(output_path)


if __name__ == "__main__":
    main()
