"""Two bounded follow-up restrictions; no incumbent-guided search controller."""

import argparse
import hashlib
import json
import os
import shutil
import sys
import time
from pathlib import Path

from ropeway_skip_stop_optimization.benchmarking.native_solvers import supervise
from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_certificate import (
    atomic_json,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_cp_sat_certificate import (
    read_reservoir_cp_checkpoint,
    validate_reservoir_cp_plan,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_diagnostics import (
    EXTRA_PROFILES,
    ReservoirDiagnostic,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_hybrid.domain import (
    load_reference,
)

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("campaign", type=Path)
    a = parser.parse_args()
    out = a.campaign.resolve()
    main = json.loads((out / "campaign.json").read_text())
    if not main.get("complete"):
        raise ValueError("main campaign must complete before follow-up")
    deadline = main["deadline_unix"]
    domain, ref = load_reference(out / "reference.json")
    src = out / "sources_followup"
    shutil.copytree(out / "sources", src)
    for path in (ROOT / "src").rglob("*.py"):
        dest = src / "src" / path.relative_to(ROOT / "src")
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, dest)
    for path in (Path(__file__), ROOT / "benchmarks/run_reservoir_diagnostics.py"):
        shutil.copy2(path, src / "benchmarks" / path.name)
    atomic_json(
        out / "source_hashes_followup.json",
        {
            str(f.relative_to(src)): hashlib.sha256(f.read_bytes()).hexdigest()
            for f in src.rglob("*")
            if f.is_file()
        },
    )
    script = src / "benchmarks/run_reservoir_diagnostics.py"
    env = {**os.environ, "PYTHONPATH": str(src / "src")}
    manifest = {
        "scope": "follow-up restrictions, bounds not global",
        "deadline_unix": deadline,
        "runs": [],
        "gates": [],
    }
    for verify in (True, False):
        for seed in (0,) if verify else (0, 1):
            profiles = EXTRA_PROFILES if seed == 0 else tuple(reversed(EXTRA_PROFILES))
            for profile in profiles:
                seconds = 30 if verify else 90
                if time.time() + seconds + 10 > deadline:
                    manifest["runs"].append(
                        {
                            "profile": profile,
                            "seed": seed,
                            "status": "NOT_STARTED",
                            "reason": "original global deadline",
                        }
                    )
                    atomic_json(out / "followup.json", manifest)
                    continue
                name = ("verify_" if verify else f"seed{seed}_") + profile
                folder = out / name
                folder.mkdir()
                command = [
                    sys.executable,
                    str(script),
                    "--input",
                    str(out / "input.pickle"),
                    "--output",
                    str(folder),
                    "--profile",
                    profile,
                    "--seed",
                    str(seed),
                    "--seconds",
                    str(seconds),
                ]
                if verify:
                    command.append("--verify")
                atomic_json(
                    folder / "config.json",
                    {
                        "profile": profile,
                        "seed": seed,
                        "budget": seconds,
                        "verify": verify,
                        "reference_tick": main["reference_tick"],
                    },
                )
                curve = []

                def observe(path, elapsed, profile=profile, curve=curve, folder=folder):
                    plan = read_reservoir_cp_checkpoint(path, domain.problem)
                    ReservoirDiagnostic(profile).validate(domain.problem, ref, plan)
                    value = validate_reservoir_cp_plan(
                        domain.problem, plan
                    ).journey_time_tick
                    curve.append({"elapsed_seconds": elapsed, "objective_tick": value})
                    atomic_json(folder / "validated_curve.json", {"events": curve})

                monitor = supervise(
                    command,
                    folder,
                    seconds=seconds,
                    global_deadline=deadline,
                    env=env,
                    checkpoint_callback=None if verify else observe,
                )
                result = (
                    json.loads((folder / "result.json").read_text())
                    if (folder / "result.json").exists()
                    else {"status": "INTERRUPTED", "passed": False}
                )
                if verify:
                    manifest["gates"].append({"profile": profile, **result})
                    atomic_json(out / "followup.json", manifest)
                    if not result.get("passed"):
                        raise RuntimeError("follow-up replay failed")
                else:
                    if (folder / "best.json").exists():
                        observe(folder / "best.json", monitor["awake_wall_seconds"])
                    entry = {
                        "profile": profile,
                        "seed": seed,
                        "folder": name,
                        "monitor": monitor,
                        "status": result.get("solver_status", result.get("status")),
                        "proof_scope": result.get("proof_scope"),
                        "ub_tick": min(
                            [
                                main["reference_tick"],
                                *[e["objective_tick"] for e in curve],
                            ]
                        ),
                        "lb_seconds": result.get("cp_lower_bound"),
                        "proven_optimal": result.get("proven_optimal", False),
                        "model_stats": result.get("model_stats"),
                        "error": result.get("error"),
                    }
                    manifest["runs"].append(entry)
                    atomic_json(out / "followup.json", manifest)
                    if entry["error"] or monitor["supervisor_reason"] in (
                        "SUSPEND_DETECTED",
                        "INVALID_CHECKPOINT",
                    ):
                        raise RuntimeError("follow-up stopped after invalid output")
                print(
                    json.dumps(
                        {
                            "profile": profile,
                            "seed": seed,
                            "verify": verify,
                            "status": result.get("solver_status", result.get("status")),
                            "ub": result.get("validated_upper_bound"),
                            "lb": result.get("cp_lower_bound"),
                        }
                    ),
                    flush=True,
                )
    manifest.update(
        complete=True, elapsed_since_main_start=time.time() - main["started_unix"]
    )
    atomic_json(out / "followup.json", manifest)


if __name__ == "__main__":
    main()
