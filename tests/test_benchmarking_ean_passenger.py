from __future__ import annotations

import json
from pathlib import Path

from ropeway_skip_stop_optimization.benchmarking.ean_passenger import (
    GurobiMipProgressRecorder,
)
from ropeway_skip_stop_optimization.benchmarking.plots import PlotBuilder, collect_result_paths


def test_gurobi_mip_progress_recorder_samples_intervals_and_incumbents() -> None:
    recorder = GurobiMipProgressRecorder()
    model = _FakeCallbackModel()

    model.values = {
        _FakeCallback.RUNTIME: 0.0,
        _FakeCallback.MIP_OBJBST: 100.0,
        _FakeCallback.MIP_OBJBND: 50.0,
        _FakeCallback.MIP_NODCNT: 0.0,
        _FakeCallback.MIP_SOLCNT: 0.0,
    }
    recorder.record_callback(model, _FakeGRB, _FakeCallback.MIP, sample_interval_seconds=5.0)

    model.values = {
        _FakeCallback.RUNTIME: 4.0,
        _FakeCallback.MIP_OBJBST: 90.0,
        _FakeCallback.MIP_OBJBND: 60.0,
        _FakeCallback.MIP_NODCNT: 8.0,
        _FakeCallback.MIP_SOLCNT: 1.0,
    }
    recorder.record_callback(model, _FakeGRB, _FakeCallback.MIP, sample_interval_seconds=5.0)

    model.values = {
        _FakeCallback.RUNTIME: 5.1,
        _FakeCallback.MIP_OBJBST: 80.0,
        _FakeCallback.MIP_OBJBND: 64.0,
        _FakeCallback.MIP_NODCNT: 10.0,
        _FakeCallback.MIP_SOLCNT: 2.0,
    }
    recorder.record_callback(model, _FakeGRB, _FakeCallback.MIP, sample_interval_seconds=5.0)

    model.values = {
        _FakeCallback.RUNTIME: 5.2,
        _FakeCallback.MIPSOL_OBJ: 78.0,
        _FakeCallback.MIPSOL_OBJBND: 64.0,
        _FakeCallback.MIPSOL_NODCNT: 10.0,
        _FakeCallback.MIPSOL_SOLCNT: 3.0,
    }
    recorder.record_callback(model, _FakeGRB, _FakeCallback.MIPSOL, sample_interval_seconds=5.0)
    recorder.record_callback(model, _FakeGRB, _FakeCallback.MIPSOL, sample_interval_seconds=5.0)

    assert [sample.event for sample in recorder.samples] == ["interval", "interval", "incumbent"]
    assert recorder.samples[0].runtime_seconds == 0.0
    assert recorder.samples[1].runtime_seconds == 5.1
    assert recorder.samples[1].mip_gap == 0.2
    assert recorder.samples[2].incumbent_objective == 78.0


def test_gurobi_mip_progress_recorder_records_final_model_state() -> None:
    recorder = GurobiMipProgressRecorder()
    model = _FakeFinalModel()

    recorder.record_final(model, _FakeGRB)

    assert len(recorder.samples) == 1
    sample = recorder.samples[0]
    assert sample.event == "final"
    assert sample.runtime_seconds == 12.5
    assert sample.node_count == 42.0
    assert sample.incumbent_objective == 120.0
    assert sample.best_bound == 100.0
    assert sample.mip_gap == 0.166
    assert sample.solution_count == 3


def test_plot_builder_writes_expected_svg_files(tmp_path: Path) -> None:
    result = _benchmark_result("run-a")
    output_paths = PlotBuilder((result,)).write_all(tmp_path)

    names = {path.name for path in output_paths}
    assert "gap_over_time.svg" in names
    assert "objective_and_bound_over_time.svg" in names
    assert "runtime_by_run.svg" in names
    assert (tmp_path / "gap_over_time.svg").read_text(encoding="utf-8").startswith("<svg")


def test_collect_result_paths_uses_input_dir_when_inputs_empty(tmp_path: Path) -> None:
    result_path = tmp_path / "result.json"
    result_path.write_text(json.dumps(_benchmark_result("run-a")), encoding="utf-8")

    assert collect_result_paths((), tmp_path) == (result_path,)


class _FakeCallback:
    MIP = 1
    MIPSOL = 2
    RUNTIME = 3
    WORK = 4
    MIP_OBJBST = 5
    MIP_OBJBND = 6
    MIP_NODCNT = 7
    MIP_SOLCNT = 8
    MIPSOL_OBJ = 9
    MIPSOL_OBJBND = 10
    MIPSOL_NODCNT = 11
    MIPSOL_SOLCNT = 12


class _FakeGRB:
    Callback = _FakeCallback


class _FakeCallbackModel:
    def __init__(self) -> None:
        self.values: dict[int, float] = {}

    def cbGet(self, code: int) -> float:
        return self.values[code]


class _FakeFinalModel:
    Runtime = 12.5
    NodeCount = 42.0
    ObjVal = 120.0
    ObjBound = 100.0
    MIPGap = 0.166
    SolCount = 3
    Work = 99.0


def _benchmark_result(label: str) -> dict[str, object]:
    return {
        "label": label,
        "runtime_seconds": 12.0,
        "mip_gap": 0.05,
        "objective_passenger_hours": 2.5,
        "model_variable_count": 100,
        "model_constraint_count": 200,
        "demand_group_count": 4,
        "ride_candidate_count": 25,
        "slot_variable_count": 180,
        "progress_samples": [
            {
                "runtime_seconds": 0.0,
                "node_count": 0,
                "incumbent_objective": 200.0,
                "best_bound": 100.0,
                "mip_gap": 0.5,
            },
            {
                "runtime_seconds": 12.0,
                "node_count": 42,
                "incumbent_objective": 120.0,
                "best_bound": 114.0,
                "mip_gap": 0.05,
            },
        ],
    }
