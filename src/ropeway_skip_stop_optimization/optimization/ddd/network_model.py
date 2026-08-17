from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import math

from ropeway_skip_stop_optimization.optimization.ddd.resource_time import (
    DddTimedResourceUsageWindow,
)
from ropeway_skip_stop_optimization.optimization.ddd.time_space import (
    DddPartialTimedArc,
    DddTimeCell,
)


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
