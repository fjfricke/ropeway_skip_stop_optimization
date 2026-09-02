from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Callable

from ropeway_skip_stop_optimization.optimization.ddd.arc_flow_network import (
    DddArcFlowBoundaryInterval,
    DddArcFlowResourceClique,
    DddCabinTimeExpandedArc,
    DddCabinTimeExpandedNetwork,
    DddCabinTimeExpandedNetworkBuilder,
    build_ddd_arc_flow_boundary_intervals,
    build_ddd_arc_flow_resource_cliques,
)
from ropeway_skip_stop_optimization.optimization.ddd.fixed_k import (
    DddFixedKTrajectoryProblem,
)
from ropeway_skip_stop_optimization.optimization.ddd.models import DddMovementProblem


DddArcFlowPreparationPhaseHook = Callable[[str], None]


@dataclass(frozen=True, slots=True)
class DddPreparedArcFlowProblem:
    """Immutable solver input shared by every complete arc-flow formulation."""

    problem: DddFixedKTrajectoryProblem
    movement: DddMovementProblem
    boundary_intervals: tuple[DddArcFlowBoundaryInterval, ...]
    networks: tuple[DddCabinTimeExpandedNetwork, ...]
    arcs: tuple[DddCabinTimeExpandedArc, ...]
    resource_cliques: tuple[DddArcFlowResourceClique, ...]
    network_build_seconds: float
    labeled_resource_cliques_complete: bool = True

    @property
    def arc_by_id(self) -> dict[str, DddCabinTimeExpandedArc]:
        return {arc.id: arc for arc in self.arcs}

    def validate(self) -> None:
        self.problem.validate()
        if self.movement != (
            self.problem.resolved_trajectory_problem.structural_movement_problem
        ):
            raise ValueError("prepared arc-flow Movement problem is inconsistent")
        if not self.networks:
            raise ValueError("prepared arc-flow problem needs cabin networks")
        expected_cabins = self.problem.resolved_trajectory_problem.cabin_ids
        if tuple(network.cabin_id for network in self.networks) != expected_cabins:
            raise ValueError("prepared arc-flow cabin networks are not canonical")
        arc_ids = tuple(arc.id for arc in self.arcs)
        if len(set(arc_ids)) != len(arc_ids):
            raise ValueError("prepared arc-flow arc IDs must be unique")
        if self.arcs != tuple(arc for network in self.networks for arc in network.arcs):
            raise ValueError("prepared arc-flow arc order is inconsistent")
        known_arc_ids = set(arc_ids)
        if any(
            not set(arc_id for arc_id, _ in clique.coefficients) <= known_arc_ids
            for clique in self.resource_cliques
        ):
            raise ValueError("prepared arc-flow clique references an unknown arc")
        if self.network_build_seconds < 0:
            raise ValueError("prepared arc-flow build time must be nonnegative")


@dataclass(frozen=True, slots=True)
class DddArcFlowProblemPreparer:
    """Build the deterministic time-expanded domain exactly once per trial."""

    def build(
        self,
        problem: DddFixedKTrajectoryProblem,
        *,
        phase_hook: DddArcFlowPreparationPhaseHook | None = None,
        build_labeled_resource_cliques: bool = True,
        deadline_monotonic: float | None = None,
    ) -> DddPreparedArcFlowProblem:
        problem.validate()
        started = perf_counter()
        resolved = problem.resolved_trajectory_problem
        movement = resolved.structural_movement_problem
        boundary_intervals = build_ddd_arc_flow_boundary_intervals(
            movement,
            problem.boundary_context.resource_occurrences,
        )
        if phase_hook is not None:
            phase_hook("network_build")
        networks = tuple(
            DddCabinTimeExpandedNetworkBuilder().build(
                movement,
                start,
                waiting_policy=resolved.waiting_policy,
                boundary_intervals=boundary_intervals,
                deadline_monotonic=deadline_monotonic,
            )
            for start in movement.starts
        )
        if phase_hook is not None:
            phase_hook("resource_index_build")
        resource_cliques = (
            build_ddd_arc_flow_resource_cliques(
                networks,
                deadline_monotonic=deadline_monotonic,
            )
            if build_labeled_resource_cliques
            else ()
        )
        prepared = DddPreparedArcFlowProblem(
            problem=problem,
            movement=movement,
            boundary_intervals=boundary_intervals,
            networks=networks,
            arcs=tuple(arc for network in networks for arc in network.arcs),
            resource_cliques=resource_cliques,
            network_build_seconds=perf_counter() - started,
            labeled_resource_cliques_complete=build_labeled_resource_cliques,
        )
        prepared.validate()
        return prepared
