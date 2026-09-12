"""Bounded ablation: global passengers and conflict-selected neighborhoods.

Screening: four old sets x legacy/global plus four conflict/global sets, 30s.
Confirmation: best global vs identical legacy neighborhood vs full CP,
two fresh seeds, 120s each. Total cap 30 minutes, including preparation.
"""

import argparse
from dataclasses import asdict
from datetime import datetime
import hashlib
import json
from pathlib import Path
import subprocess
import os
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
    read_global_bound_result,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_hybrid.optimizer import (
    select_neighborhood,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_hybrid.conflict_neighborhoods import (
    select_conflict_neighborhoods,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_hybrid.global_repair import (
    GlobalPassengerRepair,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_hybrid.repair import (
    ReservoirRepairProblem,
    ReservoirRepairOptimizer,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_cp_sat_certificate import (
    validate_reservoir_cp_plan,
    write_reservoir_cp_checkpoint,
)


def worker(args):
    if args.worker == "full":
        from run_reservoir_hybrid_comparison import worker as full_worker

        args.worker = "cp_sat"
        return full_worker(args)
    started = time.monotonic()
    args.output_dir.mkdir(exist_ok=False)
    domain, plan = load_reference(args.resume_checkpoint)
    selected = json.loads(args.selection.read_text())
    context = ReservoirRepairProblem.prepare(
        domain.problem, plan, selected["open_ids"], selected["new_slots"]
    )

    def callback(plan):
        write_reservoir_cp_checkpoint(
            args.output_dir / "incumbent.json", domain.problem, plan
        )

    common = dict(
        time_limit=max(0.001, args.time_limit - (time.monotonic() - started)),
        workers=12,
        seed=args.seed,
        presolve=False,
        on_improvement=callback,
        log_path=args.output_dir / "solver.log",
    )
    if args.worker == "global":
        best, result = GlobalPassengerRepair(context).solve(**common)
    else:
        best, result = ReservoirRepairOptimizer().solve(context, **common)
    write_reservoir_cp_checkpoint(args.output_dir / "best.json", domain.problem, best)
    result.update(
        engine=args.worker,
        seed=args.seed,
        selection=selected,
        problem_fingerprint=domain.fingerprint,
        actual_total_seconds=time.monotonic() - started,
        served=validate_reservoir_cp_plan(domain.problem, best).served,
    )
    atomic_json(args.output_dir / "result.json", result)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--resume-checkpoint", type=Path, required=True)
    p.add_argument("--bound-result", type=Path, required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--worker", choices=["legacy", "global", "full"])
    p.add_argument("--selection", type=Path)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--time-limit", type=float, default=30)
    args = p.parse_args()
    if args.worker:
        return worker(args)
    started = time.time()
    deadline = started + 1800
    args.output_dir.mkdir(exist_ok=False)
    caffeine = subprocess.Popen(["/usr/bin/caffeinate", "-i", "-w", str(os.getpid())])
    try:
        domain, plan = load_reference(args.resume_checkpoint)
        bound = read_global_bound_result(args.bound_result, domain.problem)
        seed_value = (
            validate_reservoir_cp_plan(domain.problem, plan).journey_time_tick / 1e6
        )
        write_reservoir_cp_checkpoint(
            args.output_dir / "common_seed.json", domain.problem, plan
        )
        atomic_json(args.output_dir / "bound_summary.json", asdict(bound))
        atomic_json(
            args.output_dir / "bound.json", json.loads(args.bound_result.read_text())
        )
        atomic_json(args.output_dir / "domain.json", domain.problem.manifest)
        import ortools

        atomic_json(
            args.output_dir / "versions.json",
            dict(python=sys.version, ortools=ortools.__version__),
        )
        files = [*Path("src").rglob("*.py"), *Path("benchmarks").glob("*repair*.py")]
        atomic_json(
            args.output_dir / "source_hashes.json",
            {str(f): hashlib.sha256(f.read_bytes()).hexdigest() for f in files},
        )
        report = dict(
            started_at=datetime.now().astimezone().isoformat(),
            budget_seconds=1800,
            seed_value=seed_value,
            global_lower_bound=bound.value,
            problem_fingerprint=domain.fingerprint,
            workers=12,
            memory_limit_gib=16,
            threshold_fraction=0.001,
            cases=[],
        )
        original = []
        seen = set()
        for i in range(30):
            ids, n, family = select_neighborhood(domain.problem, plan, i, 0)
            if ids in seen:
                continue
            seen.add(ids)
            original.append(dict(open_ids=list(ids), new_slots=n, family=family))
            if len(original) == 4:
                break
        selected = select_conflict_neighborhoods(domain.problem, plan, limit=4)
        atomic_json(args.output_dir / "conflict_selection.json", selected)
        report["conflict_preparation_seconds"] = time.time() - started
        selections = {f"original_{i}": s for i, s in enumerate(original)}
        selections.update(
            {f"conflict_{i}": s for i, s in enumerate(selected["neighborhoods"])}
        )
        for key, value in selections.items():
            atomic_json(args.output_dir / (key + ".json"), value)

        def run(name, engine, key, seed, budget):
            remaining = deadline - time.time()
            if remaining < budget + 2:
                report.setdefault("pending", []).append(name)
                return None
            out = args.output_dir / name
            command = [
                sys.executable,
                __file__,
                "--worker",
                engine,
                "--seed",
                str(seed),
                "--resume-checkpoint",
                str(args.output_dir / "common_seed.json"),
                "--bound-result",
                str(args.output_dir / "bound.json"),
                "--selection",
                str(args.output_dir / (key + ".json")),
                "--output-dir",
                str(out),
                "--time-limit",
                str(budget - 3),
            ]
            before = time.time()
            supervised = run_case(
                command,
                args.output_dir / (name + ".log"),
                time.monotonic() + budget,
                memory_limit=16 * 1024**3,
            )
            wall = time.time() - before
            result = (
                json.loads((out / "result.json").read_text())
                if (out / "result.json").exists()
                else dict(validated_upper_bound=seed_value, incomplete=True)
            )
            result.pop("response_stats", None)
            entry = dict(
                name=name,
                engine=engine,
                selection=key,
                seed=seed,
                **supervised,
                result=result,
                civil_wall_seconds=wall,
                sleep_or_clock_discrepancy=abs(wall - supervised["actual_seconds"]) > 5,
            )
            report["cases"].append(entry)
            report["elapsed_seconds"] = time.time() - started
            atomic_json(args.output_dir / "campaign.json", report)
            print(
                name,
                result.get("status", result.get("solver_status")),
                result["validated_upper_bound"],
                flush=True,
            )
            return entry

        for key in selections:
            for engine in (
                ("legacy", "global") if key.startswith("original") else ("global",)
            ):
                run("screen_" + engine + "_" + key, engine, key, 0, 30)
        candidates = [
            c
            for c in report["cases"]
            if c["engine"] == "global"
            and c["return_code"] == 0
            and not c["result"].get("incomplete")
        ]
        if candidates:
            best = min(
                candidates,
                key=lambda c: (
                    c["result"]["validated_upper_bound"],
                    0 if c["selection"].startswith("conflict") else 1,
                    c["name"],
                ),
            )
            report["chosen_selection"] = best["selection"]
            for seed in (1, 2):
                for engine in ("global", "legacy", "full"):
                    run(
                        f"confirm_{engine}_{seed}", engine, best["selection"], seed, 120
                    )
        confirmations = []
        for seed in (1, 2):
            cases = {
                c["engine"]: c
                for c in report["cases"]
                if c["name"].startswith("confirm_") and c["seed"] == seed
            }
            valid = len(cases) == 3 and all(
                c["return_code"] == 0
                and not c["sleep_or_clock_discrepancy"]
                and not c["result"].get("incomplete")
                for c in cases.values()
            )
            confirmations.append(
                bool(
                    valid
                    and cases["global"]["result"]["validated_upper_bound"]
                    <= 0.999
                    * min(
                        cases["legacy"]["result"]["validated_upper_bound"],
                        cases["full"]["result"]["validated_upper_bound"],
                    )
                )
            )
        report.update(
            confirmed_by_seed=confirmations,
            performance_recommendation=all(confirmations),
            elapsed_seconds=time.time() - started,
            finished_at=datetime.now().astimezone().isoformat(),
        )
        atomic_json(args.output_dir / "campaign.json", report)
    finally:
        caffeine.terminate()


if __name__ == "__main__":
    main()
