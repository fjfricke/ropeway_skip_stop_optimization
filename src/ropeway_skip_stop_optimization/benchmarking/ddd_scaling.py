from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from functools import lru_cache
import math
from time import perf_counter
from typing import Any

import gurobipy as gp

from ropeway_skip_stop_optimization.examples.registry import get_example
from ropeway_skip_stop_optimization.optimization.ddd import (
    DddLayeredTimeArcKind,
    DddLayeredTimeNetworkBuilder,
    DddMovementProblem,
    DddNetworkTimeObjective,
    DddNetworkTimeProblem,
    DddRouteOptionCost,
    DddTimeDiscretization,
    DddTimePartition,
    EanArtifactToDddMovementProblemAdapter,
    DDD_TIME_TICKS_PER_SECOND,
    ddd_tick_to_seconds,
    estimate_ddd_prefix_formulation_size,
)
from ropeway_skip_stop_optimization.optimization.ean import (
    AllPairsHeadwayPairBuilder,
    EanFleetMode,
    EanOptimizationConfig,
    NetworkEanBuildArtifactBuilder,
    SparseHeadwayPairBuilder,
    StationWaitingMode,
)
from ropeway_skip_stop_optimization.optimization.ean.optimizers.movement_model import (
    EanMovementModelBuilder,
)


DEFAULT_SCALING_EXAMPLE_IDS = (
    "three_station_half_no_skip_no_wait_v0",
    "five_station_circle_cw_half_skip_no_wait_v0",
    "three_station_full_no_skip_no_wait_v0",
    "five_station_circle_cw_full_no_skip_no_wait_v0",
    "five_station_no_wait_v0",
)
LOCAL_PREFIX_CABIN_COUNT = 2
LOCAL_PREFIX_MAX_VISIT_INDEX = 2


@dataclass(frozen=True)
class DddRawSupportCounts:
    per_cabin_counts: tuple[int, ...]
    trajectory_column_count: int
    cartesian_support_count: int

    @property
    def cartesian_support_log10(self) -> float:
        if self.cartesian_support_count <= 0:
            return float("-inf")
        return math.log10(self.cartesian_support_count)


def count_ddd_raw_trajectory_supports(
    problem: DddMovementProblem,
) -> DddRawSupportCounts:
    """Count route strings without materializing them or checking resources.

    This is the exact size of the pre-resource trajectory universe.  It is an
    upper bound on the self-conflict-pruned trajectory universe used by the
    tiny exhaustive reference solver.
    """

    problem.validate()
    options_by_state = problem.route_options_by_state_id
    counts: list[int] = []
    for start in sorted(problem.starts, key=lambda item: item.cabin_id):

        @lru_cache(maxsize=None)
        def count_from(
            state_id: str,
            time_tick: int,
            visit_index: int,
        ) -> int:
            if visit_index >= start.max_visit_count:
                raise ValueError(
                    "DDD raw-support count exhausted the visit bound for cabin "
                    f"{start.cabin_id} at tick={time_tick}"
                )
            result = 0
            for option in options_by_state[state_id]:
                next_tick = time_tick + option.duration_tick
                if next_tick > problem.operational_end_tick:
                    result += 1
                else:
                    result += count_from(
                        option.to_state_id,
                        next_tick,
                        visit_index + 1,
                    )
            return result

        counts.append(
            count_from(
                start.state_id,
                start.time_tick,
                0,
            )
        )

    cartesian = math.prod(counts)
    return DddRawSupportCounts(
        per_cabin_counts=tuple(counts),
        trajectory_column_count=sum(counts),
        cartesian_support_count=cartesian,
    )


def build_initial_ddd_network_problem(
    movement: DddMovementProblem,
) -> DddNetworkTimeProblem:
    """Build the deliberately coarse, valid Phase-0 initial discretization."""

    movement.validate()
    sentinel = ddd_tick_to_seconds(
        movement.operational_end_tick
        + max(option.duration_tick for option in movement.route_options)
        + DDD_TIME_TICKS_PER_SECOND
    )
    result = DddNetworkTimeProblem(
        movement_problem=movement,
        discretization=DddTimeDiscretization(
            tuple(
                DddTimePartition(
                    state.id,
                    (0.0, movement.operational_end_seconds, sentinel),
                )
                for state in movement.states
            )
        ),
        objective=DddNetworkTimeObjective(
            route_option_costs=tuple(
                DddRouteOptionCost(option.id, 0.0)
                for option in movement.route_options
            )
        ),
    )
    result.validate()
    return result


def build_ddd_scaling_case(example_id: str) -> dict[str, Any]:
    example = get_example(example_id)
    scenario = example.build_scenario()
    config = example.build_ean_config(scenario)
    builder = example.build_ean_artifact_builder(scenario, config)
    if not isinstance(builder, NetworkEanBuildArtifactBuilder):
        raise ValueError(f"DDD scaling requires a network builder: {example_id}")
    if builder.fleet_config.mode is not EanFleetMode.FIXED_STARTS:
        raise ValueError(f"DDD scaling requires fixed starts: {example_id}")
    if any(
        station.waiting_mode is not StationWaitingMode.NO_WAITING
        for station in config.station_configs
    ):
        raise ValueError(f"DDD scaling does not yet support waiting: {example_id}")

    sparse_started = perf_counter()
    sparse_artifact = replace(
        builder,
        headway_pair_builder=SparseHeadwayPairBuilder(),
    ).build(scenario, config)
    sparse_build_seconds = perf_counter() - sparse_started
    movement = EanArtifactToDddMovementProblemAdapter().build(sparse_artifact)

    network_started = perf_counter()
    network = DddLayeredTimeNetworkBuilder().build(
        build_initial_ddd_network_problem(movement)
    )
    ddd_network_build_seconds = perf_counter() - network_started
    source_count = sum(
        arc.kind is DddLayeredTimeArcKind.SOURCE for arc in network.arcs
    )
    movement_count = sum(
        arc.kind is DddLayeredTimeArcKind.MOVEMENT for arc in network.arcs
    )
    sink_count = sum(
        arc.kind is DddLayeredTimeArcKind.SINK for arc in network.arcs
    )
    cabin_ids = network.cabin_ids
    start_by_cabin_id = {start.cabin_id: start for start in movement.starts}
    local_depths = {
        cabin_id: min(
            LOCAL_PREFIX_MAX_VISIT_INDEX,
            start_by_cabin_id[cabin_id].max_visit_count - 1,
        )
        for cabin_id in cabin_ids[:LOCAL_PREFIX_CABIN_COUNT]
    }
    all_depth_two = {
        cabin_id: min(
            LOCAL_PREFIX_MAX_VISIT_INDEX,
            start_by_cabin_id[cabin_id].max_visit_count - 1,
        )
        for cabin_id in cabin_ids
    }
    full_depths = {
        cabin_id: start_by_cabin_id[cabin_id].max_visit_count - 1
        for cabin_id in cabin_ids
    }
    local_prefix = estimate_ddd_prefix_formulation_size(
        network,
        max_visit_index_by_cabin=local_depths,
    )
    all_depth_two_prefix = estimate_ddd_prefix_formulation_size(
        network,
        max_visit_index_by_cabin=all_depth_two,
    )
    full_prefix = estimate_ddd_prefix_formulation_size(
        network,
        max_visit_index_by_cabin=full_depths,
    )

    supports_started = perf_counter()
    raw_supports = count_ddd_raw_trajectory_supports(movement)
    support_count_seconds = perf_counter() - supports_started

    eager_artifact_started = perf_counter()
    eager_artifact = replace(
        builder,
        headway_pair_builder=AllPairsHeadwayPairBuilder(),
    ).build(scenario, config)
    eager_artifact_build_seconds = perf_counter() - eager_artifact_started
    eager_model_started = perf_counter()
    gurobi_model = gp.Model(f"ddd_g9_eager::{example_id}")
    gurobi_model.Params.OutputFlag = 0
    try:
        eager = EanMovementModelBuilder().build(
            model=gurobi_model,
            binary_vtype=gp.GRB.BINARY,
            artifact=eager_artifact,
            optimization_config=replace(
                EanOptimizationConfig.all(),
                enable_fixed_start_headway_precedence=True,
                enable_shared_merge_headway_order=True,
            ),
        )
        eager_model_build_seconds = perf_counter() - eager_model_started
        eager_metrics = {
            "artifact_build_seconds": eager_artifact_build_seconds,
            "model_build_seconds": eager_model_build_seconds,
            "variable_count": eager.variable_count,
            "constraint_count": eager.constraint_count,
            "nonzero_count": eager.nonzero_count,
            "headway_pair_count": len(eager_artifact.headway_pairs),
            "headway_order_variable_count": (
                eager.build_metrics.headway_order_family_count
            ),
            "headway_order_variable_savings": (
                eager.build_metrics.headway_order_variable_savings
            ),
            "fixed_start_headway_precedence": True,
            "shared_merge_headway_order": True,
        }
    finally:
        gurobi_model.dispose()

    anonymous_variable_count = len(network.arcs)
    anonymous_constraint_count = len(cabin_ids) + len(network.nodes)
    same_network_fully_labeled_variable_count = (
        source_count + len(cabin_ids) * (movement_count + sink_count)
    )
    result = {
        "example_id": example_id,
        "cabin_count": len(cabin_ids),
        "operational_end_seconds": movement.operational_end_seconds,
        "max_visit_count": max(start.max_visit_count for start in movement.starts),
        "sparse_artifact_build_seconds": sparse_build_seconds,
        "ddd_network_build_seconds": ddd_network_build_seconds,
        "ddd_node_count": len(network.nodes),
        "ddd_source_arc_count": source_count,
        "ddd_movement_arc_count": movement_count,
        "ddd_sink_arc_count": sink_count,
        "ddd_anonymous_variable_count": anonymous_variable_count,
        "ddd_anonymous_constraint_count": anonymous_constraint_count,
        "ddd_local_structural_constraint_count": (
            anonymous_constraint_count
            + local_prefix.prefix_conservation_row_count
            + local_prefix.prefix_link_row_count
        ),
        "ddd_local_prefix": asdict(local_prefix),
        "ddd_all_cabins_depth_two_prefix": asdict(all_depth_two_prefix),
        "ddd_full_prefix": asdict(full_prefix),
        "ddd_same_network_fully_labeled_variable_count": (
            same_network_fully_labeled_variable_count
        ),
        "raw_trajectory_support_count_seconds": support_count_seconds,
        "raw_trajectory_column_count": str(raw_supports.trajectory_column_count),
        "raw_cartesian_support_count": str(raw_supports.cartesian_support_count),
        "raw_cartesian_support_log10": raw_supports.cartesian_support_log10,
        "minimum_raw_trajectory_count_per_cabin": min(
            raw_supports.per_cabin_counts
        ),
        "maximum_raw_trajectory_count_per_cabin": max(
            raw_supports.per_cabin_counts
        ),
        "eager_ean": eager_metrics,
    }
    result["local_prefix_fraction_of_full_prefix"] = (
        local_prefix.prefix_variable_count / full_prefix.prefix_variable_count
        if full_prefix.prefix_variable_count
        else 0.0
    )
    result["local_ddd_variable_fraction_of_eager_ean"] = (
        (anonymous_variable_count + local_prefix.prefix_variable_count)
        / eager_metrics["variable_count"]
    )
    return result


def evaluate_g9_structural_gate(cases: list[dict[str, Any]]) -> dict[str, Any]:
    """Evaluate the predeclared structural, not solve-time, G9 conditions."""

    conditions = {
        "at_least_three_physical_cases": len(cases) >= 3,
        "includes_at_least_thirty_cabins": any(
            case["cabin_count"] >= 30 for case in cases
        ),
        "includes_nontrivial_stop_skip_supports": any(
            case["raw_cartesian_support_log10"] > 0.0 for case in cases
        ),
        "local_prefix_is_smaller_than_full_prefix_in_every_case": all(
            case["ddd_local_prefix"]["prefix_variable_count"]
            < case["ddd_full_prefix"]["prefix_variable_count"]
            for case in cases
        ),
        "local_ddd_has_fewer_variables_than_eager_ean_in_every_case": all(
            case["ddd_anonymous_variable_count"]
            + case["ddd_local_prefix"]["prefix_variable_count"]
            < case["eager_ean"]["variable_count"]
            for case in cases
        ),
    }
    return {
        "status": "achieved" if conditions and all(conditions.values()) else "open",
        "claim_scope": "structural_model_size_only",
        "conditions": conditions,
    }


def render_scaling_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# DDD Gate G9 scaling census",
        "",
        "All counts are measured on fixed-start, no-wait physical examples. The ",
        "local delayed case tracks two cabins through visit index two. The full-",
        "prefix column is the same-network limit in which every cabin is labelled ",
        "through its complete horizon; it is not the delayed operating point.",
        "",
        "| Example | K | DDD anonymous vars | Local prefix vars | Full prefix vars | Eager EAN vars | Eager rows | Pair universe | log10 raw supports |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for case in payload["cases"]:
        lines.append(
            "| {example_id} | {cabin_count} | {ddd_anonymous_variable_count} | "
            "{local} | {full} | {eager_vars} | {eager_rows} | {pairs} | "
            "{support_log:.1f} |".format(
                **case,
                local=case["ddd_local_prefix"]["prefix_variable_count"],
                full=case["ddd_full_prefix"]["prefix_variable_count"],
                eager_vars=case["eager_ean"]["variable_count"],
                eager_rows=case["eager_ean"]["constraint_count"],
                pairs=case["eager_ean"]["headway_pair_count"],
                support_log=case["raw_cartesian_support_log10"],
            )
        )
    lines.extend(
        (
            "",
            f"Structural Gate G9 status: **{payload['gate_g9']['status']}**.",
            "This certifies a model-size advantage for local prefix activation; ",
            "it does not claim faster solve time or that few conflicts suffice on ",
            "every instance.",
            "",
            "`raw supports` counts route strings before resource checks. It is an ",
            "exact pre-resource count and therefore an upper bound after self-",
            "conflict pruning. Timings and detailed counts are stored in JSON.",
        )
    )
    return "\n".join(lines) + "\n"
