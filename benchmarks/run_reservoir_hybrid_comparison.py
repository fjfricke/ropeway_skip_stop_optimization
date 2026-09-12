"""Frozen CP versus hybrid comparison, sequential seeds 0/1, ten minutes each."""

import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import resource
import shutil
import sys
import time

from run_reservoir_hybrid_gate_campaign import run_case
from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_certificate import (
    atomic_json,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_hybrid.domain import (
    load_reference,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_hybrid.certificates import (
    ReservoirCertificateLedger,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_hybrid.optimizer import (
    ReservoirHybridConfig,
    ReservoirHybridOptimizer,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_cp_sat_certificate import (
    write_reservoir_cp_checkpoint,
    validate_reservoir_cp_plan,
    read_reservoir_cp_checkpoint,
)


def certified_input(path, problem):
    from ropeway_skip_stop_optimization.optimization.ddd.reservoir_hybrid.certificates import (
        read_global_bound_result,
    )

    return read_global_bound_result(path, problem)


def worker(args):
    started = time.monotonic()
    args.output_dir.mkdir(parents=True, exist_ok=False)
    domain, seed_plan = load_reference(args.resume_checkpoint)
    p = domain.problem
    bound = certified_input(args.bound_result, p)
    ledger = ReservoirCertificateLedger(p)
    ledger.accept_plan(seed_plan)
    ledger.accept_bound(bound)
    atomic_json(
        args.output_dir / "config.json",
        {
            "engine": args.worker,
            "seed": args.seed,
            "time_limit": args.time_limit,
            "workers": 12,
            "initial_bound": asdict(bound),
            "seed_value": ledger.upper_bound,
            "cp_profile": "hints",
            "hybrid_repair_presolve": False,
            "hybrid_repair_seconds": 30,
            "additional_bound_budget": 0,
        },
    )
    import ortools
    import gurobipy

    atomic_json(
        args.output_dir / "versions.json",
        {
            "python": sys.version,
            "ortools": ortools.__version__,
            "gurobi": gurobipy.gurobi.version(),
        },
    )
    source_root = Path("src")
    atomic_json(
        args.output_dir / "source_hashes.json",
        {
            str(f): hashlib.sha256(f.read_bytes()).hexdigest()
            for f in sorted(source_root.rglob("*.py"))
        },
    )
    atomic_json(args.output_dir / "domain.json", p.manifest)
    write_reservoir_cp_checkpoint(args.output_dir / "initial.json", p, seed_plan)
    with (args.output_dir / "events.jsonl").open("w") as events:

        def event(value):
            events.write(json.dumps(value) + "\n")
            events.flush()

        event(
            {
                "kind": "initial",
                "elapsed_seconds": 0,
                "validated_upper_bound": ledger.upper_bound,
                "certified_lower_bound": ledger.lower_bound,
            }
        )
        remaining = max(0.001, args.time_limit - (time.monotonic() - started))
        if args.worker == "hybrid":
            optimizer = ReservoirHybridOptimizer(
                ReservoirHybridConfig(time_limit=remaining, seed=args.seed)
            )
            plan, result = optimizer.solve(
                p,
                primal_seed=seed_plan,
                initial_bound=bound,
                on_event=event,
                on_improvement=lambda s: write_reservoir_cp_checkpoint(
                    args.output_dir / "incumbent.json", p, s
                ),
            )
        else:
            from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_integrated import (
                DddIntegratedCpSatConfig,
            )
            from ropeway_skip_stop_optimization.optimization.ddd.cp_formulation import (
                DddCpFormulationConfig,
            )
            from ropeway_skip_stop_optimization.optimization.ddd.reservoir_cp_sat import (
                DddReservoirCpSatOptimizer,
            )
            from ropeway_skip_stop_optimization.benchmarking.ddd_reservoir_cp_sat import (
                _plan,
            )

            with (args.output_dir / "solver.log").open("w") as log:
                native = DddReservoirCpSatOptimizer(
                    DddIntegratedCpSatConfig(
                        total_time_limit_seconds=remaining,
                        num_workers=12,
                        seed=args.seed,
                        formulation=DddCpFormulationConfig(profile="hints"),
                        checkpoint_path=args.output_dir / "incumbent.json",
                        log_search_progress=True,
                    )
                ).solve(
                    p,
                    primal_seed=seed_plan,
                    event_callback=event,
                    log_callback=lambda line: (log.write(line + "\n"), log.flush()),
                )
            atomic_json(args.output_dir / "native_result.json", native)
            plan = _plan(native["plan"])
            result = {
                "validated_upper_bound": validate_reservoir_cp_plan(
                    p, plan
                ).journey_time_tick
                / 1e6,
                "certified_lower_bound": max(
                    bound.value, native.get("cp_lower_bound") or 0
                ),
                "solver_status": native["solver_status"],
                "events": native["events"],
                "model_stats": {
                    k: v
                    for k, v in native["model_stats"].items()
                    if k != "preprocessing"
                },
                "scope": "single_use_reservoir_global",
            }
        result.update(
            engine=args.worker,
            seed=args.seed,
            actual_total_seconds=time.monotonic() - started,
            problem_fingerprint=p.fingerprint,
            peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        )
        result["gap"] = (
            result["validated_upper_bound"] - result["certified_lower_bound"]
        ) / result["validated_upper_bound"]
        write_reservoir_cp_checkpoint(args.output_dir / "best.json", p, plan)
        atomic_json(args.output_dir / "result.json", result)


def main():
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--resume-checkpoint", type=Path, required=True)
    parser.add_argument("--bound-result", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--time-limit", type=float, default=600)
    parser.add_argument("--worker", choices=("cp_sat", "hybrid"))
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--memory-gib", type=float, default=4)
    parser.add_argument("--reuse-hybrid", type=Path)
    args = parser.parse_args()
    if args.worker:
        return worker(args)
    args.output_dir.mkdir(parents=True, exist_ok=False)
    domain, seed = load_reference(args.resume_checkpoint)
    bound = certified_input(args.bound_result, domain.problem)
    atomic_json(args.output_dir / "common_bound.json", asdict(bound))
    atomic_json(
        args.output_dir / "bound_provenance.json",
        json.loads(args.bound_result.read_text()),
    )
    write_reservoir_cp_checkpoint(
        args.output_dir / "common_seed.json", domain.problem, seed
    )
    started = time.monotonic()
    report = {
        "cases": [],
        "common_bound": asdict(bound),
        "time_limit_per_case": args.time_limit,
        "memory_limit_gib": args.memory_gib,
    }
    for s in (0, 1):
        for engine in ("cp_sat", "hybrid"):
            name = f"{engine}_{s}"
            out = args.output_dir / name
            if engine == "hybrid" and args.reuse_hybrid is not None:
                previous = json.loads((args.reuse_hybrid / "campaign.json").read_text())
                old = next(c for c in previous["cases"] if c["name"] == name)
                if (
                    old["return_code"] != 0
                    or old["result"].get("incomplete")
                    or old["peak_sampled_rss_bytes"] > args.memory_gib * 1024**3
                ):
                    raise ValueError(
                        "only completed hybrid runs under the new memory limit can be reused"
                    )
                if previous["common_bound"] != asdict(bound):
                    raise ValueError("reused run has a different initial bound")
                original_seed = read_reservoir_cp_checkpoint(
                    args.reuse_hybrid / "common_seed.json", domain.problem
                )
                if original_seed != seed:
                    raise ValueError("reused run has a different initial plan")
                recovered = read_reservoir_cp_checkpoint(
                    args.reuse_hybrid / name / "best.json", domain.problem
                )
                value = (
                    validate_reservoir_cp_plan(
                        domain.problem, recovered
                    ).journey_time_tick
                    / 1e6
                )
                if abs(value - old["result"]["validated_upper_bound"]) > 1e-6:
                    raise ValueError("reused certificate value mismatch")
                shutil.copytree(args.reuse_hybrid / name, out)
                report["cases"].append(
                    {
                        **old,
                        "reused_from": str(args.reuse_hybrid / name),
                        "old_memory_cap_was_nonbinding": True,
                    }
                )
                atomic_json(args.output_dir / "campaign.json", report)
                print(
                    name, "reused completed run under nonbinding memory cap", flush=True
                )
                continue
            command = [
                sys.executable,
                __file__,
                "--worker",
                engine,
                "--seed",
                str(s),
                "--resume-checkpoint",
                str(args.output_dir / "common_seed.json"),
                "--bound-result",
                str(args.output_dir / "bound_provenance.json"),
                "--output-dir",
                str(out),
                "--time-limit",
                str(max(0.01, args.time_limit - 5)),
            ]
            supervised = run_case(
                command,
                args.output_dir / (name + ".log"),
                time.monotonic() + args.time_limit - 2,
                memory_limit=int(args.memory_gib * 1024**3),
            )
            result = {}
            if (out / "result.json").exists():
                result = json.loads((out / "result.json").read_text())
                result.pop("events", None)
            else:
                recovered = (
                    read_reservoir_cp_checkpoint(out / "incumbent.json", domain.problem)
                    if (out / "incumbent.json").exists()
                    else seed
                )
                result = {
                    "validated_upper_bound": validate_reservoir_cp_plan(
                        domain.problem, recovered
                    ).journey_time_tick
                    / 1e6,
                    "certified_lower_bound": bound.value,
                    "incomplete": True,
                }
            report["cases"].append({"name": name, **supervised, "result": result})
            report["actual_total_seconds"] = time.monotonic() - started
            atomic_json(args.output_dir / "campaign.json", report)
            print(name, json.dumps({**supervised, "result": result}), flush=True)
    confirmations = []
    for s in (0, 1):
        cp = next(c for c in report["cases"] if c["name"] == f"cp_sat_{s}")
        hy = next(c for c in report["cases"] if c["name"] == f"hybrid_{s}")
        a, b = cp["result"], hy["result"]
        valid = (
            cp["return_code"] == hy["return_code"] == 0
            and not a.get("incomplete")
            and not b.get("incomplete")
        )
        confirmations.append(
            bool(
                valid
                and (
                    b["validated_upper_bound"] <= 0.99 * a["validated_upper_bound"]
                    or (
                        b["gap"] <= a["gap"] - 0.05
                        and b["validated_upper_bound"] <= a["validated_upper_bound"]
                    )
                )
            )
        )
    report["performance_recommendation"] = all(confirmations)
    report["confirmed_by_seed"] = confirmations
    atomic_json(args.output_dir / "campaign.json", report)


if __name__ == "__main__":
    main()
