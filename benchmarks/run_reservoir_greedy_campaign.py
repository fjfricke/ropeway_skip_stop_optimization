"""Sequential one-hour pilot; waits for existing jobs before starting its budget."""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import replace
from pathlib import Path

from run_reservoir_greedy import ROOT, active_solver_jobs

from ropeway_skip_stop_optimization.benchmarking.process_supervisor import supervise
from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_certificate import (
    atomic_json,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_cp_sat_certificate import (
    DddReservoirCpPlan,
    write_reservoir_cp_checkpoint,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_greedy import (
    pilot_problem,
    validate_lifecycle,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_greedy.history import (
    compare_historical_run,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_hybrid.domain import (
    load_reference,
)

RUNNER = ROOT / "benchmarks/run_reservoir_greedy.py"
BASE = ROOT / "benchmarks/output/reservoir_line_evolution_20260914"
DEFAULT_R0 = (
    BASE / "campaign_main_clean_1789391857/R0_all_stop_reference/artifact/best.json"
)
DEFAULT_R2 = (
    BASE / "campaign_main_clean_1789391857/R2_all_stop_reference/artifact/best.json"
)


def main():
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--r0-reference", type=Path, default=DEFAULT_R0)
    parser.add_argument("--r2-reference", type=Path, default=DEFAULT_R2)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--wait-for-solvers", action="store_true")
    parser.add_argument("--workers", type=int, default=12)
    parser.add_argument("--memory-limit-gib", type=float, default=32)
    parser.add_argument("--wall-limit-seconds", type=float, default=3600)
    parser.add_argument("--live-directory", type=Path)
    args = parser.parse_args()
    if (
        not 1 <= args.workers <= 12
        or not 0 < args.memory_limit_gib <= 32
        or not 0 < args.wall_limit_seconds <= 3600
    ):
        parser.error("invalid resource/budget limits")
    args.output.mkdir(parents=True, exist_ok=False)
    manifest = {
        "schema": "reservoir_greedy_campaign_v1",
        "status": "WAITING",
        "runs": [],
        "cases": {},
        "gate": {},
        "queued_unix": time.time(),
    }

    def persist():
        atomic_json(args.output / "campaign.json", manifest)

    persist()
    while jobs := active_solver_jobs():
        manifest["waiting_for"] = jobs
        persist()
        if not args.wait_for_solvers:
            parser.error("existing solver active")
        time.sleep(5)
    started = time.time()
    deadline = started + args.wall_limit_seconds
    manifest.update(status="RUNNING", started_unix=started, deadline_unix=deadline)
    cases = {}
    for name, path in [("R0", args.r0_reference), ("R2", args.r2_reference)]:
        source, reference = load_reference(path)
        p = pilot_problem(source.problem)
        if p.boundary_policy is None:
            raise ValueError("campaign requires current shared port evidence")
        if len(p.cycle_states) != 5 or sum(g.count for g in p.demand_groups) != 3074:
            raise ValueError("unexpected frozen case")
        if any(w for t in reference.trips for w in t.wait_ticks):
            raise ValueError("control must be no-wait")
        if any("skip" in oid for t in reference.trips for oid in t.route_option_ids):
            raise ValueError("control must be all-stop")
        metrics = validate_lifecycle(p, reference)
        case_dir = args.output / name
        case_dir.mkdir()
        domain_path = case_dir / "domain.json"
        write_reservoir_cp_checkpoint(domain_path, p, DddReservoirCpPlan((), {}))
        write_reservoir_cp_checkpoint(case_dir / "all_stop.json", p, reference)
        manifest["cases"][name] = {
            "fingerprint": p.fingerprint,
            "reference_served": metrics.served,
            "source": str(path),
            "reference_is_search_seed": False,
        }
        outside_paths = {}
        ordered = sorted(reference.trips, key=lambda t: (t.switch_ticks[0], t.cabin_id))
        for k in (0, 10, 20, 37):
            subset = DddReservoirCpPlan(
                tuple(replace(t, cabin_id=i) for i, t in enumerate(ordered[:k])), {}
            )
            validate_lifecycle(p, subset)
            from ropeway_skip_stop_optimization.optimization.ddd.reservoir_lines.evolution.passengers import (
                optimize_waiting_timetable_passengers,
            )

            assignment = optimize_waiting_timetable_passengers(
                p, subset, time_limit_seconds=2
            )
            subset = assignment.plan
            atomic_json(
                case_dir / f"outside_k{k}_assignment.json",
                {
                    "served": assignment.served,
                    "proven_optimal": assignment.proven_optimal,
                    "status": assignment.status,
                },
            )
            f = case_dir / f"outside_k{k}.json"
            write_reservoir_cp_checkpoint(f, p, subset)
            outside_paths[k] = f
        cases[name] = (p, domain_path, outside_paths)
    histories = [
        BASE / "interval_waiting_long_live_v1/intervals",
        BASE / "interval_waiting_long_live_v1/intervals_waiting",
        BASE / "fixed38_relevant_nohint_native_v1/run",
    ]
    # Include phase-arc-flow archives without claiming their local bounds global.
    phase = ROOT / "benchmarks/output/reservoir_capacity_campaign_20260911_v1"
    histories.extend([phase / "R2_phase_arc_flow_s0", phase / "R0_phase_arc_flow_s0"])
    histories.extend(sorted(BASE.glob("pattern_only_campaign_v1/screen_*")))
    for name, (p, _, _) in cases.items():
        atomic_json(
            args.output / name / "historical_comparison.json",
            [compare_historical_run(d, p) for d in histories if d.exists()],
        )
    manifest["status"] = "SCREENING"
    persist()
    live = {
        "schema": "reservoir_line_evolution_live_manifest_v1",
        "label": "Greedy insertion · CP-SAT vs Gurobi",
        "status": "running",
        "runs": [],
    }

    def run(name, case, backend, seconds, seed, initial=None):
        if time.time() + seconds + 2 > deadline:
            manifest["runs"].append({"name": name, "status": "PENDING_DEADLINE"})
            persist()
            return None
        if active_solver_jobs():
            manifest["runs"].append({"name": name, "status": "PENDING_OTHER_SOLVER"})
            persist()
            return None
        output = args.output / name
        output.mkdir()
        cmd = [
            sys.executable,
            str(RUNNER),
            "--_worker",
            "--reference-checkpoint",
            str(cases[case][1]),
            "--all-stop-reference",
            str(args.output / case / "all_stop.json"),
            "--backend",
            backend,
            "--mode",
            "insert" if initial is not None else "construct",
            "--time-limit",
            str(seconds),
            "--workers",
            str(args.workers),
            "--memory-limit-gib",
            str(args.memory_limit_gib),
            "--seed",
            str(seed),
            "--output",
            str(output),
        ]
        if initial is not None:
            cmd += ["--initial-checkpoint", str(initial)]
        if args.live_directory:
            args.live_directory.mkdir(parents=True, exist_ok=True)
            snapshot = args.live_directory / f"{name}.json"
            cmd += ["--live-snapshot", str(snapshot)]
            live["runs"].append(
                {
                    "id": name,
                    "label": name,
                    "snapshot": "/generated/evolution-live/" + snapshot.name,
                }
            )
            atomic_json(args.live_directory / "manifest.json", live)
        entry = {
            "name": name,
            "case": case,
            "backend": backend,
            "seed": seed,
            "budget_seconds": seconds,
            "status": "RUNNING",
            "command": cmd,
        }
        manifest["runs"].append(entry)
        persist()
        guard = supervise(
            cmd,
            output,
            seconds=seconds,
            memory_bytes=int(args.memory_limit_gib * 1024**3),
            global_deadline=deadline,
            system_memory_pressure_seconds=30,
        )
        entry.update(supervisor=guard, status="FINISHED")
        result_path = output / "result.json"
        result = json.loads(result_path.read_text()) if result_path.exists() else None
        entry["result"] = result
        if result is None:
            entry["status"] = "INCOMPLETE"
        persist()
        return result

    for case in ("R0", "R2"):
        for k in (0, 10, 20, 37):
            backends = ("cp_sat", "gurobi") if k in (0, 20) else ("gurobi", "cp_sat")
            for backend in backends:
                r = run(
                    f"screen_{case}_k{k}_{backend}",
                    case,
                    backend,
                    60,
                    0,
                    cases[case][2][k],
                )
                if (
                    r
                    and k >= 20
                    and r.get("metrics")
                    and r["metrics"]["served"] > r["outside_served"]
                    and r.get("new_cabin_served", 0) > 0
                ):
                    manifest["gate"][backend] = True
    manifest["status"] = "CONSTRUCTION"
    persist()
    for seed in (0, 1):
        backends = ("cp_sat", "gurobi") if seed == 0 else ("gurobi", "cp_sat")
        for backend in backends:
            if manifest["gate"].get(backend):
                run(f"construct_R2_{backend}_s{seed}", "R2", backend, 480, seed)
            else:
                manifest["runs"].append(
                    {
                        "name": f"construct_R2_{backend}_s{seed}",
                        "status": "SKIPPED_GATE",
                    }
                )
    manifest.update(
        status="COMPLETE",
        finished_unix=time.time(),
        total_wall_seconds=time.time() - started,
    )
    persist()
    lines = [
        "# Greedy reservoir pilot",
        "",
        f"Actual wall time: {manifest['total_wall_seconds']:.1f} s",
        "",
        "| Run | Status | Served | Seconds |",
        "|---|---|---:|---:|",
    ]
    for e in manifest["runs"]:
        r = e.get("result") or {}
        m = r.get("metrics") or {}
        lines.append(
            f"| {e['name']} | {r.get('termination', r.get('status', e['status']))} | {m.get('served', '—')} | {r.get('runner_total_wall_seconds', '—')} |"
        )
    lines += [
        "",
        "Historical comparisons: per-case historical_comparison.json. Their contract differences and clocks are explicit. No global greedy bound.",
    ]
    (args.output / "report.md").write_text("\n".join(lines) + "\n")
    if args.live_directory:
        live["status"] = "complete"
        atomic_json(args.live_directory / "manifest.json", live)


if __name__ == "__main__":
    main()
