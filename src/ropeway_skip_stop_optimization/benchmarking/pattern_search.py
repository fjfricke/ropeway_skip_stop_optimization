"""Reproducible fixed-start pattern-search experiments and independent EAN audit."""

from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
import json
import math
import resource
import statistics
import sys

from .ddd_fixed_k_arc_flow import (
    DddFixedKArcFlowRunConfig,
    prepare_ddd_fixed_k_arc_flow_run,
)
from .ddd_cp_sat_waiting import with_exit_waiting
from ..optimization.ddd.fixed_k import DddFixedKOperatingMode, DddFixedKStartPolicy
from ..optimization.ddd.cp_sat_certificate import (
    atomic_json,
    read_ddd_cp_sat_checkpoint,
    write_ddd_cp_sat_checkpoint,
    validate_ddd_cp_sat_domain,
    validate_ddd_cp_sat_incumbent,
    solution_from_cp_sat_payload,
)
from ..optimization.ddd.fixed_timetable_capacity import NestedDemand
from ..optimization.ddd.pattern_search import (
    PatternVnsOptimizer,
    PatternVnsConfig,
    unserved,
)
from ..optimization.ddd.cp_sat_capacity import DddCpSatCapacityOptimizer
from ..optimization.ddd.cp_sat_integrated import DddIntegratedCpSatConfig

EXAMPLE = "five_station_circle_cw_half_skip_no_wait_headway_b_v0"


@dataclass(frozen=True)
class PatternBenchmarkConfig:
    cabins: int
    seed: int = 0
    workers: int = 12
    seconds: float = 900
    demand: int = 3074
    method: str = "vns"
    oracle_seconds: float = 5
    refine_seconds: float = 15
    retry_unknown: bool = True


def independent_assignment(problem, scenario, solution, seconds=30):
    """Different EAN/Gurobi formulation; optimize service on exported movement only."""
    import gurobipy as gp
    from gurobipy import GRB
    from ..optimization.ddd.ean_plan_adapter import DddReferenceToEanMovementPlanAdapter
    from ..optimization.ean.optimizers.fixed_movement_passenger_model import (
        EanFixedMovementPassengerModelBuilder,
        EanPassengerAssignmentDomain,
    )

    started = perf_counter()
    movement = problem.resolved_trajectory_problem.structural_movement_problem
    plan = DddReferenceToEanMovementPlanAdapter(
        waiting_policy=problem.resolved_trajectory_problem.waiting_policy
    ).build(problem=movement, solution=solution, artifact=problem.artifact)
    with gp.Model() as model:
        model.Params.OutputFlag = 0
        model.Params.Threads = 1
        model.Params.TimeLimit = seconds
        passenger = EanFixedMovementPassengerModelBuilder().build(
            model=model,
            scenario=scenario,
            artifact=problem.artifact,
            movement_plan=plan,
            passenger_build=problem.passenger_build,
            objective=problem.objective,
            assignment_domain=EanPassengerAssignmentDomain.INTEGER,
            grb=GRB,
            gp=gp,
        )
        total = sum(g.count for g in problem.passenger_build.demand_groups)
        model.setObjective(
            total - gp.quicksum(passenger.variables.ride_count.values()), GRB.MINIMIZE
        )
        model.optimize()
        result = dict(
            proof_scope="FIXED_MOVEMENT",
            formulation="independent_ean_gurobi",
            status=model.Status,
            proven_optimal=model.Status == GRB.OPTIMAL,
            total_seconds=perf_counter() - started,
            variables=model.NumVars,
            constraints=model.NumConstrs,
        )
        if model.SolCount:
            assignment = passenger.extract_assignment()
            counts = {
                k: int(round(v))
                for k, v in assignment.ride_counts_by_candidate_id.items()
                if v > 0.5
            }
            checked = validate_ddd_cp_sat_incumbent(
                problem, solution, counts, provenance="independent_ean_capacity"
            )
            if abs(unserved(checked) - model.ObjVal) > 1e-5:
                raise RuntimeError("independent capacity objective mismatch")
            result.update(
                unserved_upper_bound=unserved(checked), incumbent=checked.to_payload()
            )
        return result


def run_pattern_benchmark(config, *, output, seed_path):
    if config.method not in ("vns", "cp_sat") or config.cabins not in (38, 39):
        raise ValueError("pilot requires vns/cp_sat and fixed K38/K39")
    if not math.isfinite(config.seconds) or config.seconds <= 10:
        raise ValueError("budget must exceed finalization reserve")
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    started = perf_counter()
    prepared = prepare_ddd_fixed_k_arc_flow_run(
        DddFixedKArcFlowRunConfig(
            EXAMPLE,
            config.cabins,
            DddFixedKOperatingMode.SKIP_STOP,
            start_policy=DddFixedKStartPolicy.BALANCED_REFERENCE,
            cp_seed_time_limit_seconds=0,
        )
    )
    prepared = with_exit_waiting(prepared, maximum_seconds=1200, step_seconds=1e-6)
    problem = NestedDemand(prepared.problem.passenger_build.demand_groups).apply(
        prepared.problem, config.demand
    )
    manifest = validate_ddd_cp_sat_domain(problem)
    seed = read_ddd_cp_sat_checkpoint(
        Path(seed_path), problem=problem, manifest=manifest
    )
    preparation = perf_counter() - started
    atomic_json(
        output / "config.json",
        dict(
            **vars(config),
            seed_path=str(seed_path),
            seed_unserved=unserved(seed),
            preparation_seconds=preparation,
        ),
    )
    atomic_json(output / "domain.json", manifest)

    def checkpoint(inc):
        write_ddd_cp_sat_checkpoint(
            output / "incumbent.json", problem=problem, manifest=manifest, incumbent=inc
        )

    checkpoint(seed)

    def pattern_checkpoint(pattern, inc):
        folder = output / "patterns" / pattern.id
        folder.mkdir(parents=True, exist_ok=True)
        atomic_json(
            folder / "pattern.json",
            dict(domain_id=pattern.domain_id, choices=pattern.choices),
        )
        write_ddd_cp_sat_checkpoint(
            folder / "incumbent.json", problem=problem, manifest=manifest, incumbent=inc
        )

    with (
        (output / "events.jsonl").open("w") as events,
        (output / "solver.log").open("w") as log,
    ):

        def event(row):
            row = dict(row, run_elapsed_seconds=perf_counter() - started)
            events.write(json.dumps(row) + "\n")
            events.flush()

        def line(s):
            log.write(s if s.endswith("\n") else s + "\n")
            log.flush()

        remaining = config.seconds - (perf_counter() - started)
        if config.method == "vns":
            result = PatternVnsOptimizer(
                PatternVnsConfig(
                    total_seconds=remaining,
                    workers=config.workers,
                    seed=config.seed,
                    oracle_seconds=config.oracle_seconds,
                    retry_seconds=config.refine_seconds,
                    retry_unknown=config.retry_unknown,
                )
            ).solve(
                problem,
                primal_seed=seed,
                event_callback=event,
                log_callback=line,
                checkpoint_callback=checkpoint,
                pattern_checkpoint_callback=pattern_checkpoint,
            )
        else:
            result = DddCpSatCapacityOptimizer(
                DddIntegratedCpSatConfig(
                    total_time_limit_seconds=max(1e-9, remaining - 10),
                    num_workers=config.workers,
                    seed=config.seed,
                    log_search_progress=True,
                    checkpoint_path=output / "incumbent.json",
                )
            ).solve(problem, primal_seed=seed, event_callback=event, log_callback=line)
    result["search_wall_seconds"] = perf_counter() - started
    result["preparation_seconds"] = preparation
    result["seed_unserved"] = unserved(seed)
    rows = [e for e in result.get("events", []) if e.get("kind") == "pattern_evaluated"]
    times = sorted(e["call_seconds"] for e in rows)
    if times:
        result["oracle_timing"] = dict(
            calls=len(times),
            median_seconds=statistics.median(times),
            p95_seconds=times[max(0, math.ceil(0.95 * len(times)) - 1)],
            build_seconds=sum(e["build_seconds"] for e in rows),
            solve_seconds=sum(e["solve_seconds"] for e in rows),
            validation_seconds=sum(e["validation_seconds"] for e in rows),
        )
    # Persist the raw search outcome before independent post-processing.
    atomic_json(output / "result.json", result)
    solution = solution_from_cp_sat_payload(problem, result["incumbent"])
    post = independent_assignment(problem, prepared.scenario, solution)
    atomic_json(output / "independent_assignment.json", post)
    if post.get("unserved_upper_bound", math.inf) > result["unserved_upper_bound"]:
        raise RuntimeError("independent assignment could not confirm incumbent service")
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    atomic_json(
        output / "completion.json",
        dict(
            status="complete",
            raw_unserved=result["unserved_upper_bound"],
            post_unserved=post.get("unserved_upper_bound"),
            total_seconds=perf_counter() - started,
            peak_rss_bytes=rss if sys.platform == "darwin" else rss * 1024,
        ),
    )
    return result


def screening_gate(results):
    distinct = sum(r["distinct_patterns"] for r in results)
    valid = sum(r["changed_valid_patterns"] for r in results)
    return dict(
        passed=len(results) == 2 and distinct >= 10 and valid >= 2,
        distinct_patterns=distinct,
        changed_valid_patterns=valid,
        required_distinct_patterns=10,
        required_changed_valid_patterns=2,
    )
