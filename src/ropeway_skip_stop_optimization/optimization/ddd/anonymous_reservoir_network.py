from __future__ import annotations

from collections import Counter, defaultdict, deque
from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256
import heapq
import json
from time import perf_counter

from ropeway_skip_stop_optimization.optimization.ddd.arc_flow_network import (
    DddArcFlowBuildTimeLimitError,
    DddArcFlowResourceClique,
    DddArcFlowResourceInterval,
)
from ropeway_skip_stop_optimization.optimization.ddd.models import (
    DddRouteDecision,
    DddRouteOption,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_arc_flow_problem import (
    DddReservoirArcFlowProblem,
    DddReservoirOperatingMode,
)
from ropeway_skip_stop_optimization.optimization.ddd.time_ticks import (
    ddd_seconds_to_tick,
)


class DddAnonymousReservoirArcKind(StrEnum):
    DISPATCH = "dispatch"
    MOVEMENT = "movement"
    RECOVERY = "recovery"


@dataclass(frozen=True, order=True, slots=True)
class DddAnonymousReservoirNode:
    state_id: str
    time_tick: int

    @property
    def id(self) -> str:
        return f"node::{self.state_id}::t{self.time_tick}"

    def validate(self) -> None:
        if not self.state_id or self.time_tick < 0:
            raise ValueError("anonymous reservoir node is invalid")


@dataclass(frozen=True, slots=True)
class DddAnonymousReservoirArc:
    id: str
    kind: DddAnonymousReservoirArcKind
    source_node_id: str | None
    target_node_id: str | None
    source_state_id: str | None
    target_state_id: str | None
    source_tick: int
    target_tick: int
    option_id: str | None = None
    wait_tick: int = 0
    resource_intervals: tuple[DddArcFlowResourceInterval, ...] = ()

    @property
    def is_dispatch(self) -> bool:
        return self.kind is DddAnonymousReservoirArcKind.DISPATCH

    @property
    def is_movement(self) -> bool:
        return self.kind is DddAnonymousReservoirArcKind.MOVEMENT

    @property
    def is_recovery(self) -> bool:
        return self.kind is DddAnonymousReservoirArcKind.RECOVERY

    def validate(self) -> None:
        if not self.id or self.source_tick < 0 or self.target_tick < self.source_tick:
            raise ValueError("anonymous reservoir arc identity or timing is invalid")
        if self.is_dispatch:
            if (
                self.source_node_id is not None
                or self.target_node_id is None
                or self.option_id is not None
            ):
                raise ValueError("dispatch arc endpoints are invalid")
        elif self.is_recovery:
            if (
                self.source_node_id is None
                or self.target_node_id is not None
                or self.option_id is not None
            ):
                raise ValueError("recovery arc endpoints are invalid")
        elif (
            self.source_node_id is None
            or self.target_node_id is None
            or self.option_id is None
            or self.target_tick <= self.source_tick
        ):
            raise ValueError("movement arc endpoints are invalid")
        for interval in self.resource_intervals:
            interval.validate()
            if interval.arc_id != self.id:
                raise ValueError("resource interval references another reservoir arc")


@dataclass(frozen=True, slots=True)
class DddAnonymousReservoirNetwork:
    problem_fingerprint: str
    dispatch_ticks: tuple[int, ...]
    all_stop_seed_dispatch_ticks: tuple[int, ...]
    nodes: tuple[DddAnonymousReservoirNode, ...]
    arcs: tuple[DddAnonymousReservoirArc, ...]
    resource_cliques: tuple[DddArcFlowResourceClique, ...]
    fingerprint: str

    @property
    def node_by_id(self) -> dict[str, DddAnonymousReservoirNode]:
        return {node.id: node for node in self.nodes}

    @property
    def arc_by_id(self) -> dict[str, DddAnonymousReservoirArc]:
        return {arc.id: arc for arc in self.arcs}

    @property
    def dispatch_arcs(self) -> tuple[DddAnonymousReservoirArc, ...]:
        return tuple(arc for arc in self.arcs if arc.is_dispatch)

    @property
    def movement_arcs(self) -> tuple[DddAnonymousReservoirArc, ...]:
        return tuple(arc for arc in self.arcs if arc.is_movement)

    @property
    def recovery_arcs(self) -> tuple[DddAnonymousReservoirArc, ...]:
        return tuple(arc for arc in self.arcs if arc.is_recovery)

    def validate(self, problem: DddReservoirArcFlowProblem) -> None:
        problem.validate()
        if self.problem_fingerprint != problem.fingerprint:
            raise ValueError("reservoir network belongs to another problem")
        node_ids = tuple(node.id for node in self.nodes)
        arc_ids = tuple(arc.id for arc in self.arcs)
        if len(node_ids) != len(set(node_ids)) or len(arc_ids) != len(set(arc_ids)):
            raise ValueError("reservoir node and arc ids must be unique")
        known_nodes = set(node_ids)
        known_arcs = set(arc_ids)
        for node in self.nodes:
            node.validate()
        for arc in self.arcs:
            arc.validate()
            if (
                arc.source_node_id is not None
                and arc.source_node_id not in known_nodes
            ) or (
                arc.target_node_id is not None
                and arc.target_node_id not in known_nodes
            ):
                raise ValueError("reservoir arc references an unknown node")
        if not self.dispatch_arcs or not self.recovery_arcs:
            raise ValueError("reservoir network needs dispatch and recovery arcs")
        if tuple(sorted(set(self.dispatch_ticks))) != self.dispatch_ticks:
            raise ValueError("reservoir dispatch ticks must be sorted and unique")
        if not set(self.all_stop_seed_dispatch_ticks) <= set(self.dispatch_ticks):
            raise ValueError("all-stop seed anchors are missing from dispatch grid")
        if any(
            not set(arc_id for arc_id, _ in clique.coefficients) <= known_arcs
            for clique in self.resource_cliques
        ):
            raise ValueError("reservoir clique references an unknown arc")
        if self.fingerprint != _network_fingerprint(self):
            raise ValueError("reservoir network fingerprint is inconsistent")


@dataclass(frozen=True, slots=True)
class DddAnonymousReservoirNetworkBuilder:
    """Build the exact finite-policy state-time DAG without cabin labels."""

    def build(
        self,
        problem: DddReservoirArcFlowProblem,
        *,
        deadline_monotonic: float | None = None,
    ) -> DddAnonymousReservoirNetwork:
        problem.validate()
        dispatch_ticks = _dispatch_ticks(problem)
        seed_ticks = _all_stop_seed_dispatch_ticks(problem)
        dispatch_ticks = tuple(sorted(set(dispatch_ticks) | set(seed_ticks)))
        entry_nodes = {
            DddAnonymousReservoirNode(problem.entry_state_id, tick)
            for tick in dispatch_ticks
        }
        known = {node.id: node for node in entry_nodes}
        queue = [(node.time_tick, node.state_id, node.id) for node in entry_nodes]
        heapq.heapify(queue)
        raw_arcs: dict[str, DddAnonymousReservoirArc] = {}
        options_by_state = problem.movement_core.route_options_by_state_id
        resources = problem.movement_core.resources_by_id
        processed: set[str] = set()
        while queue:
            _check_deadline(deadline_monotonic)
            _, _, node_id = heapq.heappop(queue)
            if node_id in processed:
                continue
            processed.add(node_id)
            node = known[node_id]
            if (
                node.state_id == problem.entry_state_id
                and problem.service_end_tick <= node.time_tick <= problem.operational_end_tick
            ):
                arc = DddAnonymousReservoirArc(
                    id=f"recover::t{node.time_tick}",
                    kind=DddAnonymousReservoirArcKind.RECOVERY,
                    source_node_id=node.id,
                    target_node_id=None,
                    source_state_id=node.state_id,
                    target_state_id=None,
                    source_tick=node.time_tick,
                    target_tick=node.time_tick,
                )
                raw_arcs[arc.id] = arc
            for option in options_by_state.get(node.state_id, ()):
                if not _option_allowed(problem, node.time_tick, option):
                    continue
                for wait_tick in _wait_ticks(problem, node.time_tick, option):
                    target_tick = node.time_tick + option.duration_tick + wait_tick
                    if target_tick > problem.operational_end_tick:
                        continue
                    target = DddAnonymousReservoirNode(option.to_state_id, target_tick)
                    if target.id not in known:
                        known[target.id] = target
                        heapq.heappush(queue, (target.time_tick, target.state_id, target.id))
                    arc_id = (
                        f"move::{node.state_id}::t{node.time_tick}::{option.id}::"
                        f"w{wait_tick}"
                    )
                    intervals = []
                    for usage_index, usage in enumerate(option.resource_usages):
                        enter_tick = (
                            node.time_tick
                            + usage.follower_enter_offset_tick
                            + usage.follower_enter_wait_coefficient * wait_tick
                        )
                        if enter_tick > problem.operational_end_tick:
                            continue
                        resource = resources[usage.resource_id]
                        clear_tick = (
                            node.time_tick
                            + usage.leader_clear_offset_tick
                            + usage.leader_clear_wait_coefficient * wait_tick
                            + usage.separation_after_tick(
                                resource.minimum_headway_tick
                            )
                        )
                        intervals.append(
                            DddArcFlowResourceInterval(
                                resource_id=usage.resource_id,
                                arc_id=arc_id,
                                usage_index=usage_index,
                                enter_tick=enter_tick,
                                clear_with_headway_tick=clear_tick,
                            )
                        )
                    raw_arcs[arc_id] = DddAnonymousReservoirArc(
                        id=arc_id,
                        kind=DddAnonymousReservoirArcKind.MOVEMENT,
                        source_node_id=node.id,
                        target_node_id=target.id,
                        source_state_id=node.state_id,
                        target_state_id=target.state_id,
                        source_tick=node.time_tick,
                        target_tick=target_tick,
                        option_id=option.id,
                        wait_tick=wait_tick,
                        resource_intervals=tuple(intervals),
                    )
        _check_deadline(deadline_monotonic)
        dispatch_arcs = {
            f"dispatch::t{tick}": DddAnonymousReservoirArc(
                id=f"dispatch::t{tick}",
                kind=DddAnonymousReservoirArcKind.DISPATCH,
                source_node_id=None,
                target_node_id=DddAnonymousReservoirNode(
                    problem.entry_state_id, tick
                ).id,
                source_state_id=None,
                target_state_id=problem.entry_state_id,
                source_tick=tick,
                target_tick=tick,
            )
            for tick in dispatch_ticks
        }
        raw_arcs.update(dispatch_arcs)
        kept_nodes, kept_arcs = _prune_to_complete_paths(known, raw_arcs)
        intervals = tuple(
            interval
            for arc in kept_arcs.values()
            for interval in arc.resource_intervals
        )
        cliques = _build_resource_cliques_linear_sweep(
            intervals,
            deadline_monotonic=deadline_monotonic,
        )
        partial = DddAnonymousReservoirNetwork(
            problem_fingerprint=problem.fingerprint,
            dispatch_ticks=tuple(
                tick
                for tick in dispatch_ticks
                if f"dispatch::t{tick}" in kept_arcs
            ),
            all_stop_seed_dispatch_ticks=seed_ticks,
            nodes=tuple(sorted(kept_nodes.values())),
            arcs=tuple(sorted(kept_arcs.values(), key=lambda item: item.id)),
            resource_cliques=cliques,
            fingerprint="pending",
        )
        result = DddAnonymousReservoirNetwork(
            problem_fingerprint=partial.problem_fingerprint,
            dispatch_ticks=partial.dispatch_ticks,
            all_stop_seed_dispatch_ticks=partial.all_stop_seed_dispatch_ticks,
            nodes=partial.nodes,
            arcs=partial.arcs,
            resource_cliques=partial.resource_cliques,
            fingerprint=_network_fingerprint(partial),
        )
        result.validate(problem)
        return result


def _option_allowed(
    problem: DddReservoirArcFlowProblem,
    source_tick: int,
    option: DddRouteOption,
) -> bool:
    if (
        problem.operating_mode is DddReservoirOperatingMode.ALL_STOP
        and option.decision is DddRouteDecision.SKIP
    ):
        return False
    return True


def _wait_ticks(
    problem: DddReservoirArcFlowProblem,
    source_tick: int,
    option: DddRouteOption,
) -> tuple[int, ...]:
    if option.decision is DddRouteDecision.SKIP:
        return (0,)
    assert option.platform_exit_offset_seconds is not None
    base_exit = source_tick + ddd_seconds_to_tick(option.platform_exit_offset_seconds)
    result = []
    for seconds in problem.waiting_policy.wait_values_seconds(option.station_id):
        tick = ddd_seconds_to_tick(seconds)
        actual_exit = base_exit + tick
        if (
            tick == 0
            or problem.service_start_tick <= actual_exit <= problem.service_end_tick
        ):
            result.append(tick)
    return tuple(result)


def _dispatch_ticks(problem: DddReservoirArcFlowProblem) -> tuple[int, ...]:
    step = ddd_seconds_to_tick(problem.dispatch_step_seconds)
    if step <= 0:
        raise ValueError("dispatch grid step must occupy at least one tick")
    return tuple(range(0, problem.warmup_tick, step))


def _all_stop_seed_dispatch_ticks(
    problem: DddReservoirArcFlowProblem,
) -> tuple[int, ...]:
    count = problem.all_stop_maximum_cabin_count
    cycle = problem.all_stop_cycle_seconds
    if count is None or cycle is None:
        return ()
    first = problem.warmup_seconds - cycle
    spacing = cycle / count
    ticks = tuple(
        ddd_seconds_to_tick(first + index * spacing) for index in range(count)
    )
    if any(tick < 0 or tick >= problem.warmup_tick for tick in ticks):
        raise ValueError("warm-up does not contain all all-stop dispatch anchors")
    if len(set(ticks)) != len(ticks):
        raise ValueError("all-stop dispatch anchors collapse on the exact tick grid")
    return tuple(sorted(ticks))


def _prune_to_complete_paths(
    nodes: dict[str, DddAnonymousReservoirNode],
    arcs: dict[str, DddAnonymousReservoirArc],
) -> tuple[
    dict[str, DddAnonymousReservoirNode],
    dict[str, DddAnonymousReservoirArc],
]:
    incoming: dict[str, list[DddAnonymousReservoirArc]] = defaultdict(list)
    for arc in arcs.values():
        if arc.target_node_id is not None:
            incoming[arc.target_node_id].append(arc)
    useful_nodes = {
        arc.source_node_id
        for arc in arcs.values()
        if arc.is_recovery and arc.source_node_id is not None
    }
    queue = deque(sorted(useful_nodes))
    useful_arcs = {arc.id for arc in arcs.values() if arc.is_recovery}
    while queue:
        node_id = queue.popleft()
        for arc in incoming.get(node_id, ()):
            useful_arcs.add(arc.id)
            if arc.source_node_id is not None and arc.source_node_id not in useful_nodes:
                useful_nodes.add(arc.source_node_id)
                queue.append(arc.source_node_id)
    kept_arcs = {arc_id: arcs[arc_id] for arc_id in useful_arcs}
    kept_nodes = {node_id: nodes[node_id] for node_id in useful_nodes}
    return kept_nodes, kept_arcs


def _check_deadline(deadline_monotonic: float | None) -> None:
    if deadline_monotonic is not None and perf_counter() >= deadline_monotonic:
        raise DddArcFlowBuildTimeLimitError(
            "reservoir arc-flow budget expired during network construction"
        )


def _build_resource_cliques_linear_sweep(
    intervals: tuple[DddArcFlowResourceInterval, ...],
    *,
    deadline_monotonic: float | None,
) -> tuple[DddArcFlowResourceClique, ...]:
    """Enumerate maximal interval cliques without quadratic subset tests.

    Immediately after a start tick, the active set is non-maximal exactly when
    another interval starts before every active interval ends.  That next set
    strictly contains the current one.  Otherwise the current active set is a
    maximal clique.  This is the standard interval-graph sweep criterion.
    """

    by_resource: dict[str, list[DddArcFlowResourceInterval]] = defaultdict(list)
    for interval in intervals:
        interval.validate()
        by_resource[interval.resource_id].append(interval)
    result = []
    for resource_id, resource_intervals in sorted(by_resource.items()):
        _check_deadline(deadline_monotonic)
        ordered = tuple(sorted(resource_intervals))
        starts: dict[int, list[int]] = defaultdict(list)
        for index, interval in enumerate(ordered):
            starts[interval.enter_tick].append(index)
        start_ticks = sorted(starts)
        active: set[int] = set()
        end_heap: list[tuple[int, int]] = []
        anchor_by_coefficients: dict[tuple[tuple[str, int], ...], int] = {}
        for position, tick in enumerate(start_ticks):
            if position % 256 == 0:
                _check_deadline(deadline_monotonic)
            while end_heap and end_heap[0][0] <= tick:
                _, index = heapq.heappop(end_heap)
                active.discard(index)
            for index in starts[tick]:
                active.add(index)
                heapq.heappush(
                    end_heap,
                    (ordered[index].clear_with_headway_tick, index),
                )
            next_start = (
                start_ticks[position + 1]
                if position + 1 < len(start_ticks)
                else None
            )
            earliest_end = end_heap[0][0]
            if next_start is not None and next_start < earliest_end:
                continue
            coefficients = tuple(
                sorted(Counter(ordered[index].arc_id for index in active).items())
            )
            anchor_by_coefficients.setdefault(coefficients, tick)
        for index, (coefficients, anchor) in enumerate(
            sorted(anchor_by_coefficients.items(), key=lambda item: (item[1], item[0]))
        ):
            clique = DddArcFlowResourceClique(
                id=f"{resource_id}:q{index}:t{anchor}",
                resource_id=resource_id,
                anchor_tick=anchor,
                coefficients=coefficients,
            )
            clique.validate()
            result.append(clique)
    return tuple(result)


def _network_fingerprint(network: DddAnonymousReservoirNetwork) -> str:
    payload = {
        "problem": network.problem_fingerprint,
        "dispatch": network.dispatch_ticks,
        "seed_dispatch": network.all_stop_seed_dispatch_ticks,
        "nodes": [(node.state_id, node.time_tick) for node in network.nodes],
        "arcs": [
            (
                arc.id,
                arc.kind.value,
                arc.source_node_id,
                arc.target_node_id,
                arc.option_id,
                arc.source_tick,
                arc.target_tick,
                arc.wait_tick,
                tuple(
                    (
                        interval.resource_id,
                        interval.enter_tick,
                        interval.clear_with_headway_tick,
                    )
                    for interval in arc.resource_intervals
                ),
            )
            for arc in network.arcs
        ],
        "cliques": [
            (clique.resource_id, clique.anchor_tick, clique.coefficients)
            for clique in network.resource_cliques
        ],
    }
    return sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
