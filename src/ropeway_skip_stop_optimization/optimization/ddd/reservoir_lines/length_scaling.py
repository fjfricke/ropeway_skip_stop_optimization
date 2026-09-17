from __future__ import annotations

from dataclasses import dataclass, replace
import math

from ..models import DddRouteDecision
from ..reservoir_cp_sat_problem import DddReservoirCpSatProblem
from ..time_ticks import ddd_seconds_to_tick, ddd_tick_to_seconds


@dataclass(frozen=True)
class UniformLengthScaling:
    """A controlled duration scaling for the uniform circular test domain.

    Every movement in that domain contains exactly one free rope segment after
    its station-local phases.  The local phases, resources and headways remain
    unchanged; only the free-rope travel contribution is replaced.
    """

    source_length_m: float
    target_length_m: float
    rope_speed_m_per_s: float

    @property
    def duration_delta_seconds(self) -> float:
        return (self.target_length_m - self.source_length_m) / self.rope_speed_m_per_s

    def validate(self) -> None:
        for name, value in (
            ("source length", self.source_length_m),
            ("target length", self.target_length_m),
            ("rope speed", self.rope_speed_m_per_s),
        ):
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be finite and positive")
        ddd_seconds_to_tick(self.duration_delta_seconds)


@dataclass(frozen=True)
class SaturatedAllStopReference:
    cycle_tick: int
    binding_headway_tick: int
    saturated_cabins: int
    experimental_fleet_cap: int

    @property
    def cycle_seconds(self) -> float:
        return ddd_tick_to_seconds(self.cycle_tick)


def scale_uniform_rope_length(
    problem: DddReservoirCpSatProblem,
    scaling: UniformLengthScaling,
) -> DddReservoirCpSatProblem:
    """Change only the one free-rope contribution of every route option."""
    problem.validate()
    scaling.validate()
    delta_tick = ddd_seconds_to_tick(scaling.duration_delta_seconds)
    source_travel_tick = ddd_seconds_to_tick(
        scaling.source_length_m / scaling.rope_speed_m_per_s
    )
    options = []
    for option in problem.resolved_core.route_options:
        local_duration_tick = option.duration_tick - source_travel_tick
        if local_duration_tick < option.exit_switch_offset_tick:
            raise ValueError(
                "uniform length scaling requires one free rope segment after "
                f"the station-local phases of {option.id!r}"
            )
        new_duration_tick = option.duration_tick + delta_tick
        if new_duration_tick <= option.exit_switch_offset_tick:
            raise ValueError("scaled route duration ends before the exit switch")
        options.append(
            replace(option, duration_seconds=ddd_tick_to_seconds(new_duration_tick))
        )
    target = float(scaling.target_length_m)
    suffix = (
        str(int(target))
        if target.is_integer()
        else str(target).replace(".", "p")
    )
    core = replace(
        problem.movement_core,
        scenario_id=f"{problem.movement_core.scenario_id}__rope_{suffix}m",
        route_options=tuple(options),
    )
    from ..reservoir_boundary import geometry_fingerprint

    boundary = problem.boundary_policy
    if boundary is not None:
        boundary = replace(boundary, geometry_fingerprint=geometry_fingerprint(core))
    scaled = replace(problem, movement_core=core, boundary_policy=boundary)
    scaled.validate()
    return scaled


def saturated_all_stop_reference(
    problem: DddReservoirCpSatProblem,
    *,
    fleet_multiplier: float = 1.25,
) -> SaturatedAllStopReference:
    """Return the regular no-wait All-Stop saturation for a uniform ring."""
    if not math.isfinite(fleet_multiplier) or fleet_multiplier < 1:
        raise ValueError("fleet multiplier must be finite and at least one")
    stop_options = []
    for state_id in problem.cycle_states:
        values = tuple(
            option
            for option in problem.resolved_core.route_options_by_state_id[state_id]
            if option.decision is DddRouteDecision.STOP
        )
        if len(values) != 1:
            raise ValueError("All-Stop saturation requires one stop option per state")
        stop_options.append(values[0])
    cycle_tick = sum(option.duration_tick for option in stop_options)
    binding_headway_tick = max(
        usage.leader_clear_offset_tick
        + usage.separation_after_tick(
            problem.resolved_core.resources_by_id[
                usage.resource_id
            ].minimum_headway_tick
        )
        - usage.follower_enter_offset_tick
        for option in stop_options
        for usage in option.resource_usages
    )
    if problem.boundary_policy is not None:
        binding_headway_tick = max(binding_headway_tick, problem.boundary_policy.headway_tick)
    if binding_headway_tick <= 0:
        raise ValueError("All-Stop saturation requires a positive resource headway")
    saturated = cycle_tick // binding_headway_tick
    if saturated <= 0:
        raise ValueError("All-Stop cycle cannot hold one cabin")
    return SaturatedAllStopReference(
        cycle_tick=cycle_tick,
        binding_headway_tick=binding_headway_tick,
        saturated_cabins=saturated,
        experimental_fleet_cap=math.ceil(fleet_multiplier * saturated),
    )


def with_saturation_time_contract(
    problem: DddReservoirCpSatProblem,
    reference: SaturatedAllStopReference,
) -> DddReservoirCpSatProblem:
    """Give every dispatch up to one cycle enough time for a final return."""
    service_end_tick = problem.resolved_core.passenger_service_end_tick
    operational_end_tick = service_end_tick + reference.cycle_tick
    core = replace(
        problem.movement_core,
        operational_end_seconds=ddd_tick_to_seconds(operational_end_tick),
    )
    scaled = replace(
        problem,
        movement_core=core,
        available_fleet_count=reference.experimental_fleet_cap,
        dispatch_end_seconds=reference.cycle_seconds,
    )
    scaled.validate()
    return scaled
