from __future__ import annotations

from dataclasses import replace
import json

import pytest

from ropeway_skip_stop_optimization.benchmarking.ddd_fixed_k_arc_flow import (
    DddFixedKArcFlowRunConfig,
)
from ropeway_skip_stop_optimization.benchmarking.ddd_partial_passenger_benders import (
    DddPartialPassengerGateConfig,
    DddPartialPassengerGateRunner,
    DddPartialPassengerGateVariant,
)
from ropeway_skip_stop_optimization.optimization.ddd import (
    DddFixedKOperatingMode,
    DddFixedKStartPolicy,
    DddPassengerCorePolicy,
)


def _config() -> DddPartialPassengerGateConfig:
    return DddPartialPassengerGateConfig(
        run=DddFixedKArcFlowRunConfig(
            example_id="five_station_circle_cw_half_skip_no_wait_v0",
            cabin_count=1,
            operating_mode=DddFixedKOperatingMode.SKIP_STOP,
            start_policy=DddFixedKStartPolicy.CANONICAL_ROPE,
        ),
        variants=(
            DddPartialPassengerGateVariant(
                id="all",
                policy=DddPassengerCorePolicy.ALL,
                core_variable_fraction=1.0,
                core_nonzero_fraction=1.0,
            ),
        ),
        per_variant_time_limit_seconds=10.0,
        max_iterations=2,
        reference_lp_objective=1_000_000.0,
    )


def test_partial_passenger_gate_runner_emits_fingerprinted_result() -> None:
    progress = []

    result = DddPartialPassengerGateRunner().run(
        _config(),
        progress_hook=lambda variant_id, sample: progress.append(
            (variant_id, sample.phase)
        ),
    )
    payload = result.to_payload()

    assert result.problem_fingerprint
    assert result.passenger_domain_fingerprint
    assert result.passenger_variable_count > 0
    assert result.variants[0].root.projected_lp_certified
    assert result.variants[0].core_nonzero_fraction == pytest.approx(1.0)
    assert not result.variants[0].passed
    assert progress[0] == ("all", "master_build")
    assert progress[-1] == ("all", "complete")
    assert json.loads(json.dumps(payload))["variants"][0]["root"][
        "status"
    ] == "projected_lp_optimal"


def test_partial_passenger_gate_rejects_waiting_in_version_one() -> None:
    config = _config()

    with pytest.raises(ValueError, match="No-Wait"):
        replace(
            config,
            run=replace(config.run, waiting_headway_multiplier=0.5),
        ).validate()
