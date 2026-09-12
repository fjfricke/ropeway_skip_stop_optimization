"""Twelve frozen small repairs from the same checked reservoir reference."""

import argparse
from collections import defaultdict
import json
from pathlib import Path
import sys
import time

from run_reservoir_hybrid_gate_campaign import run_case
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_hybrid.domain import (
    load_reference,
)


def main():
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--resume-checkpoint", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--no-presolve", action="store_true")
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=False)
    domain, plan = load_reference(args.resume_checkpoint)
    p = domain.problem
    trip_by_id = {t.cabin_id: t for t in plan.trips}
    rides = {r.id: r for r in p.passenger_build.ride_candidates}
    groups = {g.id: g for g in p.demand_groups}
    options = {o.id: o for o in p.resolved_core.route_options}
    costs, counts = defaultdict(float), defaultdict(int)
    for rid, n in plan.ride_counts.items():
        r = rides[rid]
        t = trip_by_id[r.cabin_id]
        arrival = (
            t.switch_ticks[r.alight_visit_index] / 1e6
            + options[
                t.route_option_ids[r.alight_visit_index]
            ].platform_entry_offset_seconds
        )
        costs[r.cabin_id] += n * (
            arrival - groups[r.demand_group_id].release_time_seconds
        )
        counts[r.cabin_id] += n
    ordered = sorted(trip_by_id, key=lambda k: (trip_by_id[k].switch_ticks[0], k))
    ranked = {
        "demand": sorted(ordered, key=lambda k: (-costs[k], k)),
        "waiting": sorted(ordered, key=lambda k: (-sum(trip_by_id[k].wait_ticks), k)),
        "replace": sorted(ordered, key=lambda k: (counts[k], -costs[k], k)),
    }
    cases = []
    for family, ranking in ranked.items():
        for j in range(4):
            size = 3 if j % 2 == 0 else 6
            anchor = ranking[j % len(ranking)]
            center = ordered.index(anchor)
            ids = sorted(
                {
                    ordered[(center + offset) % len(ordered)]
                    for offset in range(-(size // 2), size - size // 2)
                }
            )
            cases.append(
                {
                    "name": f"{family}_{j}",
                    "open_ids": ids,
                    "new_slots": 1 if j % 2 == 0 else 2,
                }
            )
    (args.output_dir / "neighborhoods.json").write_text(json.dumps(cases, indent=2))
    started = time.monotonic()
    report = {
        "cases": [],
        "common_seed": str(args.resume_checkpoint),
        "problem_fingerprint": p.fingerprint,
    }
    for case in cases:
        output = args.output_dir / case["name"]
        command = [
            sys.executable,
            "benchmarks/run_ddd_reservoir_hybrid.py",
            "--phase",
            "repair",
            "--resume-checkpoint",
            str(args.resume_checkpoint),
            "--output-dir",
            str(output),
            "--time-limit",
            "8",
            "--open-deployments",
            ",".join(map(str, case["open_ids"])),
            "--new-slots",
            str(case["new_slots"]),
        ]
        if args.no_presolve:
            command += ["--no-repair-presolve"]
        result = run_case(
            command, args.output_dir / (case["name"] + ".log"), time.monotonic() + 10
        )
        if (output / "result.json").exists():
            result["result"] = json.loads((output / "result.json").read_text())
        report["cases"].append({**case, **result})
        report["actual_total_seconds"] = time.monotonic() - started
        (args.output_dir / "campaign.json").write_text(json.dumps(report, indent=2))
        print(case["name"], json.dumps(result), flush=True)
    completed = [c.get("result", {}) for c in report["cases"]]
    report["native_feasible_repairs"] = sum(
        r.get("native_solutions", 0) > 0 for r in completed
    )
    report["improving_repairs"] = sum(
        any(e.get("improvement") for e in r.get("events", [])) for r in completed
    )
    report["G4_passed"] = (
        report["native_feasible_repairs"] >= 6 and report["improving_repairs"] >= 1
    )
    (args.output_dir / "campaign.json").write_text(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
