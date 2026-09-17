"""Publish archived greedy traces for the live dashboard, without any solver call."""

import argparse
import json
from pathlib import Path

from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_certificate import (
    atomic_json,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_greedy.progress import (
    replay_progress,
    validated_reference,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_hybrid.domain import (
    load_reference,
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", type=Path, required=True)
    parser.add_argument("--live-directory", type=Path, required=True)
    parser.add_argument("--all-stop-reference", type=Path, required=True)
    args = parser.parse_args()
    manifest = json.loads((args.live_directory / "manifest.json").read_text())
    for entry in manifest["runs"]:
        folder = args.campaign / entry["id"]
        if not (folder / "result.json").exists():
            continue
        result = json.loads((folder / "result.json").read_text())
        events = [
            json.loads(line)
            for line in (folder / "events.jsonl").read_text().splitlines()
        ]
        progress = replay_progress(events, result["steps"])
        domain, _ = load_reference(folder / "best.json")
        ref = validated_reference(domain.problem, args.all_stop_reference)
        snapshot = args.live_directory / Path(entry["snapshot"]).name
        data = json.loads(snapshot.read_text())
        data.update(
            progress=progress.export(),
            all_stop_reference=ref,
            reference_served=ref["served"],
        )
        atomic_json(snapshot, data)
        atomic_json(folder / "progress.json", progress.export())
    print("Published archived insertion progress; no optimization performed.")


if __name__ == "__main__":
    main()
