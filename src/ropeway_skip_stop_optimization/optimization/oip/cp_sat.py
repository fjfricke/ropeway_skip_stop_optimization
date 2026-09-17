from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from time import perf_counter
from typing import Any, Callable

from ortools.sat.python import cp_model

from ropeway_skip_stop_optimization.models import (
    ConstantHeadwayRule,
    LeaderBehaviorHeadwayRule,
)
from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_passenger_inventory import (
    DddOdInventoryRide,
    _aggregate_rides,
    _od_id,
)
from ropeway_skip_stop_optimization.optimization.ean.builders.passenger_builder import (
    EanPassengerCandidateBuildResult,
    EanPassengerCandidateBuilder,
)
from ropeway_skip_stop_optimization.optimization.ean.fleet import (
    EanFleetPlan,
    EanInitialPlacementState,
    EanInitialPlacementStateKind,
)
from ropeway_skip_stop_optimization.optimization.ean.formulation_config import (
    EanHorizonFormulation,
    EanTimeBoundFormulation,
)
from ropeway_skip_stop_optimization.optimization.ean.models import (
    EanActivationReference,
    EanFleetMode,
    EanTimeReference,
    HeadwayCheckpointKind,
)
from ropeway_skip_stop_optimization.optimization.ean.passenger_plan import (
    EanPassengerServicePlan,
    EanServedRideGroup,
)
from ropeway_skip_stop_optimization.optimization.ean.plan import (
    EanCabinTrajectory,
    EanCabinVisit,
    EanMovementPlan,
    EanRouteDecision,
)
from ropeway_skip_stop_optimization.optimization.ean.time_bounds import (
    build_ean_model_time_bounds,
)

from .domain import OipDomain, OipOperation


@dataclass(frozen=True)
class OipCpSatConfig:
    time_limit_seconds: float | None = None
    workers: int = 1
    seed: int = 0
    build_only: bool = False
    movement_only: bool = False
    fixed_stop_patterns: tuple[tuple[str, ...], ...] | None = None
    memory_limit_gib: float | None = None
    passenger_encoding: str = "od_inventory"
    progress_callback: Callable[["OipCpSatProgressSample"], None] | None = None
    initial_movement_plan: EanMovementPlan | None = None
    initial_fleet_plan: EanFleetPlan | None = None
    initial_passenger_plan: EanPassengerServicePlan | None = None

    def validate(self) -> None:
        if self.time_limit_seconds is not None and self.time_limit_seconds <= 0:
            raise ValueError("OIP CP-SAT time limit must be positive")
        if self.workers <= 0:
            raise ValueError("OIP CP-SAT worker count must be positive")
        if self.memory_limit_gib is not None and self.memory_limit_gib <= 0:
            raise ValueError("OIP CP-SAT memory limit must be positive")
        if self.passenger_encoding not in {"od_inventory", "groups"}:
            raise ValueError("unknown OIP CP-SAT passenger encoding")


@dataclass(frozen=True)
class OipCpSatProgressSample:
    runtime_seconds: float
    objective_value: int
    best_bound: int
    gap: float
    served_passengers: int
    unserved_passengers: int
    journey_time_seconds: float
    active_fleet: int


@dataclass(frozen=True)
class OipCpSatMovementVariables:
    cabin_active: dict[int, cp_model.IntVar]
    station_selected: dict[tuple[int, int], cp_model.IntVar]
    rope_selected: dict[tuple[int, int], cp_model.IntVar]
    previous_service: dict[int, cp_model.IntVar]
    route_active: dict[tuple[int, int], cp_model.IntVar]
    switch_time: dict[tuple[int, int], cp_model.IntVar]
    exit_time: dict[tuple[int, int], cp_model.IntVar]
    wait_time: dict[tuple[int, int], cp_model.IntVar]
    stop: dict[tuple[int, int], cp_model.IntVar]


@dataclass(frozen=True)
class OipCpSatPassengerVariables:
    ride_count: dict[str, cp_model.IntVar]
    ride_used: dict[str, cp_model.IntVar]
    unserved: dict[str, cp_model.IntVar]
    rides: dict[str, Any]
    groups_by_od: dict[tuple[str, str], tuple[Any, ...]]
    board_time: dict[str, cp_model.IntVar]
    journey: cp_model.LinearExpr
    unserved_total: cp_model.LinearExpr
    lexicographic_weight: int
    total_demand: int


@dataclass(frozen=True)
class BuiltOipCpSatModel:
    domain: OipDomain
    model: cp_model.CpModel
    movement: OipCpSatMovementVariables
    passengers: OipCpSatPassengerVariables | None
    passenger_build: EanPassengerCandidateBuildResult | None
    build_seconds: float
    resource_interval_count: int

    @property
    def model_stats(self) -> str:
        return self.model.model_stats()


@dataclass(frozen=True)
class OipCpSatResult:
    status: str
    solver_status: str
    objective_value: int | None
    best_bound: int | None
    gap: float | None
    runtime_seconds: float
    build_seconds: float
    movement_plan: EanMovementPlan | None
    fleet_plan: EanFleetPlan | None
    passenger_plan: EanPassengerServicePlan | None
    served_passengers: int | None
    unserved_passengers: int | None
    journey_time_seconds: float | None
    model_stats: str
    progress_samples: tuple[OipCpSatProgressSample, ...] = ()


def _validate_fixed_stop_patterns(
    domain: OipDomain,
    patterns: tuple[tuple[str, ...], ...] | None,
) -> tuple[frozenset[str], ...] | None:
    if patterns is None:
        return None
    if len(patterns) != domain.k_max:
        raise ValueError("fixed stop patterns must define every candidate cabin")
    station_ids = {timing.station_id for timing in domain.artifact.timings}
    result = tuple(frozenset(pattern) for pattern in patterns)
    for cabin_id, pattern in enumerate(result):
        if not pattern:
            raise ValueError(f"fixed stop pattern for cabin {cabin_id} is empty")
        unknown = pattern - station_ids
        if unknown:
            raise ValueError(
                f"fixed stop pattern for cabin {cabin_id} has unknown stations: "
                f"{sorted(unknown)!r}"
            )
        mandatory = {
            timing.station_id
            for timing in domain.artifact.timings
            if not timing.skip_allowed
        }
        if not mandatory <= pattern:
            raise ValueError(
                f"fixed stop pattern for cabin {cabin_id} skips mandatory stations"
            )
    return result


def build_oip_cp_sat_model(
    domain: OipDomain,
    *,
    passenger_builder: EanPassengerCandidateBuilder | None = None,
    passenger_encoding: str = "od_inventory",
    movement_only: bool = False,
    fixed_stop_patterns: tuple[tuple[str, ...], ...] | None = None,
) -> BuiltOipCpSatModel:
    started = perf_counter()
    domain.validate()
    artifact = domain.artifact
    grid = domain.grid
    model = cp_model.CpModel()
    bounds = build_ean_model_time_bounds(
        artifact, EanTimeBoundFormulation.INITIAL_PLACEMENT_SAFE
    )
    visits_by_cabin: dict[int, list[Any]] = defaultdict(list)
    for visit in artifact.switch_visits:
        visits_by_cabin[visit.cabin_id].append(visit)
    visits_by_cabin = {
        cabin: sorted(visits, key=lambda item: item.visit_index)
        for cabin, visits in visits_by_cabin.items()
    }
    visits_by_key = {
        (visit.cabin_id, visit.visit_index): visit
        for visit in artifact.switch_visits
    }
    patterns = _validate_fixed_stop_patterns(domain, fixed_stop_patterns)
    timing = {item.switch_id: item for item in artifact.timings}
    station_config = {item.station_id: item for item in artifact.config.station_configs}
    phase_count = artifact.initial_placement_parameters.initial_phase_visit_count
    horizon = grid.upper_tick(artifact.config.horizon_seconds)
    operation_end = grid.upper_tick(artifact.config.operational_end_seconds)

    active: dict[int, cp_model.IntVar] = {}
    station: dict[tuple[int, int], cp_model.IntVar] = {}
    rope: dict[tuple[int, int], cp_model.IntVar] = {}
    previous_service: dict[int, cp_model.IntVar] = {}
    route_active: dict[tuple[int, int], cp_model.IntVar] = {}
    switch: dict[tuple[int, int], cp_model.IntVar] = {}
    exit_time: dict[tuple[int, int], cp_model.IntVar] = {}
    wait_time: dict[tuple[int, int], cp_model.IntVar] = {}
    stop: dict[tuple[int, int], cp_model.IntVar] = {}
    reached: dict[tuple[int, int], cp_model.IntVar] = {}

    for cabin_id, visits in visits_by_cabin.items():
        active[cabin_id] = model.new_bool_var(f"cabin_active[{cabin_id}]")
        previous_service[cabin_id] = model.new_bool_var(
            f"initial_previous_service[{cabin_id}]"
        )
        for visit in visits:
            key = cabin_id, visit.visit_index
            visit_bounds = bounds.by_visit[key]
            switch[key] = model.new_int_var(
                grid.signed_lower_tick(visit_bounds.switch_lower),
                grid.signed_upper_tick(visit_bounds.switch_upper),
                f"switch[{cabin_id},{visit.visit_index}]",
            )
            exit_time[key] = model.new_int_var(
                grid.signed_lower_tick(visit_bounds.exit_lower),
                grid.signed_upper_tick(visit_bounds.exit_upper),
                f"exit[{cabin_id},{visit.visit_index}]",
            )
            wait_upper = grid.lower_tick(
                station_config[timing[visit.switch_id].station_id].max_wait_seconds
                or 0.0
            )
            wait_time[key] = model.new_int_var(
                0, wait_upper, f"wait[{cabin_id},{visit.visit_index}]"
            )
            stop[key] = model.new_bool_var(f"stop[{cabin_id},{visit.visit_index}]")
            reached[key] = model.new_bool_var(f"reached[{cabin_id},{visit.visit_index}]")
            route_active[key] = model.new_bool_var(
                f"route_active[{cabin_id},{visit.visit_index}]"
            )
            model.add(switch[key] <= operation_end).only_enforce_if(reached[key])
            model.add(switch[key] >= operation_end + 1).only_enforce_if(
                reached[key].Not()
            )
        for visit in visits[:phase_count]:
            key = cabin_id, visit.visit_index
            station[key] = model.new_bool_var(f"initial_station[{cabin_id},{visit.visit_index}]")
            rope[key] = model.new_bool_var(f"initial_rope[{cabin_id},{visit.visit_index}]")
        model.add(
            sum(station[cabin_id, visit.visit_index] + rope[cabin_id, visit.visit_index]
                for visit in visits[:phase_count])
            == active[cabin_id]
        )
        model.add(previous_service[cabin_id] <= sum(rope[cabin_id, visit.visit_index] for visit in visits[:phase_count]))

        started_literals: list[cp_model.IntVar] = []
        for visit in visits:
            key = cabin_id, visit.visit_index
            if key in station:
                started_literals.extend((station[key], rope[key]))
            # route_active is the exact AND of "a phase was selected by here"
            # and the visit event lies inside the operational horizon.
            model.add(route_active[key] <= sum(started_literals))
            model.add(route_active[key] <= reached[key])
            model.add(route_active[key] >= sum(started_literals) + reached[key] - 1)
            route_timing = timing[visit.switch_id]
            if patterns is not None:
                if route_timing.station_id in patterns[cabin_id]:
                    model.add(stop[key] == route_active[key])
                else:
                    model.add(stop[key] == 0)
            elif domain.operation is OipOperation.ALL_STOP or not route_timing.skip_allowed:
                model.add(stop[key] == route_active[key])
            else:
                model.add(stop[key] <= route_active[key])

            wait_upper = grid.lower_tick(
                station_config[route_timing.station_id].max_wait_seconds or 0.0
            )
            model.add(wait_time[key] <= wait_upper * stop[key])

            service = grid.lower_tick(
                route_timing.entry_to_platform_entry_seconds
                + route_timing.min_platform_entry_to_platform_exit_seconds
                + route_timing.platform_exit_to_exit_switch_seconds
            )
            skip = grid.lower_tick(route_timing.skip_entry_to_exit_switch_seconds)
            model.add(
                exit_time[key] == switch[key] + service + wait_time[key]
            ).only_enforce_if(
                [route_active[key], stop[key]]
            )
            model.add(exit_time[key] == switch[key] + skip).only_enforce_if(
                [route_active[key], stop[key].Not()]
            )

        for previous, current in zip(visits, visits[1:]):
            previous_key = cabin_id, previous.visit_index
            current_key = cabin_id, current.visit_index
            rope_time = grid.lower_tick(timing[previous.switch_id].rope_to_next_switch_seconds)
            model.add(
                switch[current_key] == exit_time[previous_key] + rope_time
            ).only_enforce_if(route_active[previous_key])
            start_at_current = (
                station[current_key] + rope[current_key]
                if current_key in station
                else 0
            )
            model.add(
                route_active[current_key]
                <= route_active[previous_key] + start_at_current
            )

        for phase_index, visit in enumerate(visits[:phase_count]):
            key = cabin_id, visit.visit_index
            model.add(switch[key] <= 0).only_enforce_if(station[key])
            model.add(exit_time[key] >= 0).only_enforce_if(station[key])
            previous_switch = artifact.circulation_state_ids[
                (phase_index - 1) % len(artifact.circulation_state_ids)
            ]
            if patterns is not None:
                previous_station = timing[previous_switch].station_id
                if previous_station in patterns[cabin_id]:
                    model.add(previous_service[cabin_id] >= rope[key])
                else:
                    model.add(previous_service[cabin_id] <= 1 - rope[key])
            if (
                not timing[previous_switch].skip_allowed
                and artifact.initial_boundary_service_resource(previous_switch)
                is not None
            ):
                model.add(previous_service[cabin_id] >= rope[key])
            rope_time = grid.lower_tick(timing[previous_switch].rope_to_next_switch_seconds)
            model.add(switch[key] >= 1).only_enforce_if(rope[key])
            model.add(switch[key] <= rope_time - 1).only_enforce_if(rope[key])
        model.add(switch[cabin_id, visits[-1].visit_index] >= operation_end + 1).only_enforce_if(active[cabin_id])

    cabin_ids = sorted(active)
    for first, second in zip(cabin_ids, cabin_ids[1:]):
        model.add(active[first] >= active[second])
    if domain.fixed_k is not None:
        model.add(sum(active.values()) == domain.fixed_k)
    if patterns is not None:
        groups: dict[frozenset[str], list[int]] = defaultdict(list)
        for cabin_id, mask in enumerate(patterns):
            groups[mask].append(cabin_id)
        for group in groups.values():
            categories = {}
            for cabin_id in group:
                visits = visits_by_cabin[cabin_id][:phase_count]
                categories[cabin_id] = sum(
                    2 * phase_index * station[cabin_id, visit.visit_index]
                    + (2 * phase_index + 1) * rope[cabin_id, visit.visit_index]
                    for phase_index, visit in enumerate(visits)
                )
            for previous, current in zip(group, group[1:]):
                model.add(categories[previous] <= categories[current])

    checkpoint_by_id = {item.id: item for item in artifact.headway_checkpoints}
    intervals_by_resource: dict[str, list[cp_model.IntervalVar]] = defaultdict(list)
    for candidate in artifact.headway_candidates:
        if patterns is not None:
            candidate_station = timing[
                visits_by_key[candidate.cabin_id, candidate.visit_index].switch_id
            ].station_id
            serves = candidate_station in patterns[candidate.cabin_id]
            if (
                candidate.activation_reference is EanActivationReference.SERVE
                and not serves
            ) or (
                candidate.activation_reference is EanActivationReference.SKIP
                and serves
            ):
                continue
        checkpoint = checkpoint_by_id[candidate.checkpoint_id]
        key = candidate.cabin_id, candidate.visit_index
        event = _candidate_time(
            domain, candidate.time_reference, key, switch, exit_time, wait_time,
            visits_by_key, timing
        )
        path_active = _candidate_presence(
            model, candidate.activation_reference, key, route_active, stop
        )
        within = model.new_bool_var(f"headway_within[{candidate.id}]")
        model.add_implication(within, path_active)
        model.add(event <= operation_end).only_enforce_if(within)
        model.add(event >= operation_end + 1).only_enforce_if(
            [path_active, within.Not()]
        )
        rule = artifact.headway_rule_for_checkpoint(checkpoint)
        size = _headway_size(model, domain, rule, stop[key], f"headway_size[{candidate.id}]")
        # At the end-of-platform waiting resource, occupancy begins at the
        # earliest platform exit and lasts through the selected hold.  Other
        # downstream resources are shifted by the actual platform exit.
        if checkpoint.kind is HeadwayCheckpointKind.PLATFORM_EXIT:
            config = station_config[timing[visits_by_key[key].switch_id].station_id]
            if config.waiting_mode.value == "end_of_platform_wait":
                event = event - wait_time[key]
                size = size + wait_time[key]
        end = model.new_int_var(
            -10**12, 10**12, f"headway_end[{candidate.id}]"
        )
        model.add(end == event + size)
        interval = model.new_optional_interval_var(
            event, size, end, within, f"headway_interval[{candidate.id}]"
        )
        intervals_by_resource[candidate.checkpoint_id].append(interval)

    # Rope starts represent a resource occurrence that began before t=0.
    exit_checkpoint_by_switch = {
        item.switch_id: item
        for item in artifact.headway_checkpoints
        if item.kind is HeadwayCheckpointKind.EXIT_SWITCH
    }
    for cabin_id, visits in visits_by_cabin.items():
        for phase_index, visit in enumerate(visits[:phase_count]):
            key = cabin_id, visit.visit_index
            previous_switch = artifact.circulation_state_ids[
                (phase_index - 1) % len(artifact.circulation_state_ids)
            ]
            checkpoint = exit_checkpoint_by_switch[previous_switch]
            rope_time = grid.lower_tick(timing[previous_switch].rope_to_next_switch_seconds)
            prior_exit = switch[key] - rope_time
            rule = artifact.headway_rule_for_checkpoint(checkpoint)
            size = _headway_size(
                model,
                domain,
                rule,
                previous_service[cabin_id],
                f"boundary_headway_size[{cabin_id},{phase_index}]",
            )
            end = model.new_int_var(-10**12, 10**12, f"boundary_headway_end[{cabin_id},{phase_index}]")
            model.add(end == prior_exit + size)
            intervals_by_resource[checkpoint.id].append(
                model.new_optional_interval_var(
                    prior_exit,
                    size,
                    end,
                    rope[key],
                    f"boundary_headway[{cabin_id},{phase_index}]",
                )
            )
            service_resource = artifact.initial_boundary_service_resource(
                previous_switch
            )
            if service_resource is None:
                continue
            service_rule = artifact.headway_rule_for_full_resource(service_resource)
            service_presence = model.new_bool_var(
                f"boundary_service_presence[{cabin_id},{phase_index}]"
            )
            model.add(service_presence <= rope[key])
            model.add(service_presence <= previous_service[cabin_id])
            model.add(
                service_presence >= rope[key] + previous_service[cabin_id] - 1
            )
            service_size = _headway_size(
                model,
                domain,
                service_rule,
                previous_service[cabin_id],
                f"boundary_service_size[{cabin_id},{phase_index}]",
            )
            service_end = model.new_int_var(
                -10**12,
                10**12,
                f"boundary_service_end[{cabin_id},{phase_index}]",
            )
            model.add(service_end == prior_exit + service_size)
            resource_id = f"initial_service::{previous_switch}"
            intervals_by_resource[resource_id].append(
                model.new_optional_interval_var(
                    prior_exit,
                    service_size,
                    service_end,
                    service_presence,
                    f"boundary_service[{cabin_id},{phase_index}]",
                )
            )
            # Every regular traversal of this switch happens after the
            # boundary event represented by ``prior_exit``.  Keep that known
            # order explicit instead of relying only on NoOverlap to infer a
            # disjunction.  Besides strengthening propagation, this mirrors
            # the independent boundary validator: a service cabin already on
            # the incoming rope must clear the retained station mechanism
            # before the first post-boundary STOP may exit it.
            for regular_visit in artifact.switch_visits:
                if regular_visit.switch_id != previous_switch:
                    continue
                regular_key = regular_visit.cabin_id, regular_visit.visit_index
                model.add(
                    prior_exit + service_size <= exit_time[regular_key]
                ).only_enforce_if(
                    [
                        service_presence,
                        route_active[regular_key],
                        stop[regular_key],
                    ]
                )
    for previous_switch in artifact.circulation_state_ids:
        service_resource = artifact.initial_boundary_service_resource(previous_switch)
        if service_resource is None:
            continue
        service_rule = artifact.headway_rule_for_full_resource(service_resource)
        resource_id = f"initial_service::{previous_switch}"
        for visit in artifact.switch_visits:
            if visit.switch_id != previous_switch:
                continue
            if (
                patterns is not None
                and timing[visit.switch_id].station_id
                not in patterns[visit.cabin_id]
            ):
                continue
            key = visit.cabin_id, visit.visit_index
            size = _headway_size(
                model,
                domain,
                service_rule,
                stop[key],
                f"regular_service_size[{visit.cabin_id},{visit.visit_index}]",
            )
            end = model.new_int_var(
                -10**12,
                10**12,
                f"regular_service_end[{visit.cabin_id},{visit.visit_index}]",
            )
            model.add(end == exit_time[key] + size)
            intervals_by_resource[resource_id].append(
                model.new_optional_interval_var(
                    exit_time[key],
                    size,
                    end,
                    stop[key],
                    f"regular_service[{visit.cabin_id},{visit.visit_index}]",
                )
            )
    for intervals in intervals_by_resource.values():
        if len(intervals) > 1:
            model.add_no_overlap(intervals)

    movement = OipCpSatMovementVariables(
        active, station, rope, previous_service, route_active, switch, exit_time,
        wait_time, stop
    )
    passenger_build = None
    passengers = None
    if not movement_only:
        passenger_build = (passenger_builder or EanPassengerCandidateBuilder()).build(
            domain.scenario, artifact
        )
        if passenger_encoding == "od_inventory":
            passengers = _build_inventory_passengers(
                domain, model, movement, passenger_build, visits_by_key, timing
            )
        elif passenger_encoding == "groups":
            passengers = _build_group_passengers(
                domain, model, movement, passenger_build, visits_by_key, timing
            )
        else:
            raise ValueError("unknown OIP CP-SAT passenger encoding")
        model.minimize(
            passengers.lexicographic_weight * passengers.unserved_total
            + passengers.journey
        )
    return BuiltOipCpSatModel(
        domain=domain,
        model=model,
        movement=movement,
        passengers=passengers,
        passenger_build=passenger_build,
        build_seconds=perf_counter() - started,
        resource_interval_count=sum(len(items) for items in intervals_by_resource.values()),
    )


def solve_oip_cp_sat(
    domain: OipDomain,
    config: OipCpSatConfig = OipCpSatConfig(),
    *,
    passenger_builder: EanPassengerCandidateBuilder | None = None,
) -> OipCpSatResult | BuiltOipCpSatModel:
    config.validate()
    total_started = perf_counter()
    built = build_oip_cp_sat_model(
        domain,
        passenger_builder=passenger_builder,
        passenger_encoding=config.passenger_encoding,
        movement_only=config.movement_only,
        fixed_stop_patterns=config.fixed_stop_patterns,
    )
    if config.initial_movement_plan is not None:
        if config.initial_fleet_plan is None or (
            not config.movement_only and config.initial_passenger_plan is None
        ):
            raise ValueError("OIP CP-SAT checkpoint needs movement, fleet, and passengers")
        _apply_oip_cp_sat_hint(
            built,
            config.initial_movement_plan,
            config.initial_fleet_plan,
            config.initial_passenger_plan,
        )
    if config.build_only:
        return built
    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = config.workers
    solver.parameters.random_seed = config.seed
    if config.movement_only:
        solver.parameters.stop_after_first_solution = True
    if config.time_limit_seconds is not None:
        remaining = config.time_limit_seconds - (perf_counter() - total_started)
        if remaining <= 0:
            return OipCpSatResult(
                status="unknown",
                solver_status="BUILD_TIME_LIMIT",
                objective_value=None,
                best_bound=None,
                gap=None,
                runtime_seconds=0.0,
                build_seconds=built.build_seconds,
                movement_plan=None,
                fleet_plan=None,
                passenger_plan=None,
                served_passengers=None,
                unserved_passengers=None,
                journey_time_seconds=None,
                model_stats=built.model_stats,
                progress_samples=(),
            )
        solver.parameters.max_time_in_seconds = remaining
    if config.memory_limit_gib is not None:
        solver.parameters.max_memory_in_mb = int(config.memory_limit_gib * 1024)
    callback = _OipCpSatProgressCallback(built, config.progress_callback)
    started = perf_counter()
    code = solver.solve(built.model, callback)
    runtime = perf_counter() - started
    solver_status = solver.status_name(code)
    feasible = code in (cp_model.FEASIBLE, cp_model.OPTIMAL)
    if not feasible:
        return OipCpSatResult(
            status="infeasible" if code == cp_model.INFEASIBLE else "unknown",
            solver_status=solver_status,
            objective_value=None,
            best_bound=(int(round(solver.best_objective_bound)) if code != cp_model.MODEL_INVALID and not config.movement_only else None),
            gap=None,
            runtime_seconds=runtime,
            build_seconds=built.build_seconds,
            movement_plan=None,
            fleet_plan=None,
            passenger_plan=None,
            served_passengers=None,
            unserved_passengers=None,
            journey_time_seconds=None,
            model_stats=built.model_stats,
            progress_samples=tuple(callback.samples),
        )
    movement_plan, fleet_plan = _extract_movement(built, solver)
    if config.movement_only:
        from .validation import validate_oip_movement_certificate

        validate_oip_movement_certificate(domain, movement_plan, fleet_plan)
        return OipCpSatResult(
            status="feasible", solver_status=solver_status,
            objective_value=None, best_bound=None, gap=None,
            runtime_seconds=runtime, build_seconds=built.build_seconds,
            movement_plan=movement_plan, fleet_plan=fleet_plan,
            passenger_plan=None, served_passengers=None, unserved_passengers=None,
            journey_time_seconds=None, model_stats=built.model_stats,
        )
    passenger_plan = _extract_passengers(built, solver)
    unserved = sum(passenger_plan.unserved_counts_by_demand_group_id.values())
    served = sum(ride.count for ride in passenger_plan.served_rides)
    journey_ticks = int(solver.value(built.passengers.journey))
    objective = int(round(solver.objective_value))
    bound = int(round(solver.best_objective_bound))
    gap = 0.0 if objective == bound else abs(objective - bound) / max(1, abs(objective))
    return OipCpSatResult(
        status="optimal" if code == cp_model.OPTIMAL else "feasible",
        solver_status=solver_status,
        objective_value=objective,
        best_bound=bound,
        gap=gap,
        runtime_seconds=runtime,
        build_seconds=built.build_seconds,
        movement_plan=movement_plan,
        fleet_plan=fleet_plan,
        passenger_plan=passenger_plan,
        served_passengers=served,
        unserved_passengers=unserved,
        journey_time_seconds=domain.grid.seconds(journey_ticks),
        model_stats=built.model_stats,
        progress_samples=tuple(callback.samples),
    )


def _apply_oip_cp_sat_hint(built, movement_plan, fleet_plan, passenger_plan) -> None:
    """Apply a validated portable OIP certificate as a nonbinding CP-SAT hint."""

    active = set(fleet_plan.active_cabin_ids)
    states = {state.cabin_id: state for state in fleet_plan.initial_states}
    visits = {
        (visit.cabin_id, visit.visit_index): visit
        for trajectory in movement_plan.trajectories
        for visit in trajectory.visits
    }
    variables = built.movement
    for cabin_id, variable in variables.cabin_active.items():
        built.model.add_hint(variable, int(cabin_id in active))
    for key, variable in variables.station_selected.items():
        state = states.get(key[0])
        built.model.add_hint(
            variable,
            int(
                state is not None
                and state.visit_index == key[1]
                and state.kind is not EanInitialPlacementStateKind.ROPE
            ),
        )
    for key, variable in variables.rope_selected.items():
        state = states.get(key[0])
        built.model.add_hint(
            variable,
            int(
                state is not None
                and state.visit_index == key[1]
                and state.kind is EanInitialPlacementStateKind.ROPE
            ),
        )
    for cabin_id, variable in variables.previous_service.items():
        state = states.get(cabin_id)
        built.model.add_hint(variable, int(bool(state and state.previous_service)))
    for key, variable in variables.route_active.items():
        built.model.add_hint(variable, int(key in visits))
    for key, visit in visits.items():
        if key not in variables.switch_time:
            raise ValueError("OIP CP-SAT checkpoint contains an unknown visit")
        built.model.add_hint(
            variables.switch_time[key], built.domain.grid.signed_lower_tick(visit.switch_time_seconds)
        )
        built.model.add_hint(
            variables.exit_time[key], built.domain.grid.signed_lower_tick(visit.exit_switch_time_seconds)
        )
        built.model.add_hint(variables.stop[key], int(visit.decision is EanRouteDecision.STOP))
        built.model.add_hint(
            variables.wait_time[key],
            built.domain.grid.lower_tick(max(0.0, visit.wait_seconds)),
        )

    if built.passengers is None:
        return
    groups = {
        group.id: group for group in built.passenger_build.demand_groups
    }
    hinted_counts = {ride_id: 0 for ride_id in built.passengers.ride_count}
    if built.passengers.rides and hasattr(
        next(iter(built.passengers.rides.values())), "demand_group_id"
    ):
        ids = {
            (
                ride.demand_group_id,
                ride.cabin_id,
                ride.board_visit_index,
                ride.alight_visit_index,
            ): ride_id
            for ride_id, ride in built.passengers.rides.items()
        }
        for ride in passenger_plan.served_rides:
            hinted_counts[ids[(ride.demand_group_id, ride.cabin_id, ride.board_visit_index, ride.alight_visit_index)]] += ride.count
    else:
        ids = {
            (
                ride.origin_station_id,
                ride.destination_station_id,
                ride.cabin_id,
                ride.board_visit_index,
                ride.alight_visit_index,
            ): ride_id
            for ride_id, ride in built.passengers.rides.items()
        }
        for ride in passenger_plan.served_rides:
            group = groups[ride.demand_group_id]
            hinted_counts[ids[(group.origin_station_id, group.destination_station_id, ride.cabin_id, ride.board_visit_index, ride.alight_visit_index)]] += ride.count
    for ride_id, value in hinted_counts.items():
        built.model.add_hint(built.passengers.ride_count[ride_id], value)
        built.model.add_hint(built.passengers.ride_used[ride_id], int(value > 0))


class _OipCpSatProgressCallback(cp_model.CpSolverSolutionCallback):
    def __init__(
        self,
        built: BuiltOipCpSatModel,
        progress_callback: Callable[[OipCpSatProgressSample], None] | None,
    ) -> None:
        super().__init__()
        self.built = built
        self.samples: list[OipCpSatProgressSample] = []
        self.progress_callback = progress_callback

    def on_solution_callback(self) -> None:
        passengers = self.built.passengers
        if passengers is None:
            return
        unserved = int(self.value(passengers.unserved_total))
        total = passengers.total_demand
        objective = int(round(self.objective_value))
        bound = int(round(self.best_objective_bound))
        gap = abs(objective - bound) / max(1, abs(objective))
        sample = OipCpSatProgressSample(
                runtime_seconds=self.wall_time,
                objective_value=objective,
                best_bound=bound,
                gap=gap,
                served_passengers=total - unserved,
                unserved_passengers=unserved,
                journey_time_seconds=self.built.domain.grid.seconds(
                    int(self.value(passengers.journey))
                ),
                active_fleet=sum(
                    self.boolean_value(variable)
                    for variable in self.built.movement.cabin_active.values()
                ),
            )
        self.samples.append(sample)
        if self.progress_callback is not None:
            self.progress_callback(sample)


def _candidate_time(domain, reference, key, switch, exit_time, wait_time, visits, timing):
    if reference is EanTimeReference.ENTRY_TIME:
        return switch[key]
    if reference is EanTimeReference.EXIT_SWITCH_TIME:
        return exit_time[key]
    item = timing[visits[key].switch_id]
    if reference is EanTimeReference.PLATFORM_ENTRY_TIME:
        return switch[key] + domain.grid.lower_tick(item.entry_to_platform_entry_seconds)
    if reference is EanTimeReference.PLATFORM_EXIT_TIME:
        return switch[key] + domain.grid.lower_tick(
            item.entry_to_platform_entry_seconds
            + item.min_platform_entry_to_platform_exit_seconds
        ) + wait_time[key]
    raise ValueError(f"unsupported OIP CP-SAT time reference: {reference}")


def _candidate_presence(model, reference, key, route_active, stop):
    if reference is EanActivationReference.SERVE:
        return stop[key]
    if reference is EanActivationReference.ACTIVE:
        return route_active[key]
    if reference is EanActivationReference.SKIP:
        result = model.new_bool_var(f"skip_active[{key[0]},{key[1]}]")
        model.add(result == route_active[key] - stop[key])
        return result
    raise ValueError(f"unsupported OIP CP-SAT activation: {reference}")


def _headway_size(model, domain, rule, leader_stop, name):
    if isinstance(rule, ConstantHeadwayRule):
        return domain.grid.lower_tick(rule.seconds)
    if isinstance(rule, LeaderBehaviorHeadwayRule):
        bypass = domain.grid.lower_tick(rule.bypass_leader_seconds)
        service = domain.grid.lower_tick(rule.service_leader_seconds)
        result = model.new_int_var(min(bypass, service), max(bypass, service), name)
        model.add(result == bypass + (service - bypass) * leader_stop)
        return result
    raise TypeError(f"unsupported OIP headway rule: {rule!r}")


def _build_inventory_passengers(domain, model, movement, passenger_build, visits, timing):
    grid = domain.grid
    horizon = grid.upper_tick(domain.artifact.config.horizon_seconds)
    inventory_end = horizon + 1
    groups = {group.id: group for group in passenger_build.demand_groups}
    groups_by_od_lists: dict[tuple[str, str], list[Any]] = defaultdict(list)
    for group in groups.values():
        groups_by_od_lists[group.origin_station_id, group.destination_station_id].append(group)
    groups_by_od = {
        od: tuple(sorted(items, key=lambda item: (item.release_time_seconds, item.id)))
        for od, items in groups_by_od_lists.items()
    }
    rides = _aggregate_rides(passenger_build, groups)
    intervals: dict[tuple[str, str], list[cp_model.IntervalVar]] = defaultdict(list)
    demands: dict[tuple[str, str], list[Any]] = defaultdict(list)
    for od, od_groups in groups_by_od.items():
        for index, group in enumerate(od_groups):
            release = min(inventory_end, grid.lower_tick(group.release_time_seconds))
            if release > 0:
                intervals[od].append(
                    model.new_fixed_size_interval_var(0, release, f"unreleased[{_od_id(*od)},{index}]")
                )
                demands[od].append(group.count)

    count, used, board_time = {}, {}, {}
    onboard: dict[tuple[int, int], list[cp_model.IntVar]] = defaultdict(list)
    by_alight: dict[tuple[int, int], list[cp_model.IntVar]] = defaultdict(list)
    for index, (ride_id, ride) in enumerate(sorted(rides.items())):
        count[ride_id] = model.new_int_var(0, domain.artifact.config.cabin_capacity, f"ride_count[{index}]")
        used[ride_id] = model.new_bool_var(f"ride_used[{index}]")
        model.add(count[ride_id] >= 1).only_enforce_if(used[ride_id])
        model.add(count[ride_id] == 0).only_enforce_if(used[ride_id].Not())
        board_key = ride.cabin_id, ride.board_visit_index
        alight_key = ride.cabin_id, ride.alight_visit_index
        model.add_implication(used[ride_id], movement.stop[board_key])
        model.add_implication(used[ride_id], movement.stop[alight_key])
        board_offset = grid.lower_tick(
            timing[visits[board_key].switch_id].entry_to_platform_entry_seconds
            + timing[visits[board_key].switch_id].min_platform_entry_to_platform_exit_seconds
        )
        alight_offset = grid.lower_tick(
            timing[visits[alight_key].switch_id].entry_to_platform_entry_seconds
        )
        board = model.new_int_var(0, horizon, f"board_time[{index}]")
        model.add(
            board
            == movement.switch_time[board_key]
            + board_offset
            + movement.wait_time[board_key]
        ).only_enforce_if(used[ride_id])
        model.add(board == 0).only_enforce_if(used[ride_id].Not())
        alight = movement.switch_time[alight_key] + alight_offset
        model.add(alight <= horizon).only_enforce_if(used[ride_id])
        duration = model.new_int_var(1, inventory_end, f"inventory_duration[{index}]")
        model.add(duration == inventory_end - board)
        od = ride.origin_station_id, ride.destination_station_id
        intervals[od].append(
            model.new_optional_interval_var(board, duration, inventory_end, used[ride_id], f"inventory[{index}]")
        )
        demands[od].append(count[ride_id])
        board_time[ride_id] = board
        by_alight[alight_key].append(count[ride_id])
        for visit_index in range(ride.board_visit_index, ride.alight_visit_index):
            onboard[ride.cabin_id, visit_index].append(count[ride_id])

    unserved = {}
    for od, od_groups in groups_by_od.items():
        total = sum(group.count for group in od_groups)
        model.add_cumulative(intervals[od], demands[od], total)
        served = [count[ride_id] for ride_id, ride in rides.items() if (ride.origin_station_id, ride.destination_station_id) == od]
        variable = model.new_int_var(0, total, f"unserved[{_od_id(*od)}]")
        model.add(sum(served) + variable == total)
        unserved[_od_id(*od)] = variable
    for values in onboard.values():
        model.add(sum(values) <= domain.artifact.config.cabin_capacity)

    constant = sum(
        group.count * max(0, horizon - grid.lower_tick(group.release_time_seconds))
        for group in groups.values()
    )
    terms = []
    for event, values in by_alight.items():
        alight_count = model.new_int_var(0, domain.artifact.config.cabin_capacity, f"alight_count[{event}]")
        model.add(alight_count == sum(values))
        alight_offset = grid.lower_tick(timing[visits[event].switch_id].entry_to_platform_entry_seconds)
        event_time_proto = movement.switch_time[event].proto
        switch_lower = int(event_time_proto.domain[0])
        switch_upper = int(event_time_proto.domain[len(event_time_proto.domain) - 1])
        alight_lower = switch_lower + alight_offset
        alight_upper = max(horizon, switch_upper + alight_offset)
        alight_time = model.new_int_var(
            alight_lower,
            alight_upper,
            f"alight_time[{event}]",
        )
        model.add(alight_time == movement.switch_time[event] + alight_offset)
        product = model.new_int_var(
            min(0, domain.artifact.config.cabin_capacity * alight_lower),
            domain.artifact.config.cabin_capacity * alight_upper,
            f"alight_product[{event}]",
        )
        model.add_multiplication_equality(product, [alight_count, alight_time])
        terms.append(product - horizon * alight_count)
    journey = cp_model.LinearExpr.sum(terms) + constant
    unserved_total = cp_model.LinearExpr.sum(list(unserved.values()))
    total_demand = sum(group.count for group in groups.values())
    weight = total_demand * horizon + 1
    if weight * total_demand + total_demand * horizon >= 2**63:
        raise ValueError("OIP lexicographic score exceeds CP-SAT int64 range")
    return OipCpSatPassengerVariables(
        count,
        used,
        unserved,
        rides,
        groups_by_od,
        board_time,
        journey,
        unserved_total,
        weight,
        total_demand,
    )


def _build_group_passengers(domain, model, movement, passenger_build, visits, timing):
    grid = domain.grid
    horizon = grid.upper_tick(domain.artifact.config.horizon_seconds)
    groups = {group.id: group for group in passenger_build.demand_groups}
    groups_by_od_lists: dict[tuple[str, str], list[Any]] = defaultdict(list)
    for group in groups.values():
        groups_by_od_lists[group.origin_station_id, group.destination_station_id].append(group)
    groups_by_od = {
        od: tuple(sorted(items, key=lambda item: (item.release_time_seconds, item.id)))
        for od, items in groups_by_od_lists.items()
    }
    count: dict[str, cp_model.IntVar] = {}
    used: dict[str, cp_model.IntVar] = {}
    board_time: dict[str, cp_model.IntVar] = {}
    by_group: dict[str, list[cp_model.IntVar]] = defaultdict(list)
    onboard: dict[tuple[int, int], list[cp_model.IntVar]] = defaultdict(list)
    by_alight: dict[tuple[int, int], list[cp_model.IntVar]] = defaultdict(list)
    rides = {candidate.id: candidate for candidate in passenger_build.ride_candidates}
    for index, candidate in enumerate(passenger_build.ride_candidates):
        group = groups[candidate.demand_group_id]
        upper = min(group.count, domain.artifact.config.cabin_capacity)
        variable = model.new_int_var(0, upper, f"group_ride_count[{index}]")
        present = model.new_bool_var(f"group_ride_used[{index}]")
        model.add(variable >= 1).only_enforce_if(present)
        model.add(variable == 0).only_enforce_if(present.Not())
        board_key = candidate.cabin_id, candidate.board_visit_index
        alight_key = candidate.cabin_id, candidate.alight_visit_index
        model.add_implication(present, movement.stop[board_key])
        model.add_implication(present, movement.stop[alight_key])
        board_offset = grid.lower_tick(
            timing[visits[board_key].switch_id].entry_to_platform_entry_seconds
            + timing[visits[board_key].switch_id].min_platform_entry_to_platform_exit_seconds
        )
        alight_offset = grid.lower_tick(
            timing[visits[alight_key].switch_id].entry_to_platform_entry_seconds
        )
        board = model.new_int_var(0, horizon, f"group_board_time[{index}]")
        model.add(
            board
            == movement.switch_time[board_key]
            + board_offset
            + movement.wait_time[board_key]
        ).only_enforce_if(present)
        model.add(board == 0).only_enforce_if(present.Not())
        model.add(board >= grid.lower_tick(group.release_time_seconds)).only_enforce_if(present)
        model.add(movement.switch_time[alight_key] + alight_offset <= horizon).only_enforce_if(present)
        count[candidate.id] = variable
        used[candidate.id] = present
        board_time[candidate.id] = board
        by_group[group.id].append(variable)
        by_alight[alight_key].append(variable)
        for visit_index in range(candidate.board_visit_index, candidate.alight_visit_index):
            onboard[candidate.cabin_id, visit_index].append(variable)

    unserved: dict[str, cp_model.IntVar] = {}
    for group in groups.values():
        variable = model.new_int_var(0, group.count, f"group_unserved[{group.id}]")
        model.add(sum(by_group[group.id]) + variable == group.count)
        unserved[group.id] = variable
    for values in onboard.values():
        model.add(sum(values) <= domain.artifact.config.cabin_capacity)

    event_products = []
    for event, values in by_alight.items():
        total = model.new_int_var(0, domain.artifact.config.cabin_capacity, f"group_alight_count[{event}]")
        model.add(total == sum(values))
        offset = grid.lower_tick(timing[visits[event].switch_id].entry_to_platform_entry_seconds)
        proto = movement.switch_time[event].proto
        lower = int(proto.domain[0]) + offset
        upper = int(proto.domain[len(proto.domain) - 1]) + offset
        event_time = model.new_int_var(lower, upper, f"group_alight_time[{event}]")
        model.add(event_time == movement.switch_time[event] + offset)
        product = model.new_int_var(
            min(0, domain.artifact.config.cabin_capacity * lower),
            max(0, domain.artifact.config.cabin_capacity * upper),
            f"group_alight_product[{event}]",
        )
        model.add_multiplication_equality(product, [total, event_time])
        event_products.append(product)
    release_constant = sum(
        group.count * grid.lower_tick(group.release_time_seconds)
        for group in groups.values()
    )
    unserved_total = cp_model.LinearExpr.sum(list(unserved.values()))
    journey = (
        cp_model.LinearExpr.sum(event_products)
        + horizon * unserved_total
        - release_constant
    )
    total_demand = sum(group.count for group in groups.values())
    weight = total_demand * horizon + 1
    if weight * total_demand + total_demand * horizon >= 2**63:
        raise ValueError("OIP lexicographic score exceeds CP-SAT int64 range")
    return OipCpSatPassengerVariables(
        ride_count=count,
        ride_used=used,
        unserved=unserved,
        rides=rides,
        groups_by_od=groups_by_od,
        board_time=board_time,
        journey=journey,
        unserved_total=unserved_total,
        lexicographic_weight=weight,
        total_demand=total_demand,
    )


def _extract_movement(built, solver):
    domain, artifact, grid = built.domain, built.domain.artifact, built.domain.grid
    variables = built.movement
    timing = {item.switch_id: item for item in artifact.timings}
    visits_by_cabin: dict[int, list[Any]] = defaultdict(list)
    for visit in artifact.switch_visits:
        visits_by_cabin[visit.cabin_id].append(visit)
    trajectories = []
    states = []
    active_ids = []
    for cabin_id, visits in sorted(visits_by_cabin.items()):
        visits.sort(key=lambda item: item.visit_index)
        if not solver.boolean_value(variables.cabin_active[cabin_id]):
            trajectories.append(EanCabinTrajectory(cabin_id, ()))
            continue
        active_ids.append(cabin_id)
        selected_key = next(
            key for key in variables.station_selected
            if key[0] == cabin_id and (
                solver.boolean_value(variables.station_selected[key])
                or solver.boolean_value(variables.rope_selected[key])
            )
        )
        is_rope = solver.boolean_value(variables.rope_selected[selected_key])
        selected_visit = next(item for item in visits if item.visit_index == selected_key[1])
        first_tick = solver.value(variables.switch_time[selected_key])
        if is_rope:
            phase_index = selected_key[1]
            previous_switch = artifact.circulation_state_ids[(phase_index - 1) % len(artifact.circulation_state_ids)]
            rope_tick = grid.lower_tick(timing[previous_switch].rope_to_next_switch_seconds)
            states.append(EanInitialPlacementState(
                cabin_id=cabin_id,
                kind=EanInitialPlacementStateKind.ROPE,
                # A rope boundary state is identified by the switch whose
                # exit event happened before t=0.  ``selected_visit`` is the
                # next switch reached after t=0.
                switch_id=previous_switch,
                visit_index=selected_visit.visit_index,
                progress=first_tick / rope_tick,
                previous_event_time_seconds=grid.seconds(first_tick - rope_tick),
                next_event_time_seconds=grid.seconds(first_tick),
                previous_service=solver.boolean_value(variables.previous_service[cabin_id]),
            ))
        else:
            exit_tick = solver.value(variables.exit_time[selected_key])
            stopped = solver.boolean_value(variables.stop[selected_key])
            item = timing[selected_visit.switch_id]
            earliest_platform_exit = first_tick + grid.lower_tick(
                item.entry_to_platform_entry_seconds
                + item.min_platform_entry_to_platform_exit_seconds
            )
            actual_platform_exit = earliest_platform_exit + solver.value(
                variables.wait_time[selected_key]
            )
            waiting_at_boundary = stopped and earliest_platform_exit <= 0 < actual_platform_exit
            previous_tick = earliest_platform_exit if waiting_at_boundary else first_tick
            next_tick = actual_platform_exit if waiting_at_boundary else exit_tick
            duration = max(1, next_tick - previous_tick)
            states.append(EanInitialPlacementState(
                cabin_id=cabin_id,
                kind=(
                    EanInitialPlacementStateKind.PLATFORM_WAIT
                    if waiting_at_boundary
                    else EanInitialPlacementStateKind.SERVICE_ROUTE if stopped
                    else EanInitialPlacementStateKind.SKIP_ROUTE
                ),
                switch_id=selected_visit.switch_id,
                visit_index=selected_visit.visit_index,
                progress=min(1.0, max(0.0, -previous_tick / duration)),
                previous_event_time_seconds=grid.seconds(previous_tick),
                next_event_time_seconds=grid.seconds(next_tick),
            ))
        cabin_visits = []
        for visit in visits:
            key = cabin_id, visit.visit_index
            if not solver.boolean_value(variables.route_active[key]):
                continue
            item = timing[visit.switch_id]
            switch_tick = solver.value(variables.switch_time[key])
            exit_tick = solver.value(variables.exit_time[key])
            wait_tick = solver.value(variables.wait_time[key])
            stopped = solver.boolean_value(variables.stop[key])
            next_tick = exit_tick + grid.lower_tick(item.rope_to_next_switch_seconds)
            cabin_visits.append(EanCabinVisit(
                cabin_id=cabin_id,
                visit_index=visit.visit_index,
                switch_id=visit.switch_id,
                station_id=item.station_id,
                decision=EanRouteDecision.STOP if stopped else EanRouteDecision.SKIP,
                switch_time_seconds=grid.seconds(switch_tick),
                platform_entry_time_seconds=(grid.seconds(switch_tick + grid.lower_tick(item.entry_to_platform_entry_seconds)) if stopped else None),
                platform_exit_time_seconds=(grid.seconds(switch_tick + grid.lower_tick(item.entry_to_platform_entry_seconds + item.min_platform_entry_to_platform_exit_seconds) + wait_tick) if stopped else None),
                exit_switch_time_seconds=grid.seconds(exit_tick),
                next_switch_time_seconds=grid.seconds(next_tick),
                wait_seconds=grid.seconds(wait_tick),
            ))
        trajectories.append(EanCabinTrajectory(cabin_id, tuple(cabin_visits)))
    fleet = EanFleetPlan(
        mode=EanFleetMode.OPTIMIZED_INITIAL_PLACEMENT,
        available_fleet_count=domain.k_max,
        active_cabin_ids=tuple(active_ids),
        inactive_cabin_ids=tuple(item for item in sorted(visits_by_cabin) if item not in active_ids),
        initial_states=tuple(states),
    )
    movement = EanMovementPlan(
        scenario_id=artifact.scenario_id,
        horizon_seconds=artifact.config.horizon_seconds,
        model_end_seconds=artifact.config.operational_end_seconds,
        trajectories=tuple(trajectories),
        horizon_formulation=EanHorizonFormulation.EXACT_TIME_ACTIVATION,
        fleet_mode=EanFleetMode.OPTIMIZED_INITIAL_PLACEMENT,
    )
    fleet.validate()
    movement.validate()
    return movement, fleet


def _extract_passengers(built, solver):
    passengers, grid = built.passengers, built.domain.grid
    remaining = {
        group.id: group.count
        for groups in passengers.groups_by_od.values()
        for group in groups
    }
    served = []
    positive_rides = [
        (
            solver.value(passengers.board_time[ride_id]),
            ride_id,
            solver.value(variable),
        )
        for ride_id, variable in passengers.ride_count.items()
        if solver.value(variable)
    ]
    # OD-inventory variables aggregate release groups.  Decompose them in
    # boarding-time order so later rides cannot consume early released demand
    # before an earlier ride is reconstructed.  The cumulative constraints in
    # the model guarantee that this earliest-release greedy matching exists.
    positive_rides.sort(key=lambda item: (item[0], item[1]))
    for board_tick, ride_id, count in positive_rides:
        ride = passengers.rides[ride_id]
        if hasattr(ride, "demand_group_id"):
            group = next(
                group
                for groups in passengers.groups_by_od.values()
                for group in groups
                if group.id == ride.demand_group_id
            )
            alight_key = ride.cabin_id, ride.alight_visit_index
            visit = next(
                item
                for item in built.domain.artifact.switch_visits
                if (item.cabin_id, item.visit_index) == alight_key
            )
            timing = next(
                item
                for item in built.domain.artifact.timings
                if item.switch_id == visit.switch_id
            )
            alight_tick = solver.value(built.movement.switch_time[alight_key]) + grid.lower_tick(
                timing.entry_to_platform_entry_seconds
            )
            served.append(
                EanServedRideGroup(
                    demand_group_id=group.id,
                    cabin_id=ride.cabin_id,
                    board_visit_index=ride.board_visit_index,
                    alight_visit_index=ride.alight_visit_index,
                    count=count,
                    boarding_time_seconds=grid.seconds(board_tick),
                    alighting_time_seconds=grid.seconds(alight_tick),
                )
            )
            remaining[group.id] -= count
            continue
        needed = count
        for group in passengers.groups_by_od[ride.origin_station_id, ride.destination_station_id]:
            if needed == 0 or grid.lower_tick(group.release_time_seconds) > board_tick:
                break
            assigned = min(needed, remaining[group.id])
            if not assigned:
                continue
            alight_key = ride.cabin_id, ride.alight_visit_index
            visit = next(item for item in built.domain.artifact.switch_visits if (item.cabin_id, item.visit_index) == alight_key)
            timing = next(item for item in built.domain.artifact.timings if item.switch_id == visit.switch_id)
            alight_tick = solver.value(built.movement.switch_time[alight_key]) + grid.lower_tick(timing.entry_to_platform_entry_seconds)
            served.append(EanServedRideGroup(
                demand_group_id=group.id,
                cabin_id=ride.cabin_id,
                board_visit_index=ride.board_visit_index,
                alight_visit_index=ride.alight_visit_index,
                count=assigned,
                boarding_time_seconds=grid.seconds(board_tick),
                alighting_time_seconds=grid.seconds(alight_tick),
            ))
            remaining[group.id] -= assigned
            needed -= assigned
        if needed:
            raise ValueError("OIP inventory extraction boards unreleased passengers")
    plan = EanPassengerServicePlan(
        scenario_id=built.domain.artifact.scenario_id,
        horizon_seconds=built.domain.artifact.config.horizon_seconds,
        served_rides=tuple(served),
        unserved_counts_by_demand_group_id=remaining,
    )
    plan.validate()
    return plan
