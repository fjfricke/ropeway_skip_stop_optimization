"""Public symbolic reservoir DP optimizer with independent certificate checks."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict

from ..cp_sat_certificate import stable_fingerprint
from ..reservoir_cp_sat_certificate import (
    DddReservoirCpPlan,
    DddReservoirCpTrip,
    validate_reservoir_cp_plan,
)
from ..reservoir_cp_sat_problem import DddReservoirCpSatProblem
from .config import ReservoirDpConfig
from .engine import run_native_engine
from .preparation import prepare_reservoir_dp


def _plan_from_witness(problem, prepared, witness):
    option_ids = [value["id"] for value in prepared.payload["options"]]
    trips = []
    for cabin, visits in enumerate(witness["visits"]):
        trips.append(
            DddReservoirCpTrip(
                cabin,
                tuple(option_ids[visit["option"]] for visit in visits),
                tuple(visit["start"] for visit in visits),
                tuple(visit["wait"] for visit in visits),
                witness["returns"][cabin],
            )
        )
    candidates = {
        (candidate.cabin_id, candidate.board_visit_index, candidate.demand_group_id): candidate
        for candidate in problem.passenger_build.ride_candidates
    }
    group_ids = [value["id"] for value in prepared.payload["demands"]]
    ride_counts = defaultdict(int)
    for board in witness["boards"]:
        if not board["amount"]:
            continue
        key = (board["cabin"], board["visit"], group_ids[board["demand"]])
        candidate = candidates.get(key)
        if candidate is None:
            raise ValueError(f"native DP boarded an unavailable canonical ride: {key}")
        ride_counts[candidate.id] += board["amount"]
    return DddReservoirCpPlan(tuple(trips), dict(ride_counts))


class ReservoirDpOptimizer:
    def __init__(self, config: ReservoirDpConfig | None = None):
        if config is None:
            config = ReservoirDpConfig()
        config.validate()
        self.config = config

    def solve(self, problem: DddReservoirCpSatProblem) -> tuple[dict, DddReservoirCpPlan | None]:
        prepared = prepare_reservoir_dp(problem)
        native = run_native_engine(prepared, self.config)
        plan = metrics = validation_error = None
        if native.get("plan") is not None:
            try:
                plan = _plan_from_witness(problem, prepared, native["plan"])
                metrics = validate_reservoir_cp_plan(problem, plan)
                if metrics.served != native.get("served"):
                    raise ValueError("native and independently validated service differ")
            except (IndexError, KeyError, TypeError, ValueError) as error:
                validation_error = f"{type(error).__name__}: {error}"
                plan = metrics = None
        result = {
            **native,
            "variant": str(self.config.variant),
            "model_fingerprint": stable_fingerprint(
                {
                    "prepared": prepared.fingerprint,
                    "variant": str(self.config.variant),
                    "native_source_hash": native.get("native_source_hash"),
                    "engine": native.get("engine"),
                }
            ),
            "has_valid_plan": plan is not None,
            "validation_error": validation_error,
            "metrics": None if metrics is None else asdict(metrics),
        }
        if validation_error:
            result["status"] = "invalid_candidate"
        return result, plan
