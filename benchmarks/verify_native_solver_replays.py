"""Correctness gate, not a free-search benchmark; no historical files changed."""

import argparse
import hashlib
import json
from pathlib import Path

from ropeway_skip_stop_optimization.benchmarking.ddd_fixed_k_didp import prepare_large
from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_certificate import (
    atomic_json,
    read_ddd_cp_sat_checkpoint,
    validate_ddd_cp_sat_domain,
)
from ropeway_skip_stop_optimization.optimization.ddd.native_solvers import (
    NativeSolverConfig,
    solve_native,
)
from ropeway_skip_stop_optimization.optimization.ddd.native_solvers.optimizer import (
    validate_plan,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_hybrid.domain import (
    load_reference,
)

ROOT = Path(__file__).resolve().parents[1]
REFERENCES = {
    "R": ROOT
    / "benchmarks/output/reservoir_global_repair_campaign_20260911_v1/common_seed.json",
    "K38": ROOT
    / "benchmarks/output/pattern_search_20260910/seeds/k38_waiting_n3074/incumbent.json",
    "C": ROOT / "benchmarks/output/pattern_search_followup_20260910/run/incumbent.json",
}


def frozen_cases():
    domain, seed = load_reference(REFERENCES["R"])
    cases = {"R": (domain.problem, seed, "journey_time", 368765817136)}
    for key, k, expected in [("K38", 38, 315), ("C", 39, 1402)]:
        _, p = prepare_large(k)
        seed = read_ddd_cp_sat_checkpoint(
            REFERENCES[key], problem=p, manifest=validate_ddd_cp_sat_domain(p)
        )
        cases[key] = (p, seed, "unserved", expected)
    for p, seed, obj, expected in cases.values():
        _, metrics = validate_plan(p, seed)
        value = metrics["journey_time_tick" if obj == "journey_time" else "unserved"]
        if value != expected:
            raise ValueError(f"frozen reference changed: {value} != {expected}")
    return cases


def passenger_oracle(problem, seed, objective):
    """Derive the comparison optimum; a historical incumbent is not a proof."""
    from ortools.sat.python import cp_model

    from ropeway_skip_stop_optimization.optimization.ddd.fixed_timetable_capacity import (
        FixedTimetableCapacityProbe,
    )
    from ropeway_skip_stop_optimization.optimization.ddd.reservoir_cp_sat import (
        _extract,
        _movement_values,
        build_reservoir_cp_sat,
    )

    if objective == "unserved":
        result = FixedTimetableCapacityProbe(time_limit_seconds=30, workers=1).solve(
            problem, seed.solution
        )
        return {
            "status": result["solver_status"],
            "optimum": result["unserved_upper_bound"],
            "lower_bound": result["unserved_lower_bound"],
            "proven_optimal": result["solver_status"] == "OPTIMAL",
            "proof_scope": "FIXED_MOVEMENT",
            "independently_validated": True,
        }
    built = build_reservoir_cp_sat(problem)
    model = built.movement.model
    for index, value in _movement_values(problem, built, seed).items():
        model.add(model.get_int_var_from_proto_index(index) == value)
    model.minimize(built.passengers.objective_expression)
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 30
    solver.parameters.num_search_workers = 1
    solver.parameters.absolute_gap_limit = 0
    solver.parameters.relative_gap_limit = 0
    status = solver.solve(model)
    value = None
    if status in (cp_model.FEASIBLE, cp_model.OPTIMAL):
        _, metrics = validate_plan(problem, _extract(problem, built, solver.value))
        value = metrics["journey_time_tick"]
    return {
        "status": solver.status_name(status),
        "optimum": value,
        "lower_bound": solver.best_objective_bound,
        "proven_optimal": status == cp_model.OPTIMAL
        and value == solver.best_objective_bound,
        "proof_scope": "FIXED_MOVEMENT",
        "independently_validated": value is not None,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", choices=["z3", "hexaly"], required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--comparison-time-limit", type=float, default=90)
    parser.add_argument("--oracle-only", action="store_true")
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=False)
    source_root = (
        ROOT / "src/ropeway_skip_stop_optimization/optimization/ddd/native_solvers"
    )
    report = {
        "backend": args.backend,
        "passed": True,
        "cases": [],
        "source_hashes": {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in source_root.glob("*.py")
        },
    }
    for key, (p, seed, objective, expected) in frozen_cases().items():
        oracle = passenger_oracle(p, seed, objective)
        atomic_json(args.output_dir / f"{key}_passenger_oracle.json", oracle)
        if not oracle["proven_optimal"]:
            report["passed"] = False
        if args.oracle_only:
            print(json.dumps({"case": key, **oracle}), flush=True)
            continue
        for fix_passengers in (True, False):
            label = f"{key}_{'replay' if fix_passengers else 'passenger_optimum'}"
            result, _ = solve_native(
                p,
                NativeSolverConfig(
                    backend=args.backend,
                    objective=objective,
                    time_limit=90 if fix_passengers else args.comparison_time_limit,
                ),
                fixed_plan=seed,
                fix_passengers=fix_passengers,
            )
            target = expected if fix_passengers else oracle["optimum"]
            passed = (
                result["error"] is None
                and result["proven_optimal"]
                and result["native_objective"] == target
                and (fix_passengers or oracle["proven_optimal"])
            )
            atomic_json(args.output_dir / f"{label}.json", result)
            report["cases"].append(
                {
                    "case": label,
                    "passed": passed,
                    "value": result["native_objective"],
                    "expected": target,
                    "seconds": result["timings"]["total_seconds"],
                    "error": result["error"],
                }
            )
            report["passed"] &= passed
            atomic_json(args.output_dir / "gate.json", report)
            print(json.dumps(report["cases"][-1]), flush=True)
    if args.oracle_only:
        # Oracle-only never creates an engine-admission gate.
        atomic_json(
            args.output_dir / "oracles.json", {"all_oracles_proven": report["passed"]}
        )
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
