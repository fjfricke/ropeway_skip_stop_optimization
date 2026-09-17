"""Publish the active thesis evolution attempt for the local live dashboard."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import time

from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_certificate import atomic_json


def snapshot(events: Path, *, label: str, limit: float, reference: int, status: str) -> dict:
    live = {
        "schema": "reservoir_line_evolution_live_v1", "label": label,
        "status": status, "time_limit_seconds": limit, "reference_served": reference,
        "events_seen": 0, "evaluations": 0, "feasible_evaluations": 0,
        "best": None, "best_mixed": None, "incumbents": [], "mixed_incumbents": [],
        "repair_counts": {}, "repair_seconds": 0.0, "timing_status_counts": {},
        "pattern_cache_hits": 0, "representation": "patterns_dispatch",
        "dispatch_subproblem": None, "updated_unix": time.time(), "elapsed_seconds": 0,
        "objective": "service_then_journey",
    }
    if not events.exists():
        return live
    for raw in events.read_text(errors="replace").splitlines():
        try: event = json.loads(raw)
        except json.JSONDecodeError: continue
        live["events_seen"] += 1
        live["elapsed_seconds"] = max(live["elapsed_seconds"], event.get("elapsed_seconds", 0) or 0)
        kind = event.get("kind")
        if kind == "evaluation_window":
            live["evaluations"] = event.get("evaluations_total", live["evaluations"])
            live["feasible_evaluations"] = event.get("feasible_total", live["feasible_evaluations"])
        elif kind == "incumbent":
            point = {key: event.get(key) for key in (
                "elapsed_seconds", "served", "unserved", "fleet_size", "pattern_counts",
                "journey_time_tick", "total_wait_tick", "repair_status")}
            live["incumbents"].append(point); live["best"] = point
            live["last_improvement_seconds"] = event.get("elapsed_seconds")
        elif kind == "mixed_fleet_frontier":
            point = {key: event.get(key) for key in (
                "elapsed_seconds", "served", "unserved", "fleet_size", "pattern_counts",
                "journey_time_tick", "total_wait_tick", "repair_status")}
            live["mixed_incumbents"].append(point)
            if live["best_mixed"] is None or point.get("served", -1) > live["best_mixed"].get("served", -1):
                live["best_mixed"] = point
    return live


def conflict_snapshot(events: Path, run_id: str) -> dict:
    result = {"runs": {run_id: []}, "infeasible": {run_id: []},
              "missing": {run_id: []}, "errors": {}, "updated_unix": time.time()}
    if not events.exists():
        return result
    for raw in events.read_text(errors="replace").splitlines():
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if event.get("kind") == "population":
            members = event.get("members", [])
            complete = [m.get("conflicts", 0) for m in members
                        if m.get("decoder_status") in ("NO_WAIT_VALID", "WAITING_CANDIDATE")]
            missing = [m.get("structural_violation", 0) for m in members
                       if m.get("decoder_status") == "CONSTRUCTION_FAILED"]
            def point(values):
                return {"elapsed_seconds": event.get("elapsed_seconds", 0),
                        "mean": sum(values) / len(values) if values else None,
                        "minimum": min(values) if values else None,
                        "maximum": max(values) if values else None,
                        "complete": len(values), "population": len(members),
                        "construction_failed": len(missing), "unmeasured": 0}
            result["runs"][run_id].append(point(complete))
            result["missing"][run_id].append(point(missing))
        elif event.get("kind") == "unrepaired_candidate":
            value = event.get("conflicts", 0)
            result["infeasible"][run_id].append({
                "elapsed_seconds": event.get("elapsed_seconds", 0), "mean": value,
                "minimum": value, "maximum": value, "complete": 1, "population": 1,
                "construction_failed": 0, "unmeasured": 0,
            })
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--study", type=Path, required=True)
    parser.add_argument("--live-dir", type=Path, required=True)
    parser.add_argument("--watch-seconds", type=float, required=True)
    args = parser.parse_args(); args.live_dir.mkdir(parents=True, exist_ok=True)
    deadline = time.time() + args.watch_seconds
    while time.time() < deadline:
        study_manifest_path = args.study / "manifest.json"
        study_manifest = json.loads(study_manifest_path.read_text()) if study_manifest_path.exists() else {"groups": []}
        state_path = args.study / "study.json"
        state = json.loads(state_path.read_text()) if state_path.exists() else {"attempts": [], "status": "queued"}
        attempts = state.get("attempts", [])
        active = next((a for a in reversed(attempts) if a.get("status") == "running"), None)
        chosen = active or (attempts[-1] if attempts else None)
        runs = []
        completed = sum(a.get("status") == "complete" for a in attempts)
        total = len(study_manifest.get("groups", []))
        if chosen:
            attempt = args.study / Path(chosen["result"]).parent
            run_id = "thesis_active"
            label = f"{chosen['group']} · N{chosen['demand']} · K{chosen['k']} · seed {chosen['seed']}"
            group = next((g for g in study_manifest.get("groups", []) if g.get("id") == chosen["group"]), {})
            snap = snapshot(
                attempt / "events.jsonl",
                label=label,
                limit=float(group.get("stage_seconds", 300)),
                reference=group.get("reference_served"),
                status=chosen.get("status", "running"),
            )
            prepared_path = attempt / "evolution_prepared.json"
            if prepared_path.exists():
                prepared = json.loads(prepared_path.read_text())
                snap.update(catalog_profile=prepared.get("catalog_profile"),
                            allowed_pattern_count=len(prepared.get("patterns", [])),
                            pattern_search=prepared.get("pattern_search", "independent"))
            atomic_json(args.live_dir / f"{run_id}.json", snap)
            atomic_json(args.live_dir / "conflicts.json", conflict_snapshot(attempt / "events.jsonl", run_id))
            runs.append({"id": run_id, "label": label, "status": chosen.get("status", "running"),
                         "snapshot": f"/generated/evolution-live/{run_id}.json"})
        atomic_json(args.live_dir / "manifest.json", {
            "schema": "reservoir_line_evolution_live_manifest_v1",
            "label": f"{study_manifest.get('live_label', 'Thesis Stage 2 capacity evolution')} · {completed}/{total} complete",
            "completed_runs": completed, "total_runs": total,
            "status": state.get("status", "queued"),
            "runs": runs, "updated_unix": time.time(),
        })
        if state.get("status") == "complete": break
        time.sleep(2)


if __name__ == "__main__": main()
