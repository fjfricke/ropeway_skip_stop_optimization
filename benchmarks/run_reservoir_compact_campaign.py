"""Frozen sequential architecture comparison: maximum 60 minutes after gates."""

import argparse
from dataclasses import asdict
import hashlib
import importlib.metadata
import json
import os
import psutil
from pathlib import Path
import re
import shutil
import sys
import time

from ropeway_skip_stop_optimization.benchmarking.process_supervisor import supervise
from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_certificate import (
    atomic_json,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_capacity.formulation import (
    ReservoirPhaseFormulationConfig as Config,
)

ROOT = Path(__file__).resolve().parents[1]
VARIANTS = {
    "L": Config(),
    "P1": Config(passenger_encoding="od_flow"),
    "P2": Config(passenger_encoding="od_queue"),
    "I": Config(passenger_encoding="od_flow", passenger_integrality="boarding"),
    "K": Config(passenger_encoding="od_flow", passenger_network="contracted"),
    "R": Config(resource_encoding="maximal"),
    "C": Config(conflict_cuts="local_cliques"),
}


def read(path):
    return json.loads(path.read_text()) if path.exists() else {}


def check_previous_completed(directory):
    """Check status plus live command identity, never a potentially reused PID."""
    if read(directory / "status.json").get("state") != "completed":
        raise RuntimeError("previous sequential comparison has not completed")
    prefix = str((directory / "sources").resolve()) + os.sep
    matches = []
    for process in psutil.process_iter(["pid", "cmdline", "create_time"]):
        try:
            args = process.info.get("cmdline") or []
            if any(arg.startswith(prefix) for arg in args):
                matches.append(process.info)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    if matches:
        raise RuntimeError(f"previous frozen worker still alive: {matches}")
    return dict(completed=True, active_frozen_workers=matches, checked_unix=time.time())


def summarize(run):
    result, guard = read(run / "result.json"), read(run / "supervisor.json")
    failure = read(run / "failure.json")
    recovered = not bool(result)
    log = (
        (run / "process.log").read_text(errors="replace")
        if (run / "process.log").exists()
        else ""
    )
    barrier = re.findall(r"Barrier solved model in .*? ([\d.]+) seconds", log)
    crossover = re.findall(r"Crossover time: ([\d.]+) seconds", log)
    presolved = re.findall(r"Presolved: (\d+) rows, (\d+) columns, (\d+) nonzeros", log)
    events = (
        [json.loads(line) for line in (run / "events.jsonl").read_text().splitlines()]
        if (run / "events.jsonl").exists()
        else []
    )
    if recovered:
        from ropeway_skip_stop_optimization.optimization.ddd.reservoir_hybrid.domain import (
            load_reference,
        )
        from ropeway_skip_stop_optimization.optimization.ddd.reservoir_cp_sat_certificate import (
            validate_reservoir_cp_plan,
        )

        result = read(run / "model_ready.json") | read(run / "search_started.json")
        if (run / "best.json").exists():
            domain, plan = load_reference(run / "best.json")
            metrics = validate_reservoir_cp_plan(domain.problem, plan)
            reference = read(run / "reference.json")
            if domain.problem.fingerprint != reference.get("problem_fingerprint"):
                raise ValueError("recovered checkpoint domain mismatch")
            result.update(
                validated_upper_bound=metrics.unserved,
                reference_unserved=reference["metrics"]["unserved"],
            )
        sizes = re.findall(
            r"Optimize a model with (\d+) rows, (\d+) columns and (\d+) nonzeros", log
        )
        if sizes:
            rows, columns, nonzeros = map(int, sizes[-1])
            result.update(rows=rows, variables=columns, nonzeros=nonzeros)
        bounds = [e["lower"] for e in events if e.get("event") == "restricted_bound"]
        result.update(
            restricted_lower_bound=max(bounds) if bounds else None,
            total_seconds=guard.get("civil_wall_seconds", 0),
            status=guard.get("supervisor_reason") or "INTERRUPTED",
        )
        if not sizes:
            failure = failure or {"type": "INCOMPLETE_MODEL", "proof": False}
        if guard.get("supervisor_reason") == "CONTROLLER_REPAIR_INTERRUPTION":
            failure = failure or {"type": "INCOMPLETE_COMPARISON", "proof": False}
        atomic_json(
            run / "recovered_result.json",
            result
            | {
                "origin": "independently_validated_checkpoint_and_native_log",
                "native_final_result_missing": True,
            },
        )
    improvements = [e for e in events if e.get("improvement")]
    offset = result.get("search_start_offset_seconds")
    progress = []
    upper, lower = result.get("reference_unserved"), 0
    if upper is not None:
        progress.append(dict(seconds=0, upper=upper, lower=0))
    if offset is not None:
        for event in sorted(events, key=lambda e: e.get("seconds", 0)):
            if event.get("event") == "native_solution":
                upper = (
                    min(upper, event["unserved"])
                    if upper is not None
                    else event["unserved"]
                )
            if event.get("event") == "restricted_bound":
                lower = max(lower, event["lower"])
            progress.append(
                dict(seconds=offset + event.get("seconds", 0), upper=upper, lower=lower)
            )
    if result.get("validated_upper_bound") is not None:
        progress.append(
            dict(
                seconds=result["total_seconds"],
                upper=result["validated_upper_bound"],
                lower=max(0, result.get("restricted_lower_bound") or 0),
            )
        )
    return dict(
        run=run.name,
        progress=progress,
        upper=result.get("validated_upper_bound"),
        reference_upper=read(run / "reference.json").get("metrics", {}).get("unserved"),
        lower=result.get("restricted_lower_bound"),
        variables=result.get("variables"),
        rows=result.get("rows"),
        nonzeros=result.get("nonzeros"),
        root_seconds=result.get("root_lp_complete_seconds"),
        root_total_seconds=(
            offset + result["root_lp_complete_seconds"]
            if offset is not None and result.get("root_lp_complete_seconds") is not None
            else None
        ),
        barrier_seconds=float(barrier[-1]) if barrier else None,
        crossover_seconds=float(crossover[-1]) if crossover else None,
        presolved=list(map(int, presolved[-1])) if presolved else None,
        model_seconds=result.get("model_seconds"),
        preparation_seconds=result.get("passenger_preparation_seconds"),
        hint_seconds=result.get("hint_seconds"),
        search_seconds=result.get("search_seconds"),
        validation_seconds=result.get("validation_seconds"),
        improvements=improvements,
        last_improvement_seconds=improvements[-1]["seconds"] if improvements else None,
        status=result.get("status"),
        failure=failure,
        recovered_checkpoint=recovered,
        directory=str(run.resolve()),
        supervision=guard,
    )


def rank(r):
    from report_reservoir_compact_campaign import reach

    upper = r["upper"]
    lower = max(0, r["lower"]) if r["lower"] is not None else 0
    attained = reach(r, upper, lower) if upper is not None else None
    return (
        upper if upper is not None else float("inf"),
        -lower,
        attained if attained is not None else float("inf"),
        r["root_total_seconds"]
        if r["root_total_seconds"] is not None
        else float("inf"),
        r["presolved"][1] if r["presolved"] else r["variables"] or float("inf"),
    )


def report(out, results):
    atomic_json(out / "comparison.json", results)
    lines = [
        "# Compact reservoir architecture comparison",
        "",
        "All bounds below apply only to the identical restricted graph.",
        "",
        "| Run | Reference U | Validated U | Local LB | Variables | Root seconds | Improvements | Status |",
        "|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for r in results:
        lines.append(
            f"| {r['run']} | {r['reference_upper']} | {r['upper']} | {r['lower']} | {r['variables']} | {r['root_seconds']} | {len(r['improvements'])} | {r['status']} |"
        )
    (out / "comparison.md").write_text("\n".join(lines) + "\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--reference-dir", type=Path, required=True)
    parser.add_argument("--previous-followup", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--gate-evidence", type=Path, required=True)
    parser.add_argument("--continue-campaign", type=Path)
    a = parser.parse_args()
    previous_audit = check_previous_completed(a.previous_followup)
    gate = read(a.gate_evidence)
    if not gate.get("passed"):
        raise RuntimeError("correctness/replay gates not passed")
    prior_manifest = (
        read(a.continue_campaign / "manifest.json") if a.continue_campaign else {}
    )
    started = prior_manifest.get("started_unix", time.time())
    awake_started = time.monotonic() - (time.time() - started)
    deadline = prior_manifest.get("deadline_unix", started + 3600)
    if time.time() >= deadline:
        raise RuntimeError("original campaign deadline already expired")
    if prior_manifest and prior_manifest["variants"] != {
        k: asdict(v) for k, v in VARIANTS.items()
    }:
        raise RuntimeError("resume must preserve formulation variants")
    out = a.output_dir.resolve()
    out.mkdir(parents=True, exist_ok=False)
    sources = out / "sources"
    shutil.copytree(
        ROOT / "src",
        sources / "src",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.egg-info"),
    )
    (sources / "benchmarks").mkdir()
    for name in (
        "run_reservoir_capacity_arc_flow.py",
        "report_reservoir_compact_campaign.py",
        Path(__file__).name,
    ):
        shutil.copy2(ROOT / "benchmarks" / name, sources / "benchmarks" / name)
    for name in ("pyproject.toml", "uv.lock"):
        shutil.copy2(ROOT / name, sources / name)
    hashes = {
        str(p.relative_to(sources)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sources.rglob("*")
        if p.is_file()
    }
    atomic_json(out / "source_hashes.json", hashes)
    # Gates bind to actual source contents, not a stale boolean from another build.
    for relative, digest in gate.get("source_hashes", {}).items():
        if hashlib.sha256((sources / relative).read_bytes()).hexdigest() != digest:
            raise RuntimeError("source changed after correctness gate")
    if not gate.get("source_hashes"):
        raise RuntimeError("gate lacks source hashes")
    refs = {}
    for case in ("R0", "R2"):
        path = out / f"{case}_reference.json"
        shutil.copy2(a.reference_dir / f"{case}_ss.json", path)
        refs[case] = path
    atomic_json(
        out / "manifest.json",
        dict(
            started_unix=started,
            deadline_unix=deadline,
            budget_seconds=3600,
            threads=12,
            memory_gib=24,
            variants={k: asdict(c) for k, c in VARIANTS.items()},
            versions={
                p: importlib.metadata.version(p) for p in ("gurobipy", "ortools")
            },
            references={
                k: hashlib.sha256(v.read_bytes()).hexdigest() for k, v in refs.items()
            },
            gate_evidence=str(a.gate_evidence.resolve()),
            previous_process_audit=previous_audit,
            continued_from=str(a.continue_campaign.resolve())
            if a.continue_campaign
            else None,
            continuation_note="No repeated attempts; original deadline preserved. Worker closing reserve and checkpoint recovery repaired."
            if a.continue_campaign
            else None,
        ),
    )
    env = dict(os.environ, PYTHONPATH=str(sources / "src"))
    results = (
        [
            summarize(p.parent)
            for p in sorted(a.continue_campaign.glob("*/command.json"))
        ]
        if a.continue_campaign
        else []
    )
    completed_names = {r["run"] for r in results}
    suspended = False

    def run(case, profile, seed, seconds):
        nonlocal suspended
        if f"{case}_{profile}_s{seed}" in completed_names:
            return
        if (
            suspended
            or time.time() - started - (time.monotonic() - awake_started) > 5
            or time.time() + 3 >= deadline
        ):
            return
        directory = out / f"{case}_{profile}_s{seed}"
        directory.mkdir()
        command = [
            sys.executable,
            str(sources / "benchmarks/run_reservoir_capacity_arc_flow.py"),
            "--_worker",
            "--method",
            "phase_arc_flow",
            "--reference",
            str(refs[case]),
            "--output-dir",
            str(directory),
            "--time-limit",
            str(seconds),
            "--threads",
            "12",
            "--memory-gib",
            "24",
            "--seed",
            str(seed),
            "--deadline-unix",
            str(deadline),
        ]
        for key, value in asdict(VARIANTS[profile]).items():
            command += ["--" + key.replace("_", "-"), str(value)]
        atomic_json(directory / "command.json", command)
        atomic_json(out / "status.json", dict(state="running", run=directory.name))
        guard = supervise(
            command,
            directory,
            seconds=seconds,
            memory_bytes=24 * 1024**3,
            global_deadline=deadline,
            env=env,
        )
        suspended = guard.get("supervisor_reason") == "SUSPEND_DETECTED"
        r = summarize(directory)
        results.append(r)
        report(out, results)

    for case in ("R0", "R2"):
        for profile in VARIANTS:
            run(case, profile, 0, 120)
    candidates = [
        r
        for r in results
        if r["run"].startswith("R2_")
        and not r["run"].startswith("R2_L_")
        and not r["failure"]
        and r["upper"] is not None
    ]
    if candidates:
        best = min(candidates, key=rank)["run"].split("_")[1]
        atomic_json(
            out / "selection.json",
            dict(
                profile=best,
                rule="validated UB, nonnegative local LB, build-inclusive attainment time, root completion, model size",
                structural_fallback=not any(
                    r["improvements"] or r["root_seconds"] is not None
                    for r in candidates
                ),
            ),
        )
        for seed, order in ((1, (best, "L")), (2, ("L", best))):
            for profile in order:
                run("R2", profile, seed, 300)
    atomic_json(
        out / "status.json",
        dict(
            state="completed",
            total_seconds=time.time() - started,
            runs=len(results),
            expected_runs=18,
        ),
    )
    report(out, results)
    from report_reservoir_compact_campaign import assess

    selection = read(out / "selection.json")
    atomic_json(
        out / "decision.json", assess(results, selection.get("profile", "unknown"))
    )


if __name__ == "__main__":
    main()
