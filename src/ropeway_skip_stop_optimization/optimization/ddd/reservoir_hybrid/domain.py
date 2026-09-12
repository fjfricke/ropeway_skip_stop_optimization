"""Lossless single-use domain adapter and checkpoint reconstruction."""

from dataclasses import dataclass
import json
from pathlib import Path

from ..models import (
    DddMovementCore,
    DddMovementState,
    DddResource,
    DddResourceUsage,
    DddRouteDecision,
    DddRouteOption,
)
from ..reservoir_arc_flow_problem import DddReservoirOperatingMode
from ..reservoir_cp_sat_problem import DddReservoirCpSatProblem
from ..reservoir_cp_sat_certificate import read_reservoir_cp_checkpoint
from ..trajectory_column_generation import DddTrajectoryWaitingDomain
from ..trajectory_problem import DddTrajectoryWaitingPolicy
from ...ean.models import EanDemandGroup


@dataclass(frozen=True)
class ReservoirOperatingDomain:
    problem: DddReservoirCpSatProblem
    lifecycle: str = "single_use"

    def __post_init__(self):
        if self.lifecycle != "single_use":
            raise ValueError("reusable lifecycle requires the future S6 implementation")
        self.problem.validate()

    @property
    def fingerprint(self):
        return self.problem.fingerprint


def load_reference(path: Path):
    raw = json.loads(path.read_text())
    m = raw["domain_manifest"]
    if m.get("schema") != "single_use_reservoir_cp_domain_v1":
        raise ValueError("expected a single-use reservoir checkpoint")
    c = m["movement_core"]
    core = DddMovementCore(
        **{
            k: v
            for k, v in c.items()
            if k not in ("states", "route_options", "resources")
        },
        states=tuple(DddMovementState(**s) for s in c["states"]),
        resources=tuple(DddResource(**r) for r in c["resources"]),
        route_options=tuple(
            DddRouteOption(
                **{
                    k: v
                    for k, v in o.items()
                    if k not in ("decision", "resource_usages")
                },
                decision=DddRouteDecision(o["decision"]),
                resource_usages=tuple(
                    DddResourceUsage(**u) for u in o["resource_usages"]
                ),
            )
            for o in c["route_options"]
        ),
    )
    w = dict(m["waiting_policy"])
    w["domain"] = DddTrajectoryWaitingDomain(w["domain"])
    w["maximum_wait_seconds_by_station_id"] = tuple(
        tuple(x) for x in w["maximum_wait_seconds_by_station_id"]
    )
    fields = DddReservoirCpSatProblem.__dataclass_fields__
    kwargs = {k: m[k] for k in fields if k in m}
    kwargs.update(
        movement_core=core,
        demand_groups=tuple(EanDemandGroup(**g) for g in m["demand_groups"]),
        waiting_policy=DddTrajectoryWaitingPolicy(**w),
        operating_mode=DddReservoirOperatingMode(m["operating_mode"]),
    )
    p = DddReservoirCpSatProblem(**kwargs)
    return ReservoirOperatingDomain(p), read_reservoir_cp_checkpoint(path, p)
