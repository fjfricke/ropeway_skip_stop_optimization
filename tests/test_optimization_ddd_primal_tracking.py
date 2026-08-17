from __future__ import annotations

from types import SimpleNamespace

from ropeway_skip_stop_optimization.optimization.ddd.primal_evaluation import (
    DddPrimalEvaluationStatus,
)
from ropeway_skip_stop_optimization.optimization.ddd.primal_tracking import (
    DddPrimalIncumbentTracker,
    DddPrimalRoundState,
)


class _FakePool:
    def __init__(self, added_count: int = 1) -> None:
        self.added_count = added_count
        self.candidates: list[object] = []

    def add_candidate(self, candidate: object) -> int:
        self.candidates.append(candidate)
        return self.added_count


class _FakeEvaluator:
    def __init__(self, evaluation: object) -> None:
        self.evaluation = evaluation

    def evaluate(self, _problem: object, _solution: object) -> object:
        return self.evaluation


def _schedule(*, objective: float = 5.0) -> object:
    return SimpleNamespace(
        cabin_id=0,
        route_option_ids=("stop",),
        objective_value=objective,
    )


def _evaluation(*, objective: float, movement_plan: object | None) -> object:
    return SimpleNamespace(
        status=DddPrimalEvaluationStatus.FEASIBLE,
        objective_value=objective,
        movement_plan=movement_plan,
        summary=SimpleNamespace(objective_value=objective),
        total_seconds=0.25,
    )


def test_movement_only_tracker_updates_and_remembers_incumbent() -> None:
    pool = _FakePool()
    tracker = DddPrimalIncumbentTracker(
        evaluator=None,
        trajectory_column_pool=pool,  # type: ignore[arg-type]
        trajectory_pool_enabled=False,
        remember_candidates=True,
    )
    schedule = _schedule()
    solution = SimpleNamespace(id="solution")

    outcome = tracker.consider_candidate(
        SimpleNamespace(),  # type: ignore[arg-type]
        (schedule,),  # type: ignore[arg-type]
        solution,  # type: ignore[arg-type]
    )

    assert outcome.improved_incumbent
    assert tracker.upper_bound == 5.0
    assert tracker.best_schedules == (schedule,)
    assert tracker.remembered_schedules == ((schedule,),)
    assert pool.candidates == []


def test_tracker_records_evaluation_progress_and_pool_columns() -> None:
    movement_plan = SimpleNamespace(id="movement")
    evaluation = _evaluation(objective=3.0, movement_plan=movement_plan)
    pool = _FakePool(added_count=2)
    tracker = DddPrimalIncumbentTracker(
        evaluator=_FakeEvaluator(evaluation),  # type: ignore[arg-type]
        trajectory_column_pool=pool,  # type: ignore[arg-type]
        trajectory_pool_enabled=True,
        remember_candidates=False,
    )
    round_state = DddPrimalRoundState()
    progress: list[tuple[int, float | None]] = []

    outcome = tracker.consider_candidate(
        SimpleNamespace(),  # type: ignore[arg-type]
        (_schedule(),),  # type: ignore[arg-type]
        SimpleNamespace(),  # type: ignore[arg-type]
        round_state=round_state,
        on_evaluated=lambda state, best: progress.append(
            (state.evaluation_count, best)
        ),
    )

    assert outcome.improved_incumbent
    assert round_state.status is DddPrimalEvaluationStatus.FEASIBLE
    assert round_state.evaluation_count == 1
    assert round_state.evaluation_seconds == 0.25
    assert round_state.objective_value == 3.0
    assert round_state.trajectory_pool_added_option_count == 2
    assert progress == [(1, 3.0)]
    assert len(pool.candidates) == 1


def test_external_worse_evaluation_does_not_replace_incumbent() -> None:
    tracker = DddPrimalIncumbentTracker(
        evaluator=None,
        trajectory_column_pool=_FakePool(),  # type: ignore[arg-type]
        trajectory_pool_enabled=False,
        remember_candidates=False,
        upper_bound=2.0,
    )
    round_state = DddPrimalRoundState()

    outcome = tracker.record_external_evaluation(
        schedules=(_schedule(),),  # type: ignore[arg-type]
        solution=SimpleNamespace(),  # type: ignore[arg-type]
        evaluation=_evaluation(  # type: ignore[arg-type]
            objective=4.0,
            movement_plan=SimpleNamespace(),
        ),
        round_state=round_state,
    )

    assert not outcome.improved_incumbent
    assert tracker.upper_bound == 2.0
    assert round_state.objective_value == 4.0
    assert round_state.evaluation_count == 1
