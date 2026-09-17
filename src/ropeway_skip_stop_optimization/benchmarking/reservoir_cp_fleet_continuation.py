"""Progressive fleet-cap continuation for the full reservoir CP-SAT model."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import json
import math
from pathlib import Path
from time import perf_counter, time
from typing import Callable

from .optimization_live_store import OptimizationLiveStore, reduce_optimization_events
from .optimization_events import OptimizationEventKind
from ..optimization.ddd.cp_sat_certificate import atomic_json, stable_fingerprint
from ..optimization.ddd.cp_sat_integrated import DddIntegratedCpSatConfig
from ..optimization.ddd.reservoir_cp_sat import (
    DddReservoirCpObjective,
    DddReservoirCpSatOptimizer,
    build_reservoir_cp_sat,
)
from ..optimization.ddd.reservoir_cp_sat_certificate import (
    DddReservoirCpPlan,
    read_reservoir_cp_checkpoint_for_fleet_resize,
    reservoir_cp_plan_from_payload,
    validate_reservoir_cp_plan,
)
from ..optimization.ddd.reservoir_hybrid.domain import load_reference
from ..optimization.ddd.route_topology import unique_stop_route_option


@dataclass(frozen=True, slots=True)
class FleetContinuationBudget:
    first_k: int = 1
    last_k: int = 50

    def seconds_for(self, k: int) -> float:
        if not self.first_k <= k <= self.last_k:
            raise ValueError("fleet stage lies outside the configured range")
        return 30.0 if k <= 10 else 90.0 if k <= 25 else 210.0

    @property
    def scheduled_seconds(self) -> float:
        return sum(self.seconds_for(k) for k in range(self.first_k, self.last_k + 1))

    def validate(self) -> None:
        if self.first_k < 1 or self.last_k < self.first_k:
            raise ValueError("invalid fleet continuation range")


@dataclass(frozen=True, slots=True)
class FleetContinuationConfig:
    case_file: Path
    output_dir: Path
    budget: FleetContinuationBudget = FleetContinuationBudget()
    total_time_limit_seconds: float = 7200.0
    workers: int = 12
    memory_limit_gib: float = 32.0
    seed: int = 0
    frontend_root: Path | None = None
    campaign_id: str = "reservoir_cp_fleet_continuation_r2"

    def validate(self) -> None:
        self.budget.validate()
        if not self.case_file.is_file():
            raise ValueError("frozen case checkpoint does not exist")
        if not math.isfinite(self.total_time_limit_seconds) or self.total_time_limit_seconds <= 0:
            raise ValueError("total time limit must be finite and positive")
        if self.workers <= 0 or not 0 < self.memory_limit_gib <= 32:
            raise ValueError("invalid solver resource configuration")
        if self.budget.scheduled_seconds > self.total_time_limit_seconds - 300 + 1e-9:
            raise ValueError("stage schedule must leave five minutes for preparation and finalization")
        if not self.campaign_id:
            raise ValueError("campaign ID must not be empty")


def load_frozen_r2_problem(path: Path):
    domain, _ignored_plan = load_reference(path)
    problem = domain.problem
    problem.validate()
    if sum(group.count for group in problem.demand_groups) != 3074:
        raise ValueError("pilot requires the frozen R2 demand total of 3,074")
    if problem.available_fleet_count != 50:
        raise ValueError("pilot case must be frozen with an available fleet cap of 50")
    if problem.boundary_policy is None:
        raise ValueError("pilot requires the current shared reservoir port contract")
    maxima = {value for _, value in problem.waiting_policy.maximum_wait_seconds_by_station_id}
    if maxima != {1200.0}:
        raise ValueError("pilot requires a uniform 1,200-second Waiting limit")
    if problem.operating_mode.value != "skip_stop":
        raise ValueError("pilot requires free STOP/SKIP decisions")
    return problem


def stage_problem(frozen_problem, k: int):
    if not 1 <= k <= frozen_problem.available_fleet_count:
        raise ValueError("stage fleet cap is outside the frozen domain")
    problem = replace(frozen_problem, available_fleet_count=k)
    problem.validate()
    return problem


def objective_seconds(metrics) -> float:
    return metrics.journey_time_tick / 1_000_000


def plan_diagnostics(problem, plan: DddReservoirCpPlan) -> dict:
    metrics = validate_reservoir_cp_plan(problem, plan)
    options = {option.id: option for option in problem.resolved_core.route_options}
    candidates = {candidate.id: candidate for candidate in problem.passenger_build.ride_candidates}
    trips = {trip.cabin_id: trip for trip in plan.trips}
    groups = {group.id: group for group in problem.demand_groups}
    occupancy: dict[tuple[int, int], int] = {}
    journey_tick = 0
    for ride_id, count in plan.ride_counts.items():
        if not count:
            continue
        candidate = candidates[ride_id]
        for visit in range(candidate.board_visit_index, candidate.alight_visit_index):
            occupancy[candidate.cabin_id, visit] = occupancy.get((candidate.cabin_id, visit), 0) + count
        trip = trips[candidate.cabin_id]
        stop = unique_stop_route_option(
            problem.movement,
            problem.visit_states[candidate.alight_visit_index],
            error_context="fleet continuation diagnostics",
        )
        arrival = trip.switch_ticks[candidate.alight_visit_index] + round(
            stop.platform_entry_offset_seconds * 1_000_000
        )
        release = round(groups[candidate.demand_group_id].release_time_seconds * 1_000_000)
        journey_tick += count * (arrival - release)
    stop_count = skip_count = passenger_carrying_skip_count = 0
    for trip in plan.trips:
        for visit, option_id in enumerate(trip.route_option_ids):
            if options[option_id].decision.value == "stop":
                stop_count += 1
            else:
                skip_count += 1
                passenger_carrying_skip_count += int(occupancy.get((trip.cabin_id, visit), 0) > 0)
    return {
        **asdict(metrics),
        "journey_objective_seconds": objective_seconds(metrics),
        "mean_served_journey_seconds": None if metrics.served == 0 else journey_tick / metrics.served / 1_000_000,
        "stop_count": stop_count,
        "skip_count": skip_count,
        "passenger_carrying_skip_count": passenger_carrying_skip_count,
    }


def run_stage(
    frozen_problem,
    *,
    k: int,
    time_limit_seconds: float,
    workers: int,
    seed: int,
    output_dir: Path,
    seed_checkpoint: Path | None,
    build_only: bool = False,
    event_callback: Callable[[dict], None] | None = None,
) -> dict:
    started = perf_counter()
    problem = stage_problem(frozen_problem, k)
    primal = (
        read_reservoir_cp_checkpoint_for_fleet_resize(seed_checkpoint, problem)
        if seed_checkpoint is not None
        else DddReservoirCpPlan((), {})
    )
    seed_metrics = validate_reservoir_cp_plan(problem, primal)
    output_dir.mkdir(parents=True, exist_ok=True)
    atomic_json(output_dir / "domain.json", problem.manifest)
    atomic_json(output_dir / "seed_metrics.json", plan_diagnostics(problem, primal))
    solver_config = DddIntegratedCpSatConfig(
        total_time_limit_seconds=time_limit_seconds,
        num_workers=workers,
        seed=seed,
        checkpoint_path=output_dir / "best.json",
        checkpoint_interval_seconds=1,
        log_search_progress=True,
    )
    if build_only:
        built = build_reservoir_cp_sat(
            problem,
            config=solver_config,
            objective=DddReservoirCpObjective.JOURNEY_TIME,
            deadline=perf_counter() + time_limit_seconds,
        )
        result = {
            "schema": "reservoir_cp_fleet_continuation_stage_v1",
            "build_only": True,
            "fleet_cap": k,
            "model_stats": built.stats,
            "model_fingerprint": built.fingerprint,
            "problem_fingerprint": problem.fingerprint,
            "total_wall_seconds": perf_counter() - started,
        }
    else:
        with (output_dir / "solver.log").open("w", encoding="utf-8") as log:
            def log_line(line: str) -> None:
                log.write(line if line.endswith("\n") else line + "\n")
                log.flush()

            raw = DddReservoirCpSatOptimizer(
                solver_config, DddReservoirCpObjective.JOURNEY_TIME
            ).solve(
                problem,
                primal_seed=primal,
                event_callback=event_callback,
                log_callback=log_line,
            )
        plan = reservoir_cp_plan_from_payload(raw["plan"])
        diagnostics = plan_diagnostics(problem, plan)
        result = {
            **raw,
            "schema": "reservoir_cp_fleet_continuation_stage_v1",
            "fleet_cap": k,
            "seed_objective_seconds": objective_seconds(seed_metrics),
            "native_strict_improvement": diagnostics["journey_time_tick"] < seed_metrics.journey_time_tick,
            "diagnostics": diagnostics,
            "total_wall_seconds": perf_counter() - started,
        }
    atomic_json(output_dir / "result.json", result)
    return result


def publish(store: OptimizationLiveStore) -> dict:
    snapshot = reduce_optimization_events(store.read_events())
    if snapshot.get("campaign_kind") == "reservoir_cp_fleet_continuation":
        trials = sorted(
            snapshot["trials"].values(),
            key=lambda item: item["available_fleet_count"],
        )
        bounds = []
        for trial in trials:
            lower, upper = trial.get("certified_lower_bound"), trial.get("validated_upper_bound")
            if lower is None or upper is None:
                continue
            k = trial["available_fleet_count"]
            bounds.append(
                {
                    "available_fleet_count": k,
                    "raw_lower_bound": lower,
                    "raw_upper_bound": upper,
                    "tightened_lower_bound": lower,
                    "tightened_upper_bound": upper,
                    "lower_bound_source_k": k,
                    "upper_bound_source_k": k,
                }
            )
        snapshot["policies"] = {
            "continuation": {
                "policy": {
                    "id": "continuation",
                    "label": "Full CP-SAT continuation",
                    "example_id": "historical_r2_shared_port",
                },
                "bounds": bounds,
                "trials": trials,
            }
        }
    store.publish(snapshot)
    return snapshot


def campaign_identity(config: FleetContinuationConfig, problem) -> str:
    return stable_fingerprint(
        {
            "schema": "reservoir_cp_fleet_continuation_campaign_v1",
            "problem_without_fleet": {
                key: value for key, value in problem.manifest.items() if key != "available_fleet_count"
            },
            "budget": asdict(config.budget),
            "total_time_limit_seconds": config.total_time_limit_seconds,
            "workers": config.workers,
            "memory_limit_gib": config.memory_limit_gib,
            "seed": config.seed,
        }
    )


def _read_json_lines(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    result = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            result.append(json.loads(line))
        except json.JSONDecodeError:
            # A concurrently appended final line is retried on the next poll.
            continue
    return result


def _progress_points(events: list[dict], seed_upper_seconds: float | None) -> list[dict]:
    upper = seed_upper_seconds
    lower = None
    points = []
    for event in events:
        if event.get("kind") == "incumbent" and event.get("objective_raw") is not None:
            value = int(event["objective_raw"]) / 1_000_000
            upper = value if upper is None else min(upper, value)
        if event.get("bound_raw") is not None and math.isfinite(float(event["bound_raw"])):
            value = max(0.0, float(event["bound_raw"]) / 1_000_000)
            lower = value if lower is None else max(lower, value)
        elapsed = event.get("elapsed_seconds")
        if elapsed is None or (upper is None and lower is None):
            continue
        gap = None if upper is None or lower is None else max(0.0, upper - lower) / max(abs(upper), 1) * 100
        point = {
            "seconds": float(elapsed),
            "ub": upper,
            "lb": lower,
            "gap_percent": gap,
        }
        if not points or any(point[key] != points[-1][key] for key in ("ub", "lb", "gap_percent")):
            points.append(point)
    if len(points) <= 400:
        return points
    indices = {0, len(points) - 1}
    indices.update(round(i * (len(points) - 1) / 399) for i in range(400))
    return [points[index] for index in sorted(indices)]


def _plan_summary(problem, checkpoint: Path) -> dict | None:
    if not checkpoint.is_file():
        return None
    plan = read_reservoir_cp_checkpoint_for_fleet_resize(checkpoint, problem)
    options = {option.id: option for option in problem.resolved_core.route_options}
    candidates = {candidate.id: candidate for candidate in problem.passenger_build.ride_candidates}
    passengers: dict[int, int] = {}
    for ride_id, count in plan.ride_counts.items():
        if count:
            cabin = candidates[ride_id].cabin_id
            passengers[cabin] = passengers.get(cabin, 0) + count
    cycle = len(problem.cycle_states)
    cabins = []
    for trip in plan.trips:
        decisions = [options[option_id].decision.value for option_id in trip.route_option_ids]
        stations = [options[option_id].station_id for option_id in trip.route_option_ids]
        rounds = []
        for start in range(0, len(decisions), cycle):
            rounds.append(
                [
                    station
                    for station, decision in zip(
                        stations[start : start + cycle], decisions[start : start + cycle], strict=False
                    )
                    if decision == "stop"
                ]
            )
        cabins.append(
            {
                "cabin_id": trip.cabin_id,
                "dispatch_seconds": trip.switch_ticks[0] / 1_000_000,
                "return_seconds": trip.return_tick / 1_000_000,
                "waiting_seconds": sum(trip.wait_ticks) / 1_000_000,
                "passenger_assignments": passengers.get(trip.cabin_id, 0),
                "rounds": rounds,
            }
        )
    return {"cabins": cabins}


def export_frontend_detail(campaign_dir: Path, frontend_campaign_dir: Path) -> dict:
    """Publish portable per-K solver histories and compact timetable drawings."""
    campaign_path = campaign_dir / "campaign.json"
    case_path = campaign_dir / "frozen_case.json"
    if not campaign_path.is_file() or not case_path.is_file():
        raise ValueError("continuation campaign is not initialized")
    campaign = json.loads(campaign_path.read_text(encoding="utf-8"))
    frozen = load_frozen_r2_problem(case_path)
    all_stop_reference = None
    all_stop_path = campaign_dir / "all_stop_reference.json"
    if all_stop_path.is_file():
        all_stop_domain, all_stop_plan = load_reference(all_stop_path)
        all_stop_problem = all_stop_domain.problem
        excluded = {"operating_mode", "derived_visit_count"}
        all_stop_contract = {
            key: value for key, value in all_stop_problem.manifest.items() if key not in excluded
        }
        continuation_contract = {
            key: value for key, value in frozen.manifest.items() if key not in excluded
        }
        if all_stop_contract != continuation_contract:
            raise ValueError("All-Stop reference does not match the continuation campaign")
        metrics = validate_reservoir_cp_plan(all_stop_problem, all_stop_plan)
        all_stop_reference = {
            "served": metrics.served,
            "unserved": metrics.unserved,
            "used_fleet": metrics.used_fleet,
            "journey_objective_seconds": objective_seconds(metrics),
            "label": "All-Stop reference",
        }
    raw_trials = campaign.get("trials", {})
    trials = []
    for trial in sorted(raw_trials.values(), key=lambda item: item["available_fleet_count"]):
        k = int(trial["available_fleet_count"])
        attempts = sorted((campaign_dir / "stages" / f"k{k:02d}").glob("attempt*"))
        attempt = attempts[-1] if attempts else None
        artifact = None if attempt is None else attempt / "artifact"
        events = [] if artifact is None else _read_json_lines(artifact / "native_events.jsonl")
        points = _progress_points(events, trial.get("seed_objective_seconds"))
        checkpoint = None if artifact is None else artifact / "best.json"
        problem = stage_problem(frozen, k)
        trials.append(
            {
                "k": k,
                "status": trial.get("status", "queued"),
                "solver_status": trial.get("solver_status"),
                "budget_seconds": trial.get("budget_seconds"),
                "elapsed_seconds": max(
                    [float(event.get("elapsed_seconds", 0)) for event in events] + [0.0]
                ),
                "seed_objective_seconds": trial.get("seed_objective_seconds"),
                "objective_seconds": trial.get("validated_upper_bound"),
                "lower_bound_seconds": trial.get("certified_lower_bound"),
                "gap_percent": None if trial.get("relative_gap") is None else float(trial["relative_gap"]) * 100,
                "served": trial.get("served"),
                "unserved": trial.get("unserved"),
                "used_fleet": trial.get("dispatched_fleet_count"),
                "mean_served_journey_seconds": trial.get("mean_served_journey_seconds"),
                "native_strict_improvement": trial.get("native_strict_improvement"),
                "points": points,
                "plan": None if checkpoint is None else _plan_summary(problem, checkpoint),
            }
        )
    payload = {
        "schema": "reservoir_cp_fleet_continuation_frontend_v1",
        "campaign_id": campaign["campaign_id"],
        "status": campaign.get("status"),
        "updated_unix": time(),
        "all_stop_reference": all_stop_reference,
        "trials": trials,
    }
    atomic_json(frontend_campaign_dir / "detail.json", payload)
    return payload
