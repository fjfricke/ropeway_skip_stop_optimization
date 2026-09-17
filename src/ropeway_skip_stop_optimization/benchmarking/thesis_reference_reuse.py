"""Validate saved evidence before continuing a regular All-Stop capacity bracket."""
from dataclasses import replace
import json
from pathlib import Path

from .thesis_cases import prepare_experiment_case
from ..optimization.ddd.reservoir_cp_sat_certificate import read_reservoir_cp_checkpoint


def load_capacity_reference(directory: Path, spec, config):
    result = json.loads((directory / "result.json").read_text())
    native = result.get("run", {})
    if (result.get("method") != "all_stop_phase" or result.get("case_fingerprint") != spec.fingerprint
        or native.get("proof_scope") != "REGULAR_NO_WAIT_ALL_STOP_COMMON_PHASE_AND_NESTED_DEMAND"
        or native.get("config", {}).get("cabins") != config.cabins):
        raise ValueError("capacity reference domain/fleet does not match")
    lower = native.get("proven_feasible_demand") or 0
    upper = native.get("proven_infeasible_demand")
    if upper is not None and not any(probe.get("demand") == upper and probe.get("outcome") == "infeasible"
                                     and probe.get("solver_status") == "INFEASIBLE" for probe in native.get("probes", [])):
        raise ValueError("reference has no matching native infeasibility proof; reuse the original proof source")
    plan = prepared = None
    if lower:
        prepared = prepare_experiment_case(replace(spec, demand_total=lower))
        plan = read_reservoir_cp_checkpoint(directory / "best.json", prepared.problem)
        if len(plan.trips) != config.cabins or sum(plan.ride_counts.values()) != lower:
            raise ValueError("reference checkpoint does not fully serve its claimed demand")
        if any(wait != 0 for trip in plan.trips for wait in trip.wait_ticks):
            raise ValueError("reference checkpoint contains Waiting; expected No-Wait")
        options = {option.id: option for option in prepared.problem.resolved_core.route_options}
        if any(options[o].decision.value != "stop" for trip in plan.trips for o in trip.route_option_ids):
            raise ValueError("reference checkpoint contains Skip-Stop")
        phase = plan.trips[0].switch_ticks[0]
        cycle = prepared.all_stop_cycle_tick
        if any(trip.switch_ticks[0] != phase + i * cycle // config.cabins for i, trip in enumerate(plan.trips)):
            raise ValueError("reference checkpoint is not the regular common-phase schedule")
    return lower, upper, plan, prepared
