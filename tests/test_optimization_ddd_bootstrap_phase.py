from __future__ import annotations

from types import SimpleNamespace

from ropeway_skip_stop_optimization.optimization.ddd.bootstrap_phase import (
    DddBootstrapPhaseSolver,
)
from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_primal import (
    DddCpSatPrimalResult,
    DddCpSatPrimalStatus,
)
from ropeway_skip_stop_optimization.optimization.ddd.primal_tracking import (
    DddPrimalCandidateOutcome,
)
from ropeway_skip_stop_optimization.optimization.ddd.reference import (
    DddReferenceSolution,
)
from ropeway_skip_stop_optimization.optimization.ddd.time_refinement import (
    DddRecoveredSchedule,
)


class _FakeOracle:
    def __init__(self, result: DddCpSatPrimalResult) -> None:
        self.result = result
        self.call_count = 0

    def solve(self, _problem: object) -> DddCpSatPrimalResult:
        self.call_count += 1
        return self.result


def _schedule(cabin_id: int, objective: float) -> DddRecoveredSchedule:
    return DddRecoveredSchedule(
        cabin_id=cabin_id,
        route_option_ids=(),
        events=(),
        objective_value=objective,
    )


def _oracle_result(
    status: DddCpSatPrimalStatus,
    *,
    schedules: tuple[DddRecoveredSchedule, ...] = (),
    candidates: tuple[tuple[DddRecoveredSchedule, ...], ...] = (),
) -> DddCpSatPrimalResult:
    return DddCpSatPrimalResult(
        status=status,
        schedules=schedules,
        candidate_schedules=candidates,
        wall_seconds=0.1,
        conflict_count=0,
        branch_count=0,
    )


def test_bootstrap_phase_does_nothing_when_disabled() -> None:
    oracle = _FakeOracle(_oracle_result(DddCpSatPrimalStatus.INFEASIBLE))
    progress: list[str] = []

    result = DddBootstrapPhaseSolver(enabled=False).solve(
        problem=SimpleNamespace(),  # type: ignore[arg-type]
        oracle=oracle,  # type: ignore[arg-type]
        validate_candidate=lambda _schedules: DddReferenceSolution(()),
        consume_candidate=lambda _schedules, _solution: (
            DddPrimalCandidateOutcome(None, None, False)
        ),
        on_started=lambda: progress.append("started"),
        on_finished=lambda: progress.append("finished"),
    )

    assert result.oracle_result is None
    assert not result.exact_infeasible
    assert not result.invalid_candidate
    assert oracle.call_count == 0
    assert progress == []


def test_bootstrap_phase_reports_exact_infeasibility() -> None:
    oracle = _FakeOracle(_oracle_result(DddCpSatPrimalStatus.INFEASIBLE))
    progress: list[str] = []

    result = DddBootstrapPhaseSolver(enabled=True).solve(
        problem=SimpleNamespace(),  # type: ignore[arg-type]
        oracle=oracle,  # type: ignore[arg-type]
        validate_candidate=lambda _schedules: DddReferenceSolution(()),
        consume_candidate=lambda _schedules, _solution: (
            DddPrimalCandidateOutcome(None, None, False)
        ),
        on_started=lambda: progress.append("started"),
        on_finished=lambda: progress.append("finished"),
    )

    assert result.oracle_result is oracle.result
    assert result.exact_infeasible
    assert not result.invalid_candidate
    assert oracle.call_count == 1
    assert progress == ["started", "finished"]


def test_bootstrap_phase_validates_and_consumes_all_candidates() -> None:
    first = (_schedule(0, 5.0),)
    second = (_schedule(0, 4.0),)
    oracle = _FakeOracle(
        _oracle_result(
            DddCpSatPrimalStatus.FEASIBLE,
            schedules=first,
            candidates=(first, second),
        )
    )
    validated: list[tuple[DddRecoveredSchedule, ...]] = []
    consumed: list[tuple[DddRecoveredSchedule, ...]] = []
    solution = DddReferenceSolution(())

    def validate(
        schedules: tuple[DddRecoveredSchedule, ...],
    ) -> DddReferenceSolution:
        validated.append(schedules)
        return solution

    def consume(
        schedules: tuple[DddRecoveredSchedule, ...],
        _solution: DddReferenceSolution,
    ) -> DddPrimalCandidateOutcome:
        consumed.append(schedules)
        return DddPrimalCandidateOutcome(
            objective_value=schedules[0].objective_value,
            evaluation=None,
            improved_incumbent=True,
        )

    result = DddBootstrapPhaseSolver(enabled=True).solve(
        problem=SimpleNamespace(),  # type: ignore[arg-type]
        oracle=oracle,  # type: ignore[arg-type]
        validate_candidate=validate,
        consume_candidate=consume,
    )

    assert validated == [first, second]
    assert consumed == [first, second]
    assert result.objective_value == 4.0
    assert not result.exact_infeasible
    assert not result.invalid_candidate


def test_bootstrap_phase_rejects_invalid_candidate_and_stops() -> None:
    first = (_schedule(0, 5.0),)
    second = (_schedule(0, 4.0),)
    oracle = _FakeOracle(
        _oracle_result(
            DddCpSatPrimalStatus.FEASIBLE,
            schedules=first,
            candidates=(first, second),
        )
    )
    validated: list[tuple[DddRecoveredSchedule, ...]] = []
    consumed: list[tuple[DddRecoveredSchedule, ...]] = []
    progress: list[str] = []

    def validate(
        schedules: tuple[DddRecoveredSchedule, ...],
    ) -> DddReferenceSolution | None:
        validated.append(schedules)
        return DddReferenceSolution(()) if schedules is first else None

    result = DddBootstrapPhaseSolver(enabled=True).solve(
        problem=SimpleNamespace(),  # type: ignore[arg-type]
        oracle=oracle,  # type: ignore[arg-type]
        validate_candidate=validate,
        consume_candidate=lambda schedules, _solution: (
            consumed.append(schedules)
            or DddPrimalCandidateOutcome(5.0, None, True)
        ),
        on_started=lambda: progress.append("started"),
        on_finished=lambda: progress.append("finished"),
    )

    assert validated == [first, second]
    assert consumed == [first]
    assert result.objective_value == 5.0
    assert result.invalid_candidate
    assert not result.exact_infeasible
    assert progress == ["started", "finished"]
