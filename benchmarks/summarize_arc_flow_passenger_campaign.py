"""Reproducible interpretation of passenger ablations and their time curves."""
import argparse
import json
from pathlib import Path
import re

from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_certificate import atomic_json


def target_time(row, upper, lower):
    folder = Path(row["folder"])
    ub = row["seed_value"]
    lb = 0.0
    if ub <= upper + 1e-5 and lb >= lower - 1e-5:
        return 0.0
    for line in (folder / "events.jsonl").read_text().splitlines():
        event = json.loads(line)
        if event["kind"] == "validated_incumbent":
            ub = min(ub, event["objective"])
        elif event["kind"] == "progress":
            value = event.get("certified_lower_bound")
            if value is not None:
                lb = max(lb, value)
        if ub <= upper + 1e-5 and lb >= lower - 1e-5:
            return event["elapsed_seconds"]
    if row["validated_upper_bound"] <= upper + 1e-5 and row["certified_lower_bound"] >= lower - 1e-5:
        return row["actual_total_seconds"]
    return None


def compare(candidate, baseline):
    ub, lb = candidate["validated_upper_bound"], candidate["certified_lower_bound"]
    base_ub, base_lb = baseline["validated_upper_bound"], baseline["certified_lower_bound"]
    gap = max(0, ub - lb) / max(abs(ub), 1e-9)
    base_gap = max(0, base_ub - base_lb) / max(abs(base_ub), 1e-9)
    quality = ub <= base_ub * .999
    bound = ub <= base_ub + 1e-5 and base_gap - gap >= .01 - 1e-12
    candidate_time = target_time(candidate, base_ub, base_lb)
    baseline_time = target_time(baseline, base_ub, base_lb)
    faster = (candidate_time is not None and baseline_time is not None and baseline_time > 0
              and candidate_time <= .8 * baseline_time and ub <= base_ub + 1e-5 and lb >= base_lb - 1e-5)
    return dict(cost_criterion=quality, gap_criterion=bound, time_criterion=faster,
                candidate_target_seconds=candidate_time, legacy_target_seconds=baseline_time,
                passed=quality or bound or faster, primal_only=quality and lb < base_lb - 1e-5)


def summarize(output):
    data = json.loads((output / "summary.json").read_text())
    rows = data["results"]
    lines = ["# Labelled Arc-Flow passenger ablations", "",
             "All costs are passenger seconds. Seed adoption is not an improvement.", "",
             "| Case | Profile | Seed | Validated UB | Global LB | Gap | Total s | Variables | Integer variables | Root LP s |",
             "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for row in rows:
        if "validated_upper_bound" not in row:
            lines.append(f"| {row['case']} | {row['profile']} | {row['seed']} | pending/failed | — | — | — | — | — | — |")
            continue
        log = (Path(row["folder"]) / "terminal.log").read_text()
        root = re.findall(r"Root relaxation:.*?([\d.]+) seconds", log)
        root_seconds = float(root[-1]) if root else None
        row["native_root_lp_seconds"] = root_seconds
        variables = row["movement_variable_count"] + row["passenger_variable_count"]
        lines.append(f"| {row['case']} | {row['profile']} | {row['seed']} | {row['validated_upper_bound']:.6f} | "
                     f"{row['certified_lower_bound']:.6f} | {100*row['relative_gap']:.2f}% | {row['actual_total_seconds']:.2f} | "
                     f"{variables} | {row.get('integer_variable_count')} | {root_seconds} |")
    confirmations = []
    for seed in (1, 2):
        baseline = next((r for r in rows if r["case"] == "k39_batch" and r["seed"] == seed and r["profile"] == "legacy"), None)
        candidate = next((r for r in rows if r["case"] == "k39_batch" and r["seed"] == seed and r["profile"] == data.get("winner")), None)
        if baseline and candidate and all(r.get("process_ok") and "validated_upper_bound" in r
                                          and not str(r.get("status", "")).startswith("internal")
                                          for r in (baseline, candidate)):
            confirmations.append(dict(seed=seed, **compare(candidate, baseline)))
    confirmed = len(confirmations) == 2 and all(c["passed"] for c in confirmations)
    lines += ["", f"Actual campaign time: {data['actual_seconds']:.2f} s / 10800 s.",
              f"Screening selection: {data.get('winner')}. Confirmed advantage: {confirmed}.",
              "", "## Interpretation", "",
              "Smaller pre-presolve models alone do not establish faster solving. Destination aggregation can weaken the LP; "
              "ride integrality relocation need not accelerate its solution. Native Root LP times exclude other root processing.",
              "Legacy remains the default. No additional combinations, waiting expansion or longer jobs were started.",
              "", "## Confirmation details", "", "```json", json.dumps(confirmations, indent=2), "```"]
    (output / "comparison.md").write_text("\n".join(lines) + "\n")
    atomic_json(output / "analysis.json", dict(results=rows, confirmations=confirmations,
                                               confirmed_advantage=confirmed, winner=data.get("winner")))
    return confirmed


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    summarize(parser.parse_args().output)
