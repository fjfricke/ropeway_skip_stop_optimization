"""Export completed preflight measurements without interpreting missing bounds."""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


def write_csv(path, rows):
    fields = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    rows, probes, improvements = [], [], []
    for path in sorted(args.directory.glob("*/result.json")):
        data = json.loads(path.read_text())
        run = data["run"]
        spec = json.loads((path.parent / "case_spec.json").read_text())
        monitor_path = path.parent / "supervisor.json"
        monitor = json.loads(monitor_path.read_text()) if monitor_path.exists() else {}
        events_path = path.parent / "events.jsonl"
        events = [json.loads(line) for line in events_path.read_text().splitlines() if line] if events_path.exists() else []
        row = {
            "run": path.parent.name, "method": data["method"],
            "topology": spec.get("topology"), "family": spec.get("demand_family"),
            "release_seconds": spec.get("release_resolution_seconds"),
            "demand": spec.get("demand_total"),
            "wall_seconds": monitor.get("civil_wall_seconds"),
            "peak_rss_gib": monitor.get("peak_process_tree_rss_bytes", 0) / 1024**3,
            "cpu_seconds": monitor.get("sampled_process_tree_cpu_seconds"),
            "resource_stop": monitor.get("supervisor_reason"),
            "proof_scope": run.get("proof_scope"),
        }
        if data["method"] == "all_stop_phase":
            row.update(capacity=run.get("capacity"), lower_demand=run.get("proven_feasible_demand"),
                       upper_demand_exclusive=run.get("proven_infeasible_demand"), capacity_proven=run.get("capacity_proven"))
            for probe in run.get("probes", []):
                native = probe["solve"]
                probes.append({"run": path.parent.name, "demand": probe["demand"],
                               "outcome": probe["outcome"], "elapsed_seconds": probe["elapsed_seconds"],
                               "solver_status": probe.get("solver_status", native.get("solver_status")),
                               **native.get("model_stats", {})})
        elif data["method"] == "evolution":
            best = run.get("best") or {}
            passenger = best.get("passengers") or {}
            row.update(served=passenger.get("served"), unserved=passenger.get("unserved"),
                       evaluations=run.get("evaluations"), feasible_evaluations=run.get("feasible_evaluations"))
            points = [event for event in events if event.get("kind") == "incumbent"]
            row["incumbent_events"] = len(points)
            if points:
                row["first_valid_seconds"] = points[0].get("runner_elapsed_seconds", points[0].get("elapsed_seconds"))
                row["last_improvement_seconds"] = points[-1].get("runner_elapsed_seconds", points[-1].get("elapsed_seconds"))
            for event in points:
                improvements.append({"run": path.parent.name,
                                     **{key: event.get(key) for key in ("elapsed_seconds", "runner_elapsed_seconds", "served", "unserved", "origin", "pattern_counts")}})
        else:
            row.update(upper_bound=run.get("validated_upper_bound"), lower_bound=run.get("certified_lower_bound"),
                       validation=run.get("independent_validation_status"), status=run.get("solver_status"),
                       seed_kind=run.get("seed_kind"), nodes=run.get("node_count"),
                       build_seconds=run.get("model_build_seconds"), solve_seconds=run.get("solve_seconds"),
                       variables=(run.get("movement_variable_count") or 0) + (run.get("passenger_variable_count") or 0),
                       constraints=run.get("linear_constraint_count"),
                       first_native_seconds=run.get("time_to_first_incumbent_seconds"))
        rows.append(row)
    write_csv(args.directory / "measurements.csv", rows)
    write_csv(args.directory / "capacity_probes.csv", probes)
    write_csv(args.directory / "evolution_improvements.csv", improvements)
    print(f"Exported {len(rows)} completed attempts, {len(probes)} capacity probes, {len(improvements)} evolution incumbents.")


if __name__ == "__main__":
    main()
