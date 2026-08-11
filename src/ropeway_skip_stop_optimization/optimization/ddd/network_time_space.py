from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import StrEnum
import math
from time import perf_counter
from typing import TYPE_CHECKING, Callable

import gurobipy as gp
from gurobipy import GRB

from ropeway_skip_stop_optimization.optimization.ddd.aggregate_support import (
    DddAggregateRouteCountLiteral,
    DddAggregateSupportCut,
    DddAggregateSupportDistanceCut,
)
from ropeway_skip_stop_optimization.optimization.ddd.models import (
    DddMovementProblem,
    DddRouteOption,
)
from ropeway_skip_stop_optimization.optimization.ddd.resource_time import (
    DddAnonymousResourceRow,
    DddTimedResourceUsageWindow,
    build_ddd_mandatory_resource_rows,
    ddd_feasible_source_interval,
)
from ropeway_skip_stop_optimization.optimization.ddd.support_master import (
    DddSupportConflictCut,
    DddSupportLiteral,
)
from ropeway_skip_stop_optimization.optimization.ddd.time_space import (
    DddPartialTimedArc,
    DddPartialTimedPath,
    DddPartialTimeProblem,
    DddRouteOptionCost,
    DddTerminalThresholdCost,
    DddTimeCell,
    DddTimeDiscretization,
    DddTimePartition,
    DddTimeSpaceObjective,
    ddd_partial_arc_is_compatible,
)
from ropeway_skip_stop_optimization.optimization.ddd.time_ticks import (
    ddd_seconds_to_tick,
)
from ropeway_skip_stop_optimization.optimization.ddd.timed_flow_cover import (
    DddCpSatTimedFlowSupport,
    DddTimedArcFlowCount,
    DddTimedFlowCoverCut,
    DddTimedFlowRegion,
    DddTimedFlowThresholdLiteral,
)

if TYPE_CHECKING:
    from ropeway_skip_stop_optimization.optimization.ddd.passenger_master import (
        DddPassengerMasterProblem,
        DddPassengerMasterSolution,
    )
    from ropeway_skip_stop_optimization.optimization.ddd.time_refinement import (
        DddRecoveredSchedule,
    )


@dataclass(frozen=True)
class DddNetworkTimeObjective:
    route_option_costs: tuple[DddRouteOptionCost, ...]
    terminal_costs: tuple[DddTerminalThresholdCost, ...] = ()
    default_terminal_cost: float = 0.0

    def validate(self, problem: DddMovementProblem) -> None:
        if not math.isfinite(self.default_terminal_cost):
            raise ValueError("DDD default terminal cost must be finite")
        known_option_ids = {option.id for option in problem.route_options}
        route_cost_ids: set[str] = set()
        for item in self.route_option_costs:
            item.validate()
            if item.route_option_id in route_cost_ids:
                raise ValueError(
                    f"duplicate DDD route option cost: {item.route_option_id}"
                )
            if item.route_option_id not in known_option_ids:
                raise ValueError(
                    f"DDD objective references unknown route: {item.route_option_id}"
                )
            route_cost_ids.add(item.route_option_id)
        if route_cost_ids != known_option_ids:
            raise ValueError("DDD objective must price every route option explicitly")

        known_state_ids = {state.id for state in problem.states}
        terminal_state_ids: set[str] = set()
        for item in self.terminal_costs:
            item.validate()
            if item.state_id in terminal_state_ids:
                raise ValueError(f"duplicate DDD terminal cost: {item.state_id}")
            if item.state_id not in known_state_ids:
                raise ValueError(
                    f"DDD terminal objective references unknown state: {item.state_id}"
                )
            terminal_state_ids.add(item.state_id)

    @property
    def route_cost_by_option_id(self) -> dict[str, float]:
        return {item.route_option_id: item.cost for item in self.route_option_costs}

    @property
    def terminal_cost_by_state_id(self) -> dict[str, DddTerminalThresholdCost]:
        return {item.state_id: item for item in self.terminal_costs}

    def terminal_lower_bound(
        self,
        cell: DddTimeCell,
        *,
        tolerance_seconds: float,
    ) -> float:
        terminal_cost = self.terminal_cost_by_state_id.get(cell.state_id)
        if terminal_cost is None:
            return self.default_terminal_cost
        return terminal_cost.lower_bound(
            cell,
            tolerance_seconds=tolerance_seconds,
        )

    def exact_value(
        self,
        route_option_ids: tuple[str, ...],
        terminal_state_id: str,
        terminal_time_seconds: float,
        *,
        tolerance_seconds: float,
    ) -> float:
        route_cost = sum(
            self.route_cost_by_option_id[option_id] for option_id in route_option_ids
        )
        terminal_cost = self.terminal_cost_by_state_id.get(terminal_state_id)
        if terminal_cost is None:
            return route_cost + self.default_terminal_cost
        return route_cost + terminal_cost.exact_value(
            terminal_time_seconds,
            tolerance_seconds=tolerance_seconds,
        )


@dataclass(frozen=True)
class DddNetworkTimeProblem:
    movement_problem: DddMovementProblem
    discretization: DddTimeDiscretization
    objective: DddNetworkTimeObjective

    def validate(self) -> None:
        self.movement_problem.validate()
        self.discretization.validate()
        operational_end = self.movement_problem.operational_end_tick
        required_sentinel_lower_bound = operational_end + max(
            option.duration_tick for option in self.movement_problem.route_options
        )
        target_state_ids = {
            option.to_state_id for option in self.movement_problem.route_options
        }
        missing = target_state_ids - set(self.discretization.by_state_id)
        if missing:
            raise ValueError(f"DDD target states lack time partitions: {missing}")
        for partition in self.discretization.partitions:
            boundaries = partition.boundaries_ticks
            if boundaries[0] != 0:
                raise ValueError(
                    f"DDD partition {partition.state_id!r} must start at zero"
                )
            if operational_end not in boundaries:
                raise ValueError(
                    f"DDD partition {partition.state_id!r} must contain the "
                    "operational horizon boundary"
                )
            if boundaries[-1] <= required_sentinel_lower_bound:
                raise ValueError(
                    f"DDD partition {partition.state_id!r} sentinel must exceed "
                    "the latest attainable completion"
                )
        self.objective.validate(self.movement_problem)

    def with_discretization(
        self,
        discretization: DddTimeDiscretization,
    ) -> DddNetworkTimeProblem:
        result = DddNetworkTimeProblem(
            movement_problem=self.movement_problem,
            discretization=discretization,
            objective=self.objective,
        )
        result.validate()
        return result


@dataclass(frozen=True, order=True)
class DddLayeredTimeNode:
    layer_index: int
    state_id: str
    cell: DddTimeCell

    def validate(self) -> None:
        if self.layer_index <= 0:
            raise ValueError("DDD layered node index must be positive")
        if self.state_id != self.cell.state_id:
            raise ValueError("DDD layered node and time cell states differ")
        self.cell.validate()

    @property
    def id(self) -> str:
        return f"partial_node::v{self.layer_index}::{self.cell.id}"


class DddLayeredTimeArcKind(StrEnum):
    SOURCE = "source"
    MOVEMENT = "movement"
    SINK = "sink"


@dataclass(frozen=True)
class DddLayeredTimeArc:
    id: str
    kind: DddLayeredTimeArcKind
    source_node_id: str | None
    target_node_id: str | None
    cabin_id: int | None
    partial_arc: DddPartialTimedArc | None
    lower_bound_cost: float
    resource_windows: tuple[DddTimedResourceUsageWindow, ...] = ()

    def validate(self) -> None:
        if not self.id.strip() or not math.isfinite(self.lower_bound_cost):
            raise ValueError("DDD layered arc id and cost must be valid")
        if self.kind is DddLayeredTimeArcKind.SOURCE:
            if (
                self.source_node_id is not None
                or self.target_node_id is None
                or self.cabin_id is None
                or self.partial_arc is None
            ):
                raise ValueError("DDD source arc fields are inconsistent")
        elif self.kind is DddLayeredTimeArcKind.MOVEMENT:
            if (
                self.source_node_id is None
                or self.target_node_id is None
                or self.cabin_id is not None
                or self.partial_arc is None
            ):
                raise ValueError("DDD movement arc fields are inconsistent")
        elif self.kind is DddLayeredTimeArcKind.SINK:
            if (
                self.source_node_id is None
                or self.target_node_id is not None
                or self.cabin_id is not None
                or self.partial_arc is not None
            ):
                raise ValueError("DDD sink arc fields are inconsistent")
        else:
            raise ValueError("DDD layered arc kind is invalid")
        if self.kind is DddLayeredTimeArcKind.SINK and self.resource_windows:
            raise ValueError("DDD sink arc cannot contain resource windows")
        resource_window_ids: set[str] = set()
        for window in self.resource_windows:
            window.validate()
            if window.timed_arc_id != self.id:
                raise ValueError("DDD resource window and layered arc ids differ")
            if window.id in resource_window_ids:
                raise ValueError("duplicate DDD layered arc resource window")
            resource_window_ids.add(window.id)


@dataclass(frozen=True)
class DddLayeredTimeNetwork:
    nodes: tuple[DddLayeredTimeNode, ...]
    arcs: tuple[DddLayeredTimeArc, ...]
    cabin_ids: tuple[int, ...]

    def validate(self) -> None:
        node_ids = [node.id for node in self.nodes]
        arc_ids = [arc.id for arc in self.arcs]
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("duplicate DDD layered node ids")
        if len(arc_ids) != len(set(arc_ids)):
            raise ValueError("duplicate DDD layered arc ids")
        if not self.cabin_ids or len(self.cabin_ids) != len(set(self.cabin_ids)):
            raise ValueError("DDD layered network cabin ids must be unique")
        known_node_ids = set(node_ids)
        source_cabin_ids: set[int] = set()
        for node in self.nodes:
            node.validate()
        for arc in self.arcs:
            arc.validate()
            if (
                arc.source_node_id is not None
                and arc.source_node_id not in known_node_ids
            ) or (
                arc.target_node_id is not None
                and arc.target_node_id not in known_node_ids
            ):
                raise ValueError("DDD layered arc references an unknown node")
            if arc.cabin_id is not None:
                source_cabin_ids.add(arc.cabin_id)
        unknown_source_cabins = source_cabin_ids - set(self.cabin_ids)
        if unknown_source_cabins:
            raise ValueError(
                f"DDD source arcs reference unknown cabins: {unknown_source_cabins}"
            )

    @property
    def arcs_by_id(self) -> dict[str, DddLayeredTimeArc]:
        return {arc.id: arc for arc in self.arcs}


@dataclass(frozen=True)
class DddLayeredTimeNetworkBuildStats:
    partition_cache_hits: int = 0
    partition_cache_misses: int = 0
    transition_cache_hits: int = 0
    transition_cache_misses: int = 0
    invalidated_state_count: int = 0
    resource_usage_window_count: int = 0
    horizon_optional_resource_usage_count: int = 0
    structural_earliest_time_count: int = 0
    structurally_pruned_cell_count: int = 0
    structurally_clipped_cell_count: int = 0


def build_ddd_layer_state_earliest_arrival_ticks(
    movement: DddMovementProblem,
) -> dict[tuple[int, str], int]:
    """Return safe earliest arrival ticks for the anonymous layered network.

    The dynamic program ignores resource conflicts and waiting.  Both can only
    delay a physical trajectory, so the returned values are valid lower bounds
    for every exact trajectory represented by the anonymous relaxation.
    """

    movement.validate()
    options_by_state = movement.route_options_by_state_id
    max_layer = max(start.max_visit_count for start in movement.starts)
    earliest: dict[tuple[int, str], int] = {}
    frontier: dict[str, int] = {}

    for start in movement.starts:
        for option in options_by_state.get(start.state_id, ()):
            key = (1, option.to_state_id)
            arrival_tick = start.time_tick + option.duration_tick
            earliest[key] = min(earliest.get(key, arrival_tick), arrival_tick)
            frontier[option.to_state_id] = min(
                frontier.get(option.to_state_id, arrival_tick),
                arrival_tick,
            )

    for layer_index in range(1, max_layer):
        next_frontier: dict[str, int] = {}
        for state_id, source_tick in frontier.items():
            # Route entry at exactly H is active under the canonical horizon
            # convention; strictly later events can only leave through a sink.
            if source_tick > movement.operational_end_tick:
                continue
            for option in options_by_state.get(state_id, ()):
                key = (layer_index + 1, option.to_state_id)
                arrival_tick = source_tick + option.duration_tick
                earliest[key] = min(earliest.get(key, arrival_tick), arrival_tick)
                next_frontier[option.to_state_id] = min(
                    next_frontier.get(option.to_state_id, arrival_tick),
                    arrival_tick,
                )
        frontier = next_frontier
        if not frontier:
            break

    return earliest


def _clip_cells_to_earliest_tick(
    cells: tuple[DddTimeCell, ...],
    *,
    earliest_tick: int,
) -> tuple[tuple[DddTimeCell, ...], int, int]:
    result: list[DddTimeCell] = []
    pruned_count = 0
    clipped_count = 0
    for cell in cells:
        if cell.upper_tick <= earliest_tick:
            pruned_count += 1
            continue
        lower_tick = max(cell.lower_tick, earliest_tick)
        if lower_tick != cell.lower_tick:
            clipped_count += 1
        result.append(
            DddTimeCell.from_ticks(cell.state_id, lower_tick, cell.upper_tick)
        )
    return tuple(result), pruned_count, clipped_count


@dataclass
class DddLayeredTimeNetworkBuilder:
    tolerance_seconds: float = 1e-9
    use_structural_earliest_times: bool = True
    _partition_key_by_state_id: dict[str, tuple[int, ...]] = field(
        default_factory=dict,
        init=False,
        repr=False,
    )
    _cells_by_partition_key: dict[
        tuple[str, tuple[int, ...]], tuple[DddTimeCell, ...]
    ] = field(default_factory=dict, init=False, repr=False)
    _compatible_targets_by_key: dict[tuple[object, ...], tuple[DddTimeCell, ...]] = (
        field(default_factory=dict, init=False, repr=False)
    )
    last_build_stats: DddLayeredTimeNetworkBuildStats = field(
        default_factory=DddLayeredTimeNetworkBuildStats,
        init=False,
    )

    def build(self, problem: DddNetworkTimeProblem) -> DddLayeredTimeNetwork:
        problem.validate()
        if self.tolerance_seconds < 0:
            raise ValueError("DDD network builder tolerance must be nonnegative")
        movement = problem.movement_problem
        options_by_state = movement.route_options_by_state_id
        resources_by_id = movement.resources_by_id
        route_costs = problem.objective.route_cost_by_option_id
        max_layer = max(start.max_visit_count for start in movement.starts)
        earliest_by_layer_state = (
            build_ddd_layer_state_earliest_arrival_ticks(movement)
            if self.use_structural_earliest_times
            else {}
        )
        partitions_by_state = problem.discretization.by_state_id
        partition_keys = {
            state_id: partition.boundaries_ticks
            for state_id, partition in partitions_by_state.items()
        }
        changed_state_ids = {
            state_id
            for state_id, key in partition_keys.items()
            if self._partition_key_by_state_id.get(state_id) != key
        }
        removed_state_ids = set(self._partition_key_by_state_id) - set(partition_keys)
        invalidated_state_ids = changed_state_ids | removed_state_ids
        if invalidated_state_ids:
            self._compatible_targets_by_key = {
                key: value
                for key, value in self._compatible_targets_by_key.items()
                if key[0] not in invalidated_state_ids
                and key[1] not in invalidated_state_ids
            }
            self._cells_by_partition_key = {
                key: value
                for key, value in self._cells_by_partition_key.items()
                if key[0] not in invalidated_state_ids
            }
        self._partition_key_by_state_id = dict(partition_keys)

        partition_cache_hits = 0
        partition_cache_misses = 0
        cells_by_state: dict[str, tuple[DddTimeCell, ...]] = {}
        for state_id, partition in partitions_by_state.items():
            cache_key = (state_id, partition.boundaries_ticks)
            cells = self._cells_by_partition_key.get(cache_key)
            if cells is None:
                cells = partition.cells
                self._cells_by_partition_key[cache_key] = cells
                partition_cache_misses += 1
            else:
                partition_cache_hits += 1
            cells_by_state[state_id] = cells

        transition_cache_hits = 0
        transition_cache_misses = 0
        resource_usage_window_count = 0
        horizon_optional_resource_usage_count = 0
        structurally_pruned_cell_count = 0
        structurally_clipped_cell_count = 0
        cells_by_layer_state: dict[tuple[int, str], tuple[DddTimeCell, ...]] = {}

        def target_cells(
            *,
            layer_index: int,
            state_id: str,
        ) -> tuple[DddTimeCell, ...]:
            nonlocal structurally_pruned_cell_count
            nonlocal structurally_clipped_cell_count
            key = (layer_index, state_id)
            cached = cells_by_layer_state.get(key)
            if cached is not None:
                return cached
            cells = cells_by_state[state_id]
            earliest_tick = earliest_by_layer_state.get(key)
            if earliest_tick is not None:
                cells, pruned, clipped = _clip_cells_to_earliest_tick(
                    cells,
                    earliest_tick=earliest_tick,
                )
                structurally_pruned_cell_count += pruned
                structurally_clipped_cell_count += clipped
            elif self.use_structural_earliest_times:
                cells = ()
            cells_by_layer_state[key] = cells
            return cells

        def compatible_targets(
            *,
            source_cell: DddTimeCell | None,
            fixed_source_time: float | None,
            option: DddRouteOption,
            target_layer_index: int,
        ) -> tuple[DddTimeCell, ...]:
            nonlocal transition_cache_hits, transition_cache_misses
            source_key: tuple[object, ...]
            source_state_id: str
            if source_cell is None:
                if fixed_source_time is None:
                    raise ValueError("DDD fixed source time is missing")
                source_state_id = option.from_state_id
                source_key = ("fixed", ddd_seconds_to_tick(fixed_source_time))
            else:
                source_state_id = source_cell.state_id
                source_key = (
                    "cell",
                    source_cell.lower_tick,
                    source_cell.upper_tick,
                )
            candidate_target_cells = target_cells(
                layer_index=target_layer_index,
                state_id=option.to_state_id,
            )
            target_cell_key = tuple(
                (cell.lower_tick, cell.upper_tick) for cell in candidate_target_cells
            )
            cache_key = (
                source_state_id,
                option.to_state_id,
                source_key,
                option.id,
                option.duration_tick,
                target_cell_key,
                movement.operational_end_tick,
            )
            cached = self._compatible_targets_by_key.get(cache_key)
            if cached is not None:
                transition_cache_hits += 1
                return cached
            transition_cache_misses += 1
            result = tuple(
                target_cell
                for target_cell in candidate_target_cells
                if ddd_partial_arc_is_compatible(
                    source_cell=source_cell,
                    fixed_source_time=fixed_source_time,
                    target_cell=target_cell,
                    option=option,
                    operational_end_seconds=movement.operational_end_seconds,
                    tolerance_seconds=self.tolerance_seconds,
                )
            )
            self._compatible_targets_by_key[cache_key] = result
            return result

        def resource_windows(
            *,
            arc_id: str,
            source_cell: DddTimeCell | None,
            fixed_source_tick: int | None,
            target_cell: DddTimeCell,
            option: DddRouteOption,
        ) -> tuple[DddTimedResourceUsageWindow, ...]:
            nonlocal resource_usage_window_count
            nonlocal horizon_optional_resource_usage_count
            source_interval = ddd_feasible_source_interval(
                source_cell=source_cell,
                fixed_source_tick=fixed_source_tick,
                target_cell=target_cell,
                duration_tick=option.duration_tick,
                operational_end_tick=movement.operational_end_tick,
            )
            if source_interval is None:
                raise RuntimeError(
                    "DDD compatible layered arc has no feasible source interval"
                )
            result: list[DddTimedResourceUsageWindow] = []
            for usage_index, usage in enumerate(option.resource_usages):
                window = DddTimedResourceUsageWindow.from_usage(
                    timed_arc_id=arc_id,
                    source_interval=source_interval,
                    resource=resources_by_id[usage.resource_id],
                    usage=usage,
                    usage_index=usage_index,
                )
                if window.latest_follower_enter_tick <= movement.operational_end_tick:
                    result.append(window)
                    continue
                if window.earliest_follower_enter_tick <= movement.operational_end_tick:
                    horizon_optional_resource_usage_count += 1
            resource_usage_window_count += len(result)
            return tuple(result)

        nodes_by_id: dict[str, DddLayeredTimeNode] = {}
        arcs_by_id: dict[str, DddLayeredTimeArc] = {}
        reachable_by_layer: dict[int, set[str]] = {}

        def add_node(node: DddLayeredTimeNode) -> None:
            nodes_by_id[node.id] = node
            reachable_by_layer.setdefault(node.layer_index, set()).add(node.id)

        for start in sorted(movement.starts, key=lambda item: item.cabin_id):
            for option in options_by_state.get(start.state_id, ()):
                for target_cell in compatible_targets(
                    source_cell=None,
                    fixed_source_time=start.time_seconds,
                    option=option,
                    target_layer_index=1,
                ):
                    node = DddLayeredTimeNode(1, option.to_state_id, target_cell)
                    add_node(node)
                    partial_arc = DddPartialTimedArc(
                        visit_index=0,
                        route_option_id=option.id,
                        from_state_id=option.from_state_id,
                        to_state_id=option.to_state_id,
                        source_cell_id=None,
                        target_cell=target_cell,
                    )
                    arc_id = f"source::{start.cabin_id}::{partial_arc.id}"
                    arcs_by_id[arc_id] = DddLayeredTimeArc(
                        id=arc_id,
                        kind=DddLayeredTimeArcKind.SOURCE,
                        source_node_id=None,
                        target_node_id=node.id,
                        cabin_id=start.cabin_id,
                        partial_arc=partial_arc,
                        lower_bound_cost=route_costs[option.id],
                        resource_windows=resource_windows(
                            arc_id=arc_id,
                            source_cell=None,
                            fixed_source_tick=start.time_tick,
                            target_cell=target_cell,
                            option=option,
                        ),
                    )

        for layer_index in range(1, max_layer + 1):
            layer_node_ids = tuple(sorted(reachable_by_layer.get(layer_index, ())))
            for node_id in layer_node_ids:
                node = nodes_by_id[node_id]
                if node.cell.upper_tick > movement.operational_end_tick:
                    sink_id = f"sink::{node.id}"
                    arcs_by_id[sink_id] = DddLayeredTimeArc(
                        id=sink_id,
                        kind=DddLayeredTimeArcKind.SINK,
                        source_node_id=node.id,
                        target_node_id=None,
                        cabin_id=None,
                        partial_arc=None,
                        lower_bound_cost=problem.objective.terminal_lower_bound(
                            node.cell,
                            tolerance_seconds=self.tolerance_seconds,
                        ),
                    )
                if layer_index >= max_layer:
                    continue
                for option in options_by_state.get(node.state_id, ()):
                    for target_cell in compatible_targets(
                        source_cell=node.cell,
                        fixed_source_time=None,
                        option=option,
                        target_layer_index=layer_index + 1,
                    ):
                        target = DddLayeredTimeNode(
                            layer_index + 1,
                            option.to_state_id,
                            target_cell,
                        )
                        add_node(target)
                        partial_arc = DddPartialTimedArc(
                            visit_index=layer_index,
                            route_option_id=option.id,
                            from_state_id=option.from_state_id,
                            to_state_id=option.to_state_id,
                            source_cell_id=node.cell.id,
                            target_cell=target_cell,
                        )
                        arc_id = f"movement::{node.id}::{partial_arc.id}::{target.id}"
                        arcs_by_id[arc_id] = DddLayeredTimeArc(
                            id=arc_id,
                            kind=DddLayeredTimeArcKind.MOVEMENT,
                            source_node_id=node.id,
                            target_node_id=target.id,
                            cabin_id=None,
                            partial_arc=partial_arc,
                            lower_bound_cost=route_costs[option.id],
                            resource_windows=resource_windows(
                                arc_id=arc_id,
                                source_cell=node.cell,
                                fixed_source_tick=None,
                                target_cell=target_cell,
                                option=option,
                            ),
                        )

        result = DddLayeredTimeNetwork(
            nodes=tuple(sorted(nodes_by_id.values(), key=lambda item: item.id)),
            arcs=tuple(sorted(arcs_by_id.values(), key=lambda item: item.id)),
            cabin_ids=tuple(sorted(start.cabin_id for start in movement.starts)),
        )
        result.validate()
        self.last_build_stats = DddLayeredTimeNetworkBuildStats(
            partition_cache_hits=partition_cache_hits,
            partition_cache_misses=partition_cache_misses,
            transition_cache_hits=transition_cache_hits,
            transition_cache_misses=transition_cache_misses,
            invalidated_state_count=len(invalidated_state_ids),
            resource_usage_window_count=resource_usage_window_count,
            horizon_optional_resource_usage_count=(
                horizon_optional_resource_usage_count
            ),
            structural_earliest_time_count=len(earliest_by_layer_state),
            structurally_pruned_cell_count=structurally_pruned_cell_count,
            structurally_clipped_cell_count=structurally_clipped_cell_count,
        )
        return result


class DddAnonymousFlowStatus(StrEnum):
    OPTIMAL = "optimal"
    INFEASIBLE = "infeasible"


@dataclass(frozen=True)
class DddAnonymousMasterIncumbent:
    elapsed_seconds: float
    objective_value: float
    solution_count: int


@dataclass(frozen=True)
class DddAnonymousMasterProgress:
    requested_elapsed_seconds: float | None
    elapsed_seconds: float
    incumbent_objective: float | None
    best_bound: float | None
    absolute_gap: float | None
    relative_gap: float | None
    explored_node_count: float
    open_node_count: float
    simplex_iteration_count: float
    solution_count: int


@dataclass(frozen=True)
class DddAnonymousFlowValue:
    arc_id: str
    value: int


@dataclass(frozen=True)
class DddAnonymousPrefixFlowValue:
    cabin_id: int
    arc_id: str


@dataclass(frozen=True)
class DddAnonymousFlowWarmStart:
    arc_values: tuple[DddAnonymousFlowValue, ...]
    prefix_arc_values: tuple[DddAnonymousPrefixFlowValue, ...]
    projected_cabin_count: int
    complete_cabin_count: int


@dataclass(frozen=True)
class DddAnonymousFlowFixing:
    """Complete exact fixing of every arc flow in one layered DDD network."""

    arc_values: tuple[DddAnonymousFlowValue, ...]
    projected_cabin_count: int

    def validate(self, network: DddLayeredTimeNetwork) -> None:
        network.validate()
        if self.projected_cabin_count != len(network.cabin_ids):
            raise ValueError("DDD fixed flow must project every cabin")
        ids = tuple(item.arc_id for item in self.arc_values)
        if ids != tuple(sorted(ids)) or len(ids) != len(set(ids)):
            raise ValueError("DDD fixed arc values must be sorted and unique")
        if set(ids) != {arc.id for arc in network.arcs}:
            raise ValueError("DDD fixed flow must specify every network arc")
        if any(item.value < 0 for item in self.arc_values):
            raise ValueError("DDD fixed arc flow must be nonnegative")


@dataclass(frozen=True)
class DddAnonymousFlowResult:
    status: DddAnonymousFlowStatus
    objective_value: float | None
    best_bound: float | None
    arc_values: tuple[DddAnonymousFlowValue, ...]
    prefix_arc_values: tuple[DddAnonymousPrefixFlowValue, ...]
    variable_count: int
    constraint_count: int
    prefix_variable_count: int
    conflict_constraint_count: int
    tracked_prefix_cabin_count: int
    warm_start_arc_variable_count: int
    warm_start_prefix_variable_count: int
    warm_start_projected_cabin_count: int
    warm_start_complete_cabin_count: int
    resource_constraint_count: int = 0
    mandatory_resource_constraint_count: int = 0
    additional_resource_constraint_count: int = 0
    aggregate_support_constraint_count: int = 0
    aggregate_threshold_variable_count: int = 0
    timed_flow_cover_constraint_count: int = 0
    timed_flow_threshold_variable_count: int = 0
    fixed_start_structural_constraint_count: int = 0
    fixed_flow_constraint_count: int = 0
    passenger_solution: DddPassengerMasterSolution | None = None
    solver_status_code: int | None = None
    termination_reason: str | None = None
    model_build_seconds: float = 0.0
    optimize_seconds: float = 0.0
    solution_count: int = 0
    explored_node_count: float = 0.0
    open_node_count: float = 0.0
    simplex_iteration_count: float = 0.0
    absolute_gap: float | None = None
    relative_gap: float | None = None
    time_to_first_incumbent_seconds: float | None = None
    incumbent_improvements: tuple[DddAnonymousMasterIncumbent, ...] = ()
    progress_snapshots: tuple[DddAnonymousMasterProgress, ...] = ()


def build_ddd_cp_sat_timed_flow_support(
    network: DddLayeredTimeNetwork,
    flow: DddAnonymousFlowResult,
    movement: DddMovementProblem,
) -> DddCpSatTimedFlowSupport:
    """Capture every positive non-sink master flow as a stable timed region."""

    network.validate()
    movement.validate()
    arc_by_id = {arc.id: arc for arc in network.arcs}
    counts: list[DddTimedArcFlowCount] = []
    for value in flow.arc_values:
        if value.value <= 0:
            raise ValueError("DDD timed-flow support needs positive master values")
        try:
            arc = arc_by_id[value.arc_id]
        except KeyError as error:
            raise ValueError(
                f"DDD timed-flow support references unknown arc {value.arc_id!r}"
            ) from error
        if arc.kind is DddLayeredTimeArcKind.SINK:
            continue
        region = _ddd_timed_flow_region_for_arc(
            network=network,
            movement=movement,
            arc=arc,
        )
        counts.append(DddTimedArcFlowCount(region=region, count=value.value))
    result = DddCpSatTimedFlowSupport(
        arc_flows=tuple(sorted(counts, key=lambda item: item.sort_key))
    )
    result.validate()
    return result


def _ddd_timed_flow_region_for_arc(
    *,
    network: DddLayeredTimeNetwork,
    movement: DddMovementProblem,
    arc: DddLayeredTimeArc,
) -> DddTimedFlowRegion:
    if arc.kind is DddLayeredTimeArcKind.SINK or arc.partial_arc is None:
        raise ValueError("DDD timed-flow region requires a non-sink movement arc")
    partial = arc.partial_arc
    if arc.kind is DddLayeredTimeArcKind.SOURCE:
        if arc.cabin_id is None:
            raise ValueError("DDD timed-flow source arc has no cabin id")
        starts_by_cabin = {start.cabin_id: start for start in movement.starts}
        try:
            start_tick = starts_by_cabin[arc.cabin_id].time_tick
        except KeyError as error:
            raise ValueError("DDD timed-flow source cabin has no fixed start") from error
        source_lower_tick = start_tick
        source_upper_tick = start_tick + 1
        cabin_id = arc.cabin_id
    else:
        if arc.source_node_id is None:
            raise ValueError("DDD timed-flow movement arc has no source node")
        node_by_id = {node.id: node for node in network.nodes}
        try:
            source_cell = node_by_id[arc.source_node_id].cell
        except KeyError as error:
            raise ValueError("DDD timed-flow arc source node is unknown") from error
        source_lower_tick = source_cell.lower_tick
        source_upper_tick = source_cell.upper_tick
        cabin_id = None
    options_by_id = {option.id: option for option in movement.route_options}
    try:
        option = options_by_id[partial.route_option_id]
    except KeyError as error:
        raise ValueError("DDD timed-flow arc route option is unknown") from error
    result = DddTimedFlowRegion(
        visit_index=partial.visit_index,
        route_option_id=partial.route_option_id,
        source_lower_tick=source_lower_tick,
        source_upper_tick=source_upper_tick,
        target_lower_tick=partial.target_cell.lower_tick,
        target_upper_tick=partial.target_cell.upper_tick,
        cabin_id=cabin_id,
        resource_ids=tuple(
            sorted({usage.resource_id for usage in option.resource_usages})
        ),
        origin_timed_arc_id=arc.id,
    )
    result.validate()
    return result


@dataclass(frozen=True)
class DddPrefixFormulationSize:
    """Exact extra size of the delayed prefix formulation for one depth map."""

    tracked_prefix_cabin_count: int
    prefix_variable_count: int
    movement_prefix_variable_count: int
    sink_prefix_variable_count: int
    prefix_conservation_row_count: int
    prefix_link_row_count: int


def estimate_ddd_prefix_formulation_size(
    network: DddLayeredTimeNetwork,
    *,
    max_visit_index_by_cabin: dict[int, int],
) -> DddPrefixFormulationSize:
    """Count the variables and structural rows added by prefix disaggregation.

    Visit zero is represented by the already labelled source arcs and therefore
    needs no additional prefix variables.  Positive depths use precisely the
    same arc filters as :func:`_add_prefix_conflict_formulation`.
    """

    network.validate()
    known_cabin_ids = set(network.cabin_ids)
    unknown = set(max_visit_index_by_cabin) - known_cabin_ids
    if unknown:
        raise ValueError(f"DDD prefix depth references unknown cabins: {unknown}")
    if any(value < 0 for value in max_visit_index_by_cabin.values()):
        raise ValueError("DDD prefix visit indices must be nonnegative")

    active_depths = {
        cabin_id: max_visit_index
        for cabin_id, max_visit_index in max_visit_index_by_cabin.items()
        if max_visit_index > 0
    }
    movement_arcs = tuple(
        arc for arc in network.arcs if arc.kind is DddLayeredTimeArcKind.MOVEMENT
    )
    sink_arcs = tuple(
        arc for arc in network.arcs if arc.kind is DddLayeredTimeArcKind.SINK
    )
    node_by_id = {node.id: node for node in network.nodes}
    movement_count = 0
    sink_count = 0
    linked_arc_ids: set[str] = set()
    conservation_count = 0
    for max_visit_index in active_depths.values():
        eligible_movement = tuple(
            arc
            for arc in movement_arcs
            if arc.partial_arc is not None
            and arc.partial_arc.visit_index <= max_visit_index
        )
        eligible_sink = tuple(
            arc
            for arc in sink_arcs
            if arc.source_node_id is not None
            and node_by_id[arc.source_node_id].layer_index <= max_visit_index
        )
        movement_count += len(eligible_movement)
        sink_count += len(eligible_sink)
        linked_arc_ids.update(arc.id for arc in eligible_movement)
        linked_arc_ids.update(arc.id for arc in eligible_sink)
        conservation_count += sum(
            node.layer_index <= max_visit_index for node in network.nodes
        )

    return DddPrefixFormulationSize(
        tracked_prefix_cabin_count=len(active_depths),
        prefix_variable_count=movement_count + sink_count,
        movement_prefix_variable_count=movement_count,
        sink_prefix_variable_count=sink_count,
        prefix_conservation_row_count=conservation_count,
        prefix_link_row_count=len(linked_arc_ids),
    )


@dataclass(frozen=True)
class DddAnonymousFlowMaster:
    output_flag: bool = False
    integrality_tolerance: float = 1e-6
    include_mandatory_resource_rows: bool = True
    diagnostic_snapshot_seconds: tuple[float, ...] = (1.0, 5.0, 10.0, 30.0, 60.0)

    def solve(
        self,
        network: DddLayeredTimeNetwork,
        *,
        cuts: tuple[DddSupportConflictCut, ...] = (),
        aggregate_support_cuts: tuple[DddAggregateSupportCut, ...] = (),
        aggregate_distance_cuts: tuple[DddAggregateSupportDistanceCut, ...] = (),
        timed_flow_cover_cuts: tuple[DddTimedFlowCoverCut, ...] = (),
        resource_rows: tuple[DddAnonymousResourceRow, ...] = (),
        warm_start: DddAnonymousFlowWarmStart | None = None,
        fixed_flow: DddAnonymousFlowFixing | None = None,
        passenger_problem: DddPassengerMasterProblem | None = None,
        fixed_start_movement_problem: DddMovementProblem | None = None,
        progress_callback: Callable[[DddAnonymousMasterProgress], None] | None = None,
    ) -> DddAnonymousFlowResult:
        network.validate()
        if self.integrality_tolerance <= 0:
            raise ValueError("DDD flow integrality tolerance must be positive")
        if any(value <= 0 for value in self.diagnostic_snapshot_seconds):
            raise ValueError("DDD master diagnostic times must be positive")
        if tuple(sorted(set(self.diagnostic_snapshot_seconds))) != (
            self.diagnostic_snapshot_seconds
        ):
            raise ValueError(
                "DDD master diagnostic times must be unique and increasing"
            )
        build_started = perf_counter()
        model = gp.Model("ddd_anonymous_flow")
        model.Params.OutputFlag = int(self.output_flag)
        capacity = len(network.cabin_ids)
        variables = {
            arc.id: model.addVar(
                lb=0.0,
                ub=float(capacity),
                vtype=GRB.INTEGER,
                obj=arc.lower_bound_cost,
                name=f"flow[{index}]",
            )
            for index, arc in enumerate(network.arcs)
        }
        fixed_flow_constraint_count = 0
        if fixed_flow is not None:
            fixed_flow.validate(network)
            for index, item in enumerate(fixed_flow.arc_values):
                model.addConstr(
                    variables[item.arc_id] == item.value,
                    name=f"fixed_flow[{index}]",
                )
            fixed_flow_constraint_count = len(fixed_flow.arc_values)
        source_arcs_by_cabin: dict[int, list[DddLayeredTimeArc]] = {
            cabin_id: [] for cabin_id in network.cabin_ids
        }
        incoming_by_node: dict[str, list[DddLayeredTimeArc]] = {
            node.id: [] for node in network.nodes
        }
        outgoing_by_node: dict[str, list[DddLayeredTimeArc]] = {
            node.id: [] for node in network.nodes
        }
        for arc in network.arcs:
            if arc.cabin_id is not None:
                source_arcs_by_cabin[arc.cabin_id].append(arc)
            if arc.target_node_id is not None:
                incoming_by_node[arc.target_node_id].append(arc)
            if arc.source_node_id is not None:
                outgoing_by_node[arc.source_node_id].append(arc)
        for cabin_id, arcs in source_arcs_by_cabin.items():
            model.addConstr(
                gp.quicksum(variables[arc.id] for arc in arcs) == 1,
                name=f"source[{cabin_id}]",
            )
        for node_index, node in enumerate(network.nodes):
            model.addConstr(
                gp.quicksum(variables[arc.id] for arc in incoming_by_node[node.id])
                == gp.quicksum(variables[arc.id] for arc in outgoing_by_node[node.id]),
                name=f"flow_conservation[{node_index}]",
            )
        fixed_start_structural_constraint_count = (
            _add_fixed_start_structural_capacity_rows(
                model=model,
                network=network,
                flow_variables=variables,
                movement=fixed_start_movement_problem,
            )
            if fixed_start_movement_problem is not None
            else 0
        )
        mandatory_resource_rows = (
            build_ddd_mandatory_resource_rows(
                tuple(window for arc in network.arcs for window in arc.resource_windows)
            )
            if self.include_mandatory_resource_rows
            else ()
        )
        all_resource_rows = (*mandatory_resource_rows, *resource_rows)
        _add_anonymous_resource_rows(
            model=model,
            flow_variables=variables,
            rows=all_resource_rows,
        )
        prefix_variables, tracked_prefix_cabin_count = _add_prefix_conflict_formulation(
            model=model,
            network=network,
            flow_variables=variables,
            cuts=cuts,
        )
        aggregate_threshold_variables = _add_aggregate_support_cuts(
            model=model,
            network=network,
            flow_variables=variables,
            cuts=aggregate_support_cuts,
            distance_cuts=aggregate_distance_cuts,
            capacity=capacity,
        )
        timed_flow_threshold_variables = _add_timed_flow_cover_cuts(
            model=model,
            network=network,
            flow_variables=variables,
            cuts=timed_flow_cover_cuts,
            movement=fixed_start_movement_problem,
            capacity=capacity,
        )
        passenger_model = None
        if passenger_problem is not None:
            from ropeway_skip_stop_optimization.optimization.ddd.passenger_master import (
                add_ddd_passenger_master,
            )

            passenger_model = add_ddd_passenger_master(
                model=model,
                gp=gp,
                grb=GRB,
                network=network,
                movement_flow_variables=variables,
                problem=passenger_problem,
            )
        warm_start_arc_variable_count = 0
        warm_start_prefix_variable_count = 0
        if warm_start is not None:
            for item in warm_start.arc_values:
                variable = variables.get(item.arc_id)
                if variable is None:
                    continue
                variable.Start = float(item.value)
                warm_start_arc_variable_count += 1
            for item in warm_start.prefix_arc_values:
                variable = prefix_variables.get((item.cabin_id, item.arc_id))
                if variable is None:
                    continue
                variable.Start = 1.0
                warm_start_prefix_variable_count += 1
        model.ModelSense = GRB.MINIMIZE
        model.update()
        model_build_seconds = perf_counter() - build_started
        incumbent_improvements: list[DddAnonymousMasterIncumbent] = []
        progress_snapshots: list[DddAnonymousMasterProgress] = []
        pending_snapshot_seconds = list(self.diagnostic_snapshot_seconds)
        best_incumbent = math.inf

        def diagnostic_callback(callback_model: gp.Model, where: int) -> None:
            nonlocal best_incumbent
            if where == GRB.Callback.MIPSOL:
                objective = float(callback_model.cbGet(GRB.Callback.MIPSOL_OBJ))
                if objective < best_incumbent - self.integrality_tolerance:
                    best_incumbent = objective
                    incumbent_improvements.append(
                        DddAnonymousMasterIncumbent(
                            elapsed_seconds=float(
                                callback_model.cbGet(GRB.Callback.RUNTIME)
                            ),
                            objective_value=objective,
                            solution_count=int(
                                callback_model.cbGet(GRB.Callback.MIPSOL_SOLCNT)
                            )
                            + 1,
                        )
                    )
                return
            if where != GRB.Callback.MIP or not pending_snapshot_seconds:
                return
            elapsed = float(callback_model.cbGet(GRB.Callback.RUNTIME))
            if elapsed < pending_snapshot_seconds[0]:
                return
            incumbent = _finite_master_metric(
                callback_model.cbGet(GRB.Callback.MIP_OBJBST)
            )
            bound = _finite_master_metric(callback_model.cbGet(GRB.Callback.MIP_OBJBND))
            absolute_gap, relative_gap = _master_gaps(incumbent, bound)
            while pending_snapshot_seconds and elapsed >= pending_snapshot_seconds[0]:
                snapshot = DddAnonymousMasterProgress(
                    requested_elapsed_seconds=pending_snapshot_seconds.pop(0),
                    elapsed_seconds=elapsed,
                    incumbent_objective=incumbent,
                    best_bound=bound,
                    absolute_gap=absolute_gap,
                    relative_gap=relative_gap,
                    explored_node_count=float(
                        callback_model.cbGet(GRB.Callback.MIP_NODCNT)
                    ),
                    open_node_count=float(
                        callback_model.cbGet(GRB.Callback.MIP_NODLFT)
                    ),
                    simplex_iteration_count=float(
                        callback_model.cbGet(GRB.Callback.MIP_ITRCNT)
                    ),
                    solution_count=int(callback_model.cbGet(GRB.Callback.MIP_SOLCNT)),
                )
                progress_snapshots.append(snapshot)
                if progress_callback is not None:
                    progress_callback(snapshot)

        optimize_started = perf_counter()
        model.optimize(diagnostic_callback)
        optimize_seconds = perf_counter() - optimize_started
        solution_count = int(model.SolCount)
        objective_value = float(model.ObjVal) if solution_count else None
        best_bound = (
            _finite_master_metric(model.ObjBound)
            if model.Status != GRB.INFEASIBLE
            else None
        )
        absolute_gap, relative_gap = _master_gaps(objective_value, best_bound)
        final_progress = DddAnonymousMasterProgress(
            requested_elapsed_seconds=None,
            elapsed_seconds=optimize_seconds,
            incumbent_objective=objective_value,
            best_bound=best_bound,
            absolute_gap=absolute_gap,
            relative_gap=relative_gap,
            explored_node_count=float(model.NodeCount),
            open_node_count=float(getattr(model, "OpenNodeCount", 0.0)),
            simplex_iteration_count=float(model.IterCount),
            solution_count=solution_count,
        )
        progress_snapshots.append(final_progress)
        if progress_callback is not None:
            progress_callback(final_progress)
        if model.Status == GRB.INFEASIBLE:
            return DddAnonymousFlowResult(
                status=DddAnonymousFlowStatus.INFEASIBLE,
                objective_value=None,
                best_bound=None,
                arc_values=(),
                prefix_arc_values=(),
                variable_count=model.NumVars,
                constraint_count=model.NumConstrs,
                prefix_variable_count=len(prefix_variables),
                conflict_constraint_count=len(cuts),
                tracked_prefix_cabin_count=tracked_prefix_cabin_count,
                warm_start_arc_variable_count=warm_start_arc_variable_count,
                warm_start_prefix_variable_count=(warm_start_prefix_variable_count),
                warm_start_projected_cabin_count=(
                    warm_start.projected_cabin_count if warm_start else 0
                ),
                warm_start_complete_cabin_count=(
                    warm_start.complete_cabin_count if warm_start else 0
                ),
                resource_constraint_count=len(all_resource_rows),
                mandatory_resource_constraint_count=len(mandatory_resource_rows),
                additional_resource_constraint_count=len(resource_rows),
                aggregate_support_constraint_count=(
                    len(aggregate_support_cuts) + len(aggregate_distance_cuts)
                ),
                aggregate_threshold_variable_count=len(aggregate_threshold_variables),
                timed_flow_cover_constraint_count=len(timed_flow_cover_cuts),
                timed_flow_threshold_variable_count=len(
                    timed_flow_threshold_variables
                ),
                fixed_start_structural_constraint_count=(
                    fixed_start_structural_constraint_count
                ),
                fixed_flow_constraint_count=fixed_flow_constraint_count,
                solver_status_code=int(model.Status),
                termination_reason="infeasible",
                model_build_seconds=model_build_seconds,
                optimize_seconds=optimize_seconds,
                solution_count=solution_count,
                explored_node_count=float(model.NodeCount),
                open_node_count=float(getattr(model, "OpenNodeCount", 0.0)),
                simplex_iteration_count=float(model.IterCount),
                absolute_gap=absolute_gap,
                relative_gap=relative_gap,
                time_to_first_incumbent_seconds=(
                    incumbent_improvements[0].elapsed_seconds
                    if incumbent_improvements
                    else None
                ),
                incumbent_improvements=tuple(incumbent_improvements),
                progress_snapshots=tuple(progress_snapshots),
            )
        if model.Status != GRB.OPTIMAL:
            raise RuntimeError(f"unexpected DDD flow solver status: {model.Status}")
        values: list[DddAnonymousFlowValue] = []
        for arc in network.arcs:
            raw_value = variables[arc.id].X
            integer_value = round(raw_value)
            if abs(raw_value - integer_value) > self.integrality_tolerance:
                raise RuntimeError("DDD integer flow returned a fractional value")
            if integer_value:
                values.append(DddAnonymousFlowValue(arc.id, integer_value))
        prefix_values: list[DddAnonymousPrefixFlowValue] = []
        for (cabin_id, arc_id), variable in sorted(prefix_variables.items()):
            raw_value = variable.X
            if abs(raw_value - round(raw_value)) > self.integrality_tolerance:
                raise RuntimeError("DDD prefix flow returned a fractional value")
            if round(raw_value):
                prefix_values.append(DddAnonymousPrefixFlowValue(cabin_id, arc_id))
        passenger_solution = (
            passenger_model.extract_solution(tolerance=self.integrality_tolerance)
            if passenger_model is not None
            else None
        )
        return DddAnonymousFlowResult(
            status=DddAnonymousFlowStatus.OPTIMAL,
            objective_value=objective_value,
            best_bound=best_bound,
            arc_values=tuple(values),
            prefix_arc_values=tuple(prefix_values),
            variable_count=model.NumVars,
            constraint_count=model.NumConstrs,
            prefix_variable_count=len(prefix_variables),
            conflict_constraint_count=len(cuts),
            tracked_prefix_cabin_count=tracked_prefix_cabin_count,
            warm_start_arc_variable_count=warm_start_arc_variable_count,
            warm_start_prefix_variable_count=warm_start_prefix_variable_count,
            warm_start_projected_cabin_count=(
                warm_start.projected_cabin_count if warm_start else 0
            ),
            warm_start_complete_cabin_count=(
                warm_start.complete_cabin_count if warm_start else 0
            ),
            resource_constraint_count=len(all_resource_rows),
            mandatory_resource_constraint_count=len(mandatory_resource_rows),
            additional_resource_constraint_count=len(resource_rows),
            aggregate_support_constraint_count=(
                len(aggregate_support_cuts) + len(aggregate_distance_cuts)
            ),
            aggregate_threshold_variable_count=len(aggregate_threshold_variables),
            timed_flow_cover_constraint_count=len(timed_flow_cover_cuts),
            timed_flow_threshold_variable_count=len(timed_flow_threshold_variables),
            fixed_start_structural_constraint_count=(
                fixed_start_structural_constraint_count
            ),
            fixed_flow_constraint_count=fixed_flow_constraint_count,
            passenger_solution=passenger_solution,
            solver_status_code=int(model.Status),
            termination_reason="optimal",
            model_build_seconds=model_build_seconds,
            optimize_seconds=optimize_seconds,
            solution_count=solution_count,
            explored_node_count=float(model.NodeCount),
            open_node_count=float(getattr(model, "OpenNodeCount", 0.0)),
            simplex_iteration_count=float(model.IterCount),
            absolute_gap=absolute_gap,
            relative_gap=relative_gap,
            time_to_first_incumbent_seconds=(
                incumbent_improvements[0].elapsed_seconds
                if incumbent_improvements
                else None
            ),
            incumbent_improvements=tuple(incumbent_improvements),
            progress_snapshots=tuple(progress_snapshots),
        )


def _finite_master_metric(value: object) -> float | None:
    numeric = float(value)
    return numeric if math.isfinite(numeric) and abs(numeric) < GRB.INFINITY else None


def _master_gaps(
    incumbent: float | None,
    bound: float | None,
) -> tuple[float | None, float | None]:
    if incumbent is None or bound is None:
        return None, None
    absolute = max(0.0, incumbent - bound)
    denominator = max(abs(incumbent), 1e-12)
    return absolute, absolute / denominator


def _add_fixed_start_structural_capacity_rows(
    *,
    model: gp.Model,
    network: DddLayeredTimeNetwork,
    flow_variables: dict[str, gp.Var],
    movement: DddMovementProblem,
) -> int:
    """Bound anonymous visit-state flow by physically available fixed starts.

    The anonymous network may exchange cabin identities after a merge and may
    otherwise keep too many units alive in a late visit layer.  For a fixed
    start, however, the deterministic reconverging state sequence determines
    exactly how many CP-SAT route slots exist at every ``(visit, state)``.
    Their count is a necessary lifting condition, independent of route choice
    and event times.
    """

    movement.validate()
    if set(network.cabin_ids) != {start.cabin_id for start in movement.starts}:
        raise ValueError("DDD fixed-start structural rows use different cabins")

    capacity_by_visit_state: dict[tuple[int, str], int] = {}
    for start in movement.starts:
        state_id = start.state_id
        for visit_index in range(start.max_visit_count):
            key = (visit_index, state_id)
            capacity_by_visit_state[key] = capacity_by_visit_state.get(key, 0) + 1
            options = movement.route_options_by_state_id.get(state_id, ())
            if not options:
                raise ValueError(
                    f"DDD fixed-start state {state_id!r} has no route option"
                )
            target_state_ids = {option.to_state_id for option in options}
            if len(target_state_ids) != 1:
                raise ValueError(
                    "DDD fixed-start structural rows require reconverging routes"
                )
            state_id = next(iter(target_state_ids))

    arcs_by_visit_state: dict[tuple[int, str], list[DddLayeredTimeArc]] = {}
    for arc in network.arcs:
        if arc.partial_arc is None:
            continue
        key = (arc.partial_arc.visit_index, arc.partial_arc.from_state_id)
        arcs_by_visit_state.setdefault(key, []).append(arc)

    for row_index, (key, arcs) in enumerate(sorted(arcs_by_visit_state.items())):
        model.addConstr(
            gp.quicksum(flow_variables[arc.id] for arc in arcs)
            <= capacity_by_visit_state.get(key, 0),
            name=f"fixed_start_visit_state_capacity[{row_index}]",
        )
    return len(arcs_by_visit_state)


def _add_aggregate_support_cuts(
    *,
    model: gp.Model,
    network: DddLayeredTimeNetwork,
    flow_variables: dict[str, gp.Var],
    cuts: tuple[DddAggregateSupportCut, ...],
    distance_cuts: tuple[DddAggregateSupportDistanceCut, ...],
    capacity: int,
) -> dict[tuple[int, str, int], gp.Var]:
    """Materialize thresholds required by exact-core and L1-distance cuts."""

    if not cuts and not distance_cuts:
        return {}
    for cut in cuts:
        cut.validate()
    for cut in distance_cuts:
        cut.validate()
    arcs_by_route_key: dict[tuple[int, str], list[DddLayeredTimeArc]] = {}
    for arc in network.arcs:
        if arc.partial_arc is None:
            continue
        key = (arc.partial_arc.visit_index, arc.partial_arc.route_option_id)
        arcs_by_route_key.setdefault(key, []).append(arc)
    route_count_by_key = {
        key: gp.quicksum(flow_variables[arc.id] for arc in arcs)
        for key, arcs in arcs_by_route_key.items()
    }
    threshold_variables: dict[tuple[int, str, int], gp.Var] = {}

    def threshold(
        literal: DddAggregateRouteCountLiteral,
        threshold_count: int,
    ) -> gp.Var:
        if not 1 <= threshold_count <= capacity:
            raise ValueError("DDD aggregate count threshold lies outside [1, K]")
        key = (literal.visit_index, literal.route_option_id, threshold_count)
        variable = threshold_variables.get(key)
        if variable is not None:
            return variable
        route_key = (literal.visit_index, literal.route_option_id)
        expression = route_count_by_key.get(route_key, gp.LinExpr(0.0))
        variable = model.addVar(
            vtype=GRB.BINARY,
            name=f"aggregate_ge[{len(threshold_variables)}]",
        )
        # Together these rows encode b = 1 iff x >= q for integer x in [0, K].
        model.addConstr(
            expression >= threshold_count * variable,
            name=f"aggregate_ge_lb[{len(threshold_variables)}]",
        )
        model.addConstr(
            expression
            <= (threshold_count - 1) + (capacity - threshold_count + 1) * variable,
            name=f"aggregate_ge_ub[{len(threshold_variables)}]",
        )
        threshold_variables[key] = variable
        return variable

    def equality_indicator(literal: DddAggregateRouteCountLiteral) -> object:
        route_key = (literal.visit_index, literal.route_option_id)
        if route_key not in route_count_by_key:
            return 1.0 if literal.count == 0 else 0.0
        if literal.count == 0:
            return 1 - threshold(literal, 1)
        if literal.count == capacity:
            return threshold(literal, capacity)
        if literal.count > capacity:
            raise ValueError("DDD aggregate cut count exceeds fleet size")
        return threshold(literal, literal.count) - threshold(literal, literal.count + 1)

    for cut_index, cut in enumerate(cuts):
        indicators = tuple(equality_indicator(literal) for literal in cut.literals)
        model.addConstr(
            gp.quicksum(indicators) <= len(indicators) - 1,
            name=f"aggregate_support_cut[{cut_index}]",
        )
    for cut_index, cut in enumerate(distance_cuts):
        distance_terms: list[object] = []
        for literal in cut.center:
            route_key = (literal.visit_index, literal.route_option_id)
            if route_key not in route_count_by_key:
                distance_terms.append(float(literal.count))
                continue
            distance_terms.append(float(literal.count))
            distance_terms.extend(
                -threshold(literal, threshold_count)
                for threshold_count in range(1, literal.count + 1)
            )
            distance_terms.extend(
                threshold(literal, threshold_count)
                for threshold_count in range(literal.count + 1, capacity + 1)
            )
        model.addConstr(
            gp.quicksum(distance_terms) >= cut.minimum_distance,
            name=f"aggregate_distance_cut[{cut_index}]",
        )
    return threshold_variables


def _add_timed_flow_cover_cuts(
    *,
    model: gp.Model,
    network: DddLayeredTimeNetwork,
    flow_variables: dict[str, gp.Var],
    cuts: tuple[DddTimedFlowCoverCut, ...],
    movement: DddMovementProblem | None,
    capacity: int,
) -> dict[str, gp.Var]:
    """Materialize sparse CP-certified thresholds over stable timed regions."""

    if not cuts:
        return {}
    if movement is None:
        raise ValueError("DDD timed-flow covers require the fixed-start movement")
    for cut in cuts:
        cut.validate()
    current_regions = tuple(
        (
            arc,
            _ddd_timed_flow_region_for_arc(
                network=network,
                movement=movement,
                arc=arc,
            ),
        )
        for arc in network.arcs
        if arc.kind is not DddLayeredTimeArcKind.SINK
    )
    threshold_variables: dict[str, gp.Var] = {}

    def is_child_region(
        child: DddTimedFlowRegion,
        parent: DddTimedFlowRegion,
    ) -> bool:
        return (
            child.visit_index == parent.visit_index
            and child.route_option_id == parent.route_option_id
            and child.cabin_id == parent.cabin_id
            and parent.source_lower_tick <= child.source_lower_tick
            and child.source_upper_tick <= parent.source_upper_tick
            and parent.target_lower_tick <= child.target_lower_tick
            and child.target_upper_tick <= parent.target_upper_tick
            and child.timing_scope is parent.timing_scope
        )

    def threshold(literal: DddTimedFlowThresholdLiteral) -> gp.Var:
        literal.validate()
        if literal.minimum_flow > capacity:
            raise ValueError("DDD timed-flow threshold exceeds fleet size")
        known = threshold_variables.get(literal.id)
        if known is not None:
            return known
        matching_variables = tuple(
            flow_variables[arc.id]
            for arc, region in current_regions
            if is_child_region(region, literal.region)
        )
        expression = gp.quicksum(matching_variables)
        index = len(threshold_variables)
        variable = model.addVar(
            vtype=GRB.BINARY,
            name=f"timed_flow_ge[{index}]",
        )
        model.addConstr(
            expression >= literal.minimum_flow * variable,
            name=f"timed_flow_ge_lb[{index}]",
        )
        model.addConstr(
            expression
            <= (literal.minimum_flow - 1)
            + (capacity - literal.minimum_flow + 1) * variable,
            name=f"timed_flow_ge_ub[{index}]",
        )
        threshold_variables[literal.id] = variable
        return variable

    for cut_index, cut in enumerate(cuts):
        indicators = tuple(threshold(literal) for literal in cut.literals)
        model.addConstr(
            gp.quicksum(indicators) <= len(indicators) - 1,
            name=f"timed_flow_cover[{cut_index}]",
        )
    return threshold_variables


@dataclass(frozen=True)
class DddAnonymousFlowWarmStartProjector:
    """Project a selected physical route support onto a refined time network."""

    def project(
        self,
        problem: DddNetworkTimeProblem,
        network: DddLayeredTimeNetwork,
        paths: tuple[DddPartialTimedPath, ...],
        *,
        cuts: tuple[DddSupportConflictCut, ...] = (),
    ) -> DddAnonymousFlowWarmStart:
        problem.validate()
        network.validate()
        # Warm starts are most useful while only the time discretization
        # changes. Once prefix cuts are active, constructing their labelled
        # formulation dominates and a route projection cannot reduce that
        # work; keeping it disabled also avoids biasing anonymous tails.
        if not paths or cuts:
            return DddAnonymousFlowWarmStart((), (), 0, 0)
        starts_by_cabin = {
            start.cabin_id: start for start in problem.movement_problem.starts
        }
        options_by_id = {
            option.id: option for option in problem.movement_problem.route_options
        }
        source_arcs_by_cabin: dict[int, list[DddLayeredTimeArc]] = {}
        outgoing_by_node: dict[str, list[DddLayeredTimeArc]] = {}
        for arc in network.arcs:
            if arc.cabin_id is not None:
                source_arcs_by_cabin.setdefault(arc.cabin_id, []).append(arc)
            if arc.source_node_id is not None:
                outgoing_by_node.setdefault(arc.source_node_id, []).append(arc)

        aggregate: dict[str, int] = {}
        prefix_values: list[DddAnonymousPrefixFlowValue] = []
        projected_cabin_count = 0
        complete_cabin_count = 0
        for path in sorted(paths, key=lambda item: item.cabin_id):
            start = starts_by_cabin.get(path.cabin_id)
            if start is None:
                continue
            current_tick = start.time_tick
            current_node_id: str | None = None
            projected_arc_ids: list[str] = []
            for visit_index, option_id in enumerate(path.route_option_ids):
                option = options_by_id[option_id]
                current_tick += option.duration_tick
                candidates = (
                    source_arcs_by_cabin.get(path.cabin_id, ())
                    if visit_index == 0
                    else outgoing_by_node.get(current_node_id or "", ())
                )
                matches = tuple(
                    arc
                    for arc in candidates
                    if arc.partial_arc is not None
                    and arc.partial_arc.visit_index == visit_index
                    and arc.partial_arc.route_option_id == option_id
                    and arc.partial_arc.target_cell.contains_tick(current_tick)
                )
                if len(matches) != 1:
                    break
                selected = matches[0]
                projected_arc_ids.append(selected.id)
                current_node_id = selected.target_node_id
            if not projected_arc_ids:
                continue
            projected_cabin_count += 1
            if len(projected_arc_ids) == len(path.route_option_ids):
                sinks = tuple(
                    arc
                    for arc in outgoing_by_node.get(current_node_id or "", ())
                    if arc.kind is DddLayeredTimeArcKind.SINK
                )
                if len(sinks) == 1:
                    projected_arc_ids.append(sinks[0].id)
                    complete_cabin_count += 1
            for arc_id in projected_arc_ids:
                aggregate[arc_id] = aggregate.get(arc_id, 0) + 1
            prefix_values.extend(
                DddAnonymousPrefixFlowValue(path.cabin_id, arc_id)
                for arc_id in projected_arc_ids[1:]
            )

        return DddAnonymousFlowWarmStart(
            arc_values=tuple(
                DddAnonymousFlowValue(arc_id, value)
                for arc_id, value in sorted(aggregate.items())
            ),
            prefix_arc_values=tuple(
                sorted(prefix_values, key=lambda item: (item.cabin_id, item.arc_id))
            ),
            projected_cabin_count=projected_cabin_count,
            complete_cabin_count=complete_cabin_count,
        )


@dataclass(frozen=True)
class DddRecoveredScheduleFlowProjector:
    """Project complete exact schedules onto every arc of a DDD network."""

    def refine_discretization(
        self,
        problem: DddNetworkTimeProblem,
        schedules: tuple[DddRecoveredSchedule, ...],
    ) -> DddNetworkTimeProblem:
        """Isolate every recovered event tick before fixing its anonymous flow."""

        problem.validate()
        self._validate_schedule_set(problem, schedules)
        boundaries_by_state = {
            partition.state_id: set(partition.boundaries_ticks)
            for partition in problem.discretization.partitions
        }
        for schedule in schedules:
            for event in schedule.events[1:]:
                boundaries = boundaries_by_state.get(event.state_id)
                if boundaries is None:
                    raise ValueError(
                        "DDD recovered schedule references a state without a partition"
                    )
                first = min(boundaries)
                last = max(boundaries)
                if not first <= event.time_tick < last:
                    raise ValueError(
                        "DDD recovered event lies outside its time partition"
                    )
                boundaries.add(event.time_tick)
                if event.time_tick + 1 < last:
                    boundaries.add(event.time_tick + 1)
        refined = DddTimeDiscretization(
            tuple(
                DddTimePartition.from_ticks(
                    partition.state_id,
                    tuple(sorted(boundaries_by_state[partition.state_id])),
                )
                for partition in problem.discretization.partitions
            )
        )
        result = problem.with_discretization(refined)
        result.validate()
        return result

    def project(
        self,
        problem: DddNetworkTimeProblem,
        network: DddLayeredTimeNetwork,
        schedules: tuple[DddRecoveredSchedule, ...],
    ) -> DddAnonymousFlowFixing:
        problem.validate()
        network.validate()
        self._validate_schedule_set(problem, schedules)
        if tuple(sorted(network.cabin_ids)) != tuple(
            schedule.cabin_id for schedule in sorted(
                schedules, key=lambda item: item.cabin_id
            )
        ):
            raise ValueError("DDD schedule and network cabin sets differ")

        starts_by_cabin = {
            start.cabin_id: start for start in problem.movement_problem.starts
        }
        source_arcs_by_cabin: dict[int, list[DddLayeredTimeArc]] = {}
        outgoing_by_node: dict[str, list[DddLayeredTimeArc]] = {}
        for arc in network.arcs:
            if arc.cabin_id is not None:
                source_arcs_by_cabin.setdefault(arc.cabin_id, []).append(arc)
            if arc.source_node_id is not None:
                outgoing_by_node.setdefault(arc.source_node_id, []).append(arc)

        aggregate = {arc.id: 0 for arc in network.arcs}
        for schedule in sorted(schedules, key=lambda item: item.cabin_id):
            start = starts_by_cabin[schedule.cabin_id]
            first = schedule.events[0]
            if (
                first.event_index != 0
                or first.state_id != start.state_id
                or first.time_tick != start.time_tick
            ):
                raise ValueError("DDD recovered schedule start is inconsistent")
            current_node_id: str | None = None
            for visit_index, (option_id, target_event) in enumerate(
                zip(
                    schedule.route_option_ids,
                    schedule.events[1:],
                    strict=True,
                )
            ):
                candidates = (
                    source_arcs_by_cabin.get(schedule.cabin_id, ())
                    if visit_index == 0
                    else outgoing_by_node.get(current_node_id or "", ())
                )
                matches = tuple(
                    arc
                    for arc in candidates
                    if arc.partial_arc is not None
                    and arc.partial_arc.visit_index == visit_index
                    and arc.partial_arc.route_option_id == option_id
                    and arc.partial_arc.target_cell.contains_tick(
                        target_event.time_tick
                    )
                )
                if len(matches) != 1:
                    raise ValueError(
                        "DDD recovered schedule has no unique timed network arc at "
                        f"cabin={schedule.cabin_id}, visit={visit_index}"
                    )
                selected = matches[0]
                aggregate[selected.id] += 1
                current_node_id = selected.target_node_id
            sinks = tuple(
                arc
                for arc in outgoing_by_node.get(current_node_id or "", ())
                if arc.kind is DddLayeredTimeArcKind.SINK
            )
            if len(sinks) != 1:
                raise ValueError("DDD recovered schedule has no unique sink arc")
            aggregate[sinks[0].id] += 1

        result = DddAnonymousFlowFixing(
            arc_values=tuple(
                DddAnonymousFlowValue(arc_id, value)
                for arc_id, value in sorted(aggregate.items())
            ),
            projected_cabin_count=len(schedules),
        )
        result.validate(network)
        return result

    @staticmethod
    def _validate_schedule_set(
        problem: DddNetworkTimeProblem,
        schedules: tuple[DddRecoveredSchedule, ...],
    ) -> None:
        starts_by_cabin = {
            start.cabin_id: start for start in problem.movement_problem.starts
        }
        schedule_ids = tuple(
            schedule.cabin_id
            for schedule in sorted(schedules, key=lambda item: item.cabin_id)
        )
        if schedule_ids != tuple(sorted(starts_by_cabin)):
            raise ValueError("DDD fixed-flow projection needs one schedule per cabin")
        options_by_id = {
            option.id: option for option in problem.movement_problem.route_options
        }
        for schedule in schedules:
            if len(schedule.events) != len(schedule.route_option_ids) + 1:
                raise ValueError("DDD recovered schedule event and route counts differ")
            if not schedule.route_option_ids:
                raise ValueError("DDD fixed-flow schedule must contain a movement arc")
            start = starts_by_cabin[schedule.cabin_id]
            if len(schedule.route_option_ids) > start.max_visit_count:
                raise ValueError("DDD recovered schedule exceeds its visit bound")
            first = schedule.events[0]
            if (
                first.event_index != 0
                or first.state_id != start.state_id
                or first.time_tick != start.time_tick
            ):
                raise ValueError("DDD recovered schedule start is inconsistent")
            for visit_index, (option_id, source, target) in enumerate(
                zip(
                    schedule.route_option_ids,
                    schedule.events[:-1],
                    schedule.events[1:],
                    strict=True,
                )
            ):
                option = options_by_id.get(option_id)
                if option is None:
                    raise ValueError("DDD recovered schedule references an unknown route")
                if (
                    source.event_index != visit_index
                    or target.event_index != visit_index + 1
                    or source.state_id != option.from_state_id
                    or target.state_id != option.to_state_id
                    or target.time_tick != source.time_tick + option.duration_tick
                ):
                    raise ValueError("DDD recovered schedule route chain is inconsistent")


def _add_anonymous_resource_rows(
    *,
    model: gp.Model,
    flow_variables: dict[str, gp.Var],
    rows: tuple[DddAnonymousResourceRow, ...],
) -> None:
    row_ids: set[str] = set()
    for row_index, row in enumerate(rows):
        row.validate()
        if row.id in row_ids:
            raise ValueError(f"duplicate DDD anonymous resource row id: {row.id}")
        row_ids.add(row.id)
        unknown_arc_ids = {
            term.timed_arc_id
            for term in row.terms
            if term.timed_arc_id not in flow_variables
        }
        if unknown_arc_ids:
            raise ValueError(
                "DDD anonymous resource row references unknown arcs: "
                f"{sorted(unknown_arc_ids)}"
            )
        model.addConstr(
            gp.quicksum(
                term.coefficient * flow_variables[term.timed_arc_id]
                for term in row.terms
            )
            <= row.right_hand_side,
            name=f"anonymous_resource[{row_index}]",
        )


def _add_prefix_conflict_formulation(
    *,
    model: gp.Model,
    network: DddLayeredTimeNetwork,
    flow_variables: dict[str, gp.Var],
    cuts: tuple[DddSupportConflictCut, ...],
) -> tuple[dict[tuple[int, str], gp.Var], int]:
    if not cuts:
        return {}, 0
    cut_ids: set[str] = set()
    known_route_option_ids = {
        arc.partial_arc.route_option_id
        for arc in network.arcs
        if arc.partial_arc is not None
    }
    max_visit_by_cabin: dict[int, int] = {}
    for cut in cuts:
        cut.validate()
        if cut.id in cut_ids:
            raise ValueError(f"duplicate DDD flow conflict cut id: {cut.id}")
        cut_ids.add(cut.id)
        _validate_prefix_cut_literals(
            cut,
            cabin_ids=set(network.cabin_ids),
            known_route_option_ids=known_route_option_ids,
        )
        for literal in cut.literals:
            max_visit_by_cabin[literal.cabin_id] = max(
                max_visit_by_cabin.get(literal.cabin_id, 0),
                literal.visit_index,
            )

    source_arcs = tuple(
        arc for arc in network.arcs if arc.kind is DddLayeredTimeArcKind.SOURCE
    )
    movement_arcs = tuple(
        arc for arc in network.arcs if arc.kind is DddLayeredTimeArcKind.MOVEMENT
    )
    sink_arcs = tuple(
        arc for arc in network.arcs if arc.kind is DddLayeredTimeArcKind.SINK
    )
    node_by_id = {node.id: node for node in network.nodes}
    incoming_movement_by_node: dict[str, list[DddLayeredTimeArc]] = {
        node.id: [] for node in network.nodes
    }
    outgoing_movement_by_node: dict[str, list[DddLayeredTimeArc]] = {
        node.id: [] for node in network.nodes
    }
    sink_by_node: dict[str, list[DddLayeredTimeArc]] = {
        node.id: [] for node in network.nodes
    }
    for arc in movement_arcs:
        if arc.target_node_id is not None:
            incoming_movement_by_node[arc.target_node_id].append(arc)
        if arc.source_node_id is not None:
            outgoing_movement_by_node[arc.source_node_id].append(arc)
    for arc in sink_arcs:
        if arc.source_node_id is not None:
            sink_by_node[arc.source_node_id].append(arc)

    prefix_variables: dict[tuple[int, str], gp.Var] = {}
    prefix_variables_by_arc_id: dict[str, list[gp.Var]] = {}
    active_depths = {
        cabin_id: max_visit_index
        for cabin_id, max_visit_index in max_visit_by_cabin.items()
        if max_visit_index > 0
    }
    for cabin_id, max_visit_index in sorted(active_depths.items()):
        for arc in movement_arcs:
            partial_arc = arc.partial_arc
            if partial_arc is None or partial_arc.visit_index > max_visit_index:
                continue
            variable = model.addVar(
                vtype=GRB.BINARY,
                name=f"prefix_flow[{cabin_id},{len(prefix_variables)}]",
            )
            prefix_variables[(cabin_id, arc.id)] = variable
            prefix_variables_by_arc_id.setdefault(arc.id, []).append(variable)
        for arc in sink_arcs:
            if (
                arc.source_node_id is None
                or node_by_id[arc.source_node_id].layer_index > max_visit_index
            ):
                continue
            variable = model.addVar(
                vtype=GRB.BINARY,
                name=f"prefix_sink[{cabin_id},{len(prefix_variables)}]",
            )
            prefix_variables[(cabin_id, arc.id)] = variable
            prefix_variables_by_arc_id.setdefault(arc.id, []).append(variable)

    for cabin_id, max_visit_index in sorted(active_depths.items()):
        for node_index, node in enumerate(network.nodes):
            if node.layer_index > max_visit_index:
                continue
            if node.layer_index == 1:
                incoming = gp.quicksum(
                    flow_variables[arc.id]
                    for arc in source_arcs
                    if arc.cabin_id == cabin_id and arc.target_node_id == node.id
                )
            else:
                incoming = gp.quicksum(
                    prefix_variables[(cabin_id, arc.id)]
                    for arc in incoming_movement_by_node[node.id]
                    if (cabin_id, arc.id) in prefix_variables
                )
            outgoing = gp.quicksum(
                prefix_variables[(cabin_id, arc.id)]
                for arc in (
                    *outgoing_movement_by_node[node.id],
                    *sink_by_node[node.id],
                )
                if (cabin_id, arc.id) in prefix_variables
            )
            model.addConstr(
                incoming == outgoing,
                name=f"prefix_conservation[{cabin_id},{node_index}]",
            )

    for arc_index, arc in enumerate((*movement_arcs, *sink_arcs)):
        tracked = prefix_variables_by_arc_id.get(arc.id, ())
        if tracked:
            model.addConstr(
                gp.quicksum(tracked) <= flow_variables[arc.id],
                name=f"prefix_link[{arc_index}]",
            )

    for cut_index, cut in enumerate(cuts):
        model.addConstr(
            gp.quicksum(
                _prefix_literal_expression(
                    literal=literal,
                    source_arcs=source_arcs,
                    movement_arcs=movement_arcs,
                    flow_variables=flow_variables,
                    prefix_variables=prefix_variables,
                )
                for literal in cut.literals
            )
            <= cut.right_hand_side,
            name=f"prefix_conflict[{cut_index}]",
        )
    return (
        prefix_variables,
        len(active_depths),
    )


def _validate_prefix_cut_literals(
    cut: DddSupportConflictCut,
    *,
    cabin_ids: set[int],
    known_route_option_ids: set[str],
) -> None:
    by_cabin: dict[int, dict[int, DddSupportLiteral]] = {}
    for literal in cut.literals:
        if literal.cabin_id not in cabin_ids:
            raise ValueError(
                f"DDD flow conflict cut references unknown cabin {literal.cabin_id}"
            )
        if literal.route_option_id not in known_route_option_ids:
            raise ValueError(
                "DDD flow conflict cut references unknown route option "
                f"{literal.route_option_id!r}"
            )
        visits = by_cabin.setdefault(literal.cabin_id, {})
        if literal.visit_index in visits:
            raise ValueError(
                "DDD flow conflict cut has multiple literals for one cabin visit"
            )
        visits[literal.visit_index] = literal
    for cabin_id, visits in by_cabin.items():
        if (
            cut.provenance != "exact_cp_sat_no_wait_cabin_path_core"
            and set(visits) != set(range(max(visits) + 1))
        ):
            raise ValueError(
                f"DDD flow conflict cut cabin {cabin_id} is not a complete prefix"
            )


def _prefix_literal_expression(
    *,
    literal: DddSupportLiteral,
    source_arcs: tuple[DddLayeredTimeArc, ...],
    movement_arcs: tuple[DddLayeredTimeArc, ...],
    flow_variables: dict[str, gp.Var],
    prefix_variables: dict[tuple[int, str], gp.Var],
) -> gp.LinExpr:
    if literal.visit_index == 0:
        return gp.quicksum(
            flow_variables[arc.id]
            for arc in source_arcs
            if arc.cabin_id == literal.cabin_id
            and arc.partial_arc is not None
            and arc.partial_arc.route_option_id == literal.route_option_id
        )
    return gp.quicksum(
        prefix_variables[(literal.cabin_id, arc.id)]
        for arc in movement_arcs
        if arc.partial_arc is not None
        and arc.partial_arc.visit_index == literal.visit_index
        and arc.partial_arc.route_option_id == literal.route_option_id
        and (literal.cabin_id, arc.id) in prefix_variables
    )


@dataclass(frozen=True)
class DddAnonymousFlowDecomposer:
    def decompose(
        self,
        network: DddLayeredTimeNetwork,
        result: DddAnonymousFlowResult,
    ) -> tuple[DddPartialTimedPath, ...]:
        network.validate()
        if result.status is not DddAnonymousFlowStatus.OPTIMAL:
            raise ValueError("only an optimal DDD flow can be decomposed")
        arcs_by_id = network.arcs_by_id
        residual = {item.arc_id: item.value for item in result.arc_values}
        outgoing: dict[str, list[DddLayeredTimeArc]] = {}
        source_by_cabin: dict[int, list[DddLayeredTimeArc]] = {}
        for arc in network.arcs:
            if arc.source_node_id is not None:
                outgoing.setdefault(arc.source_node_id, []).append(arc)
            if arc.cabin_id is not None:
                source_by_cabin.setdefault(arc.cabin_id, []).append(arc)
        for arcs in outgoing.values():
            arcs.sort(key=_decomposition_arc_key)
        for arcs in source_by_cabin.values():
            arcs.sort(key=lambda item: item.id)

        prefix_arc_ids_by_cabin: dict[int, set[str]] = {}
        for item in result.prefix_arc_values:
            if item.arc_id not in arcs_by_id:
                raise RuntimeError("DDD prefix flow references an unknown arc")
            prefix_arc_ids_by_cabin.setdefault(item.cabin_id, set()).add(item.arc_id)
        remaining_prefix_arcs = {
            cabin_id: set(arc_ids)
            for cabin_id, arc_ids in prefix_arc_ids_by_cabin.items()
        }
        partial_arcs_by_cabin: dict[int, list[DddPartialTimedArc]] = {}
        current_node_by_cabin: dict[int, str | None] = {}

        # Reserve every labelled prefix before extending any cabin through the
        # anonymous tail. Otherwise an early cabin can consume a shared arc
        # that a later cabin's prefix variable explicitly requires.
        for cabin_id in sorted(prefix_arc_ids_by_cabin):
            prefix_arc_ids = prefix_arc_ids_by_cabin[cabin_id]
            source_arc = _first_source_for_prefix(
                source_by_cabin.get(cabin_id, ()),
                outgoing=outgoing,
                prefix_arc_ids=prefix_arc_ids,
                residual=residual,
            )
            if source_arc is None or source_arc.partial_arc is None:
                raise RuntimeError(f"DDD flow has no source path for cabin {cabin_id}")
            _consume(source_arc.id, residual)
            partial_arcs = [source_arc.partial_arc]
            node_id = source_arc.target_node_id
            while node_id is not None:
                next_arc = _first_positive_prefix_arc(
                    outgoing.get(node_id, ()),
                    residual=residual,
                    prefix_arc_ids=prefix_arc_ids,
                )
                if next_arc is None:
                    break
                _consume(next_arc.id, residual)
                remaining_prefix_arcs.get(cabin_id, set()).discard(next_arc.id)
                if next_arc.kind is DddLayeredTimeArcKind.SINK:
                    node_id = None
                    continue
                if next_arc.partial_arc is None:
                    raise RuntimeError("DDD movement flow arc has no partial arc")
                partial_arcs.append(next_arc.partial_arc)
                node_id = next_arc.target_node_id
            partial_arcs_by_cabin[cabin_id] = partial_arcs
            current_node_by_cabin[cabin_id] = node_id
        unconsumed_prefix = {
            cabin_id: tuple(sorted(arc_ids))
            for cabin_id, arc_ids in remaining_prefix_arcs.items()
            if arc_ids
        }
        if unconsumed_prefix:
            raise RuntimeError(
                f"DDD decomposition did not consume prefix flow: {unconsumed_prefix}"
            )

        paths: list[DddPartialTimedPath] = []
        for cabin_id in sorted(network.cabin_ids):
            partial_arcs = partial_arcs_by_cabin.get(cabin_id)
            node_id = current_node_by_cabin.get(cabin_id)
            if partial_arcs is None:
                source_arc = _first_positive_arc(
                    source_by_cabin.get(cabin_id, ()),
                    residual,
                )
                if source_arc is None or source_arc.partial_arc is None:
                    raise RuntimeError(
                        f"DDD flow has no source path for cabin {cabin_id}"
                    )
                _consume(source_arc.id, residual)
                partial_arcs = [source_arc.partial_arc]
                node_id = source_arc.target_node_id
            while node_id is not None:
                next_arc = _first_positive_arc(
                    outgoing.get(node_id, ()),
                    residual,
                )
                if next_arc is None:
                    raise RuntimeError("DDD flow path ends before a sink")
                _consume(next_arc.id, residual)
                if next_arc.kind is DddLayeredTimeArcKind.SINK:
                    node_id = None
                    continue
                if next_arc.partial_arc is None:
                    raise RuntimeError("DDD movement flow arc has no partial arc")
                partial_arcs.append(next_arc.partial_arc)
                node_id = next_arc.target_node_id
            paths.append(DddPartialTimedPath(cabin_id, tuple(partial_arcs)))
        leftovers = {arc_id: value for arc_id, value in residual.items() if value}
        unknown = set(residual) - set(arcs_by_id)
        if leftovers or unknown:
            raise RuntimeError(
                f"DDD flow decomposition left residual flow: {leftovers}"
            )
        return tuple(sorted(paths, key=lambda item: item.cabin_id))


@dataclass(frozen=True)
class DddNetworkPathProblemAdapter:
    """Build the resource-free, per-path problem used only for cell lifting.

    Resource usages are deliberately stripped because this adapter checks exact
    event times against selected cells. A successful lift is not a complete
    feasibility certificate; the network refinement solver must subsequently
    validate all lifted paths together against the original movement problem.
    """

    def build(
        self,
        problem: DddNetworkTimeProblem,
        path: DddPartialTimedPath,
    ) -> DddPartialTimeProblem:
        problem.validate()
        starts = tuple(
            start
            for start in problem.movement_problem.starts
            if start.cabin_id == path.cabin_id
        )
        if len(starts) != 1:
            raise ValueError("DDD network path has no unique fixed start")
        terminal_state_id = path.terminal_cell.state_id
        terminal_cost = problem.objective.terminal_cost_by_state_id.get(
            terminal_state_id
        )
        if terminal_cost is None:
            terminal_cost = DddTerminalThresholdCost(
                state_id=terminal_state_id,
                threshold_seconds=0.0,
                before_cost=problem.objective.default_terminal_cost,
                at_or_after_cost=problem.objective.default_terminal_cost,
            )
        movement = replace(
            problem.movement_problem,
            starts=starts,
            route_options=tuple(
                replace(option, resource_usages=())
                for option in problem.movement_problem.route_options
            ),
            resources=(),
        )
        result = DddPartialTimeProblem(
            movement_problem=movement,
            terminal_state_id=terminal_state_id,
            discretization=problem.discretization,
            objective=DddTimeSpaceObjective(
                route_option_costs=problem.objective.route_option_costs,
                terminal_cost=terminal_cost,
            ),
        )
        result.validate()
        return result


def _first_positive_arc(
    arcs: tuple[DddLayeredTimeArc, ...] | list[DddLayeredTimeArc],
    residual: dict[str, int],
) -> DddLayeredTimeArc | None:
    return next((arc for arc in arcs if residual.get(arc.id, 0) > 0), None)


def _first_positive_prefix_arc(
    arcs: tuple[DddLayeredTimeArc, ...] | list[DddLayeredTimeArc],
    *,
    residual: dict[str, int],
    prefix_arc_ids: set[str],
) -> DddLayeredTimeArc | None:
    return next(
        (
            arc
            for arc in arcs
            if arc.id in prefix_arc_ids and residual.get(arc.id, 0) > 0
        ),
        None,
    )


def _first_source_for_prefix(
    arcs: tuple[DddLayeredTimeArc, ...] | list[DddLayeredTimeArc],
    *,
    outgoing: dict[str, list[DddLayeredTimeArc]],
    prefix_arc_ids: set[str],
    residual: dict[str, int],
) -> DddLayeredTimeArc | None:
    if prefix_arc_ids:
        matching = next(
            (
                arc
                for arc in arcs
                if residual.get(arc.id, 0) > 0
                and arc.target_node_id is not None
                and any(
                    outgoing_arc.id in prefix_arc_ids
                    for outgoing_arc in outgoing.get(arc.target_node_id, ())
                )
            ),
            None,
        )
        if matching is not None:
            return matching
    return _first_positive_arc(arcs, residual)


def _decomposition_arc_key(arc: DddLayeredTimeArc) -> tuple[object, ...]:
    if arc.partial_arc is None:
        return (1, math.inf, math.inf, arc.id)
    return (
        0,
        arc.partial_arc.target_cell.lower_seconds,
        arc.partial_arc.target_cell.upper_seconds,
        arc.partial_arc.route_option_id,
        arc.id,
    )


def _consume(arc_id: str, residual: dict[str, int]) -> None:
    value = residual.get(arc_id, 0)
    if value <= 0:
        raise RuntimeError(f"DDD flow arc {arc_id!r} has no residual value")
    residual[arc_id] = value - 1
