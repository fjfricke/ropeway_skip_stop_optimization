"""Separate reservoir CP runner; existing Fixed-K/Arc-Flow entry points are unchanged."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import json
import math
from pathlib import Path
import resource
import sys
from threading import Lock
from time import perf_counter

from .ddd_reservoir_arc_flow import (
    DddReservoirArcFlowRunConfig,
    prepare_ddd_reservoir_arc_flow_run,
)
from ..optimization.ddd.cp_sat_certificate import atomic_json
from ..optimization.ddd.cp_sat_integrated import DddIntegratedCpSatConfig
from ..optimization.ddd.reservoir_cp_sat import (
    DddReservoirCpSatOptimizer,
    DddReservoirCpObjective,
)
from ..optimization.ddd.reservoir_cp_sat_problem import DddReservoirCpSatProblem
from ..optimization.ddd.reservoir_cp_sat_certificate import (
    DddReservoirCpPlan,
    DddReservoirCpTrip,
    validate_reservoir_cp_plan,
    read_reservoir_cp_checkpoint,
    write_reservoir_cp_checkpoint,
)
from ..optimization.ddd.route_topology import unique_stop_route_option
from ..optimization.ddd.time_ticks import ddd_seconds_to_tick


@dataclass(frozen=True)
class DddReservoirCpSatRunConfig:
    physical: DddReservoirArcFlowRunConfig
    output_dir: Path
    solver: DddIntegratedCpSatConfig = DddIntegratedCpSatConfig()
    objective: DddReservoirCpObjective = DddReservoirCpObjective.JOURNEY_TIME
    dispatch_step_seconds: float = 0.000001
    seed_time_limit_seconds: float = 10.0
    resume_checkpoint: Path | None = None


def all_stop_reservoir_movement(problem, source):
    """Analytic boundary seed, no time-expanded graph or guessed depot headways."""
    count = min(problem.available_fleet_count, source.all_stop_maximum_cabin_count or 0)
    cycle = source.all_stop_cycle_seconds
    if not count or cycle is None:
        return None
    first = max(0, source.warmup_seconds - cycle)
    spacing = cycle / count
    trips = []
    for k in range(count):
        time = ddd_seconds_to_tick(first + k * spacing)
        if time > ddd_seconds_to_tick(problem.dispatch_end_seconds):
            break
        state = problem.entry_state_id
        ids, times = [], []
        last_return = None
        while time <= problem.resolved_core.operational_end_tick:
            o = unique_stop_route_option(
                problem.movement, state, error_context="reservoir all-stop seed"
            )
            if time + o.duration_tick > problem.resolved_core.operational_end_tick:
                break
            ids.append(o.id)
            times.append(time)
            state, time = o.to_state_id, time + o.duration_tick
            if state == problem.entry_state_id:
                last_return = (len(ids), time)
        if last_return:
            n, returned = last_return
            trips.append(
                DddReservoirCpTrip(
                    k, tuple(ids[:n]), tuple(times[:n]), (0,) * n, returned
                )
            )
    plan = DddReservoirCpPlan(tuple(trips), {})
    validate_reservoir_cp_plan(problem, plan)
    return plan


def _plan(raw):
    return DddReservoirCpPlan(
        tuple(
            DddReservoirCpTrip(
                t["cabin_id"],
                tuple(t["route_option_ids"]),
                tuple(t["switch_ticks"]),
                tuple(t["wait_ticks"]),
                t["return_tick"],
            )
            for t in raw["trips"]
        ),
        raw["ride_counts"],
    )


def run_ddd_reservoir_cp_sat(config: DddReservoirCpSatRunConfig):
    config.solver.validate()
    if (
        not math.isfinite(config.seed_time_limit_seconds)
        or config.seed_time_limit_seconds < 0
    ):
        raise ValueError("reservoir seed budget must be finite and nonnegative")
    started = perf_counter()
    deadline = started + config.solver.total_time_limit_seconds
    config.output_dir.mkdir(parents=True, exist_ok=False)
    atomic_json(
        config.output_dir / "config.json",
        json.loads(json.dumps(asdict(config), default=str)),
    )
    prepared = prepare_ddd_reservoir_arc_flow_run(config.physical)
    problem = replace(
        DddReservoirCpSatProblem.from_arc_flow(prepared.problem),
        dispatch_step_seconds=config.dispatch_step_seconds,
    )
    problem.validate()
    prepare_seconds = perf_counter() - started
    atomic_json(config.output_dir / "domain.json", problem.manifest)
    seed = None
    seed_result = None
    seed_failure = None
    before = perf_counter()
    if config.resume_checkpoint:
        seed = read_reservoir_cp_checkpoint(config.resume_checkpoint, problem)
    elif config.seed_time_limit_seconds and perf_counter() < deadline:
        try:
            movement = all_stop_reservoir_movement(problem, prepared.problem)
        except ValueError as error:
            # E.g. a coarse dispatch grid or insufficient clearing horizon.
            # Record an unavailable analytic seed; never assume feasibility.
            movement = None
            seed_failure = str(error)
        if movement is not None:
            seed_budget = min(
                config.seed_time_limit_seconds, max(1e-9, deadline - perf_counter())
            )
            seed_result = DddReservoirCpSatOptimizer(
                replace(
                    config.solver,
                    total_time_limit_seconds=seed_budget,
                    num_workers=1,
                    checkpoint_path=None,
                    log_search_progress=False,
                ),
                config.objective,
            ).solve(problem, fixed_plan=movement)
            seed = _plan(seed_result["plan"])
            atomic_json(config.output_dir / "seed_result.json", seed_result)
            write_reservoir_cp_checkpoint(
                config.output_dir / "seed.json", problem, seed
            )
    seed_seconds = perf_counter() - before
    lock = Lock()
    with (
        (config.output_dir / "events.jsonl").open("w") as events,
        (config.output_dir / "solver.log").open("w") as log,
    ):

        def event(item):
            with lock:
                events.write(
                    json.dumps(
                        {**item, "runner_elapsed_seconds": perf_counter() - started}
                    )
                    + "\n"
                )
                events.flush()

        def log_line(line):
            with lock:
                log.write(line if line.endswith("\n") else line + "\n")
                log.flush()

        solver = replace(
            config.solver,
            total_time_limit_seconds=max(1e-9, deadline - perf_counter()),
            checkpoint_path=config.output_dir / "incumbent.json",
        )
        result = DddReservoirCpSatOptimizer(solver, config.objective).solve(
            problem, primal_seed=seed, event_callback=event, log_callback=log_line
        )
    result.update(
        prepare_seconds=prepare_seconds,
        seed_seconds=seed_seconds,
        seed_failure=seed_failure,
        end_to_end_seconds=perf_counter() - started,
        peak_rss_mb=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        / (1024**2 if sys.platform == "darwin" else 1024),
        all_stop_maximum_cabin_count=prepared.all_stop_maximum_cabin_count,
        seed_upper_bound=None if seed is None else (validate_reservoir_cp_plan(problem, seed).journey_time_tick / 1e6 if config.objective is DddReservoirCpObjective.JOURNEY_TIME else validate_reservoir_cp_plan(problem, seed).unserved),
    )
    atomic_json(config.output_dir / "result.json", result)
    return result
