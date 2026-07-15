from __future__ import annotations

from types import SimpleNamespace

import pytest

from ropeway_skip_stop_optimization.benchmarking.ean_bottleneck import (
    EanBottleneckCase,
    EanBottleneckDiagnosticConfig,
    EanBottleneckDiagnosticRunner,
)
from ropeway_skip_stop_optimization.benchmarking.plots import (
    EanBottleneckPlotBuilder,
)
from ropeway_skip_stop_optimization.optimization.ean import (
    EanMipStartStrategy,
    EanMovementFeasibilityProblem,
    EanPassengerServiceProblem,
)


def test_bottleneck_runner_builds_all_three_cases(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    problems: list[object] = []
    integrated_plan = object()

    def fake_solve(self, problem, solver_policy):
        problems.append(problem)
        return (
            SimpleNamespace(
                movement_plan=(
                    integrated_plan
                    if len(problems) == 1
                    else None
                ),
                metadata=None,
            ),
            None,
        )

    monkeypatch.setattr(
        EanBottleneckDiagnosticRunner,
        "_solve",
        fake_solve,
    )
    result, output_path = EanBottleneckDiagnosticRunner(
        EanBottleneckDiagnosticConfig(
            output_dir=tmp_path,
            log_to_console=False,
        )
    ).run()

    assert output_path.is_file()
    assert [case.case for case in result.cases] == [
        EanBottleneckCase.INTEGRATED,
        EanBottleneckCase.MOVEMENT_ONLY,
        EanBottleneckCase.FIXED_MOVEMENT_PASSENGER,
    ]
    assert isinstance(problems[0], EanPassengerServiceProblem)
    assert isinstance(problems[1], EanMovementFeasibilityProblem)
    assert isinstance(problems[2], EanPassengerServiceProblem)
    assert problems[2].fixed_movement_plan is integrated_plan
    assert (
        problems[2].mip_start_strategy
        is EanMipStartStrategy.NONE
    )


def test_bottleneck_diagnostic_config_rejects_invalid_intervals() -> None:
    with pytest.raises(ValueError, match="time_limit_seconds"):
        EanBottleneckDiagnosticConfig(time_limit_seconds=0).validate()
    with pytest.raises(ValueError, match="sample_interval_seconds"):
        EanBottleneckDiagnosticConfig(
            sample_interval_seconds=0
        ).validate()


def test_bottleneck_plot_builder_writes_case_comparisons(tmp_path) -> None:
    diagnostic = {
        "example_id": "example",
        "cases": [
            {
                "case": "integrated",
                "metadata": {
                    "runtime_seconds": 10.0,
                    "variable_count": 100,
                    "constraint_count": 200,
                    "model_nonzero_count": 300,
                    "build_metrics": {
                        "passenger_candidate_generation_seconds": 1.0,
                        "movement_model_seconds": 2.0,
                        "movement_fixing_seconds": 0.0,
                        "passenger_model_seconds": 3.0,
                        "mip_start_seconds": 0.5,
                    },
                    "solve_phase_metrics": {
                        "presolve_runtime_seconds": 4.0,
                        "root_relaxation_runtime_seconds": 2.0,
                        "first_incumbent_runtime_seconds": 5.0,
                        "peak_memory_gb": 0.25,
                    },
                },
            }
        ],
    }

    paths = EanBottleneckPlotBuilder(diagnostic).write_all(
        tmp_path,
        prefix="run",
    )

    assert {path.name for path in paths} == {
        "run__runtime_by_case.svg",
        "run__model_size_by_case.svg",
        "run__build_time_by_case.svg",
        "run__solve_phases_by_case.svg",
        "run__memory_by_case.svg",
    }
    assert all(
        path.read_text(encoding="utf-8").startswith("<svg")
        for path in paths
    )


def test_bottleneck_plot_builder_writes_root_diagnostics(tmp_path) -> None:
    diagnostic = {
        "example_id": "example",
        "cases": [
            {
                "case": "integrated",
                "metadata": {},
                "root_relaxation": {
                    "samples": [
                        {
                            "runtime_seconds": 5.0,
                            "best_bound": 100.0,
                            "families": [
                                {
                                    "family": "stop",
                                    "fractional_variable_count": 4,
                                },
                                {
                                    "family": "passenger_slot",
                                    "fractional_variable_count": 12,
                                },
                            ],
                        },
                        {
                            "runtime_seconds": 10.0,
                            "best_bound": 120.0,
                            "families": [
                                {
                                    "family": "stop",
                                    "fractional_variable_count": 2,
                                },
                                {
                                    "family": "passenger_slot",
                                    "fractional_variable_count": 8,
                                },
                            ],
                        },
                    ]
                },
            }
        ],
    }

    paths = EanBottleneckPlotBuilder(diagnostic).write_all(
        tmp_path,
        prefix="run",
    )

    assert {
        "run__root_fractionality_by_case.svg",
        "run__root_bound_over_time.svg",
    }.issubset({path.name for path in paths})
