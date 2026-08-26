from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass

from ropeway_skip_stop_optimization.optimization.ddd.models import (
    DddFixedStart,
    DddMovementProblem,
)
from ropeway_skip_stop_optimization.optimization.ddd.reference import (
    DddReferenceResourceOccurrence,
)
from ropeway_skip_stop_optimization.optimization.ddd.route_topology import (
    deterministic_route_state_ids,
)
from ropeway_skip_stop_optimization.optimization.ddd.trajectory_column_generation import (
    DddTrajectoryWaitingDomain,
)
from ropeway_skip_stop_optimization.optimization.ddd.trajectory_problem import (
    DddTrajectoryWaitingPolicy,
)
from ropeway_skip_stop_optimization.optimization.ddd.time_ticks import (
    ddd_seconds_to_tick,
)


@dataclass(frozen=True, order=True, slots=True)
class DddArcFlowResourceInterval:
    resource_id: str
    arc_id: str
    usage_index: int
    enter_tick: int
    clear_with_headway_tick: int

    def validate(self) -> None:
        if not self.resource_id or not self.arc_id:
            raise ValueError("arc-flow resource interval IDs must be nonempty")
        if self.usage_index < 0 or self.enter_tick < 0:
            raise ValueError("arc-flow resource interval indices are invalid")
        if self.clear_with_headway_tick <= self.enter_tick:
            raise ValueError("arc-flow resource interval must be nonempty")

    def contains(self, tick: int) -> bool:
        return self.enter_tick <= tick < self.clear_with_headway_tick


@dataclass(frozen=True, order=True, slots=True)
class DddArcFlowBoundaryInterval:
    resource_id: str
    cabin_id: int
    enter_tick: int
    clear_with_headway_tick: int

    def validate(self) -> None:
        if not self.resource_id or self.cabin_id < 0:
            raise ValueError("arc-flow boundary interval identity is invalid")
        if self.enter_tick < 0 or self.clear_with_headway_tick <= self.enter_tick:
            raise ValueError("arc-flow boundary interval is invalid")

    def overlaps(self, interval: DddArcFlowResourceInterval) -> bool:
        return (
            self.resource_id == interval.resource_id
            and self.enter_tick < interval.clear_with_headway_tick
            and interval.enter_tick < self.clear_with_headway_tick
        )


def build_ddd_arc_flow_boundary_intervals(
    movement_problem: DddMovementProblem,
    occurrences: tuple[DddReferenceResourceOccurrence, ...],
) -> tuple[DddArcFlowBoundaryInterval, ...]:
    movement_problem.validate()
    resources = movement_problem.resources_by_id
    result: list[DddArcFlowBoundaryInterval] = []
    for occurrence in occurrences:
        resource = resources[occurrence.resource_id]
        clear_tick = ddd_seconds_to_tick(
            occurrence.leader_clear_time_seconds
        ) + occurrence.separation_after_tick(resource)
        if clear_tick <= 0:
            continue
        interval = DddArcFlowBoundaryInterval(
            resource_id=occurrence.resource_id,
            cabin_id=occurrence.cabin_id,
            enter_tick=max(
                0,
                ddd_seconds_to_tick(occurrence.follower_enter_time_seconds),
            ),
            clear_with_headway_tick=clear_tick,
        )
        interval.validate()
        result.append(interval)
    return tuple(sorted(result))


@dataclass(frozen=True, order=True, slots=True)
class DddCabinTimeExpandedArc:
    id: str
    cabin_id: int
    visit_index: int
    source_tick: int
    source_active: bool
    option_id: str | None
    wait_tick: int
    target_tick: int
    target_active: bool
    resource_intervals: tuple[DddArcFlowResourceInterval, ...] = ()

    @property
    def source_node(self) -> tuple[int, int, bool]:
        return (self.visit_index, self.source_tick, self.source_active)

    @property
    def target_node(self) -> tuple[int, int, bool]:
        return (self.visit_index + 1, self.target_tick, self.target_active)

    def validate(self) -> None:
        if not self.id or self.cabin_id < 0 or self.visit_index < 0:
            raise ValueError("time-expanded arc identity is invalid")
        if self.source_tick < 0 or self.target_tick < self.source_tick:
            raise ValueError("time-expanded arc times are invalid")
        if self.wait_tick < 0:
            raise ValueError("time-expanded arc waiting is invalid")
        if self.source_active and self.option_id is None:
            raise ValueError("active time-expanded arc needs a route option")
        if not self.source_active and self.option_id is not None:
            raise ValueError("inactive time-expanded arc cannot use a route option")
        for interval in self.resource_intervals:
            interval.validate()
            if interval.arc_id != self.id:
                raise ValueError("resource interval references another arc")


@dataclass(frozen=True, slots=True)
class DddCabinTimeExpandedNetwork:
    cabin_id: int
    start: DddFixedStart
    state_ids: tuple[str, ...]
    arcs: tuple[DddCabinTimeExpandedArc, ...]

    @property
    def nodes(self) -> tuple[tuple[int, int, bool], ...]:
        return tuple(
            sorted(
                {
                    node
                    for arc in self.arcs
                    for node in (arc.source_node, arc.target_node)
                }
            )
        )

    @property
    def arcs_by_id(self) -> dict[str, DddCabinTimeExpandedArc]:
        return {arc.id: arc for arc in self.arcs}

    def validate(self) -> None:
        self.start.validate()
        if self.cabin_id != self.start.cabin_id:
            raise ValueError("time-expanded network and start cabin differ")
        if len(self.state_ids) != self.start.max_visit_count + 1:
            raise ValueError("time-expanded state sequence has invalid length")
        if not self.arcs or len(self.arcs_by_id) != len(self.arcs):
            raise ValueError("time-expanded network arcs must be nonempty and unique")
        for arc in self.arcs:
            arc.validate()
            if arc.cabin_id != self.cabin_id:
                raise ValueError("time-expanded network mixes cabin IDs")
        first = tuple(arc for arc in self.arcs if arc.visit_index == 0)
        if not first or any(
            (arc.source_tick, arc.source_active) != (self.start.time_tick, True)
            for arc in first
        ):
            raise ValueError("time-expanded network has an invalid source")
        final = tuple(
            arc
            for arc in self.arcs
            if arc.visit_index == self.start.max_visit_count - 1
        )
        if not final or not all(not arc.target_active for arc in final):
            raise ValueError("time-expanded network does not cover the horizon")


@dataclass(frozen=True, slots=True)
class DddCabinTimeExpandedNetworkBuilder:
    """Build the exact layered route DAG used by fixed-start DDD pricing."""

    def build(
        self,
        movement_problem: DddMovementProblem,
        start: DddFixedStart,
        *,
        waiting_policy: DddTrajectoryWaitingPolicy | None = None,
        boundary_intervals: tuple[DddArcFlowBoundaryInterval, ...] = (),
    ) -> DddCabinTimeExpandedNetwork:
        movement_problem.validate()
        start.validate()
        waiting_policy = waiting_policy or DddTrajectoryWaitingPolicy()
        waiting_policy.validate(movement_problem.core)
        for boundary_interval in boundary_intervals:
            boundary_interval.validate()
        if waiting_policy.domain is not DddTrajectoryWaitingDomain.NO_WAIT:
            raise ValueError("fixed-K arc-flow v1 supports no-wait only")
        states = deterministic_route_state_ids(
            movement_problem,
            start_state_id=start.state_id,
            max_visit_count=start.max_visit_count,
            error_context="fixed-K arc-flow network",
        )
        resources = movement_problem.resources_by_id
        nodes: set[tuple[int, bool]] = {(start.time_tick, True)}
        arcs: list[DddCabinTimeExpandedArc] = []
        for visit_index, state_id in enumerate(states[:-1]):
            next_nodes: set[tuple[int, bool]] = set()
            for source_index, (source_tick, source_active) in enumerate(sorted(nodes)):
                options = (
                    movement_problem.route_options_by_state_id[state_id]
                    if source_active
                    else (None,)
                )
                for option_index, option in enumerate(options):
                    target_tick = (
                        source_tick
                        if option is None
                        else source_tick + option.duration_tick
                    )
                    target_active = (
                        option is not None
                        and target_tick <= movement_problem.operational_end_tick
                    )
                    arc_id = (
                        f"c{start.cabin_id}:v{visit_index}:s{source_index}:"
                        f"o{option_index}:t{source_tick}"
                    )
                    intervals: list[DddArcFlowResourceInterval] = []
                    if option is not None:
                        for usage_index, usage in enumerate(option.resource_usages):
                            enter_tick = source_tick + usage.follower_enter_offset_tick
                            if enter_tick > movement_problem.operational_end_tick:
                                continue
                            resource = resources[usage.resource_id]
                            clear_tick = (
                                source_tick
                                + usage.leader_clear_offset_tick
                                + usage.separation_after_tick(
                                    resource.minimum_headway_tick
                                )
                            )
                            interval = DddArcFlowResourceInterval(
                                resource_id=usage.resource_id,
                                arc_id=arc_id,
                                usage_index=usage_index,
                                enter_tick=enter_tick,
                                clear_with_headway_tick=clear_tick,
                            )
                            interval.validate()
                            intervals.append(interval)
                    if any(
                        boundary.overlaps(interval)
                        for boundary in boundary_intervals
                        for interval in intervals
                    ):
                        continue
                    arcs.append(
                        DddCabinTimeExpandedArc(
                            id=arc_id,
                            cabin_id=start.cabin_id,
                            visit_index=visit_index,
                            source_tick=source_tick,
                            source_active=source_active,
                            option_id=None if option is None else option.id,
                            wait_tick=0,
                            target_tick=target_tick,
                            target_active=target_active,
                            resource_intervals=tuple(intervals),
                        )
                    )
                    next_nodes.add((target_tick, target_active))
            nodes = next_nodes
        result = DddCabinTimeExpandedNetwork(
            cabin_id=start.cabin_id,
            start=start,
            state_ids=states,
            arcs=tuple(arcs),
        )
        result.validate()
        return result


@dataclass(frozen=True, slots=True)
class DddArcFlowResourceClique:
    id: str
    resource_id: str
    anchor_tick: int
    coefficients: tuple[tuple[str, int], ...]

    def validate(self) -> None:
        if not self.id or not self.resource_id or self.anchor_tick < 0:
            raise ValueError("arc-flow resource clique identity is invalid")
        if not self.coefficients:
            raise ValueError("arc-flow resource clique must not be empty")
        if tuple(sorted(self.coefficients)) != self.coefficients:
            raise ValueError("arc-flow resource clique terms must be sorted")
        if any(
            not arc_id or coefficient <= 0 for arc_id, coefficient in self.coefficients
        ):
            raise ValueError("arc-flow resource clique coefficient is invalid")


def build_ddd_arc_flow_resource_cliques(
    networks: tuple[DddCabinTimeExpandedNetwork, ...],
) -> tuple[DddArcFlowResourceClique, ...]:
    """Return all inclusion-maximal interval cliques, deterministically deduplicated."""

    intervals_by_resource: dict[str, list[DddArcFlowResourceInterval]] = defaultdict(
        list
    )
    for network in networks:
        network.validate()
        for arc in network.arcs:
            for interval in arc.resource_intervals:
                intervals_by_resource[interval.resource_id].append(interval)

    result: list[DddArcFlowResourceClique] = []
    for resource_id, intervals in sorted(intervals_by_resource.items()):
        ordered = tuple(sorted(intervals))
        starts: dict[int, list[int]] = defaultdict(list)
        ends: dict[int, list[int]] = defaultdict(list)
        for interval_index, interval in enumerate(ordered):
            starts[interval.enter_tick].append(interval_index)
            ends[interval.clear_with_headway_tick].append(interval_index)
        active_mask = 0
        candidate_anchor_by_mask: dict[int, int] = {}
        for tick in sorted(set(starts) | set(ends)):
            for interval_index in ends.get(tick, ()):
                active_mask &= ~(1 << interval_index)
            if tick not in starts:
                continue
            for interval_index in starts[tick]:
                active_mask |= 1 << interval_index
            candidate_anchor_by_mask.setdefault(active_mask, tick)
        maximal_masks: list[int] = []
        for mask in sorted(
            candidate_anchor_by_mask,
            key=lambda item: (-item.bit_count(), candidate_anchor_by_mask[item], item),
        ):
            if any(mask & other == mask for other in maximal_masks):
                continue
            maximal_masks.append(mask)
        anchor_by_coefficients: dict[tuple[tuple[str, int], ...], int] = {}
        for mask in maximal_masks:
            coefficients = tuple(
                sorted(
                    Counter(
                        ordered[index].arc_id for index in _set_bit_indices(mask)
                    ).items()
                )
            )
            anchor = candidate_anchor_by_mask[mask]
            anchor_by_coefficients[coefficients] = min(
                anchor,
                anchor_by_coefficients.get(coefficients, anchor),
            )
        maximal = tuple(
            sorted(anchor_by_coefficients.items(), key=lambda item: (item[1], item[0]))
        )
        for index, (coefficients, anchor) in enumerate(maximal):
            clique = DddArcFlowResourceClique(
                id=f"{resource_id}:q{index}:t{anchor}",
                resource_id=resource_id,
                anchor_tick=anchor,
                coefficients=coefficients,
            )
            clique.validate()
            result.append(clique)
    return tuple(result)


def _set_bit_indices(mask: int) -> tuple[int, ...]:
    indices: list[int] = []
    while mask:
        least_significant = mask & -mask
        indices.append(least_significant.bit_length() - 1)
        mask ^= least_significant
    return tuple(indices)
