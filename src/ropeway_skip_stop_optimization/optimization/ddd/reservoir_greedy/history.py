"""Read-only historical comparisons, with explicit contract mismatches."""

import json
from dataclasses import asdict
from pathlib import Path

from ..reservoir_hybrid.domain import load_reference
from .model import validate_lifecycle


def compare_historical_run(directory, target):
    directory = Path(directory)
    result = {
        "path": str(directory.resolve()),
        "classification": "STRUCTURAL_ONLY",
        "differences": [],
        "certificate_status": "UNAVAILABLE",
        "global_bound": None,
    }
    path = directory / "result.json"
    if not path.exists():
        result["error"] = "result.json unavailable"
        return result
    data = json.loads(path.read_text())
    result["result_schema"] = data.get("schema")
    result["recorded_wall_seconds"] = data.get(
        "runner_total_wall_seconds",
        data.get("total_wall_seconds", data.get("total_seconds")),
    )
    result["events"] = data.get("events", data.get("native_events", []))
    event_file = directory / "events.jsonl"
    if event_file.exists():
        result["events"] = [
            json.loads(line)
            for line in event_file.read_text().splitlines()
            if line.strip()
        ]
    progress = [
        e
        for e in result["events"]
        if isinstance(e, dict)
        and e.get("kind") in ("incumbent", "native_solution", "accepted_insertion")
        and e.get("served") is not None
    ]
    result["service_progress"] = progress
    result["first_service_event_seconds"] = next(
        (e.get("elapsed_seconds") for e in progress if e["served"] > 0), None
    )
    best = -1
    improvements = []
    for e in progress:
        if e["served"] > best:
            best = e["served"]
            improvements.append(e)
    result["service_improvements"] = improvements
    result["last_service_progress_seconds"] = (
        improvements[-1].get("elapsed_seconds") if improvements else None
    )
    # The historical clock origin remains explicit unless separately evidenced.
    result["clock_origin"] = "AS_RECORDED_NOT_ASSUMED_TO_INCLUDE_BUILD"
    for name in ("best.json", "incumbent.json"):
        checkpoint = directory / name
        if not checkpoint.exists():
            continue
        try:
            source, plan = load_reference(checkpoint)
            a, b = source.problem, target
            for key in (
                "movement_core",
                "demand_groups",
                "cabin_capacity",
                "available_fleet_count",
                "entry_state_id",
                "dispatch_start_seconds",
                "dispatch_end_seconds",
                "dispatch_step_seconds",
                "return_start_seconds",
                "waiting_policy",
                "boundary_policy",
            ):
                if getattr(a, key) != getattr(b, key):
                    result["differences"].append(key)
            result["source_physical_fingerprint"] = a.fingerprint
            result["source_metrics"] = (
                asdict(validate_lifecycle(a, plan))
                if all(
                    t.return_tick >= a.resolved_core.passenger_service_end_tick
                    for t in plan.trips
                )
                else None
            )
            try:
                metrics = validate_lifecycle(target, plan)
                result.update(
                    certificate_status="VALID_IN_TARGET",
                    target_metrics=asdict(metrics),
                    classification="TRANSFERABLE_PLAN"
                    if result["differences"]
                    else "SAME_PHYSICS_CHECK_SEARCH_CONTRACT",
                )
            except ValueError as e:
                result.update(
                    certificate_status="INVALID_IN_TARGET", certificate_error=str(e)
                )
            result["checkpoint"] = str(checkpoint.resolve())
        except (ValueError, KeyError, TypeError) as e:
            result["certificate_error"] = str(e)
        break
    args = directory / "arguments.json"
    if args.exists():
        result["historical_configuration"] = json.loads(args.read_text())
    # Never infer a global bound from a restricted arc-flow search or a primal value.
    return result
