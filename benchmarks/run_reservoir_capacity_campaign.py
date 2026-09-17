"""Frozen, sequential capacity pilot; 60-minute hard campaign maximum."""

import argparse
from dataclasses import asdict, replace
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from types import SimpleNamespace

from ropeway_skip_stop_optimization.benchmarking.process_supervisor import supervise
from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_certificate import (
    atomic_json,
)
from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_integrated import (
    DddIntegratedCpSatConfig,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_cp_sat import (
    DddReservoirCpSatOptimizer,
    DddReservoirCpObjective,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_cp_sat_certificate import (
    DddReservoirCpPlan,
    read_reservoir_cp_checkpoint,
    write_reservoir_cp_checkpoint,
    validate_reservoir_cp_plan,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_hybrid.domain import (
    load_reference,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_arc_flow_problem import (
    DddReservoirOperatingMode,
)
from ropeway_skip_stop_optimization.optimization.ddd.fixed_timetable_capacity import (
    NestedDemand,
)
from ropeway_skip_stop_optimization.optimization.ddd.models import DddRouteDecision
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_capacity.bound import (
    comparison_fingerprint,
)
from ropeway_skip_stop_optimization.optimization.ean.models import EanDemandGroup

ROOT = Path(__file__).resolve().parents[1]


def prepare(reference, out):
    from ropeway_skip_stop_optimization.benchmarking.ddd_reservoir_cp_sat import (
        all_stop_reservoir_movement,
    )

    domain, original = load_reference(reference)
    p = domain.problem
    if sum(g.count for g in p.demand_groups) != 3074 or p.available_fleet_count != 50:
        raise ValueError("R0 must be frozen Max50 demand 3074")
    if (
        p.fingerprint
        != "69ec6a28d939f81c27d120e817df5290f32bc323328f299e82e6aee733be0e43"
    ):
        raise ValueError("R0 physical/demand fingerprint changed")
    template = tuple(
        EanDemandGroup(f"R2::{o}::{d}::{t}", o, d, t, 1)
        for o, d in (("B", "D"), ("D", "B"), ("C", "E"), ("E", "C"))
        for t in range(300, 1101, 100)
    )
    cases = {
        "R0": p,
        "R2": replace(p, demand_groups=NestedDemand(template).groups(3074)),
    }
    cycle = (
        sum(
            o.duration_tick
            for o in p.resolved_core.route_options
            if o.decision is DddRouteDecision.STOP
        )
        / 1e6
    )
    summary = {}
    for case, problem in cases.items():
        ss = DddReservoirCpPlan(
            original.trips, original.ride_counts if case == "R0" else {}
        )
        asp = replace(problem, operating_mode=DddReservoirOperatingMode.ALL_STOP)
        ass = all_stop_reservoir_movement(
            asp,
            SimpleNamespace(
                all_stop_maximum_cabin_count=38,
                all_stop_cycle_seconds=cycle,
                warmup_seconds=300,
            ),
        )
        # 38 is only the construction of this reference, never a global fleet bound.
        variants = []
        for label, pr, seed in (("ss", problem, ss), ("as", asp, ass)):
            path = out / f"{case}_{label}.json"
            write_reservoir_cp_checkpoint(path, pr, seed)
            result = DddReservoirCpSatOptimizer(
                DddIntegratedCpSatConfig(
                    total_time_limit_seconds=45, num_workers=12, checkpoint_path=path
                ),
                DddReservoirCpObjective.UNSERVED,
            ).solve(pr, primal_seed=seed, fixed_plan=seed)
            atomic_json(out / f"{case}_{label}_preparation.json", result)
            variants.append(read_reservoir_cp_checkpoint(path, pr))
        # Common SS seed is the better checked schedule; preserve canonical identities.
        best = min(
            variants,
            key=lambda s: (
                validate_reservoir_cp_plan(problem, s).unserved,
                validate_reservoir_cp_plan(problem, s).journey_time_tick,
            ),
        )
        write_reservoir_cp_checkpoint(out / f"{case}_ss.json", problem, best)
        summary[case] = dict(
            ss=asdict(validate_reservoir_cp_plan(problem, best)),
            all_stop=asdict(validate_reservoir_cp_plan(asp, variants[1])),
        )
    atomic_json(out / "prepared.json", summary)


def schedule():
    jobs = []
    for case in ("R0", "R2"):
        for interval in (60, 15):
            jobs.append((case, "all_stop_bound", 0, 90, interval))
    for method in ("cp_sat_all_stop", "phase_arc_flow", "cp_sat"):
        for case in ("R0", "R2"):
            jobs.append((case, method, 0, 300, None))
    jobs.extend(
        (("R2", "cp_sat", 1, 300, None), ("R2", "phase_arc_flow", 1, 300, None))
    )
    return jobs


def report(out, records):
    table = []
    proof = []
    values = {}
    for item in records:
        path = out / item["name"]
        result = (
            json.loads((path / "result.json").read_text())
            if (path / "result.json").exists()
            else {}
        )
        sup = (
            json.loads((path / "supervisor.json").read_text())
            if (path / "supervisor.json").exists()
            else {}
        )
        ub = result.get("validated_upper_bound")
        expected_path = (
            out
            / "prepare"
            / f"{item['case']}_{'as' if item['method'] in ('all_stop_bound', 'cp_sat_all_stop') else 'ss'}.json"
        )
        expected, _ = load_reference(expected_path)
        if result and result.get("comparison_fingerprint") != comparison_fingerprint(
            expected.problem
        ):
            raise ValueError(
                "cannot compare results from different physical/demand contracts"
            )
        if (path / "best.json").exists() and item["method"] != "all_stop_bound":
            # Also recover validated native checkpoints after a hard timeout.
            best = read_reservoir_cp_checkpoint(path / "best.json", expected.problem)
            ub = validate_reservoir_cp_plan(expected.problem, best).unserved
        native = result.get("native_events", result.get("events", []))
        row = dict(
            **item,
            upper=ub,
            global_lower=result.get("global_lower_bound"),
            restricted_lower=result.get("restricted_lower_bound"),
            status=result.get(
                "solver_status",
                result.get("status", sup.get("supervisor_reason", "not_completed")),
            ),
            wall_seconds=sup.get("civil_wall_seconds"),
            peak_rss=sup.get("peak_process_tree_rss_bytes"),
            variables=result.get(
                "variables", result.get("model_stats", {}).get("variables")
            ),
            native_events=native,
        )
        table.append(row)
        values[item["case"], item["method"], item["seed"]] = ub
    for case in ("R0", "R2"):
        asbounds = [
            r["global_lower"]
            for r in table
            if r["case"] == case
            and r["method"] in ("all_stop_bound", "cp_sat_all_stop")
            and r["global_lower"] is not None
        ]
        ss = [
            r["upper"]
            for r in table
            if r["case"] == case
            and r["method"] in ("phase_arc_flow", "cp_sat")
            and r["upper"] is not None
        ]
        if ss and asbounds and min(ss) < max(asbounds):
            proof.append(dict(case=case, ss_unserved=min(ss), as_lower=max(asbounds)))
    advantage = all(
        values.get(("R2", "phase_arc_flow", seed)) is not None
        and values.get(("R2", "cp_sat", seed)) is not None
        and values["R2", "phase_arc_flow", seed] + 10 <= values["R2", "cp_sat", seed]
        for seed in (0, 1)
    )
    failures = [str(p.relative_to(out)) for p in out.glob("*/failure.json")]
    correctness_failure = any(
        json.loads((out / f).read_text()).get("type")
        not in ("TimeoutError", "MemoryError")
        for f in failures
    )
    gate = not correctness_failure and (bool(proof) or advantage)
    atomic_json(
        out / "comparison.json",
        dict(
            rows=table,
            capacity_proofs=proof,
            confirmed_native_advantage=advantage,
            double_ring_gate=gate,
            failures=failures,
            note="Restricted-network bounds are never global. Incomplete runs are not proofs.",
        ),
    )
    lines = [
        "# Reservoir capacity pilot",
        "",
        "| Case | Method | Seed | Validated U | Global LB | Restricted LB | Status | Wall s |",
        "|---|---|---:|---:|---:|---:|---|---:|",
    ]
    for r in table:
        lines.append(
            f"| {r['case']} | {r['method']} | {r['seed']} | {r['upper']} | {r['global_lower']} | {r['restricted_lower']} | {r['status']} | {r['wall_seconds']} |"
        )
    lines.extend(
        [
            "",
            f"Double-ring gate: **{'passed' if gate else 'not passed'}**.",
            "",
            f"Capacity certificates: {proof}",
            "",
            "No global Skip-Stop optimality is inferred from a restricted graph.",
        ]
    )
    (out / "comparison.md").write_text("\n".join(lines) + "\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--_prepare", action="store_true")
    a = parser.parse_args()
    if a._prepare:
        prepare(a.reference, a.output_dir)
        return
    out = a.output_dir.resolve()
    out.mkdir(parents=True, exist_ok=False)
    # Correctness is outside the campaign clock. The native no-hint small solve
    # and historical phase replay are mandatory tests in this suite.
    tests = [
        "tests/test_reservoir_capacity_phases.py",
        "tests/test_reservoir_capacity_bound.py",
        "tests/test_reservoir_capacity_runner.py",
        "tests/test_reservoir_hybrid.py",
        "tests/test_optimization_ddd_reservoir_cp_sat.py",
    ]
    with (out / "correctness.log").open("w") as log:
        checked = subprocess.run(
            [sys.executable, "-m", "pytest", *tests, "-q"],
            cwd=ROOT,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
    if checked.returncode:
        raise RuntimeError("correctness gate failed; campaign not started")
    sources = out / "sources"
    shutil.copytree(
        ROOT / "src",
        sources / "src",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.egg-info"),
    )
    (sources / "benchmarks").mkdir()
    for name in (Path(__file__).name, "run_reservoir_capacity_arc_flow.py"):
        shutil.copy2(ROOT / "benchmarks" / name, sources / "benchmarks" / name)
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
    started = time.time()
    awake = time.monotonic()
    deadline = started + 3600
    atomic_json(
        out / "manifest.json",
        dict(
            started_unix=started,
            deadline_unix=deadline,
            maximum_wall_seconds=3600,
            versions={
                p: importlib.metadata.version(p) for p in ("gurobipy", "ortools")
            },
            reference_sha256=hashlib.sha256(a.reference.read_bytes()).hexdigest(),
            schedule=schedule(),
        ),
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = str(sources / "src")
    prep = out / "prepare"
    prep.mkdir()
    supervise(
        [
            sys.executable,
            str(sources / "benchmarks" / Path(__file__).name),
            "--_prepare",
            "--reference",
            str(a.reference.resolve()),
            "--output-dir",
            str(prep),
        ],
        prep,
        seconds=300,
        global_deadline=deadline,
        env=env,
    )
    records = []
    for case, method, seed, seconds, interval in schedule():
        if (
            time.time() >= deadline - 30
            or time.time() - started - (time.monotonic() - awake) > 5
        ):
            break
        name = f"{case}_{method}_s{seed}" + (f"_{interval}s" if interval else "")
        reference = (
            prep
            / f"{case}_{'as' if method in ('all_stop_bound', 'cp_sat_all_stop') else 'ss'}.json"
        )
        if not (prep / "prepared.json").exists():
            break
        path = out / name
        path.mkdir()
        command = [
            sys.executable,
            str(sources / "benchmarks/run_reservoir_capacity_arc_flow.py"),
            "--_worker",
            "--method",
            "cp_sat" if method == "cp_sat_all_stop" else method,
            "--reference",
            str(reference),
            "--output-dir",
            str(path),
            "--time-limit",
            str(seconds),
            "--seed",
            str(seed),
            "--deadline-unix",
            str(deadline - 30),
        ]
        if interval:
            command.extend(["--interval-seconds", str(interval)])
            if interval == 15:
                command.extend(["--parent-interval-seconds", "60"])
        item = dict(name=name, case=case, method=method, seed=seed, budget=seconds)
        atomic_json(out / "active.json", item)
        supervise(
            command, path, seconds=seconds, global_deadline=deadline - 30, env=env
        )
        records.append(item)
        report(out, records)
    report(out, records)
    atomic_json(
        out / "completed.json",
        dict(
            wall_seconds=time.time() - started,
            finished_unix=time.time(),
            completed_attempts=len(records),
            planned_attempts=len(schedule()),
        ),
    )


if __name__ == "__main__":
    main()
