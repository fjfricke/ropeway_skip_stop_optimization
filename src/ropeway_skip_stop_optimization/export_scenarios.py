from __future__ import annotations

import argparse
import json
from dataclasses import fields, is_dataclass
from datetime import time
from enum import Enum
from enum import StrEnum
from pathlib import Path
from typing import Any

from ropeway_skip_stop_optimization.baselines import (
    build_all_stop_cycle_path,
    build_maximal_greedy_all_stop_circulation_plan,
    greedy_place_max_cabins_on_cycle,
)
from ropeway_skip_stop_optimization.examples import build_three_station_scenario
from ropeway_skip_stop_optimization.optimization import (
    FixedCabinStart,
    MilpV0Config,
    MilpV0VariableStrategy,
    MilpV1PassengerWaitingObjective,
    MilpV1PassengerWaitingConfig,
    solve_milp_v0,
    solve_milp_v1_passenger_waiting,
)
from ropeway_skip_stop_optimization.preprocessing.discretize import discretize_scenario
from ropeway_skip_stop_optimization.progress import ProgressReporter, configure_progress_logging
from ropeway_skip_stop_optimization.replay import build_replay_metrics, replay_passenger_boarding
from ropeway_skip_stop_optimization.validation import validate_scenario


class MilpExportMode(StrEnum):
    MOVEMENT = "movement"
    PASSENGER = "passenger"


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


def export_three_station_scenario(output_dir: Path, *, progress: bool | ProgressReporter = False) -> Path:
    reporter = _progress_reporter(progress)
    with reporter.phase("export_three_station_scenario.build_and_validate"):
        scenario = build_three_station_scenario()
        validate_scenario(scenario).raise_for_errors()

    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{scenario.id}.json"
    with reporter.phase("export_three_station_scenario.serialize"):
        payload = scenario_to_jsonable(scenario)
        payload["scenario_id"] = payload.pop("id")

    _write_json(output_path, payload, reporter)
    return output_path


def export_three_station_discrete_scenario(output_dir: Path, *, progress: bool | ProgressReporter = False) -> Path:
    reporter = _progress_reporter(progress)
    with reporter.phase("export_three_station_discrete_scenario.build_and_validate"):
        scenario = build_three_station_scenario()
        validate_scenario(scenario).raise_for_errors()
    with reporter.phase("export_three_station_discrete_scenario.discretize"):
        discrete = discretize_scenario(scenario)

    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{discrete.id}.json"
    with reporter.phase("export_three_station_discrete_scenario.serialize"):
        payload = scenario_to_jsonable(discrete)

    _write_json(output_path, payload, reporter)
    return output_path


def export_three_station_greedy_all_stop_movement_plan(
    output_dir: Path,
    *,
    progress: bool | ProgressReporter = False,
) -> Path:
    reporter = _progress_reporter(progress)
    with reporter.phase("export_three_station_greedy_all_stop_movement_plan.build_and_discretize"):
        scenario = build_three_station_scenario()
        validate_scenario(scenario).raise_for_errors()
        discrete = discretize_scenario(scenario)
    with reporter.phase("export_three_station_greedy_all_stop_movement_plan.build_plan"):
        plan = build_maximal_greedy_all_stop_circulation_plan(
            discrete,
            horizon_steps=discrete.horizon_steps,
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{discrete.id}__greedy_all_stop_movement_plan.json"
    with reporter.phase("export_three_station_greedy_all_stop_movement_plan.serialize"):
        payload = scenario_to_jsonable(plan)

    _write_json(output_path, payload, reporter)
    return output_path


def export_three_station_greedy_all_stop_passenger_replay(
    output_dir: Path,
    *,
    progress: bool | ProgressReporter = False,
) -> Path:
    reporter = _progress_reporter(progress)
    with reporter.phase("export_three_station_greedy_all_stop_passenger_replay.build_plan"):
        scenario = build_three_station_scenario()
        validate_scenario(scenario).raise_for_errors()
        discrete = discretize_scenario(scenario)
        plan = build_maximal_greedy_all_stop_circulation_plan(
            discrete,
            horizon_steps=discrete.horizon_steps,
        )
    with reporter.phase("export_three_station_greedy_all_stop_passenger_replay.replay"):
        replay = replay_passenger_boarding(discrete, plan)

    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{discrete.id}__greedy_all_stop_passenger_replay.json"
    with reporter.phase("export_three_station_greedy_all_stop_passenger_replay.serialize"):
        payload = scenario_to_jsonable(replay)

    _write_json(output_path, payload, reporter)
    return output_path


def export_three_station_greedy_all_stop_replay_metrics(
    output_dir: Path,
    *,
    progress: bool | ProgressReporter = False,
) -> Path:
    reporter = _progress_reporter(progress)
    with reporter.phase("export_three_station_greedy_all_stop_replay_metrics.build_replay"):
        scenario = build_three_station_scenario()
        validate_scenario(scenario).raise_for_errors()
        discrete = discretize_scenario(scenario)
        plan = build_maximal_greedy_all_stop_circulation_plan(
            discrete,
            horizon_steps=discrete.horizon_steps,
        )
        replay = replay_passenger_boarding(discrete, plan)
    with reporter.phase("export_three_station_greedy_all_stop_replay_metrics.build_metrics"):
        metrics = build_replay_metrics(discrete, replay)

    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{discrete.id}__greedy_all_stop_replay_metrics.json"
    with reporter.phase("export_three_station_greedy_all_stop_replay_metrics.serialize"):
        payload = scenario_to_jsonable(metrics)

    _write_json(output_path, payload, reporter)
    return output_path


def export_three_station_milp_v0_movement_plan(
    output_dir: Path,
    *,
    horizon_steps: int = 60,
    cabin_count: int = 23,
    variable_strategy: MilpV0VariableStrategy = MilpV0VariableStrategy.DENSE,
    progress: bool | ProgressReporter = False,
) -> Path:
    reporter = _progress_reporter(progress)
    with reporter.phase("export_three_station_milp_v0_movement_plan.build_and_discretize"):
        scenario = build_three_station_scenario()
        validate_scenario(scenario).raise_for_errors()
        discrete = discretize_scenario(scenario)
    if horizon_steps > discrete.horizon_steps:
        raise ValueError("MILP v0 export horizon_steps exceeds discrete scenario horizon")

    with reporter.phase("export_three_station_milp_v0_movement_plan.fixed_starts"):
        path = build_all_stop_cycle_path(discrete)
        start_indices = greedy_place_max_cabins_on_cycle(discrete, path.node_ids)
        if cabin_count > len(start_indices):
            raise ValueError(f"MILP v0 export requested {cabin_count} cabins, but only {len(start_indices)} fit")
        fixed_starts = tuple(
            FixedCabinStart(cabin_id=cabin_id, node_id=path.node_ids[start_index])
            for cabin_id, start_index in enumerate(start_indices[:cabin_count])
        )
    with reporter.phase(
        f"export_three_station_milp_v0_movement_plan.solve strategy={variable_strategy.value} "
        f"cabins={cabin_count} horizon={horizon_steps}"
    ):
        result = solve_milp_v0(
            discrete,
            MilpV0Config(
                horizon_steps=horizon_steps,
                fixed_starts=fixed_starts,
                variable_strategy=variable_strategy,
            ),
            progress=reporter,
        )
    if result.movement_plan is None:
        raise ValueError(f"MILP v0 did not produce a movement plan; status={result.metadata.status}")

    output_dir.mkdir(parents=True, exist_ok=True)
    strategy_label = "sparse" if variable_strategy is MilpV0VariableStrategy.SPARSE_REACHABILITY else "dense"
    output_path = output_dir / f"{discrete.id}__milp_v0_{strategy_label}_movement_plan_c{cabin_count}_h{horizon_steps}.json"
    with reporter.phase("export_three_station_milp_v0_movement_plan.serialize"):
        payload = {
            "movement_plan": scenario_to_jsonable(result.movement_plan),
            "metadata": scenario_to_jsonable(result.metadata),
        }

    _write_json(output_path, payload, reporter)
    return output_path


def export_three_station_milp_v1_passenger_waiting_plan(
    output_dir: Path,
    *,
    horizon_steps: int = 60,
    cabin_count: int = 23,
    variable_strategy: MilpV0VariableStrategy = MilpV0VariableStrategy.SPARSE_REACHABILITY,
    objective: MilpV1PassengerWaitingObjective = MilpV1PassengerWaitingObjective.FEASIBILITY,
    progress: bool | ProgressReporter = False,
) -> Path:
    reporter = _progress_reporter(progress)
    with reporter.phase("export_three_station_milp_v1_passenger_waiting_plan.build_and_discretize"):
        scenario = build_three_station_scenario()
        validate_scenario(scenario).raise_for_errors()
        discrete = discretize_scenario(scenario)
    if horizon_steps > discrete.horizon_steps:
        raise ValueError("MILP v1 passenger export horizon_steps exceeds discrete scenario horizon")

    with reporter.phase("export_three_station_milp_v1_passenger_waiting_plan.fixed_starts"):
        path = build_all_stop_cycle_path(discrete)
        start_indices = greedy_place_max_cabins_on_cycle(discrete, path.node_ids)
        if cabin_count > len(start_indices):
            raise ValueError(f"MILP v1 passenger export requested {cabin_count} cabins, but only {len(start_indices)} fit")
        fixed_starts = tuple(
            FixedCabinStart(cabin_id=cabin_id, node_id=path.node_ids[start_index])
            for cabin_id, start_index in enumerate(start_indices[:cabin_count])
        )

    with reporter.phase(
        f"export_three_station_milp_v1_passenger_waiting_plan.solve strategy={variable_strategy.value} "
        f"objective={objective.value} cabins={cabin_count} horizon={horizon_steps}"
    ):
        result = solve_milp_v1_passenger_waiting(
            discrete,
            MilpV1PassengerWaitingConfig(
                horizon_steps=horizon_steps,
                fixed_starts=fixed_starts,
                variable_strategy=variable_strategy,
                objective=objective,
            ),
            progress=reporter,
        )
    if result.movement_plan is None:
        raise ValueError(f"MILP v1 passenger waiting did not produce a movement plan; status={result.metadata.status}")

    output_dir.mkdir(parents=True, exist_ok=True)
    strategy_label = "sparse" if variable_strategy is MilpV0VariableStrategy.SPARSE_REACHABILITY else "dense"
    output_path = (
        output_dir
        / (
            f"{discrete.id}__milp_v1_passenger_waiting_{objective.value}_{strategy_label}"
            f"_movement_plan_c{cabin_count}_h{horizon_steps}.json"
        )
    )
    with reporter.phase("export_three_station_milp_v1_passenger_waiting_plan.serialize"):
        payload = {
            "movement_plan": scenario_to_jsonable(result.movement_plan),
            "metadata": scenario_to_jsonable(result.metadata),
        }

    _write_json(output_path, payload, reporter)
    return output_path


def _progress_reporter(progress: bool | ProgressReporter) -> ProgressReporter:
    if isinstance(progress, ProgressReporter):
        return progress
    return ProgressReporter(enabled=progress)


def _write_json(output_path: Path, payload: Any, reporter: ProgressReporter) -> None:
    with reporter.phase(f"write_json {output_path.name}"):
        output_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Export built-in ropeway scenarios as static JSON.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("frontend/public/scenarios"),
        help="Directory for exported scenario JSON files.",
    )
    parser.add_argument("--progress", action="store_true", help="Show export phase logs and progress bars.")
    parser.add_argument(
        "--milp-horizon",
        type=int,
        default=60,
        help="Horizon for the built-in MILP v0 movement-plan export.",
    )
    parser.add_argument(
        "--milp-cabin-count",
        type=int,
        default=23,
        help="Number of cabins for the built-in MILP v0 movement-plan export.",
    )
    parser.add_argument(
        "--milp-variable-strategy",
        choices=tuple(strategy.value for strategy in MilpV0VariableStrategy),
        default=MilpV0VariableStrategy.DENSE.value,
        help="Variable strategy for the built-in MILP export.",
    )
    parser.add_argument(
        "--milp-mode",
        choices=tuple(mode.value for mode in MilpExportMode),
        default=MilpExportMode.MOVEMENT.value,
        help="MILP model to export.",
    )
    parser.add_argument(
        "--milp-objective",
        choices=tuple(objective.value for objective in MilpV1PassengerWaitingObjective),
        default=MilpV1PassengerWaitingObjective.FEASIBILITY.value,
        help="MILP objective to use.",
    )
    args = parser.parse_args()
    milp_mode = MilpExportMode(args.milp_mode)
    milp_objective = MilpV1PassengerWaitingObjective(args.milp_objective)
    if milp_mode is MilpExportMode.MOVEMENT and milp_objective is not MilpV1PassengerWaitingObjective.FEASIBILITY:
        parser.error("--milp-mode movement currently supports only --milp-objective feasibility")
    if args.progress:
        configure_progress_logging()
    reporter = ProgressReporter(enabled=args.progress)
    output_paths = [
        export_three_station_scenario(args.output_dir, progress=reporter),
        export_three_station_discrete_scenario(args.output_dir, progress=reporter),
        export_three_station_greedy_all_stop_movement_plan(args.output_dir, progress=reporter),
        export_three_station_greedy_all_stop_passenger_replay(args.output_dir, progress=reporter),
        export_three_station_greedy_all_stop_replay_metrics(args.output_dir, progress=reporter),
    ]
    if milp_mode is MilpExportMode.MOVEMENT:
        output_paths.append(
            export_three_station_milp_v0_movement_plan(
                args.output_dir,
                horizon_steps=args.milp_horizon,
                cabin_count=args.milp_cabin_count,
                variable_strategy=MilpV0VariableStrategy(args.milp_variable_strategy),
                progress=reporter,
            )
        )
    elif milp_mode is MilpExportMode.PASSENGER:
        output_paths.append(
            export_three_station_milp_v1_passenger_waiting_plan(
                args.output_dir,
                horizon_steps=args.milp_horizon,
                cabin_count=args.milp_cabin_count,
                variable_strategy=MilpV0VariableStrategy(args.milp_variable_strategy),
                objective=milp_objective,
                progress=reporter,
            )
        )
    for output_path in output_paths:
        print(output_path)


if __name__ == "__main__":
    main()
