"""Bounded product/binary comparison; native CP-SAT search, conditional full test."""

import argparse
import hashlib
import json
import os
import platform
import shutil
import sys
import time
from pathlib import Path

import ortools

from ropeway_skip_stop_optimization.benchmarking.native_solvers import supervise
from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_certificate import (
    atomic_json,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_cp_sat_certificate import (
    read_reservoir_cp_checkpoint,
    validate_reservoir_cp_plan,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_diagnostics import (
    ReservoirDiagnostic,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_hybrid.domain import (
    load_reference,
)

ROOT = Path(__file__).resolve().parents[1]


def assess(rows, profile):
    """Both paired seeds must meet the prospectively fixed threshold."""
    comparisons = []
    for seed in (0, 1):
        pair = {
            e["cost_encoding"]: e
            for e in rows
            if e["diagnostic_profile"] == profile and e["seed"] == seed
        }
        if set(pair) != {"product", "binary"}:
            comparisons.append(
                {"seed": seed, "passed": False, "reason": "missing pair"}
            )
            continue
        old, new = pair["product"], pair["binary"]
        valid = all(
            e["status"] in ("FEASIBLE", "OPTIMAL")
            and not e.get("error")
            and e["monitor"]["exit_code"] == 0
            for e in (old, new)
        )
        better_ub = new["ub_tick"] * 1000 <= old["ub_tick"] * 999
        old_lb, new_lb = old["lb_seconds"], new["lb_seconds"]
        gap_change = None
        if old_lb is not None and new_lb is not None:
            gap_change = (1 - old_lb * 1e6 / old["ub_tick"]) - (
                1 - new_lb * 1e6 / new["ub_tick"]
            )
        better_gap = (
            new["ub_tick"] <= old["ub_tick"]
            and gap_change is not None
            and gap_change >= 0.01 - 1e-12
        )
        comparisons.append(
            {
                "seed": seed,
                "passed": valid and (better_ub or better_gap),
                "valid_pair": valid,
                "ub_improvement_fraction": 1 - new["ub_tick"] / old["ub_tick"],
                "gap_improvement_percentage_points": None
                if gap_change is None
                else gap_change * 100,
                "better_ub": better_ub,
                "better_gap": better_gap,
            }
        )
    return {"passed": all(e["passed"] for e in comparisons), "pairs": comparisons}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--reference",
        type=Path,
        default=ROOT
        / "benchmarks/output/reservoir_diagnostics_20260911_v1/reference.json",
    )
    a = parser.parse_args()
    started = time.time()
    deadline = started + 1800
    out = a.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    domain, ref = load_reference(a.reference)
    reference = validate_reservoir_cp_plan(domain.problem, ref).journey_time_tick
    if (
        reference != 368765817136
        or domain.fingerprint
        != "ea2b46d53da6f34147bfd5a9c1a635116e89eb47afd84cfd036b56971376ac65"
    ):
        raise ValueError("frozen R instance/reference changed")
    shutil.copy2(a.reference, out / "reference.json")
    import pickle

    data = pickle.dumps((domain.problem, ref))
    inp = out / "input.pickle"
    inp.write_bytes(data)
    inp.with_suffix(".sha256").write_text(hashlib.sha256(data).hexdigest())
    src = out / "sources"
    shutil.copytree(
        ROOT / "src", src / "src", ignore=shutil.ignore_patterns("__pycache__", "*.pyc")
    )
    (src / "benchmarks").mkdir()
    for name in (
        "run_reservoir_diagnostics.py",
        Path(__file__).name,
        "report_reservoir_diagnostics.py",
    ):
        shutil.copy2(ROOT / "benchmarks" / name, src / "benchmarks" / name)
    for name in ("pyproject.toml", "uv.lock"):
        shutil.copy2(ROOT / name, src / name)
    atomic_json(
        out / "source_hashes.json",
        {
            str(p.relative_to(src)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in src.rglob("*")
            if p.is_file()
        },
    )
    manifest = {
        "schema": "reservoir_binary_cost_comparison_v1",
        "started_unix": started,
        "deadline_unix": deadline,
        "time_limit_per_trial": 180,
        "workers": 12,
        "reference_tick": reference,
        "reference_used_cabins": len(ref.trips),
        "domain_fingerprint": domain.fingerprint,
        "formulation": "legacy",
        "engine_version": ortools.__version__,
        "python": sys.version,
        "platform": platform.platform(),
        "thresholds": {
            "cost_fraction": 0.001,
            "gap_percentage_points": 1,
            "required_seeds": [0, 1],
        },
        "gates": [],
        "runs": [],
    }
    env = {**os.environ, "PYTHONPATH": str(src / "src")}
    script = src / "benchmarks/run_reservoir_diagnostics.py"

    def save():
        atomic_json(out / "campaign.json", manifest)

    def execute(profile, encoding, seed, verify=False):
        seconds = 30 if verify else 180
        if time.time() + seconds + 15 > deadline:
            raise TimeoutError(
                "not enough original wall budget; no further run started"
            )
        name = ("verify" if verify else f"seed{seed}") + f"_{profile}_{encoding}"
        folder = out / name
        folder.mkdir()
        command = [
            sys.executable,
            str(script),
            "--input",
            str(inp),
            "--output",
            str(folder),
            "--profile",
            profile,
            "--cost-encoding",
            encoding,
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
                "command": command,
                "profile": profile,
                "cost_encoding": encoding,
                "seed": seed,
                "budget": seconds,
                "workers": 1 if verify else 12,
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
            else {}
        )
        if verify:
            entry = {
                "profile": profile,
                "cost_encoding": encoding,
                "monitor": monitor,
                **result,
            }
            manifest["gates"].append(entry)
            save()
            if not result.get("passed") or monitor["exit_code"] != 0:
                raise RuntimeError("historical exact replay failed")
        else:
            if (folder / "best.json").exists():
                observe(folder / "best.json", monitor["awake_wall_seconds"])
            entry = {
                "profile": f"{profile}_{encoding}",
                "diagnostic_profile": profile,
                "cost_encoding": encoding,
                "seed": seed,
                "folder": name,
                "monitor": monitor,
                "status": result.get(
                    "solver_status", result.get("status", "INTERRUPTED")
                ),
                "ub_tick": min([reference, *[e["objective_tick"] for e in curve]]),
                "lb_seconds": result.get("cp_lower_bound"),
                "proof_scope": result.get("proof_scope"),
                "proven_optimal": result.get("proven_optimal", False),
                "error": result.get("error"),
            }
            if result.get("validated_upper_bound") is not None and entry[
                "ub_tick"
            ] != round(result["validated_upper_bound"] * 1e6):
                raise ValueError(
                    "reported upper bound differs from independently checked checkpoint"
                )
            manifest["runs"].append(entry)
            save()
            if entry["error"] or monitor["supervisor_reason"] in (
                "SUSPEND_DETECTED",
                "INVALID_CHECKPOINT",
            ):
                raise RuntimeError("campaign stopped after invalid output or suspend")
        print(json.dumps(entry), flush=True)

    save()
    try:
        for encoding in ("product", "binary"):
            execute("full", encoding, 0, verify=True)
        for profile in ("timing", "full"):
            if profile == "full" and not manifest["timing_gate"]["passed"]:
                manifest["full_stage"] = "NOT_STARTED: timing threshold failed"
                break
            for seed, encoding in (
                (0, "product"),
                (0, "binary"),
                (1, "binary"),
                (1, "product"),
            ):
                execute(profile, encoding, seed)
            manifest[f"{profile}_gate"] = assess(manifest["runs"], profile)
            save()
        manifest["complete"] = True
    except (RuntimeError, TimeoutError, ValueError) as exc:
        manifest["complete"] = False
        manifest["stopped_reason"] = str(exc)
        raise
    finally:
        manifest["elapsed_seconds"] = time.time() - started
        save()


if __name__ == "__main__":
    main()
