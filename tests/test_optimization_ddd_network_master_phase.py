from __future__ import annotations

from types import SimpleNamespace

import pytest

from ropeway_skip_stop_optimization.optimization.ddd.network_master_phase import (
    DddNetworkMasterPhaseResult,
    DddNetworkMasterPhaseSolver,
)
from ropeway_skip_stop_optimization.optimization.ddd.network_time_space import (
    DddAnonymousFlowStatus,
    DddAnonymousFlowWarmStart,
)
from ropeway_skip_stop_optimization.optimization.ddd.resource_time import (
    DddAnonymousResourceRowKind,
    DddResourceWindowCutMode,
)


class _FakeMaster:
    def __init__(self, flows: tuple[object, ...]) -> None:
        self._flows = iter(flows)
        self.calls: list[dict[str, object]] = []

    def solve(self, _network: object, **kwargs: object) -> object:
        self.calls.append(kwargs)
        return next(self._flows)


def _flow(best_bound: float) -> object:
    return SimpleNamespace(
        status=DddAnonymousFlowStatus.OPTIMAL,
        best_bound=best_bound,
        arc_values=(SimpleNamespace(arc_id="arc", value=1),),
        prefix_arc_values=(),
    )


def _solve(
    solver: DddNetworkMasterPhaseSolver,
    master: _FakeMaster,
    network: object,
    **callbacks: object,
) -> DddNetworkMasterPhaseResult:
    return solver.solve(
        master=master,  # type: ignore[arg-type]
        network=network,  # type: ignore[arg-type]
        cuts=(),
        aggregate_support_cuts=(),
        aggregate_distance_cuts=(),
        timed_flow_cover_cuts=(),
        resource_rows=(),
        warm_start=None,
        passenger_problem=None,
        fixed_start_movement_problem=None,
        **callbacks,  # type: ignore[arg-type]
    )


def test_master_phase_without_separation_solves_once() -> None:
    master = _FakeMaster((_flow(12.0),))
    network = SimpleNamespace(arcs=(), cabin_ids=(0,))
    started: list[None] = []
    finished: list[None] = []
    solver = DddNetworkMasterPhaseSolver(
        resource_window_cut_mode=DddResourceWindowCutMode.OFF,
        max_resource_window_rows_per_resolve=10,
        max_resource_window_resolves=2,
    )

    result = _solve(
        solver,
        master,
        network,
        on_master_started=lambda: started.append(None),
        on_master_finished=lambda: finished.append(None),
    )

    assert len(master.calls) == 1
    assert len(started) == len(finished) == 1
    assert result.flow.best_bound == 12.0
    assert result.resource_window_resolve_count == 0
    assert result.resource_window_lower_bound_before == 12.0
    assert result.resource_window_lower_bound_after == 12.0


def test_master_phase_forwards_shared_budget_and_stops_on_time_limit() -> None:
    timed_out = SimpleNamespace(
        status=DddAnonymousFlowStatus.TIME_LIMIT,
        best_bound=7.0,
        arc_values=(),
        prefix_arc_values=(),
    )
    master = _FakeMaster((timed_out,))
    network = SimpleNamespace(arcs=(), cabin_ids=(0,))
    solver = DddNetworkMasterPhaseSolver(
        resource_window_cut_mode=DddResourceWindowCutMode.ENTRY_COUNT,
        max_resource_window_rows_per_resolve=10,
        max_resource_window_resolves=2,
    )

    result = _solve(solver, master, network, time_limit_seconds=3.0)

    assert result.flow.status is DddAnonymousFlowStatus.TIME_LIMIT
    assert len(master.calls) == 1
    assert 0.0 < master.calls[0]["time_limit_seconds"] <= 3.0
    assert result.resource_window_resolve_count == 0
    assert result.resource_window_lower_bound_before is None


def test_master_phase_rejects_nonpositive_resolve_budget() -> None:
    with pytest.raises(ValueError, match="resolve limit"):
        DddNetworkMasterPhaseSolver(
            resource_window_cut_mode=DddResourceWindowCutMode.OFF,
            max_resource_window_rows_per_resolve=10,
            max_resource_window_resolves=0,
        )


def test_master_phase_adds_rows_and_reuses_incumbent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ropeway_skip_stop_optimization.optimization.ddd import network_master_phase

    row = SimpleNamespace(
        id="row",
        kind=DddAnonymousResourceRowKind.INTERVAL_CAPACITY,
    )
    separations = iter(
        (
            SimpleNamespace(
                rows=(row,),
                candidate_window_count=2,
                violated_candidate_count=1,
                duplicate_candidate_count=0,
            ),
            SimpleNamespace(
                rows=(),
                candidate_window_count=1,
                violated_candidate_count=0,
                duplicate_candidate_count=0,
            ),
        )
    )
    monkeypatch.setattr(
        network_master_phase,
        "separate_ddd_resource_window_rows",
        lambda *_args, **_kwargs: next(separations),
    )
    master = _FakeMaster((_flow(10.0), _flow(11.0)))
    network = SimpleNamespace(
        arcs=(SimpleNamespace(resource_windows=(object(),)),),
        cabin_ids=(0,),
    )
    solver = DddNetworkMasterPhaseSolver(
        resource_window_cut_mode=DddResourceWindowCutMode.ENTRY_COUNT,
        max_resource_window_rows_per_resolve=10,
        max_resource_window_resolves=2,
    )

    result = _solve(solver, master, network)

    assert len(master.calls) == 2
    assert master.calls[1]["resource_rows"] == (row,)
    assert isinstance(master.calls[1]["warm_start"], DddAnonymousFlowWarmStart)
    assert result.active_resource_rows == (row,)
    assert result.added_resource_rows == (row,)
    assert result.resource_window_resolve_count == 1
    assert result.resource_window_candidate_count == 3
    assert result.resource_window_violated_count == 1
    assert result.resource_window_entry_row_count == 1
    assert result.resource_window_lower_bound_before == 10.0
    assert result.resource_window_lower_bound_after == 11.0
