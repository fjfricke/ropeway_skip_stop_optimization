from __future__ import annotations

from dataclasses import dataclass, field

from ropeway_skip_stop_optimization.optimization.ddd.arc_flow_network import (
    DddArcFlowResourceClique,
    build_ddd_arc_flow_resource_cliques_from_intervals,
)
from ropeway_skip_stop_optimization.optimization.ddd.arc_flow_preparation import (
    DddPreparedArcFlowProblem,
)


DddArcFlowCliqueSignature = tuple[tuple[str, int], ...]


@dataclass(frozen=True, slots=True)
class DddArcFlowResourceSeparationResult:
    """All violated selected-arc cliques and the subset not added before."""

    violations: tuple[DddArcFlowResourceClique, ...]
    new_violations: tuple[DddArcFlowResourceClique, ...]

    @property
    def duplicate_violation_count(self) -> int:
        return len(self.violations) - len(self.new_violations)


@dataclass(slots=True)
class DddArcFlowSelectedResourceCliqueSeparator:
    """Separate exact resource cliques only on selected integer Movement arcs.

    Every returned row is globally valid: all of its interval occurrences cover
    one common resource tick.  Separation on every integer candidate is therefore
    sufficient for an exact lazy-constraint MILP, while avoiding construction of
    the complete all-arc clique index.
    """

    prepared: DddPreparedArcFlowProblem
    _materialized_signatures: set[DddArcFlowCliqueSignature] = field(
        default_factory=set,
        init=False,
        repr=False,
    )

    def __post_init__(self) -> None:
        self.prepared.validate()

    @property
    def materialized_row_count(self) -> int:
        return len(self._materialized_signatures)

    def separate(
        self,
        selected_arc_ids: frozenset[str] | set[str],
    ) -> DddArcFlowResourceSeparationResult:
        unknown = set(selected_arc_ids) - set(self.prepared.arc_by_id)
        if unknown:
            raise ValueError(
                "resource separation references an unknown Movement arc: "
                f"{min(unknown)}"
            )
        intervals = tuple(
            interval
            for arc in self.prepared.arcs
            if arc.id in selected_arc_ids
            for interval in arc.resource_intervals
        )
        violations = tuple(
            clique
            for clique in build_ddd_arc_flow_resource_cliques_from_intervals(
                intervals
            )
            if sum(coefficient for _, coefficient in clique.coefficients) > 1
        )
        new_violations = tuple(
            clique
            for clique in violations
            if clique.coefficients not in self._materialized_signatures
        )
        return DddArcFlowResourceSeparationResult(
            violations=violations,
            new_violations=new_violations,
        )

    def mark_materialized(
        self,
        cliques: tuple[DddArcFlowResourceClique, ...],
    ) -> None:
        for clique in cliques:
            clique.validate()
            if clique.coefficients in self._materialized_signatures:
                raise ValueError("resource clique was materialized more than once")
            self._materialized_signatures.add(clique.coefficients)
