"""Isolated A--D ablations, historical replay gate and a 180-minute campaign."""
from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
import math
import os
from pathlib import Path
import pickle
import resource
import shutil
import signal
import subprocess
import sys
from threading import Lock
from time import perf_counter

from ropeway_skip_stop_optimization.benchmarking.ddd_fixed_k_arc_flow import (
    DddFixedKArcFlowRunConfig, prepare_ddd_fixed_k_arc_flow_run,
)
from ropeway_skip_stop_optimization.benchmarking.ddd_ring_demand_case import (
    DddRingDemandCase, RingDemandFamily, RingDemandTiming,
)
from ropeway_skip_stop_optimization.benchmarking.ddd_scaling import build_initial_ddd_network_problem
from ropeway_skip_stop_optimization.optimization.ddd.arc_flow import DddFixedKArcFlowOptimizer, DddFixedKArcFlowSolveConfig
from ropeway_skip_stop_optimization.optimization.ddd.arc_flow_passenger_formulation import (
    PASSENGER_PROFILES, DddArcFlowPassengerFormulationConfig as Config,
    prepare_arc_flow_passengers,
)
from ropeway_skip_stop_optimization.optimization.ddd.arc_flow_passenger_model import DddArcFlowPassengerModelBuilder
from ropeway_skip_stop_optimization.optimization.ddd.arc_flow_preparation import DddArcFlowProblemPreparer
from ropeway_skip_stop_optimization.optimization.ddd.arc_flow_movement_master import (
    DddArcFlowMovementMasterBuilder, build_ddd_arc_flow_movement_values,
)
from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_certificate import (
    atomic_json, solution_from_cp_sat_payload, validate_ddd_cp_sat_incumbent,
    validate_ddd_cp_sat_domain, write_ddd_cp_sat_checkpoint,
)
from ropeway_skip_stop_optimization.optimization.ddd.fixed_k import DddFixedKOperatingMode, DddFixedKStartPolicy
from ropeway_skip_stop_optimization.optimization.ddd.fixed_k_primal_seed import DddFixedKPrimalSeedFactory
from ropeway_skip_stop_optimization.optimization.ddd.time_ticks import ddd_seconds_to_tick

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = "five_station_circle_cw_half_skip_no_wait_headway_b_v0"
HISTORY = ROOT / "benchmarks/output/solver_followup_20260909"
CASES = {
    "k20_batch": (20, "frozen/k20_all_stop/cp_seed.json", 635519.998080),
    "k20_distributed": (20, "matrix/diffuse_distributed/all_stop/result.json", 332987.270547),
    "k38_control": (38, "frozen/k38_all_stop/cp_seed.json", 399287.271408),
    "k39_batch": (39, "frozen/k39_no_wait/cp_seed.json", 1262099.935264),
}


def integer_counts(counts):
    if any(not math.isfinite(value) or value < -1e-6 or abs(value-round(value)) > 1e-6
           for value in counts.values()):
        raise ValueError("Non-integer native passenger assignment")
    return {key: int(round(value)) for key, value in counts.items() if round(value) > 0}


def factory(prepared, seconds=30):
    problem = prepared.problem
    return DddFixedKPrimalSeedFactory(
        prepared.scenario, problem,
        build_initial_ddd_network_problem(problem.resolved_trajectory_problem.structural_movement_problem),
        passenger_time_limit_seconds=seconds,
    )


def freeze_case(case, folder):
    k, relative, expected = CASES[case]
    prepared = prepare_ddd_fixed_k_arc_flow_run(DddFixedKArcFlowRunConfig(
        EXAMPLE, k, DddFixedKOperatingMode.SKIP_STOP,
        start_policy=DddFixedKStartPolicy.BALANCED_REFERENCE,
        cp_seed_time_limit_seconds=0,
    ))
    if case == "k20_distributed":
        prepared = DddRingDemandCase(RingDemandFamily.DIFFUSE, RingDemandTiming.DISTRIBUTED).apply(prepared)
    source = HISTORY / relative
    raw = json.loads(source.read_text())
    payload = raw.get("incumbent", raw)
    supports = []
    for trajectory in payload["trajectory_supports"]:
        item = dict(trajectory)
        if "switch_times_tick" not in item:
            item["switch_times_tick"] = [ddd_seconds_to_tick(t) for t in item["switch_times_seconds"]]
        if "wait_ticks" not in item and "wait_seconds" in item:
            item["wait_ticks"] = [ddd_seconds_to_tick(t) for t in item["wait_seconds"]]
        supports.append(item)
    solution = solution_from_cp_sat_payload(prepared.problem, {"trajectory_supports": supports})
    seed = factory(prepared).build(solution.trajectories, provenance=f"historical_revalidated:{source}")
    checked = validate_ddd_cp_sat_incumbent(
        prepared.problem, seed.solution, integer_counts(seed.ride_counts_by_candidate_id), provenance=seed.provenance,
    )
    if abs(seed.objective_value - expected) > 1e-4:
        raise ValueError(f"{case}: historical value changed: {seed.objective_value} != {expected}")
    folder.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, folder / "historical_source.json")
    atomic_json(folder / "domain.json", prepared.problem.certificate_manifest)
    write_ddd_cp_sat_checkpoint(folder / "seed.json", problem=prepared.problem,
                               manifest=validate_ddd_cp_sat_domain(prepared.problem), incumbent=checked)
    (folder / "instance.pkl").write_bytes(pickle.dumps((prepared, seed)))
    return prepared, seed


def replay(case_folder, output):
    import gurobipy as gp
    from gurobipy import GRB
    prepared, seed = pickle.loads((case_folder / "instance.pkl").read_bytes())
    structure = DddArcFlowProblemPreparer().build(prepared.problem)
    movement_values = build_ddd_arc_flow_movement_values(structure, seed.solution)
    rows = []
    for profile in PASSENGER_PROFILES:
        started = perf_counter()
        encoding = prepare_arc_flow_passengers(structure, Config.from_profile(profile))
        model = gp.Model()
        model.Params.OutputFlag = 0
        model.Params.Threads = 1
        model.Params.TimeLimit = 60
        model.Params.MIPGap = 0
        movement = DddArcFlowMovementMasterBuilder().build(model=model, prepared=structure)
        for key, variable in movement.route_by_arc_id.items():
            variable.LB = variable.UB = movement_values[key]
        passenger = DddArcFlowPassengerModelBuilder().build_integrated(
            model=model, domain=encoding.source, route_by_arc_id=movement.route_by_arc_id,
            encoding=encoding,
        )
        value = passenger.apply_seed(ride_counts_by_candidate_id=seed.ride_counts_by_candidate_id,
                                     movement_values_by_arc_id=movement_values)
        if abs(value - seed.objective_value) > 1e-4:
            raise ValueError("replay seed objective mismatch")
        model.optimize()
        if model.Status != GRB.OPTIMAL or abs(model.ObjVal - seed.objective_value) > 1e-4:
            raise ValueError(f"replay failed: {case_folder.name}/{profile}, status={model.Status}")
        canonical = passenger.canonical_values()
        metadata = encoding.source.variable_by_id
        counts = {f.candidate_id: sum(canonical[v] for _, v in f.variable_ids_by_arc_id
                                    if metadata[v].visit_index == f.board_visit_index)
                  for f in encoding.source.flows}
        validate_ddd_cp_sat_incumbent(prepared.problem, seed.solution, integer_counts(counts), provenance="fixed_replay")
        rows.append(dict(profile=profile, objective=model.ObjVal, seconds=perf_counter() - started,
                         variables=model.NumVars, integers=model.NumIntVars, rows=model.NumConstrs,
                         model_fingerprint=encoding.fingerprint))
        atomic_json(output, rows)
        print(f"replay {case_folder.name}/{profile}: {model.ObjVal:.6f}", flush=True)
        model.dispose()
    return rows


def run_worker(case_folder, folder, profile, seconds, seed_number):
    started = perf_counter()
    prepared, seed = pickle.loads((case_folder / "instance.pkl").read_bytes())
    problem = prepared.problem
    config = DddFixedKArcFlowSolveConfig(
        time_limit_seconds=max(.001, seconds - (perf_counter() - started) - 10),
        threads=12, seed=seed_number, output_flag=True,
        passenger_formulation=Config.from_profile(profile),
    )
    atomic_json(folder / "config.json", asdict(config))
    manifest = validate_ddd_cp_sat_domain(problem)
    stream = (folder / "events.jsonl").open("w")
    lock = Lock()
    best = seed.objective_value
    validation_seconds = 0.0
    native_first = None
    improvements = []

    def emit(event):
        with lock:
            stream.write(json.dumps(dict(elapsed_seconds=perf_counter() - started, **event), default=str) + "\n")
            stream.flush()

    def incumbent(solution, counts, objective):
        nonlocal best, validation_seconds, native_first
        validation_start = perf_counter()
        checked = validate_ddd_cp_sat_incumbent(problem, solution, integer_counts(counts), provenance=f"arc_flow:{profile}")
        if abs(checked.objective - objective) > 1e-4:
            raise ValueError("native objective differs from independently checked assignment")
        first = native_first is None
        if first:
            native_first = perf_counter() - started
        improved = objective < best - 1e-5
        if first or improved:
            write_ddd_cp_sat_checkpoint(folder / "native_incumbent.json", problem=problem,
                                       manifest=manifest, incumbent=checked)
        if improved:
            best = objective
            improvements.append(dict(seconds=perf_counter() - started, objective=objective))
        emit(dict(kind="validated_incumbent", objective=objective, improved=improved,
                  first_native=first, seed_value=seed.objective_value))
        validation_seconds += perf_counter() - validation_start

    def progress(event):
        data = asdict(event)
        data["solver_elapsed_seconds"] = data.pop("elapsed_seconds")
        emit(dict(kind="progress", **data))

    try:
        result = DddFixedKArcFlowOptimizer(config).solve(
            problem, primal_seed=seed, progress_hook=progress, incumbent_hook=incumbent,
        )
        raw = asdict(result)
        raw.pop("solution", None)
        audit = raw.pop("passenger_audit_json", None)
        if audit:
            atomic_json(folder / "passenger_audit.json", json.loads(audit))
        # Also evaluate the final fixed timetable with the independent integer IP.
        remaining = seconds - (perf_counter() - started)
        post = None
        if result.solution is not None and remaining > .1:
            validation_start = perf_counter()
            post = factory(prepared, min(remaining, 10)).build(result.solution.trajectories, provenance="post_integer_ip")
            checked = validate_ddd_cp_sat_incumbent(problem, post.solution, integer_counts(post.ride_counts_by_candidate_id),
                                                   provenance=post.provenance)
            if post.objective_value <= best + 1e-5:
                best = min(best, post.objective_value)
                write_ddd_cp_sat_checkpoint(folder / "best_incumbent.json", problem=problem,
                                           manifest=manifest, incumbent=checked)
            validation_seconds += perf_counter() - validation_start
        raw.update(validated_upper_bound=best, seed_value=seed.objective_value,
                   first_native_seconds=native_first, improvements=improvements,
                   validation_seconds=validation_seconds, actual_total_seconds=perf_counter() - started,
                   post_ip_objective=None if post is None else post.objective_value,
                   peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * (1 if sys.platform == "darwin" else 1024),
                   unavailable_metrics=["exact_presolved_nonzeros", "root_crossover_seconds"])
        raw["relative_gap"] = max(0, best - raw["certified_lower_bound"]) / max(abs(best), 1e-9)
        atomic_json(folder / "result.json", raw)
    finally:
        stream.close()


def isolated(command, folder, timeout, source_root=None):
    folder.mkdir(parents=True, exist_ok=False)
    started = perf_counter()
    with (folder / "terminal.log").open("w") as log:
        environment = os.environ.copy()
        if source_root is not None:
            environment["PYTHONPATH"] = str(source_root / "src")
        process = subprocess.Popen(command, cwd=ROOT, env=environment,
                                   stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        timed_out = False
        try:
            process.wait(timeout=max(.01, timeout - 2))
        except subprocess.TimeoutExpired:
            timed_out = True
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
    atomic_json(folder / "process.json", dict(returncode=process.returncode, timed_out=timed_out,
                                               actual_seconds=perf_counter() - started))
    return process.returncode == 0 and not timed_out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--freeze-case", choices=tuple(CASES))
    parser.add_argument("--case-folder", type=Path)
    parser.add_argument("--profile", choices=PASSENGER_PROFILES)
    parser.add_argument("--seconds", type=float)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()
    if args.freeze_case:
        freeze_case(args.freeze_case, args.output_dir)
        return
    if args.worker:
        run_worker(args.case_folder, args.output_dir, args.profile, args.seconds, args.seed)
        return
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=False)
    check = subprocess.run([sys.executable, "-m", "pytest", "-q",
                            "tests/test_arc_flow_passenger_profiles.py", "tests/test_optimization_ddd_arc_flow.py",
                            "tests/test_optimization_ddd_passenger_benders.py", "tests/test_arc_flow_passenger_campaign.py"], cwd=ROOT, capture_output=True, text=True)
    (output / "correctness.txt").write_text(check.stdout + check.stderr)
    if check.returncode:
        raise RuntimeError("Correctness tests failed; campaign not started")
    # Historical replay is a correctness test, outside the performance budget.
    gate = output / "gate"
    for case in CASES:
        freeze_case(case, gate / case)
        replay(gate / case, gate / case / "replay.json")
    atomic_json(output / "gate.json", dict(passed=True))
    if args.preflight_only:
        return
    started = perf_counter()
    deadline = started + 10800
    frozen = output / "frozen"
    frozen.mkdir()
    paths = [*ROOT.glob("src/**/*.py"), *ROOT.glob("benchmarks/*.py"), *ROOT.glob("tests/*.py"), ROOT / "pyproject.toml", ROOT / "uv.lock"]
    hashes = {}
    for path in paths:
        if perf_counter() >= deadline - 15:
            raise TimeoutError("Campaign budget exhausted during source freezing")
        relative = path.relative_to(ROOT)
        hashes[str(relative)] = hashlib.sha256(path.read_bytes()).hexdigest()
        target = frozen / "sources" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
    import gurobipy as gp
    atomic_json(frozen / "versions.json", dict(python=sys.version, executable=sys.executable, gurobi=gp.gurobi.version()))
    atomic_json(frozen / "sources.json", hashes)
    for case in ("k20_batch", "k20_distributed", "k39_batch"):
        command = [sys.executable, str(Path(__file__).resolve()), "--freeze-case", case,
                   "--output-dir", str(frozen / case)]
        if not isolated(command, frozen / case, min(180, deadline - perf_counter() - 15)):
            raise RuntimeError("Timed or failed instance freeze; campaign aborted")
        previous = json.loads((gate / case / "domain.json").read_text())
        if previous != json.loads((frozen / case / "domain.json").read_text()):
            raise ValueError("Frozen domain changed since historical replay")
    results = []

    def run(case, profile, seconds, seed):
        if deadline - perf_counter() < seconds + 15:
            results.append(dict(case=case, profile=profile, seed=seed, pending=True))
            return None
        name = f"{case}_{profile}_seed{seed}"
        folder = output / "runs" / name
        print(f"starting {name}, {seconds}s", flush=True)
        command = [sys.executable, str(frozen / "sources/benchmarks/run_arc_flow_passenger_campaign.py"), "--worker", "--output-dir", str(folder),
                   "--case-folder", str(frozen / case), "--profile", profile,
                   "--seconds", str(seconds - 2), "--seed", str(seed)]
        success = isolated(command, folder, seconds, source_root=frozen / "sources")
        row = dict(case=case, profile=profile, seed=seed, folder=str(folder), process_ok=success)
        if (folder / "result.json").exists():
            row.update(json.loads((folder / "result.json").read_text()))
        results.append(row)
        atomic_json(output / "summary.json", dict(results=results, actual_seconds=perf_counter() - started, complete=False))
        print(f"finished {name}: UB={row.get('validated_upper_bound')}, LB={row.get('certified_lower_bound')}", flush=True)
        return row

    for case, seconds in (("k20_batch", 60), ("k20_distributed", 120), ("k39_batch", 900)):
        for profile in PASSENGER_PROFILES:
            run(case, profile, seconds, 0)
    candidates = [r for r in results if r["case"] == "k39_batch" and r["profile"] != "legacy"
                  and r.get("process_ok") and r.get("validated_upper_bound") is not None
                  and not str(r.get("status", "")).startswith("internal")]
    winner = None
    if candidates:
        winner = min(candidates, key=lambda r: (r["validated_upper_bound"], -r["certified_lower_bound"],
                                                r["improvements"][0]["seconds"] if r.get("improvements") else float("inf")))["profile"]
        for seed in (1, 2):
            for profile in ((winner, "legacy") if seed == 1 else ("legacy", winner)):
                run("k39_batch", profile, 900, seed)
    atomic_json(output / "summary.json", dict(results=results, winner=winner, actual_seconds=perf_counter() - started,
                                              complete=True, maximum_seconds=10800))
    from summarize_arc_flow_passenger_campaign import summarize
    summarize(output)


if __name__ == "__main__":
    main()
