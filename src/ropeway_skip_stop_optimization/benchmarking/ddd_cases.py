from __future__ import annotations

from dataclasses import dataclass, replace

from ropeway_skip_stop_optimization.examples.three_station import (
    build_three_station_scenario,
)
from ropeway_skip_stop_optimization.examples.three_station_ean import (
    build_three_station_ean_config,
    build_three_station_ean_pattern_definition,
)
from ropeway_skip_stop_optimization.models import Scenario
from ropeway_skip_stop_optimization.optimization.ddd import (
    DddFixedStart,
    DddMovementProblem,
    DddMovementState,
    DddPartialTimeProblem,
    DddRouteDecision,
    DddRouteOption,
    DddRouteOptionCost,
    DddSupportCost,
    DddSupportLiteral,
    DddSupportObjective,
    DddTerminalThresholdCost,
    DddTimeDiscretization,
    DddTimePartition,
    DddTimeSpaceObjective,
)
from ropeway_skip_stop_optimization.optimization.ean import (
    EanBuildArtifact,
    EanCabinStart,
    EanCabinStartBuilder,
    EanCabinStartKind,
    EanCirculationPattern,
    EanConfig,
    EanMovementNetwork,
    HeadwayPairBuilder,
    SparseHeadwayPairBuilder,
    StationWaitingMode,
    network_ean_builder_for_pattern,
)


THREE_STATION_TWO_CABIN_MERGE_CASE_ID = (
    "three_station_two_cabin_stop_skip_merge_v0"
)
THREE_STATION_TWO_CABIN_SECOND_START_SECONDS = 19.7
THREE_STATION_TWO_CABIN_HORIZON_SECONDS = 30.0
EVENT_CELL_BOUND_PROBE_CASE_ID = "event_cell_bound_probe_v0"


@dataclass(frozen=True)
class _TwoCabinMergeStartBuilder(EanCabinStartBuilder):
    def build(
        self,
        scenario: Scenario,
        config: EanConfig,
        network: EanMovementNetwork,
        pattern: EanCirculationPattern,
    ) -> tuple[EanCabinStart, ...]:
        return (
            EanCabinStart(
                cabin_id=0,
                first_switch_id=pattern.state_ids[0],
                kind=EanCabinStartKind.FIXED,
                time_seconds=0.0,
            ),
            EanCabinStart(
                cabin_id=1,
                first_switch_id=pattern.state_ids[0],
                kind=EanCabinStartKind.FIXED,
                time_seconds=THREE_STATION_TWO_CABIN_SECOND_START_SECONDS,
            ),
        )


def build_three_station_two_cabin_merge_artifact(
    *,
    headway_pair_builder: HeadwayPairBuilder | None = None,
) -> EanBuildArtifact:
    """Build the exact four-support Stop/Skip proof fixture.

    At the first middle-station exit, cabin 0 STOP and cabin 1 SKIP are
    separated by about 0.482 seconds, below the physical 0.7-second headway.
    The other three first-route combinations are feasible. The short exact
    horizon prevents a second route decision while retaining route clearance.
    """

    scenario = replace(
        build_three_station_scenario(),
        id=THREE_STATION_TWO_CABIN_MERGE_CASE_ID,
    )
    base_config = build_three_station_ean_config(scenario)
    config = replace(
        base_config,
        horizon_seconds=THREE_STATION_TWO_CABIN_HORIZON_SECONDS,
        tail_seconds=0.0,
        station_configs=tuple(
            replace(station, waiting_mode=StationWaitingMode.NO_WAITING)
            for station in base_config.station_configs
        ),
    )
    return network_ean_builder_for_pattern(
        pattern_definition=build_three_station_ean_pattern_definition(),
        start_builder=_TwoCabinMergeStartBuilder(),
        headway_pair_builder=(
            headway_pair_builder or SparseHeadwayPairBuilder()
        ),
    ).build(scenario, config)


def build_three_station_two_cabin_merge_probe_objective(
    problem: DddMovementProblem,
) -> DddSupportObjective:
    """Prefer the fixture's sole infeasible support in the optimistic master."""

    if {start.cabin_id for start in problem.starts} != {0, 1}:
        raise ValueError("two-cabin merge probe objective requires cabins 0 and 1")
    start_state_id = next(
        start.state_id for start in problem.starts if start.cabin_id == 0
    )
    option_id_by_decision = {
        option.decision: option.id
        for option in problem.route_options
        if option.from_state_id == start_state_id
    }
    if set(option_id_by_decision) != {
        DddRouteDecision.STOP,
        DddRouteDecision.SKIP,
    }:
        raise ValueError("two-cabin merge probe requires one Stop and one Skip option")
    return DddSupportObjective(
        costs=tuple(
            DddSupportCost(
                literal=DddSupportLiteral(
                    cabin_id=cabin_id,
                    visit_index=0,
                    route_option_id=option_id_by_decision[decision],
                ),
                cost=cost,
            )
            for cabin_id, desired_decision in (
                (0, DddRouteDecision.STOP),
                (1, DddRouteDecision.SKIP),
            )
            for decision, cost in (
                (desired_decision, 0.0),
                (
                    DddRouteDecision.SKIP
                    if desired_decision is DddRouteDecision.STOP
                    else DddRouteDecision.STOP,
                    1.0,
                ),
            )
        )
    )


def build_event_cell_bound_probe() -> DddPartialTimeProblem:
    """Build the exact LB/UB proof fixture for one safe time-cell split."""

    stop_id = "route::A_stop_to_B"
    skip_id = "route::A_skip_to_B"
    continue_id = "route::B_continue_to_C"
    movement = DddMovementProblem(
        scenario_id=EVENT_CELL_BOUND_PROBE_CASE_ID,
        passenger_service_end_seconds=9.0,
        operational_end_seconds=9.9,
        states=tuple(DddMovementState(state_id) for state_id in ("A", "B", "C")),
        starts=(DddFixedStart(0, "A", 0.0, 2),),
        route_options=(
            DddRouteOption(
                id=stop_id,
                from_state_id="A",
                to_state_id="B",
                station_id="A",
                decision=DddRouteDecision.STOP,
                duration_seconds=7.0,
                platform_entry_offset_seconds=0.0,
                platform_exit_offset_seconds=7.0,
                exit_switch_offset_seconds=7.0,
                resource_usages=(),
            ),
            DddRouteOption(
                id=skip_id,
                from_state_id="A",
                to_state_id="B",
                station_id="A",
                decision=DddRouteDecision.SKIP,
                duration_seconds=5.0,
                platform_entry_offset_seconds=None,
                platform_exit_offset_seconds=None,
                exit_switch_offset_seconds=5.0,
                resource_usages=(),
            ),
            DddRouteOption(
                id=continue_id,
                from_state_id="B",
                to_state_id="C",
                station_id="B",
                decision=DddRouteDecision.SKIP,
                duration_seconds=5.0,
                platform_entry_offset_seconds=None,
                platform_exit_offset_seconds=None,
                exit_switch_offset_seconds=5.0,
                resource_usages=(),
            ),
        ),
        resources=(),
    )
    result = DddPartialTimeProblem(
        movement_problem=movement,
        terminal_state_id="C",
        discretization=DddTimeDiscretization(
            partitions=(
                DddTimePartition("B", (5.0, 10.0)),
                DddTimePartition("C", (10.0, 12.0, 15.0)),
            )
        ),
        objective=DddTimeSpaceObjective(
            route_option_costs=(
                DddRouteOptionCost(stop_id, 0.0),
                DddRouteOptionCost(skip_id, 2.0),
                DddRouteOptionCost(continue_id, 0.0),
            ),
            terminal_cost=DddTerminalThresholdCost(
                state_id="C",
                threshold_seconds=12.0,
                before_cost=0.0,
                at_or_after_cost=1.0,
            ),
        ),
    )
    result.validate()
    return result
