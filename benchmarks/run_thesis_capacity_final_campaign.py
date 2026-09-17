"""Run the frozen final capacity campaign as fresh, sequential Evo attempts."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import time

from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_certificate import atomic_json


ROOT = Path(__file__).resolve().parents[1]
SINGLE = ROOT / "benchmarks/run_thesis_experiment.py"


def _sequences(run: dict) -> list[list[str]]:
    k = int(run["cabins"])
    if run["family"] != "f2" or run["topology"] != "t5r":
        return []
    first, second = "stop_S1_S3", "stop_S2_S4"
    alternating = [first if index % 2 == 0 else second for index in range(k)]
    split = k // 2
    return [
        ["all_stop"] * k,
        alternating,
        [second if index % 2 == 0 else first for index in range(k)],
        [first] * split + [second] * (k - split),
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    out = args.output_dir
    state_path = out / "study.json"
    if args.resume:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    else:
        out.mkdir(parents=True, exist_ok=False)
        atomic_json(out / "manifest.json", manifest)
        state = {
            "schema": "thesis_capacity_final_campaign_state_v1",
            "status": "running",
            "startedAt": datetime.now(timezone.utc).isoformat(),
            "attempts": [],
        }

    for attempt in state["attempts"]:
        if attempt["status"] == "running":
            attempt["status"] = "interrupted"

    def persist() -> None:
        state["updatedAt"] = datetime.now(timezone.utc).isoformat()
        atomic_json(state_path, state)

    persist()
    for run in manifest["groups"]:
        completed = next(
            (item for item in state["attempts"] if item["id"] == run["id"] and item["status"] == "complete"),
            None,
        )
        if completed is not None:
            continue
        previous = [item for item in state["attempts"] if item["id"] == run["id"]]
        directory = out / "runs" / run["id"] / f"attempt{len(previous) + 1:03d}"
        sequence_path = directory.parent / "initial_sequences.json"
        sequences = _sequences(run)
        if sequences:
            sequence_path.parent.mkdir(parents=True, exist_ok=True)
            atomic_json(sequence_path, sequences)
        entry = {
            "id": run["id"],
            "key": run["id"],
            "group": run["id"],
            "status": "running",
            "seed": run["seed"],
            "k": run["cabins"],
            "demand": run["demand"],
            "result": str((directory / "result.json").relative_to(out)),
            "startedAt": datetime.now(timezone.utc).isoformat(),
            "fresh": True,
            "importedSkipStopCheckpoint": False,
        }
        state["attempts"].append(entry)
        persist()
        command = [
            sys.executable,
            str(SINGLE),
            "--topology", run["topology"],
            "--geometry", "g500",
            "--demand-family", run["family"],
            "--demand-profile", "p0",
            "--objective", "unserved",
            "--method", "evolution",
            "--operating-mode", "skip_stop",
            "--demand", str(run["demand"]),
            "--cabins", str(run["cabins"]),
            "--seed", str(run["seed"]),
            "--time-limit", str(run["stage_seconds"]),
            "--workers", str(manifest["workers"]),
            "--memory-limit-gib", str(manifest["memory_gib"]),
            "--release-resolution-seconds", "15",
            "--catalog", run["catalog"],
            "--pattern-search", run["pattern_search"],
            "--population-size", "32",
            "--offspring-size", "8",
            "--passenger-time-limit", "2",
            "--output-dir", str(directory),
        ]
        if sequences:
            command.extend(("--initial-pattern-sequences", str(sequence_path)))
        before = time.time()
        result = subprocess.run(command, cwd=ROOT, check=False)
        entry.update(
            status="complete" if result.returncode == 0 and (directory / "result.json").exists() else "failed",
            exitCode=result.returncode,
            wallSeconds=time.time() - before,
            completedAt=datetime.now(timezone.utc).isoformat(),
        )
        persist()
        if entry["status"] != "complete":
            state.update(status="interrupted", stopReason=f"{run['id']} failed")
            persist()
            raise SystemExit(1)

    state.update(status="complete", completedAt=datetime.now(timezone.utc).isoformat())
    persist()


if __name__ == "__main__":
    main()
