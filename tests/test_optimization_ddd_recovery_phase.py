from __future__ import annotations

from types import SimpleNamespace

import pytest

from ropeway_skip_stop_optimization.optimization.ddd.network_refinement_model import (
    DddNetworkValidationResult,
    DddNetworkValidationStatus,
)
from ropeway_skip_stop_optimization.optimization.ddd.recovery_phase import (
    DddRecoveryPhaseSolver,
)
from ropeway_skip_stop_optimization.optimization.ddd.time_refinement import (
    DddPrimalRecoveryResult,
    DddPrimalRecoveryStatus,
    DddRecoveredSchedule,
)


class _FakeRecovery:
    def __init__(self, results: tuple[DddPrimalRecoveryResult, ...]) -> None:
        self.results = iter(results)
        self.call_count = 0

    def recover(self, _problem: object, _path: object) -> DddPrimalRecoveryResult:
        self.call_count += 1
        return next(self.results)


def _schedule(cabin_id: int, objective: float) -> DddRecoveredSchedule:
    return DddRecoveredSchedule(
        cabin_id=cabin_id,
        route_option_ids=(),
        events=(),
        objective_value=objective,
    )


def _feasible(schedule: DddRecoveredSchedule) -> DddPrimalRecoveryResult:
    return DddPrimalRecoveryResult(
        status=DddPrimalRecoveryStatus.FEASIBLE,
        schedule=schedule,
    )


def test_recovery_phase_validates_and_consumes_complete_candidate() -> None:
    first = _schedule(0, 2.5)
    second = _schedule(1, 3.5)
    recovery = _FakeRecovery((_feasible(first), _feasible(second)))
    solution = SimpleNamespace(id="validated")
    consumed: list[tuple[tuple[DddRecoveredSchedule, ...], object]] = []

    result = DddRecoveryPhaseSolver(  # type: ignore[arg-type]
        recovery=recovery
    ).solve(
        path_problems=(SimpleNamespace(), SimpleNamespace()),  # type: ignore[arg-type]
        paths=(SimpleNamespace(), SimpleNamespace()),  # type: ignore[arg-type]
        validate_candidate=lambda schedules: DddNetworkValidationResult(
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

    assert result.feasible
    assert result.schedules == (first, second)
    assert result.objective_value == pytest.approx(6.0)
    assert result.validation.status is DddNetworkValidationStatus.FEASIBLE
    assert consumed == [((first, second), solution)]
    assert recovery.call_count == 2
    assert result.seconds >= 0.0


def test_recovery_phase_short_circuits_after_failed_path() -> None:
    first = _schedule(0, 2.5)
    recovery = _FakeRecovery(
        (
            _feasible(first),
            DddPrimalRecoveryResult(
                status=DddPrimalRecoveryStatus.INFEASIBLE,
                schedule=None,
            ),
        )
    )
    validation_calls = 0
    consumed: list[object] = []

    def validate(
        _schedules: tuple[DddRecoveredSchedule, ...],
    ) -> DddNetworkValidationResult:
        nonlocal validation_calls
        validation_calls += 1
        raise AssertionError("incomplete recovery must not be validated")

    result = DddRecoveryPhaseSolver(  # type: ignore[arg-type]
        recovery=recovery
    ).solve(
        path_problems=(SimpleNamespace(), SimpleNamespace()),  # type: ignore[arg-type]
        paths=(SimpleNamespace(), SimpleNamespace()),  # type: ignore[arg-type]
        validate_candidate=validate,
        consume_candidate=lambda schedules, solution: consumed.append(
            (schedules, solution)
        ),
    )

    assert not result.feasible
    assert result.schedules == (first,)
    assert result.objective_value is None
    assert result.validation.status is DddNetworkValidationStatus.NOT_RUN
    assert validation_calls == 0
    assert consumed == []
    assert recovery.call_count == 2


def test_recovery_phase_does_not_consume_globally_invalid_candidate() -> None:
    schedule = _schedule(0, 2.5)
    consumed: list[object] = []
    validation = DddNetworkValidationResult(
        status=DddNetworkValidationStatus.RESOURCE_CONFLICT,
        solution=None,
        detail="shared resource conflict",
        conflicts=(),
        cuts=(),
    )

    result = DddRecoveryPhaseSolver(  # type: ignore[arg-type]
        recovery=_FakeRecovery((_feasible(schedule),))
    ).solve(
        path_problems=(SimpleNamespace(),),  # type: ignore[arg-type]
        paths=(SimpleNamespace(),),  # type: ignore[arg-type]
        validate_candidate=lambda _schedules: validation,
        consume_candidate=lambda schedules, solution: consumed.append(
            (schedules, solution)
        ),
    )

    assert not result.feasible
    assert result.schedules == (schedule,)
    assert result.objective_value is None
    assert result.validation is validation
    assert consumed == []


def test_recovery_phase_rejects_mismatched_problem_and_path_counts() -> None:
    solver = DddRecoveryPhaseSolver(  # type: ignore[arg-type]
        recovery=_FakeRecovery(())
    )

    with pytest.raises(ValueError, match="one problem per path"):
        solver.solve(
            path_problems=(SimpleNamespace(),),  # type: ignore[arg-type]
            paths=(),
            validate_candidate=lambda _schedules: DddNetworkValidationResult(
                status=DddNetworkValidationStatus.NOT_RUN,
                solution=None,
                detail=None,
                conflicts=(),
                cuts=(),
            ),
            consume_candidate=lambda _schedules, _solution: None,
        )
