from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import math
from typing import Protocol

from ropeway_skip_stop_optimization.optimization.ddd.reference import (
    DddReferenceTrajectory,
)


class DddTrajectoryMasterRowKind(StrEnum):
    RESOURCE_WINDOW = "resource_window"
    MERGE_WINDOW = "merge_window"
    DIRECTED_HEADWAY = "directed_headway"
    PAIR_CONFLICT = "pair_conflict"


class DddTrajectoryMasterRowScope(StrEnum):
    """Describes whether a row can participate in an omitted-column proof."""

    UNIVERSAL = "universal"
    NODE_UNIVERSAL = "node_universal"
    POOL_LOCAL = "pool_local"

    @property
    def certifies_omitted_columns(self) -> bool:
        return self in {
            DddTrajectoryMasterRowScope.UNIVERSAL,
            DddTrajectoryMasterRowScope.NODE_UNIVERSAL,
        }


@dataclass(frozen=True, slots=True)
class DddTrajectoryMasterRow:
    id: str
    kind: DddTrajectoryMasterRowKind
    scope: DddTrajectoryMasterRowScope
    right_hand_side: float
    coefficients: tuple[tuple[str, float], ...]
    provenance: tuple[tuple[str, str], ...] = ()

    def validate(self) -> None:
        if not self.id:
            raise ValueError("trajectory master row ID is required")
        if not isinstance(self.kind, DddTrajectoryMasterRowKind):
            raise ValueError("trajectory master row kind is invalid")
        if not isinstance(self.scope, DddTrajectoryMasterRowScope):
            raise ValueError("trajectory master row scope is invalid")
        if not math.isfinite(self.right_hand_side):
            raise ValueError("trajectory master row RHS must be finite")
        option_ids = tuple(option_id for option_id, _ in self.coefficients)
        if tuple(sorted(set(option_ids))) != option_ids:
            raise ValueError(
                "trajectory master row coefficients must have sorted unique IDs"
            )
        if any(
            not option_id or not math.isfinite(value) or value == 0
            for option_id, value in self.coefficients
        ):
            raise ValueError("trajectory master row coefficients must be finite")
        keys = tuple(key for key, _ in self.provenance)
        if tuple(sorted(set(keys))) != keys or any(
            not key or not value for key, value in self.provenance
        ):
            raise ValueError(
                "trajectory master row provenance must have sorted unique keys"
            )


class DddTrajectoryCoefficientOracle(Protocol):
    """Exact coefficient predicate for current and future trajectory columns."""

    def coefficient(
        self,
        row_id: str,
        trajectory: DddReferenceTrajectory,
    ) -> float: ...


@dataclass(slots=True)
class DddTrajectoryMasterRowPool:
    """Deterministic row archive with explicit proof-scope accounting."""

    _rows_by_id: dict[str, DddTrajectoryMasterRow]

    def __init__(self) -> None:
        self._rows_by_id = {}

    @property
    def rows(self) -> tuple[DddTrajectoryMasterRow, ...]:
        return tuple(self._rows_by_id[key] for key in sorted(self._rows_by_id))

    @property
    def certifying_rows(self) -> tuple[DddTrajectoryMasterRow, ...]:
        return tuple(
            row for row in self.rows if row.scope.certifies_omitted_columns
        )

    def add(self, row: DddTrajectoryMasterRow) -> bool:
        row.validate()
        existing = self._rows_by_id.get(row.id)
        if existing is None:
            self._rows_by_id[row.id] = row
            return True
        if existing != row:
            raise ValueError(
                "trajectory master row ID maps to inconsistent row payloads"
            )
        return False

    def extend(self, rows: tuple[DddTrajectoryMasterRow, ...]) -> int:
        return sum(self.add(row) for row in rows)

