from __future__ import annotations

from types import SimpleNamespace

import pytest

from ropeway_skip_stop_optimization.optimization.ddd.network_refinement_model import (
    DddNetworkValidationResult,
    DddNetworkValidationStatus,
    DddTimeSplit,
    DddWaitingSplit,
)
from ropeway_skip_stop_optimization.optimization.ddd.reference import (
    DddReferenceConflict,
    DddReferenceTrajectory,
    DddReferenceVisit,
)
from ropeway_skip_stop_optimization.optimization.ddd.resource_conflict_phase import (
    DddResourceConflictPhaseSolver,
    build_ddd_waiting_conflict_split_proofs,
)
from ropeway_skip_stop_optimization.optimization.ddd.models import DddRouteDecision
from ropeway_skip_stop_optimization.optimization.ddd.support_master import (
    DddSupportSelection,
)
from ropeway_skip_stop_optimization.optimization.ddd.time_space import (
    DddTimeDiscretization,
    DddTimePartition,
    DddWaitingInterval,
)


def _solver(*, use_universal_rows: bool = True) -> DddResourceConflictPhaseSolver:
    return DddResourceConflictPhaseSolver(
        use_universal_resource_rows=use_universal_rows,
        max_new_constraints_per_type=10,
        max_time_splits=2,
        max_prefix_variable_count=100,
        max_tracked_prefix_cabin_count=2,
        max_prefix_visit_index=2,
        tolerance_seconds=1e-9,
    )


def _discretization() -> DddTimeDiscretization:
    return DddTimeDiscretization((DddTimePartition("A", (0.0, 10.0)),))


def test_resource_conflict_phase_preserves_existing_split_without_conflicts() -> None:
    discretization = _discretization()
    split = DddTimeSplit("A", 4.0)
    refined = discretization.split(
        state_id="A",
        boundary_seconds=4.0,
        tolerance_seconds=1e-9,
    )

    result = _solver().solve(
        network=SimpleNamespace(),  # type: ignore[arg-type]
        paths=(),
        validation=DddNetworkValidationResult(
            status=DddNetworkValidationStatus.NOT_RUN,
            solution=None,
            detail=None,
            conflicts=(),
            cuts=(),
        ),
        initial_time_splits=(split,),
        refined_discretization=refined,
        active_resource_rows=(),
        existing_prefix_cuts=(),
        existing_prefix_cut_ids=frozenset(),
    )

    assert result.time_splits == (split,)
    assert result.refined_discretization == refined
    assert result.resource_time_split_count == 0
    assert result.new_resource_rows == ()
    assert result.new_prefix_cuts == ()
    assert not result.prefix_budget_exhausted
    assert not result.invalid_missing_support
    assert result.has_refinement


def test_resource_conflict_phase_rejects_conflict_without_support() -> None:
    conflict = DddReferenceConflict("merge", 0, 0, 1, 0, 1e-6)

    result = _solver(use_universal_rows=False).solve(
        network=SimpleNamespace(),  # type: ignore[arg-type]
        paths=(),
        validation=DddNetworkValidationResult(
            status=DddNetworkValidationStatus.RESOURCE_CONFLICT,
            solution=None,
            detail="conflict",
            conflicts=(conflict,),
            cuts=(),
            support_selection=None,
        ),
        initial_time_splits=(),
        refined_discretization=_discretization(),
        active_resource_rows=(),
        existing_prefix_cuts=(),
        existing_prefix_cut_ids=frozenset(),
    )

    assert result.invalid_missing_support
    assert not result.has_refinement


def test_resource_conflict_phase_rejects_nonpositive_constraint_limit() -> None:
    with pytest.raises(ValueError, match="constraint limit"):
        DddResourceConflictPhaseSolver(
            use_universal_resource_rows=True,
            max_new_constraints_per_type=0,
            max_time_splits=1,
            max_prefix_variable_count=1,
            max_tracked_prefix_cabin_count=1,
            max_prefix_visit_index=1,
            tolerance_seconds=0.0,
        )


def test_waiting_split_is_a_stable_integer_boundary() -> None:
    split = DddWaitingSplit("station", 3)

    split.validate()
    assert split.station_id == "station"
    assert split.boundary_step == 3
    with pytest.raises(ValueError, match="waiting split"):
        DddWaitingSplit("station", 0).validate()


def test_waiting_conflict_split_isolates_the_exact_observed_wait() -> None:
    interval = DddWaitingInterval("station", 1, 5, 1_000_000)
    visits = tuple(
        DddReferenceVisit(
            cabin_id=cabin_id,
            visit_index=0,
            state_id="A",
            route_option_id="stop",
            decision=DddRouteDecision.STOP,
            switch_time_seconds=0.0,
            next_switch_time_seconds=3.0,
            resource_occurrences=(),
            wait_seconds=2.0,
        )
        for cabin_id in (0, 1)
    )
    selection = DddSupportSelection(
        tuple(
            DddReferenceTrajectory(cabin_id=visit.cabin_id, visits=(visit,))
            for visit in visits
        )
    )
    selected_arcs = {
        (cabin_id, 0): SimpleNamespace(
            partial_arc=SimpleNamespace(waiting_interval=interval)
        )
        for cabin_id in (0, 1)
    }

    proofs = build_ddd_waiting_conflict_split_proofs(
        SimpleNamespace(),  # type: ignore[arg-type]
        (),
        (DddReferenceConflict("merge", 0, 0, 1, 0, 1.0),),
        selection,
        selected_arc_by_visit=selected_arcs,  # type: ignore[arg-type]
    )

    assert proofs == (
        (DddWaitingSplit("station", 2), (0,)),
        (DddWaitingSplit("station", 3), (0,)),
    )
