"""Revalidate and freeze selected historical plans; polish a completed CP run."""

from __future__ import annotations

import argparse
from hashlib import sha256
import importlib.metadata
import json
from pathlib import Path
import platform
import shutil
import subprocess
from time import perf_counter

from ropeway_skip_stop_optimization.benchmarking.ddd_fixed_k_arc_flow import (
    DddFixedKArcFlowRunConfig,
    prepare_ddd_fixed_k_arc_flow_run,
)
from ropeway_skip_stop_optimization.benchmarking.ddd_fixed_k_cp_sat import (
    _load_result_trajectories,
)
from ropeway_skip_stop_optimization.benchmarking.ddd_cp_sat_waiting import (
    with_exit_waiting,
)
from ropeway_skip_stop_optimization.benchmarking.ddd_scaling import (
    build_initial_ddd_network_problem,
)
from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_certificate import (
    atomic_json,
    read_ddd_cp_sat_checkpoint,
    solution_from_cp_sat_payload,
    validate_ddd_cp_sat_domain,
    validate_ddd_cp_sat_incumbent,
    write_ddd_cp_sat_checkpoint,
)
from ropeway_skip_stop_optimization.optimization.ddd.fixed_k import (
    DddFixedKOperatingMode,
    DddFixedKStartPolicy,
)
from ropeway_skip_stop_optimization.optimization.ddd.primal_evaluation import (
    DddEanPassengerPrimalEvaluator,
)
from ropeway_skip_stop_optimization.optimization.ddd.reference import (
    DddReferenceSolution,
)

EXAMPLE = "five_station_circle_cw_half_skip_no_wait_headway_b_v0"
ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "benchmarks/output/solver_followup_20260909"


def prepare(k, waiting=0, mode="skip_stop"):
    prepared = prepare_ddd_fixed_k_arc_flow_run(
        DddFixedKArcFlowRunConfig(
            EXAMPLE,
            k,
            DddFixedKOperatingMode(mode),
            start_policy=DddFixedKStartPolicy.BALANCED_REFERENCE,
        )
    )
    return (
        with_exit_waiting(prepared, maximum_seconds=waiting, step_seconds=1e-6)
        if waiting
        else prepared
    )


def polish(prepared, solution, output):
    """Retain the exact problem demand and independently optimize fixed movement."""
    started = perf_counter()
    problem = prepared.problem
    manifest = validate_ddd_cp_sat_domain(problem)
    validate_ddd_cp_sat_incumbent(
        problem, solution, {}, provenance="movement_validation"
    )
    evaluation = DddEanPassengerPrimalEvaluator(
        scenario=prepared.scenario,
        artifact=problem.artifact,
        objective=problem.objective,
        waiting_policy=problem.resolved_trajectory_problem.waiting_policy,
        passenger_candidate_build=problem.passenger_build,
        time_limit_seconds=30,
        mip_gap=0,
        threads=1,
    ).evaluate(
        build_initial_ddd_network_problem(
            problem.resolved_trajectory_problem.structural_movement_problem
        ),
        solution,
    )
    if evaluation.passenger_plan is None:
        raise RuntimeError(f"Independent assignment failed: {evaluation.status}")
    ids = {
        (q.demand_group_id, q.cabin_id, q.board_visit_index, q.alight_visit_index): q.id
        for q in problem.passenger_build.ride_candidates
    }
    counts = {}
    for ride in evaluation.passenger_plan.served_rides:
        key = ids[
            ride.demand_group_id,
            ride.cabin_id,
            ride.board_visit_index,
            ride.alight_visit_index,
        ]
        counts[key] = counts.get(key, 0) + int(round(ride.count))
    checked = validate_ddd_cp_sat_incumbent(
        problem, solution, counts, provenance="independent_fixed_movement_ip"
    )
    if abs(checked.objective - evaluation.objective_value) > 1e-5:
        raise RuntimeError(
            "Independent assignment objective disagrees with certificate"
        )
    write_ddd_cp_sat_checkpoint(
        output / "cp_seed.json", problem=problem, manifest=manifest, incumbent=checked
    )
    result = dict(
        objective=checked.objective,
        served=sum(counts.values()),
        unserved=sum(checked.unserved_counts.values()),
        solver_status=evaluation.solver_status,
        proof_scope="FIXED_MOVEMENT",
        setup_seconds=evaluation.setup_seconds,
        solve_seconds=evaluation.solve_seconds,
        evaluator_total_seconds=evaluation.total_seconds,
        total_seconds=perf_counter() - started,
        problem_fingerprint=problem.fingerprint,
        legacy_problem_fingerprint=problem.legacy_fingerprint,
        finite_validation="PASSED",
        continuation_status="NOT_PROVEN",
    )
    atomic_json(output / "validation.json", result)
    atomic_json(output / "problem_manifest.json", problem.certificate_manifest)
    return checked, result


def freeze():
    folder = OUTPUT / "frozen"
    folder.mkdir(parents=True, exist_ok=False)
    historic = ROOT / "benchmarks/output"
    boundary = (
        historic
        / "ddd_fixed_k_arc_flow_campaigns/five_station_b_balanced_fixed_k_boundary_screening/policies"
    )
    cases = [
        (
            "k20_all_stop",
            20,
            0,
            "all_stop",
            boundary / "all_stop/k20/result.json",
            635519.998,
        ),
        (
            "k20_skip_stop",
            20,
            0,
            "skip_stop",
            boundary / "skip_stop/k20/result.json",
            525730.908,
        ),
        (
            "k38_all_stop",
            38,
            0,
            "all_stop",
            boundary / "all_stop/k38/result.json",
            399287.271408,
        ),
        (
            "k39_no_wait",
            39,
            0,
            "skip_stop",
            historic
            / "ddd_integrated_cp_sat_waiting/k39/no_wait_600s_seed0/best_incumbent.json",
            1262099.935264,
        ),
        (
            "k39_waiting",
            39,
            1200,
            "skip_stop",
            historic / "ddd_reservation_insertion/assignment_polished_v1/cp_seed.json",
            1007532.083464,
        ),
    ]
    results = []
    all_stop38 = None
    for name, k, waiting, mode, source, expected in cases:
        target = folder / name
        target.mkdir()
        prepared = prepare(k, waiting, mode)
        raw = json.loads(source.read_text())
        if raw.get("schema", "").startswith("integrated_cp_sat"):
            seed = read_ddd_cp_sat_checkpoint(
                source,
                problem=prepared.problem,
                manifest=validate_ddd_cp_sat_domain(prepared.problem),
            )
            solution = seed.solution
        else:
            solution = DddReferenceSolution(
                _load_result_trajectories(source, prepared.problem, raw)
            )
        checked, result = polish(prepared, solution, target)
        if abs(checked.objective - expected) > 0.01:
            raise RuntimeError(
                f"{name}: historical objective not reproduced: {checked.objective} vs {expected}"
            )
        shutil.copyfile(source, target / "source.json")
        results.append(
            dict(
                case=name,
                source=str(source),
                source_sha256=sha256(source.read_bytes()).hexdigest(),
                **result,
            )
        )
        if name == "k38_all_stop":
            all_stop38 = checked
        print(name, result, flush=True)
    # Explicitly transfer only the known All-Stop movement into free Skip-Stop
    # Waiting; use the target's physical resource representation and revalidate.
    prepared = prepare(38, 1200)
    target = folder / "k38_all_stop_in_waiting"
    target.mkdir()
    solution = solution_from_cp_sat_payload(prepared.problem, all_stop38.to_payload())
    checked, result = polish(prepared, solution, target)
    if abs(checked.objective - 399287.271408) > 1e-5:
        raise RuntimeError("K38 All-Stop inclusion changed passenger objective")
    results.append(dict(case="k38_all_stop_in_waiting", **result))
    atomic_json(folder / "headline_validation.json", results)
    files = [
        ROOT / "pyproject.toml",
        *sorted((ROOT / "src").rglob("*.py")),
        *sorted((ROOT / "benchmarks").glob("*.py")),
    ]
    files = [p for p in files if "frontend" not in p.relative_to(ROOT).parts]
    atomic_json(
        folder / "software_snapshot.json",
        {
            "git_head": subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
            ).strip(),
            "git_status": subprocess.check_output(
                ["git", "status", "--short"], cwd=ROOT, text=True
            ),
            "platform": platform.platform(),
            "python": platform.python_version(),
            "packages": {
                name: importlib.metadata.version(name)
                for name in ["ortools", "gurobipy"]
            },
            "source_sha256": {
                str(p.relative_to(ROOT)): sha256(p.read_bytes()).hexdigest()
                for p in files
            },
        },
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["freeze", "polish"])
    parser.add_argument("--run-dir", type=Path)
    args = parser.parse_args()
    if args.action == "freeze":
        freeze()
        return
    config = json.loads((args.run_dir / "config.json").read_text())
    prepared = prepare(
        config["cabin_count"], config["maximum_wait_seconds"], config["operating_mode"]
    )
    checkpoint = args.run_dir / "incumbent.json"
    checked = read_ddd_cp_sat_checkpoint(
        checkpoint,
        problem=prepared.problem,
        manifest=validate_ddd_cp_sat_domain(prepared.problem),
    )
    output = args.run_dir / "post_ip"
    output.mkdir(exist_ok=False)
    _, result = polish(prepared, checked.solution, output)
    result["raw_cp_ub"] = checked.objective
    atomic_json(output / "validation.json", result)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
