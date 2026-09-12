"""IBM comparison runner using the exact CP-SAT reservoir input contract."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import json
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
from ..optimization.ddd.reservoir_cp_sat import DddReservoirCpObjective
from ..optimization.ddd.reservoir_cp_sat_problem import DddReservoirCpSatProblem
from ..optimization.ddd.reservoir_cp_sat_certificate import (
    DddReservoirCpPlan,
    read_reservoir_cp_checkpoint,
    validate_reservoir_cp_plan,
    write_reservoir_cp_checkpoint,
)
from ..optimization.ddd.reservoir_ibm_cp import (
    DddReservoirIbmCpConfig,
    DddReservoirIbmCpOptimizer,
)


@dataclass(frozen=True)
class DddReservoirIbmCpRunConfig:
    physical: DddReservoirArcFlowRunConfig
    output_dir: Path
    solver: DddReservoirIbmCpConfig = DddReservoirIbmCpConfig()
    objective: DddReservoirCpObjective = DddReservoirCpObjective.JOURNEY_TIME
    dispatch_step_seconds: float = 0.000001
    resume_checkpoint: Path | None = None


def run_ddd_reservoir_ibm_cp(config: DddReservoirIbmCpRunConfig):
    config.solver.validate()
    started = perf_counter()
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
    atomic_json(config.output_dir / "domain.json", problem.manifest)
    seed = (
        read_reservoir_cp_checkpoint(config.resume_checkpoint, problem)
        if config.resume_checkpoint
        else DddReservoirCpPlan((), {})
    )
    metrics = validate_reservoir_cp_plan(problem, seed)
    write_reservoir_cp_checkpoint(config.output_dir / "seed.json", problem, seed)
    prepare_seconds = perf_counter() - started
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
                log.write(line)
                log.flush()

        solver = replace(
            config.solver,
            total_time_limit_seconds=max(
                1e-9, config.solver.total_time_limit_seconds - prepare_seconds
            ),
            checkpoint_path=config.output_dir / "incumbent.json",
            export_path=config.output_dir / "model.cpo",
        )
        result = DddReservoirIbmCpOptimizer(solver, config.objective).solve(
            problem, primal_seed=seed, event_callback=event, log_callback=log_line
        )
    result.update(
        prepare_seconds=prepare_seconds,
        end_to_end_seconds=perf_counter() - started,
        seed_upper_bound=metrics.journey_time_tick / 1e6
        if config.objective is DddReservoirCpObjective.JOURNEY_TIME
        else metrics.unserved,
        peak_rss_mb=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        / (1024**2 if sys.platform == "darwin" else 1024),
        peak_rss_scope="python_parent_only; native engine memory in solver_infos",
        all_stop_maximum_cabin_count=prepared.all_stop_maximum_cabin_count,
    )
    atomic_json(config.output_dir / "result.json", result)
    return result
