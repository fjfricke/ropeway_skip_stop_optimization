"""Solver-free adapters for portable charts and event-accurate timetable replay."""
import json
import math
from pathlib import Path
from ropeway_skip_stop_optimization.optimization.ddd.time_ticks import ddd_seconds_to_tick


def write_snapshot(path, payload):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload))
    temporary.replace(path)


def read_events(path):
    events = []
    if path.exists():
        for line in path.read_text().splitlines():
            try:
                events.append(json.loads(line))
            except ValueError:
                continue  # A writer may still be finishing its final JSONL record.
    return events


def replay_payload(certificate=None, result=None):
    native = (result or {}).get("run", {})
    if certificate:
        core = certificate["domain_manifest"]["movement_core"]
        trips = certificate["plan"]["trips"]
        counts = certificate["plan"].get("ride_counts", {})
        rides = []
        for key, count in counts.items():
            cabin, board, alight = map(int, key.rsplit("::", 3)[1:])
            rides.append((cabin, board, alight, count))
        loads_available = True
    else:
        core = native.get("fixed_k_problem_manifest", {}).get("trajectory_problem", {}).get("movement_core", {})
        trips = native.get("trajectory_supports", [])
        passenger = native.get("validated_passenger_plan")
        rides = [(ride["cabin_id"], ride["board_visit_index"], ride["alight_visit_index"], ride["count"])
                 for ride in (passenger or {}).get("served_rides", [])]
        loads_available = passenger is not None
    options = {option["id"]: option for option in core.get("route_options", [])}
    visits = []
    for trip in trips:
        cabin = trip["cabin_id"]
        times = trip.get("switch_times_seconds")
        if times is None:
            times = [tick / 1e6 for tick in trip["switch_ticks"]]
        waits = trip.get("wait_seconds")
        if waits is None:
            waits = [tick / 1e6 for tick in trip.get("wait_ticks", [0] * len(times))]
        for i, (option_id, start, wait) in enumerate(zip(trip["route_option_ids"], times, waits)):
            option = options[option_id]
            entry = option.get("platform_entry_offset_seconds")
            exit_ = option.get("platform_exit_offset_seconds")
            start_tick = ddd_seconds_to_tick(start)
            wait_tick = ddd_seconds_to_tick(wait)
            visits.append({
                "cabin": cabin, "index": i, "station": option["station_id"],
                "start": start_tick / 1e6, "end": (start_tick + ddd_seconds_to_tick(option["duration_seconds"]) + wait_tick) / 1e6,
                "arrival": None if entry is None else (start_tick + ddd_seconds_to_tick(entry)) / 1e6,
                "boarding": None if exit_ is None else (start_tick + ddd_seconds_to_tick(exit_) + wait_tick) / 1e6,
                "stop": option["decision"] == "stop", "waiting": wait,
                "boarded": sum(q for k, b, a, q in rides if k == cabin and b == i) if loads_available else None,
                "alighted": sum(q for k, b, a, q in rides if k == cabin and a == i) if loads_available else None,
                "load": sum(q for k, b, a, q in rides if k == cabin and b <= i < a) if loads_available else None,
            })
    return {"schema": "thesis_timetable_replay_v1", "visits": visits,
            "loadsAvailable": loads_available,
            "horizon": core.get("passenger_service_end_seconds"),
            "end": max((visit["end"] for visit in visits), default=0)}


def write_detail(run_dir: Path, target: Path, result: dict, summary: dict):
    native = result.get("run", {})
    points = []
    diagnostics = []
    last_event = 0.0
    reference_probes = []
    for event in read_events(run_dir / "events.jsonl"):
        t = event.get("runner_elapsed_seconds", event.get("elapsed_seconds"))
        if not isinstance(t, (int, float)):
            continue
        last_event = max(last_event, t)
        if event.get("kind") == "capacity_probe":
            reference_probes.append(event)
        if summary["method"] == "evolution" and event.get("kind") == "incumbent":
            points.append({"seconds": t, "value": event.get("served"), "kind": "validated"})
        if summary["method"] == "labelled_arc_flow":
            for key, kind in (("solver_incumbent", "native"), ("certified_lower_bound", "bound")):
                value = event.get(key)
                if isinstance(value, (int, float)) and math.isfinite(value) and abs(value) < 1e50:
                    points.append({"seconds": t, "value": value, "kind": kind})
        if event.get("kind") == "evaluation_window":
            diagnostics.append({k: event.get(k) for k in ("elapsed_seconds", "evaluations_total", "feasible_total", "window_feasible_ratio")})
    if summary.get("elapsedSeconds") is None and last_event:
        summary["elapsedSeconds"] = last_event
    if summary.get("validated"):
        points.append({"seconds": summary.get("elapsedSeconds") or 0,
                       "value": summary.get("served") if summary["method"] == "evolution" else summary.get("journeyTime"), "kind": "validated"})
    replays = []
    certificates = list(sorted((run_dir / "incumbents").glob("*.json")))
    if (run_dir / "best.json").exists():
        certificates.append(run_dir / "best.json")
    for i, path in enumerate(certificates):
        certificate = json.loads(path.read_text())
        payload = replay_payload(certificate=certificate)
        file = f"replay_{i:05d}.json"
        write_snapshot(target / file, payload)
        metrics = certificate.get("metrics", {})
        replays.append({"label": "Final validated plan" if path.name == "best.json" else f"Improvement {i + 1}",
                        "file": file, "served": metrics.get("served"), "unserved": metrics.get("unserved")})
    if not replays and summary.get("validated") and native.get("trajectory_supports"):
        file = "replay_final.json"
        write_snapshot(target / file, replay_payload(result=result))
        replays.append({"label": "Final validated plan", "file": file})
    detail = {"schema": "thesis_run_detail_v1", "points": points, "diagnostics": diagnostics,
              "referenceProbes": [{key: probe.get(key) for key in ("demand", "outcome", "solver_status", "elapsed_seconds")}
                                  for probe in native.get("probes", []) or reference_probes],
              "replays": replays, "boundScope": summary.get("boundScope"),
              "nativePointsAreValidated": False,
              "artifacts": [path.name for path in target.glob("*.json") if path.name != "detail.json"]}
    write_snapshot(target / "detail.json", detail)
    summary["detail"] = summary["snapshot"].rsplit("/", 1)[0] + "/detail.json"
