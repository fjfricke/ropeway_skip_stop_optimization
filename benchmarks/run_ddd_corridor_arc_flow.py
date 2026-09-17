"""Run the fixed-start interval-corridor arc-flow pilot."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sys
from time import perf_counter

from ropeway_skip_stop_optimization.benchmarking.ddd_fixed_k_didp import (
    EXAMPLE,
    prepare_large,
    prepare_small,
)
from ropeway_skip_stop_optimization.optimization.ddd.corridor_arc_flow import (
    CorridorAdaptiveConfig,
    CorridorAdaptiveOptimizer,
    CorridorArcFlowConfig,
    CorridorArcFlowMode,
    CorridorArcFlowOptimizer,
    CorridorArcFlowSolveConfig,
    build_cycle_spacing_waiting_policy,
    prepare_corridor_problem,
    optimize_corridor_seed_passengers,
)
from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_certificate import (
    atomic_json,
    solution_from_cp_sat_payload,
)
from ropeway_skip_stop_optimization.optimization.ddd.fixed_k import DddFixedKStartPolicy
from ropeway_skip_stop_optimization.benchmarking.ddd_scaling import (
    build_initial_ddd_network_problem,
)
from ropeway_skip_stop_optimization.optimization.ddd.fixed_k_seed import (
    DddFixedKSeedCoordinator,
    DddFixedKSeedStatus,
)
from ropeway_skip_stop_optimization.optimization.ddd.fixed_k_primal_seed import (
    load_ddd_fixed_k_root_cg_seed_trajectories,
)
from ropeway_skip_stop_optimization.optimization.ddd.reference import DddReferenceSolution
from ropeway_skip_stop_optimization.optimization.ddd.fixed_k_certificate import (
    DddFixedKPrimalValidator,
)
from ropeway_skip_stop_optimization.benchmarking.environment import (
    current_git_commit,
    git_is_dirty,
    gurobi_version,
)
from ropeway_skip_stop_optimization.benchmarking.native_solvers import supervise


def _payload(result):
    data = asdict(result)
    data.pop("solution", None)
    data.pop("relaxed_candidate", None)
    data["status"] = result.status.value
    data["mode"] = result.mode.value
    return data


def _source_hashes() -> dict[str, str]:
    root = Path(__file__).resolve().parents[1]
    files = [Path(__file__), *sorted((
        root / "src/ropeway_skip_stop_optimization/optimization/ddd/corridor_arc_flow"
    ).glob("*.py"))]
    return {
        str(path.resolve().relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in files
    }


def main() -> None:
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("--mode", choices=["inner", "outer", "adaptive"], default="adaptive")
    parser.add_argument("--example", default=EXAMPLE)
    parser.add_argument("--cabins", type=int, required=True)
    parser.add_argument("--small-case", action="store_true")
    parser.add_argument("--start-policy", choices=["canonical_rope", "balanced_reference"], default="balanced_reference")
    parser.add_argument("--demand", type=int, default=3074)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--waiting-cap-multiplier", type=float)
    group.add_argument("--maximum-wait-seconds", type=float)
    parser.add_argument("--time-limit", type=float, default=300.0)
    parser.add_argument("--threads", type=int, default=12)
    parser.add_argument("--memory-limit-gib", type=float, default=32.0)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--checkpoint-import", type=Path)
    parser.add_argument("--seed-time-limit", type=float, default=30.0)
    parser.add_argument("--seed-passenger-time-limit", type=float, default=30.0)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--build-only", action="store_true")
    parser.add_argument("--_worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if not 0 < args.memory_limit_gib <= 32:
        parser.error("--memory-limit-gib must lie in (0, 32]")
    if not args._worker:
        args.output_dir.mkdir(parents=True, exist_ok=False)
        atomic_json(args.output_dir / "arguments.json", {
            **{k: str(v) if isinstance(v, Path) else v for k, v in vars(args).items()},
        })
        metrics = supervise(
            [sys.executable, str(Path(__file__).resolve()), *sys.argv[1:], "--_worker"],
            args.output_dir,
            seconds=args.time_limit,
            memory_bytes=int(args.memory_limit_gib * 1024**3),
            system_memory_pressure_seconds=30.0,
        )
        summary = {"supervisor": metrics}
        result_path = args.output_dir / "result.json"
        if result_path.is_file():
            result_payload = json.loads(result_path.read_text())
            summary["result_schema"] = result_payload.get("schema")
            summary["best_validated_unserved"] = (
                result_payload.get("best_inner") or {}
            ).get("objective_value", result_payload.get("objective_value"))
            summary["global_lower_bound"] = result_payload.get(
                "best_global_lower_bound",
                result_payload.get("certified_global_lower_bound"),
            )
        print(json.dumps(summary, indent=2), flush=True)
        return
    args.output_dir.mkdir(parents=True, exist_ok=True)
    started = perf_counter()
    formulation = CorridorArcFlowConfig(
        waiting_cap_multiplier=(
            None
            if args.maximum_wait_seconds is not None
            else (2.0 if args.waiting_cap_multiplier is None else args.waiting_cap_multiplier)
        ),
        explicit_maximum_wait_seconds=args.maximum_wait_seconds,
    )
    if args.small_case:
        scenario, base = prepare_small(args.cabins, waiting=1, step=1e-6)
    else:
        scenario, base = prepare_large(
            args.cabins, example=args.example, waiting=0, demand=args.demand,
            start_policy=DddFixedKStartPolicy(args.start_policy),
        )
    policy = build_cycle_spacing_waiting_policy(base, formulation)
    maximum = max(value for _, value in policy.maximum_wait_seconds_by_station_id)
    if args.small_case:
        scenario, problem = prepare_small(args.cabins, waiting=maximum, step=1e-6)
    else:
        scenario, problem = prepare_large(
            args.cabins, example=args.example, waiting=maximum, step=1e-6,
            demand=args.demand, start_policy=DddFixedKStartPolicy(args.start_policy),
        )
    seed_solution = None
    seed_ride_counts = None
    if args.checkpoint_import is not None:
        raw_checkpoint = json.loads(args.checkpoint_import.read_text())
        if raw_checkpoint.get("schema") in ("integrated_cp_sat_v1", "integrated_cp_sat_v2"):
            raw_incumbent = raw_checkpoint["incumbent"]
            seed_solution = solution_from_cp_sat_payload(problem, raw_incumbent)
            seed_ride_counts = {
                key: int(value) for key, value in raw_incumbent["ride_counts"].items()
            }
            DddFixedKPrimalValidator().validate(
                problem,
                seed_solution,
                seed_ride_counts,
                provenance=f"corridor_import:{args.checkpoint_import}",
            )
        else:
            trajectories, _ = load_ddd_fixed_k_root_cg_seed_trajectories(
                args.checkpoint_import, problem=problem
            )
            seed_solution = DddReferenceSolution(trajectories)
    elif not args.build_only and args.seed_time_limit > 0:
        seed_result = DddFixedKSeedCoordinator(
            cp_sat_time_limit_seconds=args.seed_time_limit,
            cp_sat_num_workers=args.threads,
        ).solve(
            build_initial_ddd_network_problem(
                problem.resolved_trajectory_problem.structural_movement_problem
            ),
            boundary_occurrences=problem.boundary_context.resource_occurrences,
        )
        if seed_result.status is DddFixedKSeedStatus.INTERNAL_VALIDATION_ERROR:
            raise RuntimeError(seed_result.detail or "corridor seed validation failed")
        if seed_result.status is DddFixedKSeedStatus.FEASIBLE:
            seed_solution = DddReferenceSolution(seed_result.trajectories)
    prepared = prepare_corridor_problem(problem, config=formulation, seed=seed_solution)
    seed_passenger_result = None
    if seed_solution is not None and not args.build_only and args.seed_passenger_time_limit > 0:
        available = max(0.001, args.time_limit - (perf_counter() - started))
        seed_passenger_result = optimize_corridor_seed_passengers(
            prepared,
            seed_solution,
            time_limit_seconds=min(args.seed_passenger_time_limit, available),
            threads=args.threads,
        )
        seed_ride_counts = dict(seed_passenger_result.ride_counts)
        atomic_json(args.output_dir / "seed_passengers.json", asdict(seed_passenger_result))
    elapsed_before_solve = perf_counter() - started
    remaining_seconds = max(0.001, args.time_limit - elapsed_before_solve)
    atomic_json(args.output_dir / "config.json", {
        **{k: str(v) if isinstance(v, Path) else v for k, v in vars(args).items()},
        "resolved_maximum_wait_seconds": maximum,
        "problem_fingerprint": problem.fingerprint,
        "model_fingerprint": prepared.model_fingerprint,
        "git_commit": current_git_commit(),
        "git_dirty": git_is_dirty(),
        "gurobi_version": gurobi_version(),
        "source_hashes": _source_hashes(),
        "checkpoint_sha256": (
            None if args.checkpoint_import is None
            else hashlib.sha256(args.checkpoint_import.read_bytes()).hexdigest()
        ),
    })
    atomic_json(args.output_dir / "prepared.json", {
        "time_partition_count": len(prepared.time_partitions),
        "wait_partition_count": len(prepared.wait_partitions),
        "corridor_count": len(prepared.arcs),
        "waiting_policy": asdict(prepared.waiting_policy),
        "preparation_seconds": perf_counter() - started,
        "remaining_solver_seconds": remaining_seconds,
        "seed_available": seed_solution is not None,
    })
    if args.build_only:
        return
    if args.mode == "adaptive":
        live_rounds = []

        def save_round(item):
            live_rounds.append({
                "index": item.index,
                "inner": None if item.inner is None else _payload(item.inner),
                "outer": None if item.outer is None else _payload(item.outer),
                "split_keys": item.split_keys,
                "split_boundaries": item.split_boundaries,
                "conflicting_corridor_count": item.conflicting_corridor_count,
            })
            atomic_json(args.output_dir / "progress.json", {
                "schema": "ddd_corridor_adaptive_progress_v1",
                "elapsed_seconds": perf_counter() - started,
                "rounds": live_rounds,
            })

        result = CorridorAdaptiveOptimizer(
            CorridorAdaptiveConfig(
                total_time_limit_seconds=remaining_seconds,
                threads=args.threads,
                seed=args.seed,
                memory_limit_gib=args.memory_limit_gib,
            ), formulation,
        ).solve(
            prepared,
            seed=seed_solution,
            seed_ride_counts=seed_ride_counts,
            round_callback=save_round,
        )
        rounds = []
        for item in result.rounds:
            rounds.append({
                "index": item.index,
                "inner": None if item.inner is None else _payload(item.inner),
                "outer": None if item.outer is None else _payload(item.outer),
                "split_keys": item.split_keys,
                "split_boundaries": item.split_boundaries,
                "conflicting_corridor_count": item.conflicting_corridor_count,
            })
        payload = {
            "schema": "ddd_corridor_adaptive_result_v1",
            "best_inner": None if result.best_inner is None else _payload(result.best_inner),
            "best_global_lower_bound": result.best_global_lower_bound,
            "rounds": rounds,
            "total_seconds": perf_counter() - started,
        }
        solution = None if result.best_inner is None else result.best_inner.solution
    else:
        result = CorridorArcFlowOptimizer(CorridorArcFlowSolveConfig(
            mode=CorridorArcFlowMode(args.mode), time_limit_seconds=remaining_seconds,
            threads=args.threads, seed=args.seed,
            memory_limit_gib=args.memory_limit_gib,
        )).solve(
            prepared, seed=seed_solution, seed_ride_counts=seed_ride_counts
        )
        payload = {"schema": "ddd_corridor_result_v1", **_payload(result), "total_seconds": perf_counter() - started}
        solution = result.solution
    atomic_json(args.output_dir / "result.json", payload)
    if solution is not None:
        atomic_json(args.output_dir / "best_movement.json", asdict(solution))
    if args.mode == "adaptive":
        summary = {
            "schema": payload["schema"],
            "best_validated_unserved": (
                None if result.best_inner is None else result.best_inner.objective_value
            ),
            "global_lower_bound": result.best_global_lower_bound,
            "round_count": len(result.rounds),
            "total_seconds": payload["total_seconds"],
        }
    else:
        summary = {
            "schema": payload["schema"],
            "status": result.status.value,
            "validated_unserved": (
                result.objective_value if result.solution is not None else None
            ),
            "relaxation_objective": result.objective_value,
            "global_lower_bound": result.certified_global_lower_bound,
            "solver_bound": result.solver_bound,
            "total_seconds": payload["total_seconds"],
        }
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == "__main__":
    main()
