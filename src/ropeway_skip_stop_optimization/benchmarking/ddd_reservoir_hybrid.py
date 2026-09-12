"""Bound pilot runner. Later gated phases are explicitly unavailable."""

from dataclasses import asdict, dataclass
import hashlib
import json
import math
from pathlib import Path
import resource
import sys
from time import perf_counter

from ..optimization.ddd.cp_sat_certificate import atomic_json
from ..optimization.ddd.reservoir_hybrid.arrival_curves import (
    ArrivalCurveEvaluator,
    ArrivalIntervalPartition,
)
from ..optimization.ddd.reservoir_hybrid.bound_domain import prepare_bound
from ..optimization.ddd.reservoir_hybrid.bound_model import (
    PROFILES,
    BoundSizeLimit,
    ReservoirArrivalBoundBuilder,
    ReservoirArrivalBoundOptimizer,
    analytical_bound,
)
from ..optimization.ddd.reservoir_hybrid.certificates import ReservoirCertificateLedger
from ..optimization.ddd.reservoir_hybrid.domain import load_reference


@dataclass(frozen=True)
class DddReservoirHybridRunConfig:
    resume_checkpoint: Path
    output_dir: Path
    phase: str = "bound"
    lifecycle: str = "single_use"
    bound_profile: str = "resource_windows"
    initial_bound_step_seconds: float = 60
    total_time_limit_seconds: float = 300
    num_workers: int = 12
    max_variables: int | None = 50000
    max_rows: int | None = 250000
    build_only: bool = False
    journey_encoding: str = "legacy"
    lp_method: int = -1
    open_deployments: tuple[int, ...] = ()
    new_slots: int = 0
    repair_presolve: bool = True
    initial_bound_result: Path | None = None
    seed: int = 0
    refinement_rounds: int = 5
    normalize_empty_tails: bool = False

    def validate(self):
        if (
            self.phase not in ("replay", "bound", "repair", "refine", "hybrid")
            or self.lifecycle != "single_use"
        ):
            raise ValueError(
                "later lifecycles are gated; use single_use replay/bound/refine/repair/hybrid"
            )
        if self.bound_profile not in PROFILES:
            raise ValueError("unknown bound profile")
        if self.journey_encoding not in ("legacy", "ride_bounds", "time_moments"):
            raise ValueError("unknown journey encoding")
        if self.lp_method not in (-1, 0, 1, 2):
            raise ValueError("unsupported LP method")
        for v in (self.initial_bound_step_seconds, self.total_time_limit_seconds):
            if not math.isfinite(v) or v <= 0:
                raise ValueError("positive finite time values required")
        for v in (self.num_workers,):
            if type(v) is not int or v <= 0:
                raise ValueError("positive integer limits required")
        for v in (self.max_variables, self.max_rows):
            if v is not None and (type(v) is not int or v <= 0):
                raise ValueError("size limits must be positive integers or None")
        if type(self.new_slots) is not int or self.new_slots < 0:
            raise ValueError("new slots must be a nonnegative integer")
        if (
            type(self.refinement_rounds) is not int
            or not 1 <= self.refinement_rounds <= 5
        ):
            raise ValueError("pilot refinement rounds must be between 1 and 5")


def run_ddd_reservoir_hybrid(config):
    config.validate()
    started = perf_counter()
    deadline = started + config.total_time_limit_seconds
    out = config.output_dir
    out.mkdir(parents=True, exist_ok=False)
    atomic_json(
        out / "config.json", json.loads(json.dumps(asdict(config), default=str))
    )
    root = Path(__file__).resolve().parents[1]
    sources = {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*.py"))
    }
    atomic_json(out / "source_hashes.json", sources)
    import gurobipy
    import ortools

    atomic_json(
        out / "versions.json",
        {
            "python": sys.version,
            "gurobi": gurobipy.gurobi.version(),
            "ortools": ortools.__version__,
        },
    )
    domain, plan = load_reference(config.resume_checkpoint)
    p = domain.problem
    if config.normalize_empty_tails:
        from ..optimization.ddd.reservoir_hybrid.repair import trim_empty_tails

        plan = trim_empty_tails(p, plan)
    atomic_json(out / "domain.json", p.manifest)
    ledger = ReservoirCertificateLedger(p)
    ledger.accept_plan(plan)
    part = ArrivalIntervalPartition.build(
        p, round(config.initial_bound_step_seconds * 1e6)
    )
    atomic_json(out / "partition.json", list(part.points))
    atomic_json(
        out / "arrival_identity.json", ArrivalCurveEvaluator().evaluate(p, plan, part)
    )
    from ..optimization.ddd.reservoir_cp_sat_certificate import (
        write_reservoir_cp_checkpoint,
    )

    write_reservoir_cp_checkpoint(out / "reference.json", p, plan)
    result = {
        "status": "replay_complete",
        "problem_fingerprint": p.fingerprint,
        "validated_upper_bound": ledger.upper_bound,
        "seed_adoption_is_improvement": False,
        "analytical_lower_bound": analytical_bound(p),
        "certified_lower_bound": analytical_bound(p),
    }
    if config.phase == "replay":
        result["all_stop"] = replay_all_stop(p, out, deadline)
    built = None
    with (out / "events.jsonl").open("w") as events:

        def event(item):
            events.write(
                json.dumps({"elapsed_seconds": perf_counter() - started, **item}) + "\n"
            )
            events.flush()

        event({"kind": "reference_validated", **result})
        try:
            if config.phase == "hybrid":
                from ..optimization.ddd.reservoir_hybrid.optimizer import (
                    ReservoirHybridOptimizer,
                    ReservoirHybridConfig,
                )
                from ..optimization.ddd.reservoir_hybrid.certificates import (
                    read_global_bound_result,
                )

                initial_bound = (
                    None
                    if config.initial_bound_result is None
                    else read_global_bound_result(config.initial_bound_result, p)
                )
                candidate, hybrid = ReservoirHybridOptimizer(
                    ReservoirHybridConfig(
                        time_limit=max(0.001, deadline - perf_counter()),
                        workers=config.num_workers,
                        seed=config.seed,
                        repair_presolve=config.repair_presolve,
                        normalize_empty_tails=config.normalize_empty_tails,
                    )
                ).solve(
                    p,
                    primal_seed=plan,
                    initial_bound=initial_bound,
                    on_event=event,
                    on_improvement=lambda s: write_reservoir_cp_checkpoint(
                        out / "incumbent.json", p, s
                    ),
                )
                result.update(hybrid, status="hybrid_complete")
                write_reservoir_cp_checkpoint(out / "best.json", p, candidate)
            if config.phase == "refine":
                from ..optimization.ddd.reservoir_hybrid.refinement import (
                    ReservoirBoundRefiner,
                )

                refined = ReservoirBoundRefiner().solve(
                    p,
                    plan,
                    time_limit=max(0.001, deadline - perf_counter()),
                    method=config.lp_method,
                    workers=config.num_workers,
                    on_round=lambda item: (
                        atomic_json(out / f"round_{item['round']}.json", item),
                        event(item),
                    ),
                    max_rounds=config.refinement_rounds,
                )
                result.update(refined, status="refinement_complete")
            if config.phase == "repair":
                from ..optimization.ddd.reservoir_hybrid.repair import (
                    ReservoirRepairProblem,
                    ReservoirRepairOptimizer,
                )

                context = ReservoirRepairProblem.prepare(
                    p, plan, config.open_deployments, config.new_slots
                )
                candidate, repaired = ReservoirRepairOptimizer().solve(
                    context,
                    time_limit=max(0.001, deadline - perf_counter()),
                    workers=config.num_workers,
                    on_improvement=lambda s: write_reservoir_cp_checkpoint(
                        out / "incumbent.json", p, s
                    ),
                    log_path=out / "solver.log",
                    presolve=config.repair_presolve,
                    seed=config.seed,
                )
                ledger.accept_plan(candidate)
                result.update(repaired)
                write_reservoir_cp_checkpoint(out / "best.json", p, ledger.plan)
            if config.phase == "bound":
                prepared = prepare_bound(p, part, deadline)
                event(
                    {
                        "kind": "network_built",
                        "arcs": len(prepared.arcs),
                        "network_build_seconds": prepared.build_seconds,
                    }
                )
                built = ReservoirArrivalBoundBuilder().build(
                    prepared,
                    config.bound_profile,
                    deadline=deadline,
                    max_variables=config.max_variables,
                    max_rows=config.max_rows,
                    journey_encoding=config.journey_encoding,
                )
                built.model.Params.LogFile = str(out / "solver.log")
                built.model.Params.LogToConsole = 0
                built.model.Params.OutputFlag = 1
                atomic_json(out / "projection.json", built.project(plan))
                event(
                    {
                        "kind": "model_built",
                        "variables": built.model.NumVars,
                        "rows": built.model.NumConstrs,
                    }
                )
                if config.build_only:
                    result.update(
                        status="build_only_complete",
                        variables=built.model.NumVars,
                        rows=built.model.NumConstrs,
                    )
                else:
                    bound, solved = ReservoirArrivalBoundOptimizer().solve(
                        built,
                        deadline=deadline,
                        threads=config.num_workers,
                        events=event,
                        method=config.lp_method,
                    )
                    ledger.accept_bound(bound)
                    result.update(solved)
                result["network_build_seconds"] = prepared.build_seconds
        except (BoundSizeLimit, TimeoutError) as error:
            result.update(
                status="model_size_limit"
                if isinstance(error, BoundSizeLimit)
                else "deadline",
                detail=str(error),
            )
            if isinstance(error, BoundSizeLimit):
                result["partial_variable_families"] = error.variable_families
                result["partial_row_families"] = error.row_families
            event({"kind": "gate_limit", **result})
        finally:
            if built:
                built.model.dispose()
        result["actual_total_seconds"] = perf_counter() - started
        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        result["peak_rss_bytes"] = rss if sys.platform == "darwin" else rss * 1024
        event({"kind": "finished", **result})
    atomic_json(out / "result.json", result)
    return result


def replay_all_stop(problem, out, deadline):
    """Reproduce analytic movement and optimize only its integer assignment."""
    from .ddd_reservoir_arc_flow import (
        DddReservoirArcFlowRunConfig,
        prepare_ddd_reservoir_arc_flow_run,
    )
    from .ddd_reservoir_cp_sat import all_stop_reservoir_movement, _plan
    from ..optimization.ddd.cp_sat_integrated import DddIntegratedCpSatConfig
    from ..optimization.ddd.reservoir_cp_sat import DddReservoirCpSatOptimizer
    from ..optimization.ddd.reservoir_cp_sat_certificate import (
        validate_reservoir_cp_plan,
        write_reservoir_cp_checkpoint,
        read_reservoir_cp_checkpoint,
    )

    source = prepare_ddd_reservoir_arc_flow_run(
        DddReservoirArcFlowRunConfig(
            example_id="five_station_circle_cw_half_skip_no_wait_headway_b_v0",
            available_fleet_count=problem.available_fleet_count,
            waiting_max_seconds=1200,
            waiting_step_seconds=0.000001,
        )
    ).problem
    movement = all_stop_reservoir_movement(problem, source)
    if movement is None:
        raise ValueError("analytic All-Stop reference unavailable")
    left = deadline - perf_counter()
    if left <= 0:
        raise TimeoutError("deadline before fixed All-Stop assignment")
    solved = DddReservoirCpSatOptimizer(
        DddIntegratedCpSatConfig(total_time_limit_seconds=min(60, left), num_workers=1)
    ).solve(problem, fixed_plan=movement)
    atomic_json(out / "all_stop_assignment.json", solved)
    if solved.get("solver_status") != "OPTIMAL":
        raise ValueError("All-Stop assignment was not proved optimal; G0 remains open")
    plan = _plan(solved["plan"])
    metrics = validate_reservoir_cp_plan(problem, plan)
    write_reservoir_cp_checkpoint(out / "all_stop.json", problem, plan)
    read_reservoir_cp_checkpoint(out / "all_stop.json", problem)
    return {
        "metrics": asdict(metrics),
        "scope": "fixed_movement_assignment",
        "solver_status": solved.get("solver_status"),
    }
