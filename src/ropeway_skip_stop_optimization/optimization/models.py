from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from ropeway_skip_stop_optimization.models import MovementPlan


@dataclass(frozen=True)
class FixedCabinStart:
    cabin_id: int
    node_id: str

    def validate(self) -> None:
        if self.cabin_id < 0:
            raise ValueError("fixed cabin start cabin_id must be nonnegative")
        if not self.node_id:
            raise ValueError("fixed cabin start needs a node_id")


class MilpV0VariableStrategy(Enum):
    DENSE = "dense"
    SPARSE_REACHABILITY = "sparse_reachability"


@dataclass(frozen=True)
class MilpV0Config:
    horizon_steps: int
    fixed_starts: tuple[FixedCabinStart, ...]
    allow_move_arcs: bool = True
    allow_wait_arcs: bool = True
    allow_skip_arcs: bool = True
    variable_strategy: MilpV0VariableStrategy = MilpV0VariableStrategy.DENSE

    def validate(self) -> None:
        if self.horizon_steps < 0:
            raise ValueError("MILP v0 horizon_steps must be nonnegative")
        if not self.fixed_starts:
            raise ValueError("MILP v0 needs at least one fixed cabin start")
        cabin_ids = [start.cabin_id for start in self.fixed_starts]
        if len(cabin_ids) != len(set(cabin_ids)):
            raise ValueError("MILP v0 fixed cabin starts must have unique cabin ids")
        for start in self.fixed_starts:
            start.validate()
        if not (self.allow_move_arcs or self.allow_wait_arcs):
            raise ValueError("MILP v0 needs at least one allowed arc kind")


@dataclass(frozen=True)
class MilpV0VariableIndex:
    x_keys: tuple[tuple[int, int, str], ...]
    y_keys: tuple[tuple[int, int, str], ...]
    node_ids_by_cabin_time: dict[tuple[int, int], tuple[str, ...]]
    arc_ids_by_cabin_time: dict[tuple[int, int], tuple[str, ...]]
    out_arc_ids_by_cabin_time_node: dict[tuple[int, int, str], tuple[str, ...]]
    in_arc_ids_by_cabin_time_node: dict[tuple[int, int, str], tuple[str, ...]]
    reachable_cabin_ids_by_time_node: dict[tuple[int, str], tuple[int, ...]]


@dataclass(frozen=True)
class MilpSolveMetadata:
    status: str
    objective_value: float | None
    selected_arc_ids_by_cabin: dict[int, tuple[str, ...]]
    variable_count: int
    constraint_count: int


@dataclass(frozen=True)
class MilpMovementPlanResult:
    movement_plan: MovementPlan | None
    metadata: MilpSolveMetadata


@dataclass(frozen=True)
class MovementPlanValidationIssue:
    code: str
    message: str
    time_step: int | None = None
    cabin_id: int | None = None
    node_id: str | None = None
    arc_id: str | None = None
    constraint_id: str | None = None


@dataclass(frozen=True)
class MovementPlanValidationResult:
    issues: tuple[MovementPlanValidationIssue, ...] = ()

    @property
    def is_valid(self) -> bool:
        return not self.issues

    def raise_for_errors(self) -> None:
        if self.is_valid:
            return
        details = "; ".join(f"{issue.code}: {issue.message}" for issue in self.issues)
        raise ValueError(f"movement plan validation failed: {details}")
