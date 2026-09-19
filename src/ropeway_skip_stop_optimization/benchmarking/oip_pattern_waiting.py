"""Frozen short-horizon OIP fixed-pattern waiting pilot."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta

from .thesis_contract import HEADWAY_CONTRACT, ThesisWindows

from ropeway_skip_stop_optimization.benchmarking.thesis_cases import (
    ExperimentCaseSpec,
    ThesisDemandFamily,
    ThesisDemandProfile,
    ThesisGeometry,
    ThesisObjective,
    ThesisTopology,
    build_demand_groups,
    prepare_experiment_case,
)
from ropeway_skip_stop_optimization.examples.registry import get_example
from ropeway_skip_stop_optimization.models import Demand
from ropeway_skip_stop_optimization.optimization.ean import (
    EanFleetCardinalityMode,
    EanFleetMode,
    StationWaitingMode,
)
from ropeway_skip_stop_optimization.optimization.oip import (
    OipDomain,
    OipOperation,
    OipTimeGrid,
    prepare_oip_domain,
)


@dataclass(frozen=True, slots=True)
class PreparedOipPatternWaitingPilot:
    domain: OipDomain
    pattern_mixes: dict[str, tuple[tuple[str, ...], ...]]
    cycle_seconds: float
    demand_window_seconds: float
    passenger_horizon_seconds: float
    operation_seconds: float


def prepare_oip_pattern_waiting_pilot(
    *,
    maximum_wait_seconds: float,
    legacy_headways: bool = False,
    operation: OipOperation = OipOperation.SKIP_STOP,
    demand_total: int = 3_210,
    cabin_count: int = 62,
    ticks_per_second: int = 1_000,
    demand_family: ThesisDemandFamily | str = ThesisDemandFamily.F2,
) -> PreparedOipPatternWaitingPilot:
    if maximum_wait_seconds < 0:
        raise ValueError("maximum_wait_seconds must be nonnegative")
    demand_family = ThesisDemandFamily(demand_family)
    spec = ExperimentCaseSpec(
        topology=ThesisTopology.T5R,
        geometry=ThesisGeometry.G500,
        demand_family=demand_family,
        demand_profile=ThesisDemandProfile.P0,
        objective=ThesisObjective.UNSERVED,
        demand_total=demand_total,
        release_resolution_seconds=15,
        maximum_wait_seconds=maximum_wait_seconds,
    )
    reference = prepare_experiment_case(spec, fleet_cap=cabin_count)
    cycle_seconds = reference.all_stop_cycle_tick / 1_000_000
    windows = ThesisWindows(cycle_seconds)
    demand_window_seconds = windows.demand_window_seconds
    passenger_horizon_seconds = windows.service_horizon_seconds
    operation_seconds = windows.operation_seconds

    example = get_example(spec.example_id)
    base = example.build_scenario(legacy_headways=legacy_headways)
    groups = build_demand_groups(
        spec,
        station_ids=tuple(f"S{i}" for i in range(5)),
        free_rope_lengths=tuple(
            segment.length_m
            for segment in base.track_segments
            if segment.kind.value == "rope"
        ),
        service_start_tick=0,
        demand_window_tick=round(demand_window_seconds * 1_000_000),
    )
    anchor = datetime.combine(date(2000, 1, 2), base.service_start_time)
    scenario = replace(
        base,
        id=(
            f"oip_t5r_g500_{demand_family.value}_p0_n{demand_total}_k{cabin_count}_"
            f"w{maximum_wait_seconds:g}"
        ),
        service_end_time=(anchor + timedelta(seconds=operation_seconds)).time(),
        demands=tuple(
            Demand(
                arrival_time=(
                    anchor + timedelta(seconds=group.release_time_seconds)
                ).time(),
                origin=group.origin_station_id,
                destination=group.destination_station_id,
                count=group.count,
            )
            for group in groups
        ),
        experiment_metadata={
            "schema": "oip_pattern_waiting_pilot_v1",
            "topology": "t5r",
            "geometry": "g500",
            "architecture": "B",
            "headway_contract": ("architecture_b_stop_leader_entry_and_exit" if legacy_headways else HEADWAY_CONTRACT),
            "demand_family": demand_family.value,
            "demand_profile": "p0",
            "demand_total": demand_total,
            "release_resolution_seconds": 15,
            "all_stop_cycle_seconds": cycle_seconds,
            "demand_window_seconds": demand_window_seconds,
            "completion_seconds": windows.completion_seconds,
            "continuation_seconds": windows.continuation_seconds,
            "maximum_wait_seconds": maximum_wait_seconds,
            "technical_test_load": True,
        },
    )
    scenario.validate()
    config = example.build_ean_config(scenario)
    mode = (
        StationWaitingMode.NO_WAITING
        if maximum_wait_seconds == 0
        else StationWaitingMode.END_OF_PLATFORM_WAIT
    )
    config = replace(
        config,
        horizon_seconds=passenger_horizon_seconds,
        tail_seconds=operation_seconds - passenger_horizon_seconds,
        station_configs=tuple(
            replace(
                item,
                waiting_mode=mode,
                max_wait_seconds=(
                    None if maximum_wait_seconds == 0 else maximum_wait_seconds
                ),
            )
            for item in config.station_configs
        ),
    )
    builder = example.build_ean_artifact_builder(scenario, config)
    builder = replace(
        builder,
        fleet_config=replace(
            builder.fleet_config,
            mode=EanFleetMode.OPTIMIZED_INITIAL_PLACEMENT,
            available_fleet_count=cabin_count,
            cardinality_mode=EanFleetCardinalityMode.EXACT,
        ),
    )
    artifact = builder.build(scenario, config)
    station_ids = tuple(dict.fromkeys(item.station_id for item in artifact.timings))
    all_stop = tuple(station_ids)
    direct_a = ("S1", "S3")
    direct_b = ("S2", "S4")
    mixes = {
        "all_stop": tuple(all_stop for _ in range(cabin_count)),
        "f2_direct": tuple(
            direct_a if index < cabin_count // 2 else direct_b
            for index in range(cabin_count)
        ),
        "mixed": tuple(
            direct_a if index < 16 else direct_b if index < 32 else all_stop
            for index in range(cabin_count)
        ),
    }
    domain = prepare_oip_domain(
        scenario=scenario,
        artifact=artifact,
        operation=operation,
        fixed_k=cabin_count,
        grid=OipTimeGrid(ticks_per_second),
    )
    return PreparedOipPatternWaitingPilot(
        domain=domain,
        pattern_mixes=mixes,
        cycle_seconds=cycle_seconds,
        demand_window_seconds=demand_window_seconds,
        passenger_horizon_seconds=passenger_horizon_seconds,
        operation_seconds=operation_seconds,
    )
