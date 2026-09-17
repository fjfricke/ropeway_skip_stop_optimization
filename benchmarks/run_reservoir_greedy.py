"""Supervised greedy insertion. Never starts alongside another solver job."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from dataclasses import asdict, replace
from pathlib import Path

import psutil

from ropeway_skip_stop_optimization.benchmarking.native_solvers import supervise
from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_certificate import (
    atomic_json,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_cp_sat_certificate import (
    DddReservoirCpPlan,
    write_reservoir_cp_checkpoint,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_greedy import *
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_greedy.progress import (
    GreedyProgress,
    validated_reference,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_hybrid.domain import (
    load_reference,
)

ROOT = Path(__file__).resolve().parents[1]


def active_solver_jobs():
    own = psutil.Process()
    excluded = {own.pid, *[p.pid for p in own.parents()]}
    found = []
    for p in psutil.process_iter(["pid", "cmdline"]):
        try:
            cmd = p.info["cmdline"] or []
            if p.pid in excluded or not cmd:
                continue
            text = " ".join(cmd)
            if any(
                "run_" + name in text for name in ("thesis", "reservoir", "ddd_")
            ) and any("python" in c for c in cmd[:1]):
                found.append({"pid": p.pid, "command": text})
        except psutil.Error:
            pass
    return found


def main():
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--reference-checkpoint", type=Path, required=True)
    parser.add_argument("--initial-checkpoint", type=Path)
    parser.add_argument("--backend", choices=["cp_sat", "gurobi"], default="cp_sat")
    parser.add_argument(
        "--objective", choices=["unserved", "journey_time"], default="unserved"
    )
    parser.add_argument("--mode", choices=["insert", "construct"], default="construct")
    parser.add_argument("--maximum-cabins", type=int)
    parser.add_argument("--maximum-wait-seconds", type=float, default=60)
    parser.add_argument("--dispatch-window-end", type=float, default=300)
    parser.add_argument("--time-limit", type=float, default=480)
    parser.add_argument("--insertion-time-limit", type=float, default=10)
    parser.add_argument("--extended-time-limit", type=float, default=60)
    parser.add_argument("--workers", type=int, default=12)
    parser.add_argument("--memory-limit-gib", type=float, default=32)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--live-snapshot", type=Path)
    parser.add_argument("--all-stop-reference", type=Path)
    parser.add_argument("--wait-for-solvers", action="store_true")
    parser.add_argument("--build-only", action="store_true")
    parser.add_argument("--_worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    config = GreedyConfig(
        args.backend,
        args.time_limit,
        args.insertion_time_limit,
        args.extended_time_limit,
        args.workers,
        args.seed,
        objective=args.objective,
    )
    if not 0 < args.memory_limit_gib <= 32:
        parser.error("memory maximum is 32 GiB")
    if not args._worker:
        args.output.mkdir(parents=True, exist_ok=False)
        while jobs := active_solver_jobs():
            atomic_json(
                args.output / "waiting.json",
                {
                    "status": "WAITING_FOR_EXISTING_SOLVERS",
                    "jobs": jobs,
                    "updated_unix": time.time(),
                },
            )
            if not args.wait_for_solvers:
                parser.error("another solver is active; use --wait-for-solvers")
            time.sleep(5)
        command = [
            sys.executable,
            str(Path(__file__).resolve()),
            *sys.argv[1:],
            "--_worker",
        ]
        guard = supervise(
            command,
            args.output,
            seconds=args.time_limit,
            memory_bytes=int(args.memory_limit_gib * 1024**3),
            system_memory_pressure_seconds=30,
        )
        atomic_json(args.output / "supervisor.json", guard)
        if guard["supervisor_reason"] or guard["exit_code"]:
            raise SystemExit(1)
        return
    started = time.perf_counter()
    domain, _ = load_reference(args.reference_checkpoint)
    p = pilot_problem(
        domain.problem, args.maximum_wait_seconds, args.dispatch_window_end
    )
    if args.maximum_cabins is not None:
        p = replace(p, available_fleet_count=args.maximum_cabins)
        p.validate()
    initial = DddReservoirCpPlan((), {})
    if args.initial_checkpoint:
        source, initial = load_reference(args.initial_checkpoint)
        # Check source geometry, then validate unchanged certificate in actual target.
        if source.problem.movement_core != domain.problem.movement_core:
            raise ValueError("initial geometry/horizon differs")
        validate_lifecycle(p, initial)
    atomic_json(
        args.output / "instance.json",
        {
            "domain": p.manifest,
            "fingerprint": p.fingerprint,
            "config": asdict(config),
            "sources": {
                str(path.relative_to(ROOT)): hashlib.sha256(
                    path.read_bytes()
                ).hexdigest()
                for path in (
                    ROOT
                    / "src/ropeway_skip_stop_optimization/optimization/ddd/reservoir_greedy"
                ).glob("*.py")
            },
        },
    )
    if args.build_only:
        b = build_insertion(
            prepare_insertion(p, initial),
            deadline=started + args.time_limit,
            objective=args.objective,
        )
        atomic_json(
            args.output / "result.json",
            {
                "status": "BUILT",
                "variables": len(b.movement.model.proto.variables),
                "constraints": len(b.movement.model.proto.constraints),
                "fingerprint": b.fingerprint,
            },
        )
        return
    reference = (
        validated_reference(p, args.all_stop_reference)
        if args.all_stop_reference
        else None
    )
    progress = GreedyProgress()
    last_snapshot = -float("inf")
    last_event = None
    points = []
    steps = 0
    feasible = 0
    best = None

    def snapshot(status="running", last=None, force=False):
        nonlocal last_snapshot, last_event
        if last is not None:
            last_event = last
        now = time.perf_counter()
        if not force and status == "running" and now - last_snapshot < 0.25:
            return
        last_snapshot = now
        atomic_json(args.output / "progress.json", progress.export())
        if args.live_snapshot:
            atomic_json(
                args.live_snapshot,
                {
                    "schema": "reservoir_greedy_live_v1",
                    "label": f"Greedy · {args.backend} · {args.objective} · seed {args.seed}",
                    "objective": args.objective,
                    "status": status,
                    "time_limit_seconds": args.time_limit,
                    "reference_served": None
                    if reference is None
                    else reference["served"],
                    "all_stop_reference": reference,
                    "progress": progress.export(),
                    "elapsed_seconds": time.perf_counter() - started,
                    "evaluations": steps,
                    "feasible_evaluations": feasible,
                    "best": best,
                    "best_mixed": None,
                    "incumbents": points,
                    "mixed_incumbents": [],
                    "repair_counts": {},
                    "repair_seconds": 0,
                    "updated_unix": time.time(),
                    "representation": "greedy",
                    "last_insertion": last_event,
                },
            )

    def event(e):
        nonlocal steps, feasible, best
        with (args.output / "events.jsonl").open("a") as stream:
            stream.write(json.dumps(e) + "\n")
        progress.consume(e)
        if e["kind"] == "insertion_finished":
            iterations_dir = args.output / "iterations"
            iterations_dir.mkdir(exist_ok=True)
            atomic_json(
                iterations_dir / f"{e.get('iteration_id', 0)}.json", e["summary"]
            )
        if e["kind"] == "native_solution":
            feasible += 1
        if e["kind"] == "accepted_insertion":
            steps += 1
            best = {**e, "pattern_counts": {}}
            points.append(best)
        snapshot(
            last=e,
            force=e["kind"]
            in ("insertion_started", "insertion_finished", "accepted_insertion"),
        )

    def save(plan):
        nonlocal best
        write_reservoir_cp_checkpoint(args.output / "best.json", p, plan)
        archive = args.output / "plans"
        archive.mkdir(exist_ok=True)
        write_reservoir_cp_checkpoint(
            archive / f"k_{len(plan.trips):03d}.json", p, plan
        )
        if best:
            skip = {
                o.id
                for o in p.resolved_core.route_options
                if o.decision.value == "skip"
            }
            best["pattern_counts"] = {
                "all-stop": sum(
                    not any(o in skip for o in t.route_option_ids) for t in plan.trips
                ),
                "skip-stop": sum(
                    any(o in skip for o in t.route_option_ids) for t in plan.trips
                ),
            }
            best["total_wait_tick"] = sum(sum(t.wait_ticks) for t in plan.trips)
            snapshot(force=True)

    def save_candidate(plan):
        write_reservoir_cp_checkpoint(args.output / "latest_insertion.json", p, plan)

    save(initial)
    snapshot()
    remaining = max(0.001, args.time_limit - (time.perf_counter() - started) - 1)
    if args.mode == "insert":
        r = solve_insertion(
            p,
            initial,
            backend=args.backend,
            objective=args.objective,
            seconds=remaining,
            workers=args.workers,
            seed=args.seed,
            on_event=event,
            on_candidate=save_candidate,
            log_path=args.output / "search.log",
        )
    else:
        r = construct_greedy(
            p,
            replace(config, time_limit=remaining),
            initial_plan=initial,
            on_event=event,
            on_plan=save,
            on_candidate=save_candidate,
            log_directory=args.output,
        )
    plan = r.pop("plan")
    if plan:
        save(plan)
    r["runner_total_wall_seconds"] = time.perf_counter() - started
    atomic_json(args.output / "result.json", r)
    snapshot("complete")


if __name__ == "__main__":
    main()
