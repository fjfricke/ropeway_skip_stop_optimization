"""Demand-only Max50 probe with frozen sources and independently checked fleets."""

import argparse
from dataclasses import asdict, replace
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import pickle
import shutil
import sys
import time

from ropeway_skip_stop_optimization.benchmarking.native_solvers import supervise
from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_certificate import (
    atomic_json,
)
from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_integrated import (
    DddIntegratedCpSatConfig,
)
from ropeway_skip_stop_optimization.optimization.ddd.fixed_timetable_capacity import (
    NestedDemand,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_cp_sat import (
    DddReservoirCpSatOptimizer,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_cp_sat_certificate import (
    read_reservoir_cp_checkpoint,
    validate_reservoir_cp_plan,
    write_reservoir_cp_checkpoint,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_hybrid.domain import (
    load_reference,
)

ROOT = Path(__file__).resolve().parents[1]


def checked_metrics(problem, plan):
    metrics = asdict(validate_reservoir_cp_plan(problem, plan))
    candidates = {q.id: q for q in problem.passenger_build.ride_candidates}
    boards = {t.cabin_id: 0 for t in plan.trips}
    for rid, amount in plan.ride_counts.items():
        boards[candidates[rid].cabin_id] += amount
    metrics.update(
        passenger_carrying_cabins=sum(n > 0 for n in boards.values()),
        boarded_by_cabin=boards,
        empty_cabins=sum(n == 0 for n in boards.values()),
    )
    return metrics


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--reference", type=Path)
    p.add_argument("--prepared-seed", type=Path)
    p.add_argument("--deadline-unix", type=float)
    p.add_argument("--demand", type=int, default=3074)
    p.add_argument("--run-seconds", type=float, default=300)
    p.add_argument("--seeds", type=int, nargs="+", default=[0, 1])
    p.add_argument("--_input", type=Path)
    p.add_argument("--_phase", choices=["prepare", "search"])
    p.add_argument("--_seed", type=int, default=0)
    args = p.parse_args()
    out = args.output_dir.resolve()
    if args._input:
        blob = args._input.read_bytes()
        if (
            hashlib.sha256(blob).hexdigest()
            != args._input.with_suffix(".sha256").read_text()
        ):
            raise ValueError("frozen input hash mismatch")
        problem, old_plan = pickle.loads(
            blob
        )  # Locally generated, hashed private input.
        seed = (
            old_plan
            if args._phase == "prepare"
            else read_reservoir_cp_checkpoint(out.parent / "prepare/best.json", problem)
        )
        write_reservoir_cp_checkpoint(out / "best.json", problem, seed)
        with (out / "events.jsonl").open("w") as stream:

            def emit(event):
                stream.write(json.dumps(event) + "\n")
                stream.flush()

            config = DddIntegratedCpSatConfig(
                total_time_limit_seconds=45
                if args._phase == "prepare"
                else args.run_seconds - 15,
                num_workers=1 if args._phase == "prepare" else 12,
                seed=args._seed,
                checkpoint_path=out / "best.json",
                checkpoint_interval_seconds=1,
                log_search_progress=True,
            )
            result = DddReservoirCpSatOptimizer(config).solve(
                problem,
                primal_seed=seed,
                fixed_plan=seed if args._phase == "prepare" else None,
                event_callback=emit,
            )
        atomic_json(out / "result.json", result)
        plan = read_reservoir_cp_checkpoint(out / "best.json", problem)
        atomic_json(out / "checked_metrics.json", checked_metrics(problem, plan))
        return

    started = time.time()
    deadline = min(started + 900, args.deadline_unix or float("inf"))
    out.mkdir(parents=True, exist_ok=False)
    domain, old_plan = load_reference(args.reference)
    old = domain.problem
    desired = {g.id: g for g in NestedDemand(old.demand_groups).groups(args.demand)}
    problem = replace(
        old, demand_groups=tuple(desired[g.id] for g in old.demand_groups)
    )
    problem.validate()
    if args.demand <= sum(g.count for g in old.demand_groups):
        raise ValueError("probe requires increased demand")
    for a, b in zip(old.demand_groups, problem.demand_groups, strict=True):
        if b.count < a.count or replace(a, count=b.count) != b:
            raise ValueError("demand probe changed more than nested counts")
    a, b = dict(old.manifest), dict(problem.manifest)
    a.pop("demand_groups")
    b.pop("demand_groups")
    if a != b:
        raise ValueError("non-demand domain change")
    if tuple(q.id for q in old.passenger_build.ride_candidates) != tuple(
        q.id for q in problem.passenger_build.ride_candidates
    ):
        raise ValueError("candidate identity changed")
    before = checked_metrics(old, old_plan)
    transported = checked_metrics(problem, old_plan)
    atomic_json(out / "original_metrics.json", before)
    atomic_json(out / "transported_metrics.json", transported)
    atomic_json(out / "original_domain.json", old.manifest)
    atomic_json(out / "domain.json", problem.manifest)
    write_reservoir_cp_checkpoint(out / "transported_seed.json", problem, old_plan)
    if args.prepared_seed:
        prepared_seed = read_reservoir_cp_checkpoint(args.prepared_seed, problem)
        if prepared_seed.trips != old_plan.trips:
            raise ValueError("prepared seed changed fixed movements")
        (out / "prepare").mkdir()
        write_reservoir_cp_checkpoint(out / "prepare/best.json", problem, prepared_seed)
        atomic_json(
            out / "prepare/checked_metrics.json",
            checked_metrics(problem, prepared_seed),
        )
    path = out / "input.pickle"
    blob = pickle.dumps((problem, old_plan))
    path.write_bytes(blob)
    path.with_suffix(".sha256").write_text(hashlib.sha256(blob).hexdigest())
    sources = out / "sources"
    shutil.copytree(
        ROOT / "src",
        sources / "src",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.egg-info"),
    )
    (sources / "benchmarks").mkdir()
    shutil.copy2(__file__, sources / "benchmarks" / Path(__file__).name)
    for name in ("pyproject.toml", "uv.lock"):
        shutil.copy2(ROOT / name, sources / name)
    atomic_json(
        out / "source_hashes.json",
        {
            str(f.relative_to(sources)): hashlib.sha256(f.read_bytes()).hexdigest()
            for f in sources.rglob("*")
            if f.is_file()
        },
    )
    manifest = dict(
        started_unix=started,
        deadline_unix=deadline,
        maximum_seconds=900,
        demand=args.demand,
        original_demand=sum(g.count for g in old.demand_groups),
        operation="reservoir_single_use",
        objective="journey_time",
        workers=12,
        formulation="legacy",
        cost_encoding="product",
        run_seconds=args.run_seconds,
        seeds=args.seeds,
        original_fingerprint=old.fingerprint,
        fingerprint=problem.fingerprint,
        reference_sha256=hashlib.sha256(args.reference.read_bytes()).hexdigest(),
        ortools_version=importlib.metadata.version("ortools"),
        runs=[],
        lower_bound_transfer=False,
        only_demand_changed=True,
        prepared_seed_source=str(args.prepared_seed) if args.prepared_seed else None,
        prepared_seed_sha256=hashlib.sha256(args.prepared_seed.read_bytes()).hexdigest()
        if args.prepared_seed
        else None,
    )
    atomic_json(out / "campaign.json", manifest)
    env = {**os.environ, "PYTHONPATH": str(sources / "src")}
    for name, phase, seed_id, seconds in (
        [] if args.prepared_seed else [("prepare", "prepare", 0, 60)]
    ) + [(f"seed_{s}", "search", s, args.run_seconds) for s in args.seeds]:
        if time.time() + seconds + 20 >= deadline:
            manifest["stop_reason"] = "shared deadline"
            break
        folder = out / name
        folder.mkdir()
        curve = []

        def observe(checkpoint, elapsed):
            plan = read_reservoir_cp_checkpoint(checkpoint, problem)
            metrics = checked_metrics(problem, plan)
            if not curve or metrics != curve[-1]["metrics"]:
                event = {"elapsed_seconds": elapsed, "metrics": metrics}
                curve.append(event)
                atomic_json(folder / "validated_curve.json", {"events": curve})
                print(
                    json.dumps(
                        {
                            "run": name,
                            "elapsed": elapsed,
                            **{
                                k: metrics[k]
                                for k in (
                                    "journey_time_tick",
                                    "served",
                                    "unserved",
                                    "used_fleet",
                                    "peak_active_fleet",
                                    "passenger_carrying_cabins",
                                )
                            },
                        }
                    ),
                    flush=True,
                )

        command = [
            sys.executable,
            str(sources / "benchmarks" / Path(__file__).name),
            "--output-dir",
            str(folder),
            "--_input",
            str(path),
            "--_phase",
            phase,
            "--_seed",
            str(seed_id),
            "--run-seconds",
            str(args.run_seconds),
        ]
        monitor = supervise(
            command,
            folder,
            seconds=seconds,
            global_deadline=deadline,
            checkpoint_callback=observe,
            env=env,
        )
        if (folder / "best.json").exists():
            observe(folder / "best.json", monitor["awake_wall_seconds"])
        result_path = folder / "result.json"
        result = json.loads(result_path.read_text()) if result_path.exists() else None
        entry = {
            "name": name,
            "phase": phase,
            "monitor": monitor,
            "status": result["solver_status"] if result else "INTERRUPTED",
            "metrics": curve[-1]["metrics"] if curve else None,
            "native_lower_bound": result.get("cp_lower_bound") if result else None,
            "proven_optimal": result.get("proven_optimal", False) if result else False,
        }
        manifest["runs"].append(entry)
        atomic_json(out / "campaign.json", manifest)
        if monitor["supervisor_reason"] in (
            "SUSPEND_DETECTED",
            "INVALID_CHECKPOINT",
            "MEMORY_LIMIT",
        ) or monitor["exit_code"] not in (0, -15):
            manifest["stop_reason"] = monitor["supervisor_reason"] or "process failure"
            break
        if phase == "prepare" and (not result or not curve):
            manifest["stop_reason"] = "no validated prepared seed"
            break
    manifest.update(complete=True, actual_seconds=time.time() - started)
    atomic_json(out / "campaign.json", manifest)
    print(
        json.dumps(
            {
                "completed": True,
                "runs": manifest["runs"],
                "actual_seconds": manifest["actual_seconds"],
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
