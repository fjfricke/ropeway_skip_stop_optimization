from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import math
from time import perf_counter
from typing import Any

from ropeway_skip_stop_optimization.examples.registry import EXAMPLES, get_example
from ropeway_skip_stop_optimization.optimization.ean import (
    EanFleetMode,
    NetworkEanBuildArtifactBuilder,
    SparseHeadwayPairBuilder,
    StationWaitingMode,
)


DEFAULT_QUANTA_SECONDS = (0.5, 1.0, 5.0)


@dataclass(frozen=True)
class UniformGridEstimate:
    """First-order movement-only full-grid counts, before reachability pruning."""

    quantum_seconds: float
    time_point_count: int
    timed_state_node_count: int
    route_departure_copy_count: int
    unit_holding_arc_count: int
    anonymous_cabin_arc_count: int
    labeled_cabin_arc_count: int
    resource_slot_row_count: int


def estimate_uniform_grid(
    *,
    horizon_seconds: float,
    quantum_seconds: float,
    state_count: int,
    route_option_count: int,
    holding_state_count: int,
    resource_count: int,
    cabin_count: int,
) -> UniformGridEstimate:
    if horizon_seconds <= 0:
        raise ValueError("horizon_seconds must be positive")
    if quantum_seconds <= 0:
        raise ValueError("quantum_seconds must be positive")
    for label, value in (
        ("state_count", state_count),
        ("route_option_count", route_option_count),
        ("holding_state_count", holding_state_count),
        ("resource_count", resource_count),
        ("cabin_count", cabin_count),
    ):
        if value < 0:
            raise ValueError(f"{label} must be nonnegative")

    time_point_count = math.ceil(horizon_seconds / quantum_seconds) + 1
    route_departure_copy_count = route_option_count * time_point_count
    unit_holding_arc_count = holding_state_count * (time_point_count - 1)
    anonymous_arc_count = route_departure_copy_count + unit_holding_arc_count
    return UniformGridEstimate(
        quantum_seconds=quantum_seconds,
        time_point_count=time_point_count,
        timed_state_node_count=state_count * time_point_count,
        route_departure_copy_count=route_departure_copy_count,
        unit_holding_arc_count=unit_holding_arc_count,
        anonymous_cabin_arc_count=anonymous_arc_count,
        labeled_cabin_arc_count=cabin_count * anonymous_arc_count,
        resource_slot_row_count=resource_count * time_point_count,
    )


def build_example_census(
    example_id: str,
    *,
    quanta_seconds: tuple[float, ...] = DEFAULT_QUANTA_SECONDS,
) -> dict[str, Any]:
    example = get_example(example_id)
    scenario = example.build_scenario()
    config = example.build_ean_config(scenario)
    builder = example.build_ean_artifact_builder(scenario, config)
    if not isinstance(builder, NetworkEanBuildArtifactBuilder):
        raise ValueError(f"DDD census requires a network artifact builder: {example_id}")
    if builder.fleet_config.mode is not EanFleetMode.FIXED_STARTS:
        raise ValueError(f"DDD Phase 0 census supports fixed starts only: {example_id}")

    sparse_builder = replace(
        builder,
        headway_pair_builder=SparseHeadwayPairBuilder(),
    )
    started = perf_counter()
    artifact = sparse_builder.build(scenario, config)
    elapsed_seconds = perf_counter() - started
    network = artifact.movement_network
    conflict_index = artifact.resource_conflict_index
    if network is None or conflict_index is None:
        raise ValueError(f"network provenance missing from artifact: {example_id}")

    waiting_station_ids = {
        station_config.station_id
        for station_config in config.station_configs
        if station_config.waiting_mode is not StationWaitingMode.NO_WAITING
    }
    holding_state_count = len(
        {
            option.from_state_id
            for option in network.route_options
            if option.station_id in waiting_station_ids
        }
    )
    cabin_count = len(artifact.cabin_starts)
    minimum_return_seconds = min(
        network.minimum_return_seconds_by_state().values()
    )
    estimates = tuple(
        estimate_uniform_grid(
            horizon_seconds=config.operational_end_seconds,
            quantum_seconds=quantum,
            state_count=len(network.states),
            route_option_count=len(network.route_options),
            holding_state_count=holding_state_count,
            resource_count=len(network.resources),
            cabin_count=cabin_count,
        )
        for quantum in quanta_seconds
    )

    return {
        "example_id": example_id,
        "fleet_mode": artifact.fleet_mode.value,
        "cabin_count": cabin_count,
        "passenger_service_end_seconds": config.passenger_service_end_seconds,
        "operational_end_seconds": config.operational_end_seconds,
        "state_count": len(network.states),
        "route_option_count": len(network.route_options),
        "resource_count": len(network.resources),
        "holding_state_count": holding_state_count,
        "minimum_positive_return_seconds": minimum_return_seconds,
        "ean_visit_count": len(artifact.switch_visits),
        "ean_transition_count": len(artifact.switch_transitions),
        "ean_checkpoint_count": len(artifact.headway_checkpoints),
        "ean_candidate_count": len(artifact.headway_candidates),
        "complete_headway_pair_universe_count": (
            conflict_index.complete_headway_pair_count
        ),
        "materialized_headway_pair_count": len(artifact.headway_pairs),
        "sparse_artifact_build_seconds": elapsed_seconds,
        "uniform_grid_estimates": [asdict(estimate) for estimate in estimates],
    }


def fixed_start_example_ids() -> tuple[str, ...]:
    result: list[str] = []
    for example_id in sorted(EXAMPLES):
        example = get_example(example_id)
        scenario = example.build_scenario()
        config = example.build_ean_config(scenario)
        builder = example.build_ean_artifact_builder(scenario, config)
        if (
            isinstance(builder, NetworkEanBuildArtifactBuilder)
            and builder.fleet_config.mode is EanFleetMode.FIXED_STARTS
        ):
            result.append(example_id)
    return tuple(result)


def render_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# DDD Phase-0 movement census",
        "",
        "Sparse artifacts count candidates and the exact complete pair universe; ",
        "they intentionally materialize zero headway pairs.",
        "",
        "| Example | K | H [s] | States | Options | Visits | Candidates | Pair universe | Sparse build [s] |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for case in payload["cases"]:
        lines.append(
            "| {example_id} | {cabin_count} | {operational_end_seconds:g} | "
            "{state_count} | {route_option_count} | {ean_visit_count} | "
            "{ean_candidate_count} | {complete_headway_pair_universe_count} | "
            "{sparse_artifact_build_seconds:.3f} |".format(**case)
        )
    lines.extend(("", "Uniform-grid estimates are stored in the JSON output."))
    return "\n".join(lines) + "\n"
