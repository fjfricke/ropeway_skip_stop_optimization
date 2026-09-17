"""Frozen one-hour R2 comparison for pattern-only dispatch optimization."""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import subprocess
import sys
import time

import numpy as np

from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_certificate import atomic_json
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_hybrid.domain import load_reference
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_lines import (
    ReservoirLineCatalogProfile, ReservoirLineConfig, ReservoirLineFormulation,
    ReservoirLineMode, ReservoirLinePreparation, ReservoirLineVariant,
    prepare_line_problem,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_lines.evolution import (
    PatternGenomeFactory, genome_from_plan,
)


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "benchmarks/run_reservoir_line_evolution.py"


def _read(path):
    return json.loads(Path(path).read_text()) if Path(path).exists() else None


def _event_sequences(path: Path):
    rows = []
    if not path.exists():
        return rows
    for line in path.read_text().splitlines():
        event = json.loads(line)
        if event.get("kind") in ("unrepaired_candidate", "conflict_frontier") and event.get("pattern_ids"):
            rows.append((int(event.get("conflicts", 10**9)), tuple(event["pattern_ids"])))
    return sorted(rows, key=lambda row: (row[0], row[1]))


def main():
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--reference-checkpoint", type=Path, required=True)
    parser.add_argument("--valid-k38-checkpoint", type=Path, required=True)
    parser.add_argument("--candidate-events", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--dispatch-window-end", type=float, default=300)
    parser.add_argument("--wall-limit-seconds", type=float, default=3600)
    parser.add_argument("--workers", type=int, default=12)
    parser.add_argument("--memory-limit-gib", type=float, default=32)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-dispatch-baseline", action="store_true",
                        help="Use an already documented dispatch-gene baseline and run only pattern-only")
    args = parser.parse_args()
    if not 0 < args.wall_limit_seconds <= 3600:
        parser.error("wall limit must lie in (0, 3600]")
    args.output.mkdir(parents=True, exist_ok=False)
    started = time.time(); deadline = started + args.wall_limit_seconds
    domain, _ = load_reference(args.reference_checkpoint)
    _, valid_plan = load_reference(args.valid_k38_checkpoint)
    config = ReservoirLineConfig(
        dispatch_window_end_seconds=args.dispatch_window_end,
        passenger_service_start_seconds=args.dispatch_window_end,
        variant=ReservoirLineVariant.INTERVALS,
        preparation=ReservoirLinePreparation.ENCODING_SPECIFIC,
        formulation=ReservoirLineFormulation.SHARED_ROUNDS,
        mode=ReservoirLineMode.EXACT_SERVICE,
        catalog_profile=ReservoirLineCatalogProfile.RELEVANT,
        maximum_cabins=38, workers=args.workers,
    )
    prepared = prepare_line_problem(domain.problem, config)
    valid = tuple(genome_from_plan(domain.problem, prepared, valid_plan).pattern_ids)
    conflict_rows = [(n, sequence) for n, sequence in _event_sequences(args.candidate_events)
                     if len(sequence) == 38 and sequence != valid]
    six = next((sequence for n, sequence in conflict_rows if n == 6), None)
    forty_two = next((sequence for n, sequence in conflict_rows
                      if 6 < n <= 42 and sequence != six), None)
    # If old logs do not contain both thresholds, preserve a deterministic,
    # explicitly labelled fallback rather than silently reusing one sequence.
    factory = PatternGenomeFactory(domain.problem, prepared, fixed_k=38, seed=0)
    six = six or factory.random().pattern_ids
    if forty_two is None:
        for _ in range(100):
            candidate = factory.random().pattern_ids
            if candidate not in (valid, six):
                forty_two = candidate
                break
    if forty_two is None:
        raise RuntimeError("could not generate a distinct fourth control sequence")
    all_stop = ("all_stop",) * 38
    controls = {"valid": valid, "six_conflicts_or_fallback": six,
                "forty_two_conflicts_or_fallback": forty_two, "all_stop": all_stop}
    controls_dir = args.output / "controls"; controls_dir.mkdir()
    for name, sequence in controls.items():
        atomic_json(controls_dir / f"{name}.json", {"pattern_ids": sequence})

    initial_factory = PatternGenomeFactory(domain.problem, prepared, fixed_k=38, seed=0)
    initial = []
    # Demand-oriented arrangements first, then deterministic random mixtures.
    non_all = initial_factory.demand_patterns
    for arrangement in ("alternating", "grouped", "random"):
        sequence = tuple(non_all[i % len(non_all)] for i in range(38))
        initial.append(initial_factory.random(patterns=sequence, arrangement=arrangement).pattern_ids)
    while len(initial) < 32:
        candidate = initial_factory.random(
            patterns=tuple(initial_factory.rng.choice(non_all, 38, replace=True))
        ).pattern_ids
        if candidate not in initial and set(candidate) != {"all_stop"}: initial.append(candidate)
    atomic_json(args.output / "initial_patterns.json", initial)

    manifest = {"schema": "reservoir_pattern_only_campaign_v1", "started_unix": started,
                "deadline_unix": deadline, "controls": {k: dict(Counter(v)) for k,v in controls.items()},
                "runs": [], "status": "running"}
    def save():
        manifest["elapsed_seconds"] = time.time() - started
        atomic_json(args.output / "campaign.json", manifest)
    def run(name, seconds, extra):
        if time.time() + seconds + 2 > deadline:
            manifest["status"] = "deadline"; save(); return None
        out = args.output / name
        command = [sys.executable, str(RUNNER), "--reference-checkpoint", str(args.reference_checkpoint),
            "--output", str(out), "--engine", "ga", "--operator-profile", "mixed_global",
            "--dispatch-window-end", str(args.dispatch_window_end), "--fixed-k", "38",
            "--time-limit", str(seconds), "--workers", str(args.workers),
            "--memory-limit-gib", str(args.memory_limit_gib), "--seed", "0",
            "--no-reference-initialization", "--no-all-stop-initialization", *extra]
        entry = {"name": name, "budget_seconds": seconds, "command": command,
                 "status": "planned" if args.dry_run else "running"}
        manifest["runs"].append(entry); save()
        if args.dry_run: return entry
        before = time.time()
        with (args.output / f"{name}.log").open("w") as log:
            completed = subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                                       timeout=max(1, deadline-time.time()))
        entry.update(exit_code=completed.returncode, actual_wall_seconds=time.time()-before,
                     result=_read(out / "result.json"))
        entry["status"] = "complete" if entry["result"] else "incomplete"; save(); return entry

    screening = []
    for control_name in controls:
        for subproblem in ("timing_then_passengers", "joint_service"):
            entry = run(f"screen_{control_name}_{subproblem}", 34, [
                "--representation", "patterns_only", "--dispatch-subproblem", subproblem,
                "--evaluation-time-limit", "30", "--evaluate-only",
                str(controls_dir / f"{control_name}.json")])
            if entry is None: return
            screening.append(entry)
    if args.dry_run:
        manifest["status"] = "dry_run_complete"; save(); return
    def screening_score(subproblem):
        rows = [e for e in screening if subproblem in e["name"]]
        evaluations = [((e.get("result") or {}).get("evaluation") or {}) for e in rows]
        valid_evaluations = [e for e in evaluations if e.get("passengers")]
        return (-len(valid_evaluations), -sum(e["passengers"]["served"] for e in valid_evaluations),
                sum(e.get("movement", {}).get("decode_seconds", 1e9) for e in valid_evaluations))
    selected = min(("timing_then_passengers", "joint_service"), key=screening_score)
    manifest["selected_subproblem"] = selected
    manifest["screening_scores"] = {s: screening_score(s) for s in
                                     ("timing_then_passengers", "joint_service")}; save()
    common = ["--initial-pattern-sequences", str(args.output / "initial_patterns.json"),
              "--population-size", "32", "--offspring-size", "8"]
    live_dir = ROOT / "frontend/public/generated/evolution-live"
    live_dir.mkdir(parents=True, exist_ok=True)
    live_runs = [
        {"id": "pattern_compare_only", "label": f"K38 · patterns only · {selected}",
         "snapshot": "/generated/evolution-live/pattern_compare_only.json"},
    ]
    if not args.skip_dispatch_baseline:
        live_runs.insert(0,
            {"id": "pattern_compare_dispatch", "label": "K38 · patterns and dispatch genes",
             "snapshot": "/generated/evolution-live/pattern_compare_dispatch.json"})
    live_manifest = {
        "schema": "reservoir_line_evolution_live_manifest_v1",
        "label": "R2 · Dispatch genes vs pattern-only",
        "status": "running", "started_unix": time.time(),
        "runs": live_runs,
    }
    atomic_json(live_dir / "manifest.json", live_manifest)
    if not args.skip_dispatch_baseline:
        if run("comparison_dispatch_genes", 1500, common + [
            "--representation", "patterns_dispatch", "--dispatch-decoder", "intervals",
            "--waiting-construction", "prefix_first", "--selection-profile", "grouped",
            "--waiting-repair-seconds", "0", "--passenger-time-limit", "2",
            "--live-snapshot", str(live_dir / "pattern_compare_dispatch.json"),
            "--live-label", "K38 · patterns and dispatch genes"]) is None: return
    if run("comparison_patterns_only", 1500, common + [
        "--representation", "patterns_only", "--dispatch-subproblem", selected,
        "--evaluation-time-limit", "8",
        "--live-snapshot", str(live_dir / "pattern_compare_only.json"),
        "--live-label", f"K38 · patterns only · {selected}"]) is None: return
    manifest["status"] = "complete"; manifest["finished_unix"] = time.time(); save()
    live_manifest.update(status="complete", finished_unix=time.time())
    atomic_json(live_dir / "manifest.json", live_manifest)


if __name__ == "__main__":
    main()
