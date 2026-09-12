"""Frozen sequential campaign. Every slot includes build and validation time."""

import argparse
import hashlib
import importlib.metadata
import json
import math
import os
import pickle
import shutil
import sys
import time
from pathlib import Path
from types import SimpleNamespace

from verify_native_solver_replays import frozen_cases

from ropeway_skip_stop_optimization.benchmarking.native_solvers import (
    assess_campaign,
    supervise,
    worker,
)
from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_certificate import (
    atomic_json,
    read_ddd_cp_sat_checkpoint,
    validate_ddd_cp_sat_domain,
)
from ropeway_skip_stop_optimization.optimization.ddd.native_solvers.optimizer import (
    validate_plan,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_cp_sat_certificate import (
    read_reservoir_cp_checkpoint,
)

ROOT = Path(__file__).resolve().parents[1]


def installed_version(name):
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def read_json(path):
    return json.loads(path.read_text())


def child(args):
    started = time.monotonic()
    # Private, locally generated input: source manifest verifies its bytes before
    # unpickling. This is not a public checkpoint format or an untrusted import.
    expected = (args._input.with_suffix(".sha256")).read_text().strip()
    data = args._input.read_bytes()
    if hashlib.sha256(data).hexdigest() != expected:
        raise ValueError("frozen input changed")
    problem, seed, objective, _ = pickle.loads(data)
    run = SimpleNamespace(
        output_dir=args._run_dir,
        time_limit=150,
        backend=args._backend,
        objective=objective,
        num_workers=12,
        seed=args._seed,
        build_only=False,
    )
    try:
        worker(problem, seed, run, started=started)
    except Exception as exc:  # noqa: BLE001 - preserve diagnostics across optional native engine failures
        atomic_json(
            args._run_dir / "result.json",
            {
                "status": "ERROR",
                "error": f"{type(exc).__name__}: {exc}",
                "proven_optimal": False,
            },
        )


def main():
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--gates-dir", type=Path)
    parser.add_argument(
        "--backends",
        nargs="+",
        choices=["cp_sat", "hexaly", "z3"],
        default=["cp_sat", "hexaly", "z3"],
    )
    parser.add_argument("--_input", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--_run-dir", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--_backend", help=argparse.SUPPRESS)
    parser.add_argument("--_seed", type=int, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args._input:
        return child(args)
    if args.output_dir is None or args.gates_dir is None:
        parser.error("output and gates directories required")
    civil, awake = time.time(), time.monotonic()
    deadline = civil + 3600
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=False)
    cases = frozen_cases()
    manifest = {
        "schema": "native_solver_campaign_v1",
        "started_unix": civil,
        "deadline_unix": deadline,
        "maximum_wall_seconds": 3600,
        "cases": [],
        "gates": {},
        "instances": {},
        "common_bounds": {},
        "selected_backends": args.backends,
        "versions": {
            name: installed_version(name)
            for name in ("z3-solver", "hexaly", "ortools", "psutil")
        },
    }
    # Freeze actual source bytes, excluding caches/artifacts, not just git HEAD.
    source_dir = output / "sources"
    shutil.copytree(
        ROOT / "src",
        source_dir / "src",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.egg-info"),
    )
    for name in ("run_native_solver_campaign.py", "verify_native_solver_replays.py"):
        target = source_dir / "benchmarks" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / "benchmarks" / name, target)
    for name in ("pyproject.toml", "uv.lock"):
        shutil.copy2(ROOT / name, source_dir / name)
    hashes = {
        str(p.relative_to(source_dir)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in source_dir.rglob("*")
        if p.is_file()
    }
    atomic_json(output / "source_hashes.json", hashes)
    for backend in ("z3", "hexaly"):
        gate = args.gates_dir / f"{backend}.json"
        manifest["gates"][backend] = (
            read_json(gate)
            if gate.exists()
            else {"passed": False, "reason": "correctness/engine gate pending"}
        )
    for backend in ("tempest", "patty"):
        gate = args.gates_dir / f"{backend}.json"
        manifest["gates"][backend] = (
            read_json(gate) if gate.exists() else {"gate": "NOT_CERTIFIED"}
        )
    for key, (problem, seed, objective, expected) in cases.items():
        data = pickle.dumps((problem, seed, objective, expected))
        path = output / f"{key}.pickle"
        path.write_bytes(data)
        path.with_suffix(".sha256").write_text(hashlib.sha256(data).hexdigest())
        from ropeway_skip_stop_optimization.optimization.ddd.native_solvers import (
            prepare_native_structure,
        )

        prepared = prepare_native_structure(problem)
        manifest["instances"][key] = {
            "domain_fingerprint": prepared.domain_fingerprint,
            "reference": expected,
            "objective": objective,
        }
        manifest["common_bounds"][key] = (
            0 if objective == "unserved" else prepared.bounds.analytical_lower_bound
        )
    bound_path = (
        ROOT
        / "benchmarks/output/reservoir_hybrid_comparison_20260911_v1/common_bound.json"
    )
    if bound_path.exists():
        bound = read_json(bound_path)
        provenance = read_json(bound_path.with_name("bound_provenance.json"))
        if (
            bound["fingerprint"] == manifest["instances"]["R"]["domain_fingerprint"]
            and provenance["problem_fingerprint"] == bound["fingerprint"]
            and provenance["G3_passed"]
            and bound["value"] == provenance["certified_lower_bound"]
        ):
            manifest["common_bounds"]["R"] = max(
                manifest["common_bounds"]["R"], math.floor(bound["value"] * 1000000)
            )
            shutil.copy2(bound_path, output / "common_bound.json")
            shutil.copy2(
                bound_path.with_name("bound_provenance.json"),
                output / "bound_provenance.json",
            )
    env = {**os.environ, "PYTHONPATH": str(source_dir / "src")}
    atomic_json(output / "campaign.json", manifest)
    stopped = False
    engines = args.backends
    for repeat in range(3):
        order = engines[repeat:] + engines[:repeat]
        for key in ("R", "C"):
            problem, seed, objective, reference = cases[key]
            for backend in order:
                label = f"{key}_{backend}_{repeat}"
                entry = {
                    "case": key,
                    "backend": backend,
                    "repetition": repeat,
                    "name": label,
                }
                if backend != "cp_sat" and not manifest["gates"][backend].get("passed"):
                    entry.update(
                        status="NOT_STARTED",
                        reason="correctness/engine gate not passed",
                    )
                elif stopped or time.time() + 150 + 30 > deadline:
                    entry.update(
                        status="NOT_STARTED", reason="shared deadline or suspend"
                    )
                else:
                    folder = output / label
                    folder.mkdir()
                    curve = []

                    def observe(
                        path,
                        elapsed,
                        problem=problem,
                        key=key,
                        objective=objective,
                        reference=reference,
                        curve=curve,
                        folder=folder,
                    ):
                        plan = (
                            read_reservoir_cp_checkpoint(path, problem)
                            if key == "R"
                            else read_ddd_cp_sat_checkpoint(
                                path,
                                problem=problem,
                                manifest=validate_ddd_cp_sat_domain(problem),
                            )
                        )
                        _, metrics = validate_plan(problem, plan)
                        value = metrics[
                            "journey_time_tick"
                            if objective == "journey_time"
                            else "unserved"
                        ]
                        curve.append(
                            {
                                "elapsed_seconds": elapsed,
                                "validated_objective": value,
                                "improves_reference": value < reference,
                            }
                        )
                        atomic_json(folder / "validated_curve.json", {"events": curve})

                    command = [
                        sys.executable,
                        str(source_dir / "benchmarks/run_native_solver_campaign.py"),
                        "--_input",
                        str(output / f"{key}.pickle"),
                        "--_run-dir",
                        str(folder),
                        "--_backend",
                        backend,
                        "--_seed",
                        str(repeat),
                    ]
                    monitor = supervise(
                        command,
                        folder,
                        seconds=150,
                        global_deadline=deadline,
                        checkpoint_callback=observe,
                        env=env,
                    )
                    if (folder / "best.json").exists():
                        observe(folder / "best.json", monitor["awake_wall_seconds"])
                    result = (
                        read_json(folder / "result.json")
                        if (folder / "result.json").exists()
                        else {"status": "INTERRUPTED", "proven_optimal": False}
                    )
                    ub = min([reference, *[x["validated_objective"] for x in curve]])
                    native_lb = result.get("lower_bound")
                    lb = max(
                        manifest["common_bounds"][key],
                        native_lb if native_lb is not None else 0,
                    )
                    if lb > ub:
                        raise ValueError("comparable LB exceeds validated UB")
                    entry.update(
                        status=result["status"],
                        validated_upper_bound=ub,
                        native_lower_bound=native_lb,
                        comparable_lower_bound=lb,
                        gap=(ub - lb) / ub if ub else 0,
                        strict_improvements=sum(
                            e["improves_reference"]
                            and (
                                i == 0
                                or e["validated_objective"]
                                < min(x["validated_objective"] for x in curve[:i])
                            )
                            for i, e in enumerate(curve)
                        ),
                        error=result.get("error"),
                        metrics=monitor,
                        result_path=str(folder / "result.json"),
                    )
                    stopped = (
                        monitor["supervisor_reason"]
                        in ("SUSPEND_DETECTED", "INVALID_CHECKPOINT")
                        or result.get("status") == "ERROR"
                        or time.time() - civil - (time.monotonic() - awake) > 5
                    )
                manifest["cases"].append(entry)
                manifest["actual_civil_seconds"] = time.time() - civil
                atomic_json(output / "campaign.json", manifest)
                print(json.dumps(entry), flush=True)
    for backend in ("tempest", "patty"):
        for operation in ("fixed_k", "reservoir"):
            manifest["cases"].append(
                {
                    "backend": backend,
                    "operation": operation,
                    "status": "NOT_STARTED",
                    "reason": "exact temporal semantics gate not passed",
                }
            )
    manifest["actual_civil_seconds"] = time.time() - civil
    manifest["complete"] = True
    manifest["recommendations"] = assess_campaign(manifest["cases"])
    atomic_json(output / "campaign.json", manifest)
    rows = [
        "# Native solver campaign",
        "",
        "| Case | Engine | Repeat | Status | Validated UB | Comparable LB | Gap |",
        "|---|---|---:|---|---:|---:|---:|",
    ]
    for c in manifest["cases"]:
        gap = c.get("gap")
        rows.append(
            f"| {c.get('case', c.get('operation'))} | {c['backend']} | {c.get('repetition', '—')} | {c['status']} | {c.get('validated_upper_bound', '—')} | {c.get('comparable_lower_bound', '—')} | {'—' if gap is None else format(gap, '.2%')} |"
        )
    rows += [
        "",
        "R values are person-ticks; C values are persons. Reference adoption is not improvement.",
        "No recommendation is made for engines without both confirmation repetitions.",
        f"Actual campaign wall time: {manifest['actual_civil_seconds']:.2f} seconds.",
    ]
    (output / "report.md").write_text("\n".join(rows) + "\n")


if __name__ == "__main__":
    main()
