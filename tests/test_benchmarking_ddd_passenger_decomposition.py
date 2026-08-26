from __future__ import annotations

import json

from ropeway_skip_stop_optimization.benchmarking.ddd_fixed_k_arc_flow import (
    DddFixedKArcFlowRunConfig,
)
from ropeway_skip_stop_optimization.benchmarking.ddd_passenger_decomposition import (
    DddPassengerDecompositionDiagnosticConfig,
    run_ddd_passenger_decomposition_diagnostic,
    write_ddd_passenger_decomposition_diagnostic,
)
from ropeway_skip_stop_optimization.optimization.ddd import (
    DddFixedKOperatingMode,
    DddFixedKStartPolicy,
)


def test_passenger_decomposition_diagnostic_writes_reproducible_sample(
    tmp_path,
) -> None:
    config = DddPassengerDecompositionDiagnosticConfig(
        run=DddFixedKArcFlowRunConfig(
            example_id="five_station_circle_cw_half_skip_no_wait_v0",
            cabin_count=1,
            operating_mode=DddFixedKOperatingMode.SKIP_STOP,
            start_policy=DddFixedKStartPolicy.CANONICAL_ROPE,
            total_time_limit_seconds=10.0,
        ),
        movement_time_limit_seconds=10.0,
        passenger_time_limit_seconds=10.0,
        solver_seeds=(0,),
    )

    result = run_ddd_passenger_decomposition_diagnostic(config)
    output_path = tmp_path / "diagnostic.json"
    write_ddd_passenger_decomposition_diagnostic(result, output_path)
    payload = json.loads(output_path.read_text(encoding="utf-8"))

    assert result.unique_movement_count == 1
    assert result.samples[0].passenger is not None
    assert result.samples[0].passenger.gap_is_exact
    assert payload["method"] == (
        "complete_ddd_movement_passenger_lp_ip_diagnostic"
    )
    assert payload["samples"][0]["passenger"]["lp"]["assignment_domain"] == (
        "lp_relaxation"
    )
