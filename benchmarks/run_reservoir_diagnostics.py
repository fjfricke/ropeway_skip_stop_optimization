"""Sequential bounded CP-SAT ablation; original domain and solver stay intact."""

import argparse
import hashlib
import json
import os
import pickle
import shutil
import sys
import time
from pathlib import Path

from ortools.sat.python import cp_model

from ropeway_skip_stop_optimization.benchmarking.process_supervisor import supervise
from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_certificate import (
    atomic_json,
)
from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_integrated import (
    DddIntegratedCpSatConfig,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_cp_sat import (
    DddReservoirCpSatOptimizer,
    _movement_values,
    build_reservoir_cp_sat,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_cp_sat_certificate import (
    read_reservoir_cp_checkpoint,
    validate_reservoir_cp_plan,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_diagnostics import (
    ALL_PROFILES,
    PROFILES,
    ReservoirDiagnostic,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_hybrid.domain import (
    load_reference,
)

from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_passenger import (
    DddCpSatCostEncoding,
)

ROOT = Path(__file__).resolve().parents[1]


def child(args):
    data = args.input.read_bytes()
    if (
        hashlib.sha256(data).hexdigest()
        != args.input.with_suffix(".sha256").read_text().strip()
    ):
        raise ValueError("frozen input changed")
    problem, ref = pickle.loads(
        data
    )  # Private locally frozen input, never public imports.
    diagnostic = ReservoirDiagnostic(args.profile)
    expected = validate_reservoir_cp_plan(problem, ref).journey_time_tick
    started = time.monotonic()
    if args.verify:
        b = build_reservoir_cp_sat(
            problem,
            config=DddIntegratedCpSatConfig(
                cost_encoding=DddCpSatCostEncoding(args.cost_encoding)
            ),
        )
        info = diagnostic.apply(problem, b, ref)
        model = b.movement.model
        for i, value in _movement_values(problem, b, ref).items():
            model.add(model.get_int_var_from_proto_index(i) == value)
        for q, v in b.passengers.ride_count.items():
            model.add(v == ref.ride_counts.get(q, 0))
        model.minimize(b.passengers.objective_expression)
        solver = cp_model.CpSolver()
        solver.parameters.num_search_workers = 1
        solver.parameters.max_time_in_seconds = max(
            0.1, args.seconds - (time.monotonic() - started) - 2
        )
        status = solver.solve(model)
        value = (
            int(solver.value(b.passengers.objective_expression))
            if status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
            else None
        )
        atomic_json(
            args.output / "result.json",
            {
                "passed": status == cp_model.OPTIMAL and value == expected,
                "objective_tick": value,
                "expected": expected,
                "status": solver.status_name(status),
                "diagnostic": info,
                "total_seconds": time.monotonic() - started,
            },
        )
        return
    with (
        (args.output / "events.jsonl").open("w") as events,
        (args.output / "solver.log").open("w") as logs,
    ):

        def event(e):
            events.write(json.dumps(e) + "\n")
            events.flush()

        def log(s):
            logs.write(s + "\n")
            logs.flush()

        config = DddIntegratedCpSatConfig(
            total_time_limit_seconds=max(1, args.seconds - 5),
            num_workers=12,
            seed=args.seed,
            cost_encoding=DddCpSatCostEncoding(args.cost_encoding),
            log_search_progress=True,
            checkpoint_path=args.output / "best.json",
            checkpoint_interval_seconds=1,
        )
        result = DddReservoirCpSatOptimizer(config).solve(
            problem,
            primal_seed=ref,
            diagnostic=diagnostic,
            event_callback=event,
            log_callback=log,
        )
        atomic_json(args.output / "result.json", result)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--output", type=Path, required=True)
    p.add_argument(
        "--reference",
        type=Path,
        default=ROOT
        / "benchmarks/output/reservoir_global_repair_campaign_20260911_v1/common_seed.json",
    )
    p.add_argument("--seconds", type=float, default=120)
    p.add_argument("--total-seconds", type=float, default=1800)
    p.add_argument("--input", type=Path)
    p.add_argument("--profile", choices=ALL_PROFILES)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--verify", action="store_true")
    p.add_argument(
        "--cost-encoding", choices=list(DddCpSatCostEncoding), default="product"
    )
    a = p.parse_args()
    if a.input:
        try:
            child(a)
        except Exception as e:
            atomic_json(
                a.output / "result.json",
                {
                    "status": "ERROR",
                    "error": f"{type(e).__name__}: {e}",
                    "passed": False,
                },
            )
            raise
        return
    started = time.time()
    deadline = started + a.total_seconds
    a.output = a.output.resolve()
    a.output.mkdir(parents=True, exist_ok=False)
    domain, ref = load_reference(a.reference)
    reference = validate_reservoir_cp_plan(domain.problem, ref).journey_time_tick
    shutil.copy2(a.reference, a.output / "reference.json")
    data = pickle.dumps((domain.problem, ref))
    inp = a.output / "input.pickle"
    inp.write_bytes(data)
    inp.with_suffix(".sha256").write_text(hashlib.sha256(data).hexdigest())
    src = a.output / "sources"
    shutil.copytree(
        ROOT / "src",
        src / "src",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "node_modules", "dist"),
    )
    (src / "benchmarks").mkdir()
    shutil.copy2(Path(__file__), src / "benchmarks" / Path(__file__).name)
    for name in ("pyproject.toml", "uv.lock"):
        shutil.copy2(ROOT / name, src / name)
    atomic_json(
        a.output / "source_hashes.json",
        {
            str(f.relative_to(src)): hashlib.sha256(f.read_bytes()).hexdigest()
            for f in src.rglob("*")
            if f.is_file()
        },
    )
    manifest = {
        "schema": "reservoir_diagnosis_v1",
        "started_unix": started,
        "deadline_unix": deadline,
        "domain_fingerprint": domain.fingerprint,
        "reference_tick": reference,
        "reference_used_cabins": len(ref.trips),
        "time_limit_per_trial": a.seconds,
        "workers": 12,
        "formulation": "legacy",
        "cost_encoding": a.cost_encoding,
        "gates": [],
        "runs": [],
    }
    env = {**os.environ, "PYTHONPATH": str(src / "src")}
    script = src / "benchmarks" / Path(__file__).name

    def execute(profile, seed, verify=False):
        name = ("verify_" if verify else f"seed{seed}_") + profile
        folder = a.output / name
        folder.mkdir()
        sec = 30 if verify else a.seconds
        cmd = [
            sys.executable,
            str(script),
            "--input",
            str(inp),
            "--output",
            str(folder),
            "--profile",
            profile,
            "--seed",
            str(seed),
            "--seconds",
            str(sec),
            "--cost-encoding",
            a.cost_encoding,
        ]
        if verify:
            cmd.append("--verify")
        atomic_json(
            folder / "config.json",
            {
                "profile": profile,
                "seed": seed,
                "verify": verify,
                "budget": sec,
                "reference_tick": reference,
                "domain_fingerprint": domain.fingerprint,
            },
        )
        curve = []

        def observe(path, elapsed):
            plan = read_reservoir_cp_checkpoint(path, domain.problem)
            ReservoirDiagnostic(profile).validate(domain.problem, ref, plan)
            value = validate_reservoir_cp_plan(domain.problem, plan).journey_time_tick
            curve.append({"elapsed_seconds": elapsed, "objective_tick": value})
            atomic_json(folder / "validated_curve.json", {"events": curve})

        monitor = supervise(
            cmd,
            folder,
            seconds=sec,
            global_deadline=deadline,
            env=env,
            checkpoint_callback=None if verify else observe,
        )
        result = (
            json.loads((folder / "result.json").read_text())
            if (folder / "result.json").exists()
            else {"status": "INTERRUPTED", "passed": False}
        )
        if not verify and (folder / "best.json").exists():
            observe(folder / "best.json", monitor["awake_wall_seconds"])
        entry = {"profile": profile, "seed": seed, "folder": name, "monitor": monitor}
        if verify:
            entry.update(result)
        else:
            entry.update(
                status=result.get("solver_status", result.get("status")),
                error=result.get("error"),
                proof_scope=result.get("proof_scope"),
                ub_tick=min([reference, *[e["objective_tick"] for e in curve]]),
                lb_seconds=result.get("cp_lower_bound"),
                proven_optimal=result.get("proven_optimal", False),
                model_stats=result.get("model_stats"),
                last_improvement=None,
                improvements=0,
            )
            best = reference
            for e in curve:
                if e["objective_tick"] < best:
                    best = e["objective_tick"]
                    entry["improvements"] += 1
                    entry["last_improvement"] = e["elapsed_seconds"]
        print(json.dumps(entry), flush=True)
        return entry

    for profile in PROFILES:
        if time.time() + 35 > deadline:
            break
        gate = execute(profile, 0, True)
        manifest["gates"].append(gate)
        atomic_json(a.output / "campaign.json", manifest)
        if not gate.get("passed"):
            raise RuntimeError(
                "historical replay failed; no performance trials admitted"
            )
    if len(manifest["gates"]) != len(PROFILES):
        raise RuntimeError("gate budget exhausted")
    for seed in (0, 1):
        order = PROFILES if seed == 0 else tuple(reversed(PROFILES))
        for profile in order:
            if time.time() + a.seconds + 15 > deadline:
                manifest["runs"].append(
                    {
                        "profile": profile,
                        "seed": seed,
                        "status": "NOT_STARTED",
                        "reason": "global deadline",
                    }
                )
                continue
            entry = execute(profile, seed)
            manifest["runs"].append(entry)
            manifest["elapsed_seconds"] = time.time() - started
            atomic_json(a.output / "campaign.json", manifest)
            if entry["monitor"]["supervisor_reason"] in (
                "SUSPEND_DETECTED",
                "INVALID_CHECKPOINT",
            ) or entry.get("error"):
                raise RuntimeError("campaign stopped after invalid output or suspend")
    manifest.update(complete=True, elapsed_seconds=time.time() - started)
    atomic_json(a.output / "campaign.json", manifest)


if __name__ == "__main__":
    main()
