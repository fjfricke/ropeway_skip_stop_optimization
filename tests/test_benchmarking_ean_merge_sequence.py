from __future__ import annotations

import json

from ropeway_skip_stop_optimization.benchmarking.ean_merge_sequence import (
    EanMergeSequenceGateCase,
    solve_ean_merge_sequence_gate,
    write_ean_merge_sequence_gate_results,
)
from ropeway_skip_stop_optimization.optimization.ean import (
    EanMergeGateFormulation,
    EanMergeGateSolveConfig,
)


def test_merge_sequence_gate_runner_compares_and_serializes(tmp_path) -> None:
    case = EanMergeSequenceGateCase(
        stream_size=2,
        release_pattern="adversarial",
        service_headway_seconds=10.0,
        skip_headway_seconds=5.0,
        seed=3,
    )
    config = EanMergeGateSolveConfig(
        time_limit_seconds=10.0,
        threads=1,
        seed=3,
    )
    results = solve_ean_merge_sequence_gate(
        case,
        formulations=(
            EanMergeGateFormulation.ENUMERATION,
            EanMergeGateFormulation.PAIRWISE_FIFO,
            EanMergeGateFormulation.LATTICE,
            EanMergeGateFormulation.SLOTS,
            EanMergeGateFormulation.CP_SAT,
        ),
        config=config,
    )
    output = tmp_path / "gate.json"

    write_ean_merge_sequence_gate_results(
        output,
        case=case,
        config=config,
        results=results,
    )

    assert all(result.status == "optimal" for result in results)
    assert len({round(result.objective or -1.0, 6) for result in results}) == 1
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert payload["case"]["stream_size"] == 2
    assert len(payload["results"]) == 5
