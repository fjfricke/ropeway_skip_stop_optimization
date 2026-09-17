"""Versioned physical protection of the single shared reservoir cross-section."""

import json
import math
from dataclasses import asdict, dataclass, replace
from decimal import ROUND_CEILING, Decimal
from itertools import pairwise
from pathlib import Path

from .cp_sat_certificate import stable_fingerprint
from .time_ticks import DDD_TIME_TICKS_PER_SECOND

LEGACY_BOUNDARY = "ideal_entry_state_no_depot_resource_unique_state_tick_v1"
SHARED_BOUNDARY = "shared_rope_headway_dispatch_passage_return_v1"


def geometry_fingerprint(core):
    """Exclude demand/horizons; bind evidence to the actual movement geometry."""
    return stable_fingerprint(
        {
            "states": [asdict(s) for s in core.states],
            "routes": [asdict(o) for o in core.route_options],
            "resources": [asdict(r) for r in core.resources],
        }
    )


def outward_tick(seconds):
    if isinstance(seconds, bool) or not math.isfinite(seconds) or seconds <= 0:
        raise ValueError("reservoir rope headway must be finite and positive")
    # Decimal text avoids an extra tick from binary floating-point conversion.
    return int(
        (Decimal(str(seconds)) * DDD_TIME_TICKS_PER_SECOND).to_integral_value(
            rounding=ROUND_CEILING
        )
    )


@dataclass(frozen=True)
class ReservoirBoundaryPolicy:
    port_id: str
    entry_state_id: str
    rope_headway_seconds: float
    source: str
    geometry_fingerprint: str
    contract: str = SHARED_BOUNDARY

    @property
    def headway_tick(self):
        return outward_tick(self.rope_headway_seconds)

    @property
    def resource_id(self):
        return f"__reservoir_port__::{self.port_id}"

    def validate(self, core, entry_state_id):
        if self.contract != SHARED_BOUNDARY:
            raise ValueError("unsupported reservoir boundary contract")
        if (
            not isinstance(self.port_id, str)
            or not self.port_id
            or not isinstance(self.source, str)
            or not self.source
            or self.entry_state_id != entry_state_id
        ):
            raise ValueError("invalid reservoir port identity or headway evidence")
        if self.resource_id in {r.id for r in core.resources}:
            raise ValueError(
                "reservoir port resource ID collides with a movement resource"
            )
        if self.geometry_fingerprint != geometry_fingerprint(core):
            raise ValueError(
                "reservoir headway evidence belongs to different geometry; rederive it"
            )
        if self.headway_tick >= 2**63 - core.operational_end_tick:
            raise ValueError("reservoir port protection exceeds integer time range")

    @classmethod
    def from_headway_policy(cls, core, entry_state_id, policy):
        """Read the explicit derived rope quantity, never an exit-rule minimum."""
        if policy is None or policy.legacy:
            raise ValueError(
                "shared reservoir port requires a derived rope-headway policy"
            )
        values = [
            q.value for q in policy.derived_quantities if q.id == "rope_headway_seconds"
        ]
        if len(values) != 1:
            raise ValueError("missing unambiguous derived rope_headway_seconds")
        return cls(
            entry_state_id,
            entry_state_id,
            values[0],
            "DerivedHeadwayPolicy.rope_headway_seconds; policy="
            + stable_fingerprint(asdict(policy)),
            geometry_fingerprint(core),
        )


def state_protection_tick(problem, state_id):
    policy = problem.boundary_policy
    return (
        policy.headway_tick
        if policy is not None and state_id == problem.entry_state_id
        else 1
    )


def state_resource_id(problem, state_id):
    policy = problem.boundary_policy
    return (
        policy.resource_id
        if policy is not None and state_id == problem.entry_state_id
        else f"__state__::{state_id}"
    )


def port_events(problem, plan):
    """Reconstruct actual passages, independently of solver/prepared intervals."""
    options = {o.id: o for o in problem.resolved_core.route_options}
    events = []
    for trip in plan.trips:
        for i, (oid, time) in enumerate(
            zip(trip.route_option_ids, trip.switch_ticks, strict=True)
        ):
            if options[oid].from_state_id == problem.entry_state_id:
                events.append(
                    (time, trip.cabin_id, "dispatch" if i == 0 else "passage")
                )
        events.append((trip.return_tick, trip.cabin_id, "return"))
    return sorted(events)


def validate_port_separation(problem, plan):
    events = port_events(problem, plan)
    minimum = min((b[0] - a[0] for a, b in pairwise(events)), default=None)
    policy = problem.boundary_policy
    if policy is not None:
        for a, b in pairwise(events):
            gap = b[0] - a[0]
            if gap < policy.headway_tick:
                raise ValueError(
                    f"reservoir port/headway conflict at {policy.port_id}: "
                    f"cabin {a[1]} {a[2]} at {a[0]}, cabin {b[1]} {b[2]} at {b[0]}; "
                    f"gap {gap} ticks < required {policy.headway_tick}"
                )
    return {
        "port_event_count": len(events),
        "minimum_port_gap_tick": minimum,
        "required_port_gap_tick": policy.headway_tick if policy else None,
    }


def add_boundary_arguments(parser):
    parser.add_argument(
        "--reservoir-port-policy",
        choices=("legacy_ideal", "shared_rope_headway"),
        default=None,
    )
    parser.add_argument(
        "--port-headway-evidence",
        type=Path,
        help="JSON ReservoirBoundaryPolicy bound to the checkpoint geometry",
    )


def apply_boundary_arguments(problem, args, *, derived_policy=None):
    mode = getattr(args, "reservoir_port_policy", None)
    evidence = getattr(args, "port_headway_evidence", None)
    if mode not in (None, "legacy_ideal", "shared_rope_headway"):
        raise ValueError("unsupported reservoir port policy")
    if evidence and mode != "shared_rope_headway":
        raise ValueError(
            "--port-headway-evidence requires --reservoir-port-policy shared_rope_headway"
        )
    if mode is None:
        return problem  # Preserve an imported contract, including the new one.
    if mode == "legacy_ideal":
        if problem.boundary_policy is not None:
            raise ValueError(
                "cannot silently weaken a shared reservoir checkpoint to legacy"
            )
        return problem
    boundary = problem.boundary_policy
    if evidence:
        boundary = ReservoirBoundaryPolicy(**json.loads(evidence.read_text()))
    elif derived_policy is not None:
        boundary = ReservoirBoundaryPolicy.from_headway_policy(
            problem.movement_core, problem.entry_state_id, derived_policy
        )
    if boundary is None:
        raise ValueError(
            "legacy checkpoint lacks rope-headway evidence; supply --port-headway-evidence"
        )
    result = replace(problem, boundary_policy=boundary)
    result.validate()
    return result
