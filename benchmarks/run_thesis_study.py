"""Execute an explicitly frozen fixed-K study, with restartable attempts."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import hashlib
from pathlib import Path
import subprocess
import sys
import time
import zipfile

from ropeway_skip_stop_optimization.benchmarking.native_solvers import supervise
from ropeway_skip_stop_optimization.benchmarking.thesis_study import (
    DemandLadder, confirmed_service, journey_confirmed, manifest_identity, validate_study,
)
from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_certificate import atomic_json

ROOT = Path(__file__).resolve().parents[1]
SINGLE = ROOT / "benchmarks/run_thesis_experiment.py"


def verify_evidence(manifest):
    files = [(group.get("reference") or {}).get("result") for group in manifest["groups"]]
    hashes = [(group.get("reference") or {}).get("sha256") for group in manifest["groups"]]
    files.append(manifest.get("source_resolution_evidence"))
    hashes.append(manifest.get("source_resolution_sha256"))
    for path, expected in zip(files, hashes, strict=True):
        if not path or not expected or not Path(path).is_file() or hashlib.sha256(Path(path).read_bytes()).hexdigest() != expected:
            raise ValueError(f"frozen study evidence is missing or has changed: {path}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--wall-time-limit", type=float, required=True)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--build-only", action="store_true")
    parser.add_argument("--_worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text())
    validate_study(manifest, require_ready=not args.build_only)
    if args.wall_time_limit <= 0:
        parser.error("wall time must be positive")
    if args.build_only:
        print(json.dumps({"identity": manifest_identity(manifest), "groups": manifest["groups"]}, indent=2))
        return
    out = args.output_dir
    identity = manifest_identity(manifest)
    state_path = out / "study.json"
    if not args._worker:
        verify_evidence(manifest)
        if args.resume:
            old = json.loads(state_path.read_text())
            if old["manifestIdentity"] != identity:
                parser.error("resume manifest differs from the frozen study")
        elif out.exists():
            parser.error("output exists; use --resume with the same manifest")
        else:
            out.mkdir(parents=True)
            atomic_json(out / "manifest.json", manifest)
        session = len(list(out.glob("supervision_*"))) + 1
        monitoring = out / f"supervision_{session:03d}"
        monitoring.mkdir()
        # Each resumed invocation retains its own reconstructible code snapshot.
        with zipfile.ZipFile(monitoring / "sources.zip", "w", zipfile.ZIP_DEFLATED) as archive:
            for path in sorted([*ROOT.joinpath("src").rglob("*.py"), *ROOT.joinpath("benchmarks").glob("*.py"), ROOT / "pyproject.toml", ROOT / "uv.lock"]):
                if path.is_file():
                    archive.write(path, str(path.relative_to(ROOT)))
        result = supervise([sys.executable, str(Path(__file__).resolve()), *sys.argv[1:], "--_worker"],
                           monitoring, seconds=args.wall_time_limit,
                           memory_bytes=int(manifest.get("memory_gib", 32) * 1024**3),
                           system_memory_pressure_seconds=30)
        state = json.loads(state_path.read_text()) if state_path.exists() else {"manifestIdentity": identity, "attempts": [], "sessions": []}
        state.setdefault("sessions", []).append(result)
        state["cumulativeWallSeconds"] = sum(item.get("civil_wall_seconds", 0) for item in state["sessions"])
        if result["supervisor_reason"] or result["exit_code"]:
            state.update(status="interrupted", stopReason=result["supervisor_reason"] or "worker_failed")
        atomic_json(state_path, state)
        if state["status"] != "complete":
            raise SystemExit(1)
        return

    started = time.time()
    deadline = started + args.wall_time_limit
    state = json.loads(state_path.read_text()) if state_path.exists() else {
        "schema": "thesis_study_state_v1", "manifestIdentity": identity,
        "startedAt": datetime.now(timezone.utc).isoformat(), "attempts": [], "sessions": [],
    }
    state.update(status="running", stopReason=None)
    for attempt in state["attempts"]:
        if attempt["status"] == "running":
            attempt["status"] = "interrupted"

    def persist():
        state["currentSessionSeconds"] = time.time() - started
        atomic_json(state_path, state)

    def run(group, seed, demand, cabins, mode, parent):
        key = f"{group['id']}/seed{seed}/n{demand}_k{cabins}_{mode}"
        previous = [item for item in state["attempts"] if item["key"] == key]
        completed = next((item for item in previous if item["status"] == "complete"), None)
        if completed:
            return json.loads((out / completed["result"]).read_text()), completed["key"]
        remaining = deadline - time.time()
        if remaining < 10:
            raise TimeoutError("study deadline")
        directory = out / "runs" / key / f"attempt{len(previous) + 1:03d}"
        directory.parent.mkdir(parents=True, exist_ok=True)
        entry = {"key": key, "status": "running", "group": group["id"], "seed": seed,
                 "k": cabins, "demand": demand, "mode": mode,
                 "parent": None, "result": str((directory / "result.json").relative_to(out)),
                 "startedAt": datetime.now(timezone.utc).isoformat()}
        command = [sys.executable, str(SINGLE), "--topology", group["topology"],
                   "--geometry", "g500", "--demand-family", group["family"], "--demand-profile", "p0",
                   "--objective", group["objective"], "--method", "evolution" if group["objective"] == "unserved" else "labelled_arc_flow",
                   "--operating-mode", mode, "--demand", str(demand), "--cabins", str(cabins),
                   "--seed", str(seed), "--time-limit", str(min(group["stage_seconds"], remaining - 5)),
                   "--workers", str(manifest.get("workers", 12)), "--memory-limit-gib", str(manifest.get("memory_gib", 32)),
                   "--release-resolution-seconds", str(group["resolution_seconds"]), "--output-dir", str(directory)]
        if group["objective"] == "journey_time":
            command.extend(("--mip-gap", str(group.get("mip_gap", 0.0))))
        if group["objective"] == "unserved":
            command.extend(("--catalog", group.get("catalog", "od_endpoints_v1"),
                            "--pattern-search", group.get("pattern_search", "independent")))
            if parent:
                parent_result, parent_key = parent
                best = parent_result.get("run", {}).get("best") or {}
                patterns = (best.get("movement") or {}).get("genome", {}).get("pattern_ids") or []
                if patterns:
                    info = directory.parent / f"parent_{len(previous) + 1:03d}.json"
                    atomic_json(info, [[patterns[i % len(patterns)] for i in range(cabins)]])
                    command.extend(("--initial-pattern-sequences", str(info)))
                    entry.update(parent=parent_key, transfer="patterns_only_researched_not_an_incumbent")
        state["attempts"].append(entry)
        persist()
        before = time.time()
        process = subprocess.run(command, cwd=ROOT, check=False)
        entry.update(wallSeconds=time.time() - before, exitCode=process.returncode)
        if process.returncode or not (directory / "result.json").exists():
            entry["status"] = "interrupted"
            persist()
            raise RuntimeError("stage interrupted; resume retries in a new attempt directory")
        entry["status"] = "complete"
        persist()
        return json.loads((directory / "result.json").read_text()), key

    persist()
    try:
        for group in manifest["groups"]:
            for seed in group["seeds"]:
                parent = None  # Never transfer between independent seeds or groups.
                if group["objective"] == "journey_time":
                    unresolved = 0
                    for cabins in group["k_values"]:
                        run(group, seed, group["demand"], cabins, "all_stop", None)
                        result, _ = run(group, seed, group["demand"], cabins, "skip_stop", None)
                        unresolved = 0 if journey_confirmed(result) else unresolved + 1
                        if unresolved >= 2:
                            break
                else:
                    ladder = DemandLadder(group["demand"], max_levels=group.get("max_demand_levels", 5))
                    while True:
                        full = False
                        for cabins in group["k_values"]:
                            result, key = run(group, seed, ladder.current, cabins, "skip_stop", parent)
                            service = confirmed_service(result)
                            if service is not None:
                                parent = result, key
                            if service is not None and service[1] == 0:
                                full = True
                                break
                        if ladder.advance(full) is None:
                            break
        state.update(status="complete", completedAt=datetime.now(timezone.utc).isoformat())
    except (TimeoutError, RuntimeError) as error:
        state.update(status="interrupted", stopReason=str(error))
    finally:
        persist()
    if state["status"] != "complete":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
