from __future__ import annotations

from types import SimpleNamespace

import pytest

from ropeway_skip_stop_optimization.benchmarking.ean_root_relaxation import (
    EanRootRelaxationRecorder,
    EanVariableFamily,
)


class _FakeVariable:
    def __init__(self, *, variable_type: str, objective: float = 0.0) -> None:
        self.VType = variable_type
        self.Obj = objective


class _FakeCallback:
    MIPNODE = 1
    MIPNODE_STATUS = 2
    MIPNODE_NODCNT = 3
    MIPNODE_OBJBST = 4
    MIPNODE_OBJBND = 5
    RUNTIME = 6
    WORK = 7


class _FakeGRB:
    Callback = _FakeCallback
    OPTIMAL = 2
    INFINITY = 1e100


class _FakeCallbackModel:
    def __init__(self) -> None:
        self.values: dict[int, float] = {}
        self.node_values: dict[_FakeVariable, float] = {}

    def cbGet(self, code: int) -> float:
        return self.values[code]

    def cbGetNodeRel(
        self,
        variables: list[_FakeVariable],
    ) -> list[float]:
        return [self.node_values[variable] for variable in variables]


def test_root_relaxation_recorder_groups_fractional_variables() -> None:
    stop = _FakeVariable(variable_type="B")
    switch_time = _FakeVariable(variable_type="C")
    slot = _FakeVariable(variable_type="B", objective=10.0)
    unserved = _FakeVariable(variable_type="I", objective=100.0)
    movement_model = SimpleNamespace(
        variables=SimpleNamespace(
            switch_time={(0, 0): switch_time},
            exit_switch_time={},
            wait_time={},
            stop={(0, 0): stop},
            visit_active={(0, 0): 1.0},
            checkpoint_within_horizon={},
            headway_order={},
        )
    )
    passenger_model = SimpleNamespace(
        variables=SimpleNamespace(
            slot={("ride", 0): slot},
            slot_board_time=None,
            slot_alight_time=None,
            unserved={"group": unserved},
        )
    )
    recorder = EanRootRelaxationRecorder(sample_interval_seconds=5.0)
    recorder.bind_models(movement_model, passenger_model)
    recorder.begin_run()
    model = _FakeCallbackModel()
    model.values = {
        _FakeCallback.MIPNODE_STATUS: _FakeGRB.OPTIMAL,
        _FakeCallback.MIPNODE_NODCNT: 0.0,
        _FakeCallback.MIPNODE_OBJBST: 200.0,
        _FakeCallback.MIPNODE_OBJBND: 120.0,
        _FakeCallback.RUNTIME: 10.0,
        _FakeCallback.WORK: 4.0,
    }
    model.node_values = {
        stop: 0.25,
        switch_time: 8.0,
        slot: 0.5,
        unserved: 1.2,
    }

    recorder.record_callback(
        model,
        _FakeGRB,
        _FakeCallback.MIPNODE,
        sample_interval_seconds=1.0,
    )

    sample = recorder.diagnostic.samples[0]
    metrics = {metric.family: metric for metric in sample.families}
    assert sample.fractional_variable_count == 3
    assert sample.fractional_distance_sum == pytest.approx(0.95)
    assert sample.linear_objective_value == pytest.approx(125.0)
    assert metrics[EanVariableFamily.STOP].fractional_share == 1.0
    assert (
        metrics[
            EanVariableFamily.PASSENGER_SLOT
        ].maximum_fractional_distance
        == 0.5
    )
    assert metrics[EanVariableFamily.SWITCH_TIME].fractional_share is None


def test_root_relaxation_recorder_samples_only_optimal_root_nodes() -> None:
    stop = _FakeVariable(variable_type="B")
    movement_model = SimpleNamespace(
        variables=SimpleNamespace(
            switch_time={},
            exit_switch_time={},
            wait_time={},
            stop={(0, 0): stop},
            visit_active={},
            checkpoint_within_horizon={},
            headway_order={},
        )
    )
    recorder = EanRootRelaxationRecorder(sample_interval_seconds=5.0)
    recorder.bind_models(movement_model, None)
    model = _FakeCallbackModel()
    model.node_values = {stop: 0.5}

    for runtime, status, node_count in (
        (1.0, 1, 0.0),
        (2.0, _FakeGRB.OPTIMAL, 1.0),
        (3.0, _FakeGRB.OPTIMAL, 0.0),
        (6.0, _FakeGRB.OPTIMAL, 0.0),
        (8.0, _FakeGRB.OPTIMAL, 0.0),
    ):
        model.values = {
            _FakeCallback.MIPNODE_STATUS: status,
            _FakeCallback.MIPNODE_NODCNT: node_count,
            _FakeCallback.MIPNODE_OBJBST: 100.0,
            _FakeCallback.MIPNODE_OBJBND: 50.0,
            _FakeCallback.RUNTIME: runtime,
            _FakeCallback.WORK: runtime,
        }
        recorder.record_callback(
            model,
            _FakeGRB,
            _FakeCallback.MIPNODE,
            sample_interval_seconds=1.0,
        )

    assert [
        sample.runtime_seconds
        for sample in recorder.diagnostic.samples
    ] == [3.0, 8.0]
