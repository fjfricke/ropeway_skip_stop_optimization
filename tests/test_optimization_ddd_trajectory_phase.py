from __future__ import annotations

from types import SimpleNamespace

from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_primal import (
    DddCpSatPrimalStatus,
)
from ropeway_skip_stop_optimization.optimization.ddd.trajectory_passenger_lp import (
    DddTrajectoryPassengerLpStatus,
)
from ropeway_skip_stop_optimization.optimization.ddd.trajectory_phase import (
    DddTrajectoryPhaseSolver,
)


class _FakePool:
    def __init__(
        self,
        *,
        fingerprint: str,
        column_count: int,
        has_recombination_choice: bool,
    ) -> None:
        self.fingerprint = fingerprint
        self.column_count = column_count
        self.has_recombination_choice = has_recombination_choice
        self.candidates: tuple[object, ...] = ()


class _FakeEvaluator:
    def __init__(self, pool_evaluation: object) -> None:
        self.pool_evaluation = pool_evaluation
        self.pool_evaluation_count = 0

    def evaluate_trajectory_pool(self, _problem: object, _pool: object) -> object:
        self.pool_evaluation_count += 1
        return self.pool_evaluation

    def build_trajectory_pricing_signal(
        self,
        _problem: object,
        _lp_result: object,
    ) -> object:
        return SimpleNamespace(preferences=("preference",), fingerprint="signal")


class _FakeOracle:
    def __init__(self, result: object) -> None:
        self.result = result
        self.calls: list[dict[str, object]] = []

    def solve(self, _problem: object, **kwargs: object) -> object:
        self.calls.append(kwargs)
        callback = kwargs.get("candidate_callback")
        if callable(callback):
            callback(1, 0.25)
        return self.result


def _solver(*, pricing_enabled: bool) -> DddTrajectoryPhaseSolver:
    return DddTrajectoryPhaseSolver(
        pool_enabled=True,
        pricing_enabled=pricing_enabled,
        pricing_interval=1,
    )


def _pool_evaluation(*, lp_result: object | None = None) -> object:
    return SimpleNamespace(
        pool_result=SimpleNamespace(
            schedules=("pool-schedule",),
            reference_solution=SimpleNamespace(id="pool-solution"),
        ),
        lp_result=lp_result,
        evaluation=None,
    )


def _pricing_result(*, schedules: tuple[object, ...]) -> object:
    return SimpleNamespace(
        status=DddCpSatPrimalStatus.FEASIBLE,
        candidate_schedules=(schedules,),
        schedules=(),
        passenger_pricing_objective_value=4.0,
        passenger_pricing_objective_bound=3.0,
    )


def test_trajectory_phase_evaluates_changed_recombinable_pool() -> None:
    pool = _FakePool(
        fingerprint="new-pool",
        column_count=2,
        has_recombination_choice=True,
    )
    pool_evaluation = _pool_evaluation()
    evaluator = _FakeEvaluator(pool_evaluation)
    consumed: list[object] = []
    progress: list[str] = []

    result = _solver(pricing_enabled=False).solve(
        round_index=1,
        problem=SimpleNamespace(),  # type: ignore[arg-type]
        paths=(),
        column_pool=pool,  # type: ignore[arg-type]
        evaluator=evaluator,  # type: ignore[arg-type]
        pricing_oracle=SimpleNamespace(),  # type: ignore[arg-type]
        previous_pool_result=None,
        previous_pool_lp_result=None,
        previous_pool_fingerprint="old-pool",
        best_schedules=lambda: (),
        validate_candidate=lambda _schedules: None,
        consume_candidate=lambda _schedules, _solution: None,
        consume_pool_evaluation=consumed.append,  # type: ignore[arg-type]
        on_pool_started=lambda: progress.append("started"),
        on_pool_finished=lambda: progress.append("finished"),
    )

    assert result.pool_result is pool_evaluation.pool_result
    assert result.pool_lp_result is None
    assert result.pool_fingerprint == "new-pool"
    assert result.pool_solved_this_round
    assert result.pricing_status is DddCpSatPrimalStatus.NOT_RUN
    assert consumed == [pool_evaluation]
    assert progress == ["started", "finished"]


def test_trajectory_phase_prices_valid_candidate_and_resolves_expanded_pool() -> None:
    lp_result = SimpleNamespace(
        status=DddTrajectoryPassengerLpStatus.OPTIMAL,
        duals=SimpleNamespace(),
    )
    pool = _FakePool(
        fingerprint="before-pricing",
        column_count=1,
        has_recombination_choice=False,
    )
    priced_pool_evaluation = _pool_evaluation(lp_result=lp_result)
    evaluator = _FakeEvaluator(priced_pool_evaluation)
    candidate = (SimpleNamespace(cabin_id=0),)
    oracle = _FakeOracle(_pricing_result(schedules=candidate))
    solution = SimpleNamespace(id="validated")
    consumed_candidates: list[object] = []
    candidate_progress: list[tuple[int, float]] = []

    def consume_candidate(schedules: object, validated: object) -> None:
        consumed_candidates.append((schedules, validated))
        pool.column_count += 1
        pool.fingerprint = "after-pricing"

    result = _solver(pricing_enabled=True).solve(
        round_index=1,
        problem=SimpleNamespace(),  # type: ignore[arg-type]
        paths=(SimpleNamespace(id="path"),),  # type: ignore[arg-type]
        column_pool=pool,  # type: ignore[arg-type]
        evaluator=evaluator,  # type: ignore[arg-type]
        pricing_oracle=oracle,  # type: ignore[arg-type]
        previous_pool_result=SimpleNamespace(id="old"),  # type: ignore[arg-type]
        previous_pool_lp_result=lp_result,  # type: ignore[arg-type]
        previous_pool_fingerprint="before-pricing",
        best_schedules=lambda: (SimpleNamespace(id="incumbent"),),  # type: ignore[return-value]
        validate_candidate=lambda _schedules: solution,  # type: ignore[return-value]
        consume_candidate=consume_candidate,  # type: ignore[arg-type]
        consume_pool_evaluation=lambda _evaluation: None,
        on_candidate_found=lambda index, seconds: candidate_progress.append(
            (index, seconds)
        ),
    )

    assert result.pricing_status is DddCpSatPrimalStatus.FEASIBLE
    assert result.pricing_preference_count == 1
    assert result.pricing_candidate_count == 1
    assert result.pricing_objective_value == 4.0
    assert result.pricing_objective_bound == 3.0
    assert result.pricing_signal_fingerprint == "signal"
    assert result.pricing_seconds >= 0.0
    assert result.pool_solved_this_round
    assert result.pool_fingerprint == "after-pricing"
    assert evaluator.pool_evaluation_count == 1
    assert consumed_candidates == [(candidate, solution)]
    assert candidate_progress == [(1, 0.25)]
    assert oracle.calls[0]["hint_schedules"][0].id == "incumbent"  # type: ignore[index,union-attr]


def test_trajectory_phase_rejects_invalid_pricing_candidate() -> None:
    lp_result = SimpleNamespace(
        status=DddTrajectoryPassengerLpStatus.OPTIMAL,
        duals=SimpleNamespace(),
    )
    pool = _FakePool(
        fingerprint="pool",
        column_count=1,
        has_recombination_choice=False,
    )
    candidate = (SimpleNamespace(cabin_id=0),)
    consumed: list[object] = []

    result = _solver(pricing_enabled=True).solve(
        round_index=1,
        problem=SimpleNamespace(),  # type: ignore[arg-type]
        paths=(),
        column_pool=pool,  # type: ignore[arg-type]
        evaluator=_FakeEvaluator(_pool_evaluation()),  # type: ignore[arg-type]
        pricing_oracle=_FakeOracle(  # type: ignore[arg-type]
            _pricing_result(schedules=candidate)
        ),
        previous_pool_result=None,
        previous_pool_lp_result=lp_result,  # type: ignore[arg-type]
        previous_pool_fingerprint="pool",
        best_schedules=lambda: (),
        validate_candidate=lambda _schedules: None,
        consume_candidate=lambda schedules, solution: consumed.append(
            (schedules, solution)
        ),
        consume_pool_evaluation=lambda _evaluation: None,
    )

    assert result.invalid_candidate
    assert consumed == []
    assert not result.pool_solved_this_round
