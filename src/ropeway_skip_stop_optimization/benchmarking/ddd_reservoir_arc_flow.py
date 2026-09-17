from __future__ import annotations

from dataclasses import dataclass, replace
import math

from ropeway_skip_stop_optimization.examples.registry import get_example
from ropeway_skip_stop_optimization.models import Scenario
from ropeway_skip_stop_optimization.optimization.ddd.artifact_adapter import (
    EanArtifactToDddMovementProblemAdapter,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_arc_flow_problem import (
    DddReservoirArcFlowProblem,
    DddReservoirOperatingMode,
)
from ropeway_skip_stop_optimization.optimization.ddd.trajectory_column_generation import (
    DddTrajectoryWaitingDomain,
)
from ropeway_skip_stop_optimization.optimization.ddd.trajectory_problem import (
    DddTrajectoryWaitingPolicy,
)
from ropeway_skip_stop_optimization.optimization.ean import (
    EanFleetMode,
    EvenlySpacedAllStopCabinStartBuilder,
    NetworkEanBuildArtifactBuilder,
    SparseHeadwayPairBuilder,
    StationWaitingMode,
    analyze_all_stop_start_capacity,
)
from ropeway_skip_stop_optimization.optimization.ean.builders.passenger_builder import (
    expand_demands_to_ean_groups,
)


@dataclass(frozen=True, slots=True)
class DddReservoirArcFlowRunConfig:
    example_id: str
    available_fleet_count: int | None = None
    fleet_multiplier_over_all_stop: float = 1.5
    entry_state_id: str = "A_entry_cw"
    warmup_seconds: float = 300.0
    service_seconds: float = 1200.0
    recovery_seconds: float = 300.0
    dispatch_step_seconds: float = 1.0
    waiting_max_seconds: float = 0.0
    waiting_step_seconds: float = 1.0
    operating_mode: DddReservoirOperatingMode = DddReservoirOperatingMode.SKIP_STOP

    def validate(self) -> None:
        if not self.example_id or not self.entry_state_id:
            raise ValueError("reservoir run needs example and entry state ids")
        if self.available_fleet_count is not None and self.available_fleet_count <= 0:
            raise ValueError("reservoir available fleet must be positive")
        if (
            not math.isfinite(self.fleet_multiplier_over_all_stop)
            or self.fleet_multiplier_over_all_stop < 1
        ):
            raise ValueError("reservoir fleet multiplier must be at least one")
        for value in (
            self.warmup_seconds,
            self.service_seconds,
            self.recovery_seconds,
            self.dispatch_step_seconds,
            self.waiting_step_seconds,
        ):
            if not math.isfinite(value) or value <= 0:
                raise ValueError("reservoir run time values must be positive")
        if not math.isfinite(self.waiting_max_seconds) or self.waiting_max_seconds < 0:
            raise ValueError("reservoir waiting maximum must be nonnegative")
        if self.waiting_max_seconds and not math.isclose(
            self.waiting_max_seconds / self.waiting_step_seconds,
            round(self.waiting_max_seconds / self.waiting_step_seconds),
            rel_tol=0.0,
            abs_tol=1e-9,
        ):
            raise ValueError("waiting maximum must be a multiple of its step")


@dataclass(frozen=True, slots=True)
class DddPreparedReservoirArcFlowRun:
    scenario: Scenario
    problem: DddReservoirArcFlowProblem
    all_stop_maximum_cabin_count: int
    headway_policy: object | None = None


def prepare_ddd_reservoir_arc_flow_run(
    config: DddReservoirArcFlowRunConfig,
) -> DddPreparedReservoirArcFlowRun:
    config.validate()
    example = get_example(config.example_id)
    scenario = example.build_scenario()
    ean_config = example.build_ean_config(scenario)
    builder = example.build_ean_artifact_builder(scenario, ean_config)
    if not isinstance(builder, NetworkEanBuildArtifactBuilder):
        raise ValueError("reservoir arc-flow requires the network EAN builder")
    builder = replace(
        builder,
        fleet_config=replace(
            builder.fleet_config,
            mode=EanFleetMode.FIXED_STARTS,
            available_fleet_count=None,
        ),
        start_builder=EvenlySpacedAllStopCabinStartBuilder(1),
        headway_pair_builder=SparseHeadwayPairBuilder(),
    )
    no_wait_config = replace(
        ean_config,
        horizon_seconds=config.service_seconds,
        station_configs=tuple(
            replace(
                station,
                waiting_mode=StationWaitingMode.NO_WAITING,
                fifo_capacity=None,
                max_wait_seconds=None,
            )
            for station in ean_config.station_configs
        ),
    )
    analysis_artifact = builder.build(scenario, no_wait_config)
    analysis = analyze_all_stop_start_capacity(analysis_artifact)
    if config.waiting_max_seconds > 0:
        movement_config = replace(
            no_wait_config,
            station_configs=tuple(
                replace(
                    station,
                    waiting_mode=StationWaitingMode.END_OF_PLATFORM_WAIT,
                    fifo_capacity=None,
                    max_wait_seconds=config.waiting_max_seconds,
                )
                for station in no_wait_config.station_configs
            ),
        )
        artifact = builder.build(scenario, movement_config)
        waiting_policy = DddTrajectoryWaitingPolicy(
            domain=DddTrajectoryWaitingDomain.BOUNDED_WAIT,
            step_seconds=config.waiting_step_seconds,
            maximum_wait_seconds_by_station_id=tuple(
                sorted(
                    (station.station_id, config.waiting_max_seconds)
                    for station in movement_config.station_configs
                )
            ),
            earliest_wait_time_seconds=config.warmup_seconds,
        )
    else:
        artifact = analysis_artifact
        waiting_policy = DddTrajectoryWaitingPolicy()
    core = EanArtifactToDddMovementProblemAdapter(
        waiting_step_seconds=config.waiting_step_seconds
    ).build_movement_core(artifact)
    available = config.available_fleet_count or math.ceil(
        config.fleet_multiplier_over_all_stop * analysis.maximum_cabin_count
    )
    problem = DddReservoirArcFlowProblem(
        movement_core=core,
        demand_groups=expand_demands_to_ean_groups(scenario),
        cabin_capacity=int(round(artifact.config.cabin_capacity)),
        available_fleet_count=available,
        entry_state_id=config.entry_state_id,
        warmup_seconds=config.warmup_seconds,
        service_seconds=config.service_seconds,
        recovery_seconds=config.recovery_seconds,
        dispatch_step_seconds=config.dispatch_step_seconds,
        operating_mode=config.operating_mode,
        waiting_policy=waiting_policy,
        all_stop_maximum_cabin_count=analysis.maximum_cabin_count,
        all_stop_cycle_seconds=analysis.cycle_seconds,
        all_stop_headway_seconds=analysis.limiting_headway_seconds,
    )
    problem.validate()
    return DddPreparedReservoirArcFlowRun(
        scenario=scenario,
        problem=problem,
        all_stop_maximum_cabin_count=analysis.maximum_cabin_count,
        headway_policy=artifact.headway_policy,
    )
