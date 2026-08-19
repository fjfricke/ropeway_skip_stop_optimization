from __future__ import annotations

from dataclasses import dataclass
import math

from ropeway_skip_stop_optimization.models import Scenario
from ropeway_skip_stop_optimization.optimization.ddd.models import (
    DddRouteDecision,
    DddRouteOption,
)
from ropeway_skip_stop_optimization.optimization.ddd.reference import (
    DddReferenceHorizonCoverageError,
    DddReferenceResourceConflictError,
    DddReferenceResourceOccurrence,
    DddReferenceTrajectory,
    DddReferenceVisit,
    find_ddd_reference_conflicts,
)
from ropeway_skip_stop_optimization.optimization.ddd.artifact_adapter import (
    EanArtifactToDddMovementProblemAdapter,
)
from ropeway_skip_stop_optimization.optimization.ddd.route_topology import (
    deterministic_route_state_ids,
    unique_stop_route_option,
)
from ropeway_skip_stop_optimization.optimization.ddd.trajectory_problem import (
    DddReservoirDispatchCardinalityMode,
    DddReservoirTrajectoryKind,
    DddReservoirTrajectoryStartDomain,
    DddReservoirTrajectoryState,
    DddTrajectoryProblem,
)
from ropeway_skip_stop_optimization.optimization.ddd.time_ticks import (
    DDD_TIME_TICK_SECONDS,
    ddd_quantize_time_seconds,
)
from ropeway_skip_stop_optimization.optimization.ean.builders.passenger_builder import (
    EanPassengerCandidateBuildResult,
    expand_demands_to_ean_groups,
)
from ropeway_skip_stop_optimization.optimization.ean.artifact import EanBuildArtifact
from ropeway_skip_stop_optimization.optimization.ean.formulation_config import (
    EanHorizonFormulation,
)
from ropeway_skip_stop_optimization.optimization.ean.models import (
    EanFleetMode,
    EanRideCandidate,
)
from ropeway_skip_stop_optimization.optimization.ean.plan import (
    EanCabinTrajectory,
    EanCabinVisit,
    EanMovementPlan,
    EanRouteDecision,
)


DDD_RESERVOIR_TIME_TOLERANCE_SECONDS = 1e-9


def ddd_reservoir_covers_horizon(
    final_event_time_seconds: float,
    operational_end_seconds: float,
    *,
    tolerance_seconds: float = DDD_RESERVOIR_TIME_TOLERANCE_SECONDS,
) -> bool:
    """Accept a continuously reconstructed terminal event within tolerance."""

    return final_event_time_seconds + tolerance_seconds >= operational_end_seconds


def build_ddd_reservoir_dispatch_anchors(
    domain: DddReservoirTrajectoryStartDomain,
    *,
    anchor_count: int,
) -> tuple[float, ...]:
    """Return deterministic finite-grid anchors used only for primal pricing."""

    if anchor_count <= 0:
        return ()
    if anchor_count == 1:
        return (-domain.warmup_seconds,)
    latest = -DDD_TIME_TICK_SECONDS
    step = (domain.warmup_seconds + latest) / (anchor_count - 1)
    anchors = {
        ddd_quantize_time_seconds(-domain.warmup_seconds + index * step)
        for index in range(anchor_count)
    }
    anchors.update((-domain.warmup_seconds, latest))
    return tuple(
        sorted(
            value
            for value in anchors
            if -domain.warmup_seconds <= value < 0.0
        )
    )


@dataclass(frozen=True)
class DddReservoirFleetPlan:
    available_cabin_ids: tuple[int, ...]
    dispatched_cabin_ids: tuple[int, ...]
    stored_cabin_ids: tuple[int, ...]
    dispatch_time_seconds_by_cabin_id: dict[int, float]

    @property
    def available_fleet_count(self) -> int:
        return len(self.available_cabin_ids)

    @property
    def dispatched_fleet_count(self) -> int:
        return len(self.dispatched_cabin_ids)

    @property
    def peak_active_fleet_count(self) -> int:
        # Version 1 has no removal, hence every dispatched cabin remains active.
        return self.dispatched_fleet_count

    def validate(self) -> None:
        if self.available_cabin_ids != tuple(range(len(self.available_cabin_ids))):
            raise ValueError("reservoir available cabins must be the canonical prefix")
        if tuple(sorted(set(self.dispatched_cabin_ids))) != self.dispatched_cabin_ids:
            raise ValueError("reservoir dispatched cabins are not normalized")
        if tuple(sorted(set(self.stored_cabin_ids))) != self.stored_cabin_ids:
            raise ValueError("reservoir stored cabins are not normalized")
        available = set(self.available_cabin_ids)
        dispatched = set(self.dispatched_cabin_ids)
        stored = set(self.stored_cabin_ids)
        if dispatched & stored or dispatched | stored != available:
            raise ValueError("reservoir dispatched/stored partition is invalid")
        if dispatched != set(self.dispatch_time_seconds_by_cabin_id):
            raise ValueError("reservoir dispatch times do not cover dispatched cabins")
        if any(
            not math.isfinite(value) or value >= 0.0
            for value in self.dispatch_time_seconds_by_cabin_id.values()
        ):
            raise ValueError("reservoir dispatch times must be finite and negative")


def build_ddd_stored_reservoir_trajectory(
    *,
    cabin_id: int,
    domain: DddReservoirTrajectoryStartDomain,
) -> DddReferenceTrajectory:
    if domain.cardinality_mode is DddReservoirDispatchCardinalityMode.EXACT:
        raise ValueError("exact-dispatch reservoir domain has no stored column")
    if cabin_id not in domain.cabin_ids:
        raise ValueError("stored reservoir cabin is outside the domain")
    return DddReferenceTrajectory(
        cabin_id=cabin_id,
        visits=(),
        reservoir_state=DddReservoirTrajectoryState(
            kind=DddReservoirTrajectoryKind.STORED,
            interface_id=domain.boundary.id,
        ),
    )


def build_ddd_reservoir_all_stop_seed(
    problem: DddTrajectoryProblem,
) -> tuple[DddReferenceTrajectory, ...]:
    """Construct a deterministic headway-spaced dispatch prefix."""

    problem.validate()
    if not isinstance(problem.start_domain, DddReservoirTrajectoryStartDomain):
        raise ValueError("reservoir seed needs a reservoir start domain")
    domain = problem.start_domain
    movement = problem.structural_movement_problem
    dispatch_spacing = max(
        resource.maximum_headway_seconds or resource.headway_seconds
        for resource in movement.resources
    )
    selected: list[DddReferenceTrajectory] = []
    pool: list[DddReferenceTrajectory] = []
    dispatch_prefix_open = True
    for cabin_id in domain.cabin_ids:
        dispatch_time = -domain.warmup_seconds + cabin_id * dispatch_spacing
        candidate: DddReferenceTrajectory | None = None
        if dispatch_prefix_open and dispatch_time < -DDD_RESERVOIR_TIME_TOLERANCE_SECONDS:
            state_id = domain.boundary.entry_state_id
            switch_time = dispatch_time
            route_ids = []
            for _ in range(domain.maximum_visit_count):
                option = unique_stop_route_option(
                    movement,
                    state_id,
                    error_context="reservoir all-stop seed",
                )
                route_ids.append(option.id)
                state_id = option.to_state_id
                switch_time += option.duration_seconds
                if switch_time > movement.operational_end_seconds:
                    break
            try:
                candidate = build_ddd_reservoir_reference_trajectory(
                    problem=problem,
                    cabin_id=cabin_id,
                    dispatch_time_seconds=dispatch_time,
                    route_option_ids=tuple(route_ids),
                )
                conflicts = find_ddd_reference_conflicts(
                    tuple(
                        occurrence
                        for item in (*selected, candidate)
                        for occurrence in item.resource_occurrences
                    ),
                    movement,
                )
                if conflicts:
                    raise DddReferenceResourceConflictError(str(conflicts[0]))
            except (ValueError, DddReferenceResourceConflictError):
                candidate = None
        stored = None
        if domain.cardinality_mode is DddReservoirDispatchCardinalityMode.OPTIONAL:
            stored = build_ddd_stored_reservoir_trajectory(
                cabin_id=cabin_id,
                domain=domain,
            )
            pool.append(stored)
        if candidate is None:
            dispatch_prefix_open = False
            if domain.cardinality_mode is DddReservoirDispatchCardinalityMode.EXACT:
                raise ValueError(
                    "warm-up cannot construct a complete exact-dispatch all-stop seed"
                )
            assert stored is not None
            selected.append(stored)
        else:
            selected.append(candidate)
            pool.append(candidate)
    validate_ddd_reservoir_solution(problem, tuple(selected))
    return tuple(pool)


def build_ddd_reservoir_neighbor_k_initial_pool(
    *,
    target_problem: DddTrajectoryProblem,
    source_domain: DddReservoirTrajectoryStartDomain,
    source_incumbent_trajectories: tuple[DddReferenceTrajectory, ...],
) -> tuple[DddReferenceTrajectory, ...]:
    """Transfer a validated neighboring-K incumbent into a fresh target pool."""

    target_problem.validate()
    target_domain = target_problem.start_domain
    if not isinstance(target_domain, DddReservoirTrajectoryStartDomain):
        raise ValueError("neighbor-K warm start requires a reservoir target")
    source_domain.validate(target_problem.movement_core)
    if source_domain.boundary != target_domain.boundary:
        raise ValueError("neighbor-K reservoir boundary does not match the target")
    if not math.isclose(
        source_domain.warmup_seconds,
        target_domain.warmup_seconds,
        rel_tol=0.0,
        abs_tol=DDD_RESERVOIR_TIME_TOLERANCE_SECONDS,
    ):
        raise ValueError("neighbor-K reservoir warm-up does not match the target")
    if source_domain.maximum_visit_count != target_domain.maximum_visit_count:
        raise ValueError("neighbor-K reservoir visit domain does not match the target")

    source_cabin_ids = {item.cabin_id for item in source_incumbent_trajectories}
    if source_cabin_ids != set(source_domain.cabin_ids):
        raise ValueError(
            "neighbor-K source trajectories must contain exactly one incumbent "
            "trajectory per source cabin"
        )
    if len(source_incumbent_trajectories) != len(source_cabin_ids):
        raise ValueError("neighbor-K source incumbent contains duplicate cabins")

    target_cabin_ids = set(target_domain.cabin_ids)
    transferred = tuple(
        trajectory
        for trajectory in source_incumbent_trajectories
        if trajectory.cabin_id in target_cabin_ids
    )
    for trajectory in transferred:
        validate_ddd_reservoir_reference_trajectory(target_problem, trajectory)

    candidates = (*build_ddd_reservoir_all_stop_seed(target_problem), *transferred)
    pool = []
    for trajectory in candidates:
        if trajectory not in pool:
            pool.append(trajectory)
    if {item.cabin_id for item in pool} != target_cabin_ids:
        raise RuntimeError("neighbor-K initial pool does not cover the target fleet")
    return tuple(sorted(pool, key=lambda item: (item.cabin_id, repr(item))))


def build_ddd_reservoir_reference_trajectory(
    *,
    problem: DddTrajectoryProblem,
    cabin_id: int,
    dispatch_time_seconds: float,
    route_option_ids: tuple[str, ...],
    wait_seconds_by_visit: tuple[float, ...] = (),
    tolerance_seconds: float = DDD_RESERVOIR_TIME_TOLERANCE_SECONDS,
) -> DddReferenceTrajectory:
    problem.validate()
    if not isinstance(problem.start_domain, DddReservoirTrajectoryStartDomain):
        raise ValueError("reservoir trajectory needs a reservoir start domain")
    domain = problem.start_domain
    if cabin_id not in domain.cabin_ids:
        raise ValueError("reservoir trajectory cabin is outside the domain")
    if not math.isfinite(dispatch_time_seconds) or not (
        -domain.warmup_seconds - tolerance_seconds
        <= dispatch_time_seconds
        < -tolerance_seconds
    ):
        raise ValueError("reservoir dispatch time lies outside [-W, 0)")
    if not route_option_ids:
        raise ValueError("dispatched reservoir trajectory needs a route sequence")
    if wait_seconds_by_visit and len(wait_seconds_by_visit) != len(route_option_ids):
        raise ValueError("reservoir wait sequence must match the route sequence")

    core = problem.movement_core
    options_by_id = {option.id: option for option in core.route_options}
    expected_state = domain.boundary.entry_state_id
    switch_time = dispatch_time_seconds
    visits = []
    for visit_index, option_id in enumerate(route_option_ids):
        option = options_by_id.get(option_id)
        if option is None or option.from_state_id != expected_state:
            raise ValueError("reservoir route sequence is not a valid state path")
        if visit_index == 0 and (
            domain.boundary.allowed_first_route_option_ids
            and option.id not in domain.boundary.allowed_first_route_option_ids
        ):
            raise ValueError("reservoir trajectory uses a forbidden first route")
        if switch_time < -tolerance_seconds and option.decision is not DddRouteDecision.STOP:
            raise ValueError("reservoir warm-up visits must use the common all-stop policy")
        wait_seconds = (
            wait_seconds_by_visit[visit_index] if wait_seconds_by_visit else 0.0
        )
        _validate_visit_wait(
            problem=problem,
            option=option,
            switch_time_seconds=switch_time,
            wait_seconds=wait_seconds,
            tolerance_seconds=tolerance_seconds,
        )
        next_switch_time = switch_time + option.duration_seconds + wait_seconds
        visit = DddReferenceVisit(
            cabin_id=cabin_id,
            visit_index=visit_index,
            state_id=option.from_state_id,
            route_option_id=option.id,
            decision=option.decision,
            switch_time_seconds=switch_time,
            next_switch_time_seconds=next_switch_time,
            resource_occurrences=tuple(
                DddReferenceResourceOccurrence(
                    resource_id=usage.resource_id,
                    cabin_id=cabin_id,
                    visit_index=visit_index,
                    leader_clear_time_seconds=(
                        switch_time
                        + usage.leader_clear_offset_with_wait(wait_seconds)
                    ),
                    follower_enter_time_seconds=(
                        switch_time
                        + usage.follower_enter_offset_with_wait(wait_seconds)
                    ),
                    separation_after_seconds=usage.separation_after_seconds,
                    quantize_times=False,
                )
                for usage in option.resource_usages
                if switch_time
                + usage.follower_enter_offset_with_wait(wait_seconds)
                <= core.operational_end_seconds + tolerance_seconds
            ),
            wait_seconds=wait_seconds,
            quantize_times=False,
        )
        visits.append(visit)
        expected_state = option.to_state_id
        switch_time = visit.next_switch_time_seconds
        if ddd_reservoir_covers_horizon(
            switch_time,
            core.operational_end_seconds,
            tolerance_seconds=tolerance_seconds,
        ):
            break
    if not ddd_reservoir_covers_horizon(
        switch_time,
        core.operational_end_seconds,
        tolerance_seconds=tolerance_seconds,
    ):
        raise DddReferenceHorizonCoverageError(
            "reservoir trajectory ends before clearing the operational horizon"
        )
    if len(visits) > domain.maximum_visit_count:
        raise ValueError("reservoir trajectory exceeds its visit bound")
    result = DddReferenceTrajectory(
        cabin_id=cabin_id,
        visits=tuple(visits),
        boundary_resource_occurrences=_reservoir_dispatch_occurrences(
            domain=domain,
            cabin_id=cabin_id,
            dispatch_time_seconds=dispatch_time_seconds,
        ),
        reservoir_state=DddReservoirTrajectoryState(
            kind=DddReservoirTrajectoryKind.DISPATCHED,
            interface_id=domain.boundary.id,
            dispatch_time_seconds=dispatch_time_seconds,
        ),
    )
    validate_ddd_reservoir_reference_trajectory(
        problem,
        result,
        tolerance_seconds=tolerance_seconds,
    )
    return result


def validate_ddd_reservoir_reference_trajectory(
    problem: DddTrajectoryProblem,
    trajectory: DddReferenceTrajectory,
    *,
    tolerance_seconds: float = DDD_RESERVOIR_TIME_TOLERANCE_SECONDS,
) -> None:
    problem.validate()
    if not isinstance(problem.start_domain, DddReservoirTrajectoryStartDomain):
        raise ValueError("reservoir validation needs a reservoir domain")
    domain = problem.start_domain
    state = trajectory.reservoir_state
    if state is None:
        raise ValueError("reservoir trajectory has no reservoir state")
    if trajectory.initial_state is not None:
        raise ValueError("reservoir trajectory cannot contain an OIP initial state")
    state.validate()
    if trajectory.cabin_id not in domain.cabin_ids:
        raise ValueError("reservoir trajectory cabin is outside the domain")
    if state.interface_id != domain.boundary.id:
        raise ValueError("reservoir trajectory uses another interface")
    if state.kind is DddReservoirTrajectoryKind.STORED:
        if domain.cardinality_mode is DddReservoirDispatchCardinalityMode.EXACT:
            raise ValueError("exact-dispatch reservoir cabin cannot remain stored")
        if trajectory.visits or trajectory.resource_occurrences:
            raise ValueError("stored reservoir trajectory must be physically empty")
        return
    if state.dispatch_time_seconds is None or not trajectory.visits:
        raise ValueError("dispatched reservoir trajectory is incomplete")
    if not (
        -domain.warmup_seconds - tolerance_seconds
        <= state.dispatch_time_seconds
        < -tolerance_seconds
    ):
        raise ValueError("reservoir dispatch time lies outside [-W, 0)")
    options_by_id = {option.id: option for option in problem.movement_core.route_options}
    expected_state = domain.boundary.entry_state_id
    expected_time = state.dispatch_time_seconds
    for visit_index, visit in enumerate(trajectory.visits):
        if visit.cabin_id != trajectory.cabin_id or visit.visit_index != visit_index:
            raise ValueError("reservoir visit identity is inconsistent")
        if visit.state_id != expected_state or not math.isclose(
            visit.switch_time_seconds,
            expected_time,
            rel_tol=0.0,
            abs_tol=tolerance_seconds,
        ):
            raise ValueError("reservoir visit path or time chain is inconsistent")
        option = options_by_id.get(visit.route_option_id)
        if option is None or option.from_state_id != expected_state:
            raise ValueError("reservoir visit references an invalid route")
        if visit.decision is not option.decision:
            raise ValueError("reservoir visit decision does not match its route")
        if visit_index == 0 and (
            domain.boundary.allowed_first_route_option_ids
            and option.id not in domain.boundary.allowed_first_route_option_ids
        ):
            raise ValueError("reservoir trajectory uses a forbidden first route")
        if expected_time < -tolerance_seconds and option.decision is not DddRouteDecision.STOP:
            raise ValueError("reservoir warm-up visits must be all-stop")
        _validate_visit_wait(
            problem=problem,
            option=option,
            switch_time_seconds=expected_time,
            wait_seconds=visit.wait_seconds,
            tolerance_seconds=tolerance_seconds,
        )
        expected_occurrences = tuple(
            DddReferenceResourceOccurrence(
                resource_id=usage.resource_id,
                cabin_id=trajectory.cabin_id,
                visit_index=visit_index,
                leader_clear_time_seconds=(
                    expected_time
                    + usage.leader_clear_offset_with_wait(visit.wait_seconds)
                ),
                follower_enter_time_seconds=(
                    expected_time
                    + usage.follower_enter_offset_with_wait(visit.wait_seconds)
                ),
                separation_after_seconds=usage.separation_after_seconds,
                quantize_times=False,
            )
            for usage in option.resource_usages
            if (
                expected_time
                + usage.follower_enter_offset_with_wait(visit.wait_seconds)
                <= problem.movement_core.operational_end_seconds + tolerance_seconds
            )
        )
        if not _resource_occurrences_match(
            visit.resource_occurrences,
            expected_occurrences,
            tolerance_seconds=tolerance_seconds,
        ):
            raise ValueError("reservoir visit resource occurrences are inconsistent")
        expected_time += option.duration_seconds + visit.wait_seconds
        if not math.isclose(
            visit.next_switch_time_seconds,
            expected_time,
            rel_tol=0.0,
            abs_tol=tolerance_seconds,
        ):
            raise ValueError("reservoir visit next-switch time is inconsistent")
        expected_state = option.to_state_id
    if not ddd_reservoir_covers_horizon(
        expected_time,
        problem.movement_core.operational_end_seconds,
        tolerance_seconds=tolerance_seconds,
    ):
        raise DddReferenceHorizonCoverageError(
            "reservoir trajectory does not clear the operational horizon"
        )
    if len(trajectory.visits) > domain.maximum_visit_count:
        raise ValueError("reservoir trajectory exceeds its visit bound")
    expected_dispatch_occurrences = _reservoir_dispatch_occurrences(
        domain=domain,
        cabin_id=trajectory.cabin_id,
        dispatch_time_seconds=state.dispatch_time_seconds,
    )
    if not _resource_occurrences_match(
        trajectory.boundary_resource_occurrences,
        expected_dispatch_occurrences,
        tolerance_seconds=tolerance_seconds,
    ):
        raise ValueError(
            "reservoir trajectory dispatch-resource occurrences are inconsistent"
        )
    conflicts = find_ddd_reference_conflicts(
        trajectory.resource_occurrences,
        problem.structural_movement_problem,
        tolerance_seconds=tolerance_seconds,
    )
    if conflicts:
        raise DddReferenceResourceConflictError(
            f"reservoir trajectory has a self-conflict: {conflicts[0]}"
        )


def validate_ddd_reservoir_solution(
    problem: DddTrajectoryProblem,
    trajectories: tuple[DddReferenceTrajectory, ...],
    *,
    tolerance_seconds: float = DDD_RESERVOIR_TIME_TOLERANCE_SECONDS,
) -> DddReservoirFleetPlan:
    if not isinstance(problem.start_domain, DddReservoirTrajectoryStartDomain):
        raise ValueError("reservoir solution validation needs a reservoir domain")
    domain = problem.start_domain
    selected_cabin_ids = tuple(item.cabin_id for item in trajectories)
    if (
        len(selected_cabin_ids) != len(domain.cabin_ids)
        or set(selected_cabin_ids) != set(domain.cabin_ids)
    ):
        raise ValueError("reservoir solution must select one column per available cabin")
    for trajectory in trajectories:
        validate_ddd_reservoir_reference_trajectory(
            problem, trajectory, tolerance_seconds=tolerance_seconds
        )
    conflicts = find_ddd_reference_conflicts(
        tuple(
            occurrence
            for trajectory in trajectories
            for occurrence in trajectory.resource_occurrences
        ),
        problem.structural_movement_problem,
        tolerance_seconds=tolerance_seconds,
    )
    if conflicts:
        raise DddReferenceResourceConflictError(
            f"reservoir solution has a resource conflict: {conflicts[0]}"
        )
    dispatched = tuple(
        sorted(
            item.cabin_id
            for item in trajectories
            if item.reservoir_state is not None
            and item.reservoir_state.kind is DddReservoirTrajectoryKind.DISPATCHED
        )
    )
    if dispatched and dispatched != tuple(range(len(dispatched))):
        raise ValueError("reservoir dispatched cabins must form a canonical prefix")
    stored = tuple(item for item in domain.cabin_ids if item not in set(dispatched))
    if (
        domain.cardinality_mode is DddReservoirDispatchCardinalityMode.EXACT
        and stored
    ):
        raise ValueError("exact-dispatch reservoir solution leaves cabins stored")
    result = DddReservoirFleetPlan(
        available_cabin_ids=domain.cabin_ids,
        dispatched_cabin_ids=dispatched,
        stored_cabin_ids=stored,
        dispatch_time_seconds_by_cabin_id={
            item.cabin_id: float(item.reservoir_state.dispatch_time_seconds)
            for item in trajectories
            if item.reservoir_state is not None
            and item.reservoir_state.kind is DddReservoirTrajectoryKind.DISPATCHED
            and item.reservoir_state.dispatch_time_seconds is not None
        },
    )
    result.validate()
    return result


def validate_ddd_reservoir_plan_against_artifact(
    *,
    problem: DddTrajectoryProblem,
    artifact: EanBuildArtifact,
    trajectories: tuple[DddReferenceTrajectory, ...],
    tolerance_seconds: float = DDD_RESERVOIR_TIME_TOLERANCE_SECONDS,
) -> tuple[EanMovementPlan, DddReservoirFleetPlan]:
    """Validate a reservoir incumbent against its complete physical network core.

    Regular resources use the exact effective policy.  Dominated resources remain
    covered by the artifact's checked dominance certificates; unlike OIP there is
    no unknown pre-horizon cabin occurrence because the physical network is empty
    before the first explicit dispatch.
    """

    artifact.validate()
    problem.validate()
    expected_core = EanArtifactToDddMovementProblemAdapter(
        tolerance_seconds=tolerance_seconds,
    ).build_movement_core(artifact)
    if problem.movement_core != expected_core:
        raise ValueError(
            "reservoir trajectory problem does not match the supplied EAN artifact"
        )
    fleet_plan = validate_ddd_reservoir_solution(
        problem,
        trajectories,
        tolerance_seconds=tolerance_seconds,
    )
    movement_plan = build_ean_reservoir_movement_plan(
        problem=problem,
        trajectories=trajectories,
    )
    if movement_plan.scenario_id != artifact.scenario_id:
        raise ValueError("reservoir movement plan scenario does not match artifact")
    if not math.isclose(
        movement_plan.horizon_seconds,
        artifact.config.passenger_service_end_seconds,
        rel_tol=0.0,
        abs_tol=tolerance_seconds,
    ) or not math.isclose(
        movement_plan.model_end_seconds,
        artifact.config.operational_end_seconds,
        rel_tol=0.0,
        abs_tol=tolerance_seconds,
    ):
        raise ValueError("reservoir movement plan horizon does not match artifact")
    movement_plan.validate()
    return movement_plan, fleet_plan


def build_ddd_reservoir_passenger_candidates(
    *,
    scenario: Scenario,
    problem: DddTrajectoryProblem,
) -> EanPassengerCandidateBuildResult:
    """Build a conservative local-visit Passenger universe for reservoir paths."""

    problem.validate()
    if not isinstance(problem.start_domain, DddReservoirTrajectoryStartDomain):
        raise ValueError("reservoir Passenger candidates need a reservoir domain")
    domain = problem.start_domain
    movement = problem.structural_movement_problem
    states = deterministic_route_state_ids(
        movement,
        start_state_id=domain.boundary.entry_state_id,
        max_visit_count=domain.maximum_visit_count,
        error_context="reservoir Passenger candidates",
    )
    station_by_visit = []
    minimum_duration_by_visit = []
    for state_id in states:
        options = movement.route_options_by_state_id[state_id]
        station_ids = {option.station_id for option in options}
        if len(station_ids) != 1:
            raise ValueError("reservoir state maps to multiple Passenger stations")
        station_by_visit.append(next(iter(station_ids)))
        minimum_duration_by_visit.append(min(option.duration_seconds for option in options))
    groups = expand_demands_to_ean_groups(scenario)
    candidates = []
    for group in groups:
        for cabin_id in domain.cabin_ids:
            for board_index, station_id in enumerate(station_by_visit[:-1]):
                if station_id != group.origin_station_id:
                    continue
                for alight_index in range(board_index + 1, len(station_by_visit)):
                    if station_by_visit[alight_index] != group.destination_station_id:
                        continue
                    earliest_alight = -domain.warmup_seconds + sum(
                        minimum_duration_by_visit[:alight_index]
                    )
                    if earliest_alight > movement.passenger_service_end_seconds:
                        continue
                    candidates.append(
                        EanRideCandidate(
                            id=(
                                f"reservoir_ride::{group.id}::cabin_{cabin_id}::"
                                f"board_{board_index}::alight_{alight_index}"
                            ),
                            demand_group_id=group.id,
                            cabin_id=cabin_id,
                            board_visit_index=board_index,
                            alight_visit_index=alight_index,
                        )
                    )
    result = EanPassengerCandidateBuildResult(
        demand_groups=groups,
        ride_candidates=tuple(candidates),
    )
    result.validate()
    return result


def build_ean_reservoir_trajectory(
    *,
    problem: DddTrajectoryProblem,
    trajectory: DddReferenceTrajectory,
) -> EanCabinTrajectory:
    validate_ddd_reservoir_reference_trajectory(problem, trajectory)
    if not trajectory.visits:
        return EanCabinTrajectory(cabin_id=trajectory.cabin_id, visits=())
    options_by_id = {
        option.id: option for option in problem.movement_core.route_options
    }
    visits = []
    for visit in trajectory.visits:
        option = options_by_id[visit.route_option_id]
        is_stop = option.decision is DddRouteDecision.STOP
        visits.append(
            EanCabinVisit(
                cabin_id=trajectory.cabin_id,
                visit_index=visit.visit_index,
                switch_id=visit.state_id,
                station_id=option.station_id,
                decision=(EanRouteDecision.STOP if is_stop else EanRouteDecision.SKIP),
                switch_time_seconds=visit.switch_time_seconds,
                platform_entry_time_seconds=(
                    visit.switch_time_seconds + option.platform_entry_offset_seconds
                    if option.platform_entry_offset_seconds is not None
                    else None
                ),
                platform_exit_time_seconds=(
                    visit.switch_time_seconds
                    + option.platform_exit_offset_seconds
                    + visit.wait_seconds
                    if option.platform_exit_offset_seconds is not None
                    else None
                ),
                exit_switch_time_seconds=(
                    visit.switch_time_seconds
                    + option.exit_switch_offset_seconds
                    + visit.wait_seconds
                ),
                next_switch_time_seconds=visit.next_switch_time_seconds,
                wait_seconds=visit.wait_seconds,
            )
        )
    result = EanCabinTrajectory(cabin_id=trajectory.cabin_id, visits=tuple(visits))
    result.validate()
    return result


def _validate_visit_wait(
    *,
    problem: DddTrajectoryProblem,
    option: DddRouteOption,
    switch_time_seconds: float,
    wait_seconds: float,
    tolerance_seconds: float,
) -> None:
    if not math.isfinite(wait_seconds) or wait_seconds < -tolerance_seconds:
        raise ValueError("DDD trajectory wait must be finite and nonnegative")
    wait_seconds = max(0.0, wait_seconds)
    policy = problem.waiting_policy
    allowed = policy.wait_values_seconds(option.station_id)
    if not any(
        math.isclose(wait_seconds, value, rel_tol=0.0, abs_tol=tolerance_seconds)
        for value in allowed
    ):
        raise ValueError("DDD trajectory wait lies outside the configured domain")
    if option.decision is DddRouteDecision.SKIP and wait_seconds > tolerance_seconds:
        raise ValueError("DDD SKIP route cannot wait")
    if wait_seconds <= tolerance_seconds:
        return
    if option.platform_exit_offset_seconds is None:
        raise ValueError("DDD waiting requires a STOP platform-exit event")
    minimum_exit = switch_time_seconds + option.platform_exit_offset_seconds
    if minimum_exit < policy.earliest_wait_time_seconds - tolerance_seconds:
        raise ValueError("DDD reservoir warm-up visits cannot wait")


def _resource_occurrences_match(
    actual: tuple[DddReferenceResourceOccurrence, ...],
    expected: tuple[DddReferenceResourceOccurrence, ...],
    *,
    tolerance_seconds: float,
) -> bool:
    if len(actual) != len(expected):
        return False
    return all(
        first.resource_id == second.resource_id
        and first.cabin_id == second.cabin_id
        and first.visit_index == second.visit_index
        and first.separation_after_seconds == second.separation_after_seconds
        and first.boundary_only == second.boundary_only
        and first.boundary_origin == second.boundary_origin
        and math.isclose(
            first.leader_clear_time_seconds,
            second.leader_clear_time_seconds,
            rel_tol=0.0,
            abs_tol=tolerance_seconds,
        )
        and math.isclose(
            first.follower_enter_time_seconds,
            second.follower_enter_time_seconds,
            rel_tol=0.0,
            abs_tol=tolerance_seconds,
        )
        for first, second in zip(actual, expected, strict=True)
    )


def build_ean_reservoir_movement_plan(
    *,
    problem: DddTrajectoryProblem,
    trajectories: tuple[DddReferenceTrajectory, ...],
) -> EanMovementPlan:
    validate_ddd_reservoir_solution(problem, trajectories)
    result = EanMovementPlan(
        scenario_id=problem.movement_core.scenario_id,
        horizon_seconds=problem.movement_core.passenger_service_end_seconds,
        model_end_seconds=problem.movement_core.operational_end_seconds,
        trajectories=tuple(
            build_ean_reservoir_trajectory(problem=problem, trajectory=item)
            for item in sorted(trajectories, key=lambda value: value.cabin_id)
        ),
        horizon_formulation=EanHorizonFormulation.EXACT_TIME_ACTIVATION,
        fleet_mode=EanFleetMode.OPTIMIZED_INITIAL_PLACEMENT,
    )
    result.validate()
    return result


def _reservoir_dispatch_occurrences(
    *,
    domain: DddReservoirTrajectoryStartDomain,
    cabin_id: int,
    dispatch_time_seconds: float,
) -> tuple[DddReferenceResourceOccurrence, ...]:
    return tuple(
        DddReferenceResourceOccurrence(
            resource_id=usage.resource_id,
            cabin_id=cabin_id,
            visit_index=-1,
            leader_clear_time_seconds=(
                dispatch_time_seconds + usage.leader_clear_offset_seconds
            ),
            follower_enter_time_seconds=(
                dispatch_time_seconds + usage.follower_enter_offset_seconds
            ),
            separation_after_seconds=usage.separation_after_seconds,
            boundary_origin=True,
            quantize_times=False,
        )
        for usage in domain.boundary.dispatch_resource_usages
    )
