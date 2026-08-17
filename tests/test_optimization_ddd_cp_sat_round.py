from __future__ import annotations

from types import SimpleNamespace

from ropeway_skip_stop_optimization.optimization.ddd.aggregate_support import (
    DddAggregateRouteCountLiteral,
)
from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_primal import (
    DddCpSatPrimalResult,
    DddCpSatPrimalStatus,
)
from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_round import (
    DddCpSatMasterCoupling,
    DddCpSatRoundSolver,
)


class _FakeOracle:
    def __init__(self, result: DddCpSatPrimalResult) -> None:
        self.result = result
        self.calls: list[dict[str, object]] = []

    def solve(self, _problem: object, **kwargs: object) -> DddCpSatPrimalResult:
        self.calls.append(kwargs)
        return self.result


def _solver(
    *,
    coupling: DddCpSatMasterCoupling = DddCpSatMasterCoupling.FREE_ROUTE_CHOICES,
    use_nearest_support: bool = False,
) -> DddCpSatRoundSolver:
    return DddCpSatRoundSolver(
        use_primal_oracle=True,
        master_coupling=coupling,
        use_timed_flow_covers=False,
        use_cabin_path_cuts=False,
        use_nearest_support=use_nearest_support,
        collect_local_explainability=False,
        retry_interval=10,
        diversification_interval=0,
        max_prefix_variable_count=100,
        max_tracked_prefix_cabin_count=2,
        max_prefix_visit_index=2,
    )


def _solve(
    solver: DddCpSatRoundSolver,
    oracle: _FakeOracle,
    *,
    round_index: int,
    has_incumbent: bool,
    consumed: list[tuple[object, object, int]],
) -> object:
    return solver.solve(
        round_index=round_index,
        problem=SimpleNamespace(movement_problem=object()),  # type: ignore[arg-type]
        network=SimpleNamespace(),  # type: ignore[arg-type]
        flow=SimpleNamespace(),  # type: ignore[arg-type]
        paths=(),
        existing_prefix_cuts=(),
        existing_aggregate_support_cut_ids=frozenset(),
        existing_aggregate_distance_cut_ids=frozenset(),
        existing_timed_flow_cover_cut_ids=frozenset(),
        has_incumbent=has_incumbent,
        best_schedules=(),
        excluded_schedules=(),
        primal_oracle=oracle,  # type: ignore[arg-type]
        nearest_support_oracle=oracle,  # type: ignore[arg-type]
        local_resource_analyzer=SimpleNamespace(),  # type: ignore[arg-type]
        validate_candidate=lambda schedules: SimpleNamespace(schedules=schedules),
        consume_candidate=lambda schedules, solution, count: consumed.append(
            (schedules, solution, count)
        ),
    )


def test_cp_sat_round_skips_unneeded_retry() -> None:
    oracle = _FakeOracle(
        DddCpSatPrimalResult(
            status=DddCpSatPrimalStatus.UNKNOWN,
            schedules=(),
            wall_seconds=0.0,
            conflict_count=0,
            branch_count=0,
        )
    )

    result = _solve(
        _solver(),
        oracle,
        round_index=2,
        has_incumbent=True,
        consumed=[],
    )

    assert result.status is DddCpSatPrimalStatus.NOT_RUN
    assert oracle.calls == []


def test_cp_sat_round_validates_and_consumes_feasible_candidates() -> None:
    schedule = SimpleNamespace(cabin_id=0)
    oracle = _FakeOracle(
        DddCpSatPrimalResult(
            status=DddCpSatPrimalStatus.FEASIBLE,
            schedules=(schedule,),  # type: ignore[arg-type]
            candidate_schedules=((schedule,),),  # type: ignore[arg-type]
            wall_seconds=0.25,
            conflict_count=3,
            branch_count=7,
            search_complete=True,
        )
    )
    consumed: list[tuple[object, object, int]] = []

    result = _solve(
        _solver(),
        oracle,
        round_index=1,
        has_incumbent=False,
        consumed=consumed,
    )

    assert result.status is DddCpSatPrimalStatus.FEASIBLE
    assert result.candidate_count == 1
    assert result.search_complete
    assert len(consumed) == 1
    assert consumed[0][0] == (schedule,)
    assert consumed[0][2] == 1


def test_cp_sat_round_builds_aggregate_core_cut() -> None:
    literal = DddAggregateRouteCountLiteral(
        visit_index=0,
        route_option_id="skip",
        count=1,
    )
    oracle = _FakeOracle(
        DddCpSatPrimalResult(
            status=DddCpSatPrimalStatus.INFEASIBLE,
            schedules=(),
            wall_seconds=0.1,
            conflict_count=1,
            branch_count=2,
            infeasible_core=(literal,),
        )
    )

    result = _solve(
        _solver(coupling=DddCpSatMasterCoupling.FIXED_AGGREGATE_SUPPORT),
        oracle,
        round_index=3,
        has_incumbent=True,
        consumed=[],
    )

    assert not result.exact_infeasible
    assert len(result.aggregate_support_cuts) == 1
    assert result.aggregate_support_cuts[0].literals == (literal,)
