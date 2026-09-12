"""Separate local results from global lower-bound certificates."""

from dataclasses import dataclass
from math import isfinite
import json

from ..reservoir_cp_sat_certificate import validate_reservoir_cp_plan


@dataclass(frozen=True)
class GlobalReservoirBound:
    fingerprint: str
    value: float
    model_fingerprint: str
    source: str


@dataclass(frozen=True)
class LocalRepairResult:
    value: float


def read_global_bound_result(path, problem):
    """Import locally produced LP provenance, not local or incomplete LP values.

    Metadata checks do not replace the producer's mathematical projection proof.
    Only use result artifacts from the verified bound implementation.
    """
    result = json.loads(path.read_text())
    if result.get("problem_fingerprint") != problem.fingerprint:
        raise ValueError("foreign bound domain")
    candidates = [
        r
        for r in result.get("rounds", [result])
        if r.get("status") == 2
        and r.get("raw_lp_bound") is not None
        and r.get("objective_scope") == "single_use_reservoir_global"
    ]
    if not candidates:
        raise ValueError("no completed global LP certificate")
    best = max(candidates, key=lambda r: r["raw_lp_bound"])
    if not isfinite(best["raw_lp_bound"]) or not best.get("model_fingerprint"):
        raise ValueError("invalid LP certificate")
    return GlobalReservoirBound(
        problem.fingerprint,
        best["raw_lp_bound"],
        best["model_fingerprint"],
        "optimal_lp",
    )


class ReservoirCertificateLedger:
    def __init__(self, problem):
        self.problem = problem
        self.lower_bound = 0.0
        self.upper_bound = None
        self.plan = None

    def accept_plan(self, plan):
        value = validate_reservoir_cp_plan(self.problem, plan).journey_time_tick / 1e6
        if value + 1e-5 < self.lower_bound:
            raise ValueError("global LB exceeds validated UB")
        if self.upper_bound is None or value < self.upper_bound:
            self.upper_bound, self.plan = value, plan

    def accept_bound(self, bound):
        if not isinstance(bound, GlobalReservoirBound):
            raise ValueError("local/pool bound is not a global certificate")
        if bound.fingerprint != self.problem.fingerprint or not isfinite(bound.value):
            raise ValueError("incompatible global bound")
        if self.upper_bound is not None and bound.value > self.upper_bound + 1e-5:
            raise ValueError("global LB exceeds validated UB")
        self.lower_bound = max(self.lower_bound, bound.value)
