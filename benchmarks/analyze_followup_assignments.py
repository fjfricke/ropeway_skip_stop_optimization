"""Describe validated assignments from saved data, without invoking a solver."""

from __future__ import annotations

import json
from pathlib import Path
from statistics import mean, median

BASE = (
    Path(__file__).resolve().parents[1] / "benchmarks/output/solver_followup_20260909"
)


def describe(checkpoint: Path, manifest: Path):
    saved = json.loads(checkpoint.read_text())
    incumbent = saved["incumbent"]
    problem = json.loads(manifest.read_text())
    groups = {g["id"]: g for g in problem["demand_groups"]}
    candidates = {r["id"]: r for r in problem["ride_candidates"]}
    options = {
        r["id"]: r
        for r in problem["trajectory_problem"]["movement_core"]["route_options"]
    }
    trajectories = {t["cabin_id"]: t for t in incumbent["trajectory_supports"]}
    before_departure, aboard, journey = [], [], []
    by_od = {}
    for candidate_id, count in incumbent["ride_counts"].items():
        if not count:
            continue
        candidate = candidates[candidate_id]
        group = groups[candidate["demand_group_id"]]
        trajectory = trajectories[candidate["cabin_id"]]
        board, alight = candidate["board_visit_index"], candidate["alight_visit_index"]
        board_option = options[trajectory["route_option_ids"][board]]
        alight_option = options[trajectory["route_option_ids"][alight]]
        assert board_option["decision"] == alight_option["decision"] == "stop"
        departure = (
            trajectory["switch_times_seconds"][board]
            + board_option["platform_exit_offset_seconds"]
            + trajectory["wait_seconds"][board]
        )
        arrival = (
            trajectory["switch_times_seconds"][alight]
            + alight_option["platform_entry_offset_seconds"]
        )
        release = group["release_time_seconds"]
        before_departure.extend([departure - release] * count)
        aboard.extend([arrival - departure] * count)
        journey.extend([arrival - release] * count)
        key = f"{group['origin_station_id']}->{group['destination_station_id']}"
        by_od.setdefault(key, []).extend([arrival - release] * count)
    # This diagnostic deliberately compares the two fully served plans.
    assert not any(incumbent["unserved_counts"].values())
    assert len(journey) == sum(g["count"] for g in groups.values())
    assert min(before_departure) >= -1e-6 and min(aboard) >= -1e-6
    assert abs(sum(journey) - incumbent["objective"]) < 1e-4
    return {
        "checkpoint": str(checkpoint.relative_to(BASE)),
        "manifest": str(manifest.relative_to(BASE)),
        "served": len(journey),
        "objective": incumbent["objective"],
        "mean_release_to_departure_seconds": mean(before_departure),
        "mean_departure_to_alight_seconds": mean(aboard),
        "mean_journey_seconds": mean(journey),
        "median_journey_seconds": median(journey),
        "mean_journey_by_od": {
            key: mean(values) for key, values in sorted(by_od.items())
        },
        "semantics": (
            "Departure = nominal platform exit plus chosen exit wait. "
            "Release-to-departure includes boarding and exit waiting; it is not "
            "a separately observed physical passenger queue time."
        ),
    }


def main():
    results = {
        "k38_all_stop": describe(
            BASE / "frozen/k38_all_stop/cp_seed.json",
            BASE / "frozen/k38_all_stop/problem_manifest.json",
        ),
        "k39_waiting": describe(
            BASE / "k39_waiting_1800s_seed0/post_ip/cp_seed.json",
            BASE / "frozen/k39_waiting/problem_manifest.json",
        ),
    }
    (BASE / "assignment_diagnostics.json").write_text(
        json.dumps(results, indent=2, allow_nan=False) + "\n"
    )
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
