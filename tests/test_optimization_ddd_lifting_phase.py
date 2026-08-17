from __future__ import annotations

from types import SimpleNamespace

from ropeway_skip_stop_optimization.optimization.ddd.lifting_phase import (
    DddLiftingPhaseSolver,
)
from ropeway_skip_stop_optimization.optimization.ddd.network_refinement_model import (
    DddNetworkValidationResult,
    DddNetworkValidationStatus,
)
from ropeway_skip_stop_optimization.optimization.ddd.time_refinement import (
    DddEventCellInconsistency,
    DddRecoveredSchedule,
    DddStrictTimeLiftResult,
    DddStrictTimeLiftStatus,
    DddTimeRefinementStalledError,
)
from ropeway_skip_stop_optimization.optimization.ddd.time_space import (
    DddTimeDiscretization,
    DddTimePartition,
)


class _FakeLifter:
    def __init__(self, results: tuple[object, ...]) -> None:
        self.results = iter(results)

    def lift(self, _problem: object, _path: object) -> DddStrictTimeLiftResult:
        result = next(self.results)
        if isinstance(result, Exception):
            raise result
        assert isinstance(result, DddStrictTimeLiftResult)
        return result


def _schedule(cabin_id: int) -> DddRecoveredSchedule:
    return DddRecoveredSchedule(
        cabin_id=cabin_id,
        route_option_ids=(),
        events=(),
        objective_value=float(cabin_id + 1),
    )


def _discretization() -> DddTimeDiscretization:
    return DddTimeDiscretization((DddTimePartition("A", (0.0, 10.0)),))


def _solver(*results: object) -> DddLiftingPhaseSolver:
    return DddLiftingPhaseSolver(
        lifter=_FakeLifter(results),  # type: ignore[arg-type]
        max_time_splits=2,
        tolerance_seconds=1e-9,
    )


def test_lifting_phase_validates_and_consumes_complete_candidate() -> None:
    first = _schedule(0)
    second = _schedule(1)
    solution = SimpleNamespace(id="validated")
    consumed: list[object] = []

    result = _solver(
        DddStrictTimeLiftResult(DddStrictTimeLiftStatus.FEASIBLE, first),
        DddStrictTimeLiftResult(DddStrictTimeLiftStatus.FEASIBLE, second),
    ).solve(
        discretization=_discretization(),
        path_problems=(SimpleNamespace(), SimpleNamespace()),  # type: ignore[arg-type]
        paths=(SimpleNamespace(), SimpleNamespace()),  # type: ignore[arg-type]
        validate_candidate=lambda _schedules: DddNetworkValidationResult(
            status=DddNetworkValidationStatus.FEASIBLE,
            solution=solution,  # type: ignore[arg-type]
            detail=None,
            conflicts=(),
            cuts=(),
        ),
        consume_candidate=lambda schedules, validated: consumed.append(
            (schedules, validated)
        ),
    )

    assert result.statuses == (
        DddStrictTimeLiftStatus.FEASIBLE,
        DddStrictTimeLiftStatus.FEASIBLE,
    )
    assert result.validation.status is DddNetworkValidationStatus.FEASIBLE
    assert result.time_splits == ()
    assert result.refined_discretization == _discretization()
    assert result.stalled_detail is None
    assert consumed == [((first, second), solution)]


def test_lifting_phase_builds_split_for_event_cell_inconsistency() -> None:
    inconsistency = DddEventCellInconsistency(
        state_id="A",
        selected_cell_id="A::0",
        exact_source_time_seconds=4.0,
        required_source_lower_seconds=4.0,
        required_source_upper_seconds=4.0,
        split_boundary_seconds=4.0,
        failed_target_cell_id="A::1",
    )
    validation_calls = 0

    def validate(_schedules: tuple[DddRecoveredSchedule, ...]) -> object:
        nonlocal validation_calls
        validation_calls += 1
        raise AssertionError("incomplete lift must not be validated")

    result = _solver(
        DddStrictTimeLiftResult(
            DddStrictTimeLiftStatus.EVENT_CELL_INCONSISTENCY,
            None,
            (inconsistency,),
        )
    ).solve(
        discretization=_discretization(),
        path_problems=(SimpleNamespace(),),  # type: ignore[arg-type]
        paths=(SimpleNamespace(),),  # type: ignore[arg-type]
        validate_candidate=validate,  # type: ignore[arg-type]
        consume_candidate=lambda _schedules, _solution: None,
    )

    assert result.statuses == (DddStrictTimeLiftStatus.EVENT_CELL_INCONSISTENCY,)
    assert tuple(
        (split.state_id, split.boundary_seconds) for split in result.time_splits
    ) == (("A", 4.0),)
    assert result.refined_discretization.partition(
        "A"
    ).boundaries_seconds == (0.0, 4.0, 10.0)
    assert result.validation.status is DddNetworkValidationStatus.NOT_RUN
    assert validation_calls == 0


def test_lifting_phase_reports_first_stalled_error_as_invalid() -> None:
    consumed: list[object] = []

    result = _solver(
        DddTimeRefinementStalledError("first failure"),
        DddTimeRefinementStalledError("second failure"),
    ).solve(
        discretization=_discretization(),
        path_problems=(SimpleNamespace(), SimpleNamespace()),  # type: ignore[arg-type]
        paths=(SimpleNamespace(), SimpleNamespace()),  # type: ignore[arg-type]
        validate_candidate=lambda _schedules: DddNetworkValidationResult(
            status=DddNetworkValidationStatus.FEASIBLE,
            solution=SimpleNamespace(),  # type: ignore[arg-type]
            detail=None,
            conflicts=(),
            cuts=(),
        ),
        consume_candidate=lambda schedules, solution: consumed.append(
            (schedules, solution)
        ),
    )

    assert result.statuses == ()
    assert result.validation.status is DddNetworkValidationStatus.INVALID
    assert result.validation.detail == "first failure"
    assert result.time_splits == ()
    assert result.stalled_detail == "first failure"
    assert consumed == []
