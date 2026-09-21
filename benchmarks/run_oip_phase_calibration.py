"""Exact short-contract OIP common-phase calibration; never starts main runs."""
from __future__ import annotations

import argparse
from dataclasses import asdict
from enum import Enum
import json
from pathlib import Path
import shutil
import sys
import time

from ropeway_skip_stop_optimization.benchmarking.oip_pattern_waiting import prepare_oip_pattern_waiting_pilot
from ropeway_skip_stop_optimization.benchmarking.process_supervisor import supervise
from ropeway_skip_stop_optimization.benchmarking.thesis_contract import solver_versions, source_digest
from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_certificate import atomic_json
from ropeway_skip_stop_optimization.optimization.oip.phase_reference import solve_phase_reference, regular_geometry

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = "oip_regular_phase_short_1ms_v1"
FEASIBLE_STATUSES = frozenset({"FEASIBLE", "OPTIMAL"})


def serializable(value):
    return json.loads(json.dumps(asdict(value), default=lambda item: item.value
                                if isinstance(item, Enum) else str(item)))


def publish(output, frontend):
    if frontend is not None:
        for name in ("campaign.json", "references.json", "current_probe.json"):
            if not (output / name).exists():
                continue
            atomic_json(frontend / name, json.loads((output / name).read_text()))
        try:
            from benchmarks.thesis_publication import publish_calibration
        except ImportError:
            from thesis_publication import publish_calibration
        publish_calibration(output,frontend.parent)


def previous_probe_state(output: Path, family: str, attempt: str):
    """Return the proven bracket and preferred retry from earlier attempts."""
    try:
        attempt_number = int(attempt.rsplit("_", 1)[1])
    except (IndexError, ValueError) as exc:
        raise ValueError(f"invalid attempt name: {attempt}") from exc
    history = []
    certificates = []
    for number in range(1, attempt_number):
        folder = output / family / f"attempt_{number}"
        probes_path = folder / "probes.json"
        if probes_path.exists():
            history.extend(json.loads(probes_path.read_text()))
        certificate_path = folder / "certificate.json"
        if certificate_path.exists():
            certificates.append(certificate_path)
    feasible = [int(probe["demand"]) for probe in history
                if probe.get("status") in FEASIBLE_STATUSES]
    infeasible = [int(probe["demand"]) for probe in history
                  if probe.get("status") == "INFEASIBLE"]
    lower = max(feasible, default=0)
    upper = min(infeasible, default=None)
    retry = next((int(probe["demand"]) for probe in reversed(history)
                  if probe.get("status") == "UNKNOWN"
                  and int(probe["demand"]) > lower
                  and (upper is None or int(probe["demand"]) < upper)), None)
    best_certificate = None
    for path in certificates:
        certificate = json.loads(path.read_text())
        if int(certificate.get("demand", -1)) == lower:
            best_certificate = path
    return lower, upper, retry, history, best_certificate


def worker(args):
    started = time.monotonic()
    deadline = started + args.seconds - 30
    output = args.output.resolve()
    folder = output / args.worker / args.attempt
    folder.mkdir(parents=True, exist_ok=True)
    lower, upper, retry, history, best_certificate = previous_probe_state(
        output, args.worker, args.attempt) if args.continue_bracket else (0, None, None, [], None)
    probes = []
    if best_certificate is not None:
        shutil.copy2(best_certificate, folder / "certificate.json")
    candidate = retry if retry is not None else (
        (lower + upper) // 2 if upper is not None else (min(20000, 2 * lower) if lower else 500)
    )
    while time.monotonic() < deadline:
        prepared = prepare_oip_pattern_waiting_pilot(
            maximum_wait_seconds=0, cabin_count=62, legacy_headways=True,
            demand_total=candidate, demand_family=args.worker)
        domain = prepared.domain
        atomic_json(output / "current_probe.json", {"family": args.worker, "demand": candidate,
                    "started_unix": time.time(), "lower": lower, "upper": upper})
        refs = json.loads((output / "references.json").read_text())
        refs["current_probe"] = {"family": args.worker, "demand": candidate,
                                 "started_unix": time.time()}
        atomic_json(output / "references.json", refs)
        publish(output, args.frontend)
        result, certificate = solve_phase_reference(domain,
            seconds=max(0, deadline - time.monotonic()), workers=12)
        probes.append({"demand": candidate, **result})
        atomic_json(folder / "probes.json", probes)
        if certificate is not None:
            lower = candidate
            movement, fleet, passengers = certificate
            atomic_json(folder / "certificate.json", {
                "domain_fingerprint": domain.fingerprint,
                "comparison_fingerprint": domain.comparison_fingerprint,
                "demand": candidate, "phase_tick": result["phase_tick"],
                "movement_plan": serializable(movement), "fleet_plan": serializable(fleet),
                "passenger_plan": serializable(passengers),
            })
        elif result["status"] == "INFEASIBLE":
            upper = candidate
        exact = upper is not None and upper == lower + 1
        evidence = {
            "job_id": f"oip_{args.worker}_k62", "family": args.worker,
            "capacity_proven": exact, "proven_feasible_demand": lower,
            "proven_infeasible_demand": upper,
            "capacity": lower if exact else None,
            "load_120": (6 * lower + 4) // 5 if exact else None,
            "reference_kind": "regular_all_stop_free_common_phase",
            "proof_scope": "OIP_REGULAR_NO_WAIT_FULL_CYCLE_PHASE_GRID_NESTED_DEMAND",
            "contract_id": CONTRACT, "domain_fingerprint": domain.fingerprint,
            "demand_window_seconds": prepared.demand_window_seconds,
            "horizon_seconds": prepared.passenger_horizon_seconds,
            "operation_seconds": prepared.operation_seconds,
            "movement_cycle_ticks": regular_geometry(domain)[2][-1],
            "ticks_per_second": domain.grid.ticks_per_second,
            "elapsed_seconds": time.monotonic() - started,
            "continued_from_previous_attempts": bool(history),
            "previous_probe_count": len(history),
            "latest_probe": {"demand": candidate, "status": result["status"]},
        }
        atomic_json(folder / "result.json", evidence)
        refs = json.loads((output / "references.json").read_text())
        refs["evidence"] = [e for e in refs["evidence"] if e["job_id"] != evidence["job_id"]] + [evidence]
        atomic_json(output / "references.json", refs)
        publish(output, args.frontend)
        if exact or result["status"] == "UNKNOWN" or lower == 20000:
            break
        candidate = (lower + upper) // 2 if upper is not None else min(20000, 2 * candidate)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--frontend", type=Path)
    parser.add_argument("--seconds", type=int, default=1800)
    parser.add_argument("--build-only", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--continue-unresolved", action="store_true",
                        help="reuse proven brackets from earlier attempts")
    parser.add_argument("--families", nargs="+", choices=("f2", "f3", "f0"))
    parser.add_argument("--maximum-attempts", type=int)
    parser.add_argument("--attempt", default="attempt_1", help=argparse.SUPPRESS)
    parser.add_argument("--worker", choices=("f2", "f3", "f0"), help=argparse.SUPPRESS)
    parser.add_argument("--continue-bracket", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.seconds <= 60:
        parser.error("budget must exceed 60 seconds including validation reserve")
    if args.worker:
        worker(args)
        return
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    config = {"seconds_per_family": args.seconds, "contract_id": CONTRACT,
              "source_digest": source_digest(ROOT), "solver_versions": solver_versions()}
    if (output / "campaign.json").exists():
        state = json.loads((output / "campaign.json").read_text())
        ignored_identity_keys = {"source_digest"}
        if args.continue_unresolved:
            ignored_identity_keys.add("seconds_per_family")
        comparable_identity = {key: value for key, value in config.items() if key not in ignored_identity_keys}
        stored_comparable = {key: value for key, value in state["identity"].items()
                             if key not in ignored_identity_keys}
        source_changed = state["identity"].get("source_digest") != config["source_digest"]
        if (not args.resume or stored_comparable != comparable_identity
                or (source_changed and not args.continue_unresolved)):
            raise ValueError("existing campaign requires --resume and identical configuration/code")
        if source_changed:
            state.setdefault("continuation_source_digests", []).append({
                "source_digest": config["source_digest"], "started_unix": time.time(),
            })
    else:
        state = {
            "campaign_id": output.name, "identity": config, "status": "prepared",
            "execution_started_unix": None,
            "description": "OIP · K62 · No-Wait · exakte gemeinsame Phase · Nachfrage 1464 s + 900 s Abschluss + 300 s Weiterfahrt",
            "jobs": [dict(id=f"oip_{f}_k62", group="oip", family=f, cabins=62,
                         reference_kind="regular_all_stop_free_common_phase", status="planned", attempts=[])
                     for f in ("f2", "f3", "f0")],
        }
        atomic_json(output / "references.json", {"contract_id": CONTRACT, "evidence": []})
    atomic_json(output / "campaign.json", state)
    publish(output, args.frontend)
    if args.build_only:
        return
    state["status"] = "running"
    state["execution_started_unix"] = state["execution_started_unix"] or time.time()
    selected_families = set(args.families or ("f2", "f3", "f0"))
    for job in state["jobs"]:
        if (job["family"] not in selected_families or job["status"] == "complete"
                or (args.maximum_attempts is not None
                    and len(job["attempts"]) >= args.maximum_attempts)):
            continue
        job["status"] = "running"
        attempt = {"started_unix": time.time(), "source_digest": config["source_digest"],
                   "continues_bracket": bool(args.continue_unresolved and job["attempts"]),
                   "budget_seconds": args.seconds}
        job["attempts"].append(attempt)
        atomic_json(output / "campaign.json", state)
        publish(output, args.frontend)
        command = [sys.executable, str(Path(__file__).resolve()), "--output", str(output),
                   "--seconds", str(args.seconds), "--worker", job["family"],
                   "--attempt", f"attempt_{len(job['attempts'])}"]
        if args.continue_unresolved and len(job["attempts"]) > 1:
            command.append("--continue-bracket")
        if args.frontend:
            command += ["--frontend", str(args.frontend.resolve())]
        guard = supervise(command, output / job["family"] / f"supervision_{len(job['attempts'])}",
                          seconds=args.seconds, memory_bytes=32 * 1024**3,
                          system_memory_pressure_seconds=30)
        attempt.update(finished_unix=time.time(), supervisor=guard)
        result_path = output / job["family"] / f"attempt_{len(job['attempts'])}" / "result.json"
        result = json.loads(result_path.read_text()) if result_path.exists() else {}
        job["status"] = "complete" if guard["exit_code"] == 0 and result.get("capacity_proven") else "unresolved"
        atomic_json(output / "campaign.json", state)
        publish(output, args.frontend)
    state["finished_unix"] = time.time()
    state["status"] = "complete" if all(j["status"] == "complete" for j in state["jobs"]) else "unresolved"
    atomic_json(output / "campaign.json", state)
    publish(output, args.frontend)


if __name__ == "__main__":
    main()
