from __future__ import annotations

from pathlib import Path
from dataclasses import replace

import pytest

from ropeway_skip_stop_optimization.benchmarking.ddd_fleet_sweep import (
    DddFleetPolicyConfig,
    DddFleetSweepAnalyzer,
    DddFleetSweepConfig,
    DddFleetSweepRunner,
    DddFleetTrialResult,
    DispatchCardinality,
    trial_fingerprint,
)
from ropeway_skip_stop_optimization.benchmarking.optimization_events import (
    OptimizationEventKind,
    OptimizationProgressEvent,
)
from ropeway_skip_stop_optimization.benchmarking.optimization_live_store import (
    OptimizationLivePaths,
    OptimizationLiveStore,
    reduce_optimization_events,
)


def test_optional_dispatch_envelope_preserves_bound_provenance() -> None:
    config = _config()
    analysis = DddFleetSweepAnalyzer().analyze(
        config,
        (
            _trial(18, lower=100.0, upper=140.0),
            _trial(19, lower=110.0, upper=130.0),
            _trial(20, lower=105.0, upper=125.0),
        ),
    )
    bounds = analysis["policies"]["skip"]["bounds"]
    assert bounds[0]["tightened_lower_bound"] == 110.0
    assert bounds[0]["lower_bound_source_k"] == 19
    assert bounds[2]["tightened_upper_bound"] == 125.0
    assert bounds[2]["upper_bound_source_k"] == 20


def test_exact_dispatch_does_not_mix_fleet_bounds() -> None:
    config = replace(
        _config(),
        dispatch_cardinality=DispatchCardinality.EXACT,
    )
    analysis = DddFleetSweepAnalyzer().analyze(
        config,
        (_trial(18, lower=100.0, upper=140.0), _trial(19, lower=110.0, upper=130.0)),
    )
    first = analysis["policies"]["skip"]["bounds"][0]
    assert first["tightened_lower_bound"] == 100.0
    assert first["tightened_upper_bound"] == 140.0


def test_trial_fingerprint_is_stable_and_covers_k() -> None:
    config = _config()
    policy = config.policies[0]
    assert trial_fingerprint(config, policy, 18) == trial_fingerprint(config, policy, 18)
    assert trial_fingerprint(config, policy, 18) != trial_fingerprint(config, policy, 19)


def test_event_store_is_ordered_atomic_and_reducible(tmp_path: Path) -> None:
    frontend = tmp_path / "frontend"
    store = OptimizationLiveStore(
        OptimizationLivePaths(tmp_path / "campaign", frontend)
    )
    store.append(
        OptimizationProgressEvent(
            sequence=1,
            kind=OptimizationEventKind.CAMPAIGN_STARTED,
            campaign_id="test",
            payload={"label": "Test"},
        )
    )
    store.append(
        OptimizationProgressEvent(
            sequence=2,
            kind=OptimizationEventKind.TRIAL_STARTED,
            campaign_id="test",
            policy_id="skip",
            available_fleet_count=18,
        )
    )
    snapshot = reduce_optimization_events(store.read_events())
    store.publish(snapshot)
    assert snapshot["status"] == "running"
    assert snapshot["trials"]["skip__k18"]["status"] == "running"
    assert (frontend / "test" / "snapshot.json").exists()
    assert (frontend / "index.json").exists()
    with pytest.raises(ValueError, match="expected event sequence"):
        store.append(
            OptimizationProgressEvent(
                sequence=4,
                kind=OptimizationEventKind.HEARTBEAT,
                campaign_id="test",
            )
        )


def test_sweep_runner_publishes_complete_campaign(tmp_path: Path) -> None:
    config = _config()
    store = OptimizationLiveStore(
        OptimizationLivePaths(tmp_path / "test", tmp_path / "frontend")
    )

    call_count = 0

    def execute(**kwargs: object) -> DddFleetTrialResult:
        nonlocal call_count
        call_count += 1
        fleet_count = int(kwargs["available_fleet_count"])
        callback = kwargs["on_round"]
        assert callable(callback)
        callback(
            {
                "round_index": 1,
                "global_lower_bound": float(fleet_count),
                "global_upper_bound": float(fleet_count + 2),
            }
        )
        checkpoint = Path(kwargs["trial_dir"]) / "checkpoint.json"
        checkpoint.write_text("{}\n", encoding="utf-8")
        return replace(
            _trial(
                fleet_count,
                lower=float(fleet_count),
                upper=float(fleet_count + 2),
            ),
            checkpoint_path=str(checkpoint),
        )

    result = DddFleetSweepRunner(executor=execute).run(
        config,
        output_root=tmp_path,
        live_store=store,
    )
    assert result["status"] == "complete"
    snapshot = reduce_optimization_events(store.read_events())
    assert snapshot["status"] == "complete"
    assert snapshot["trial_count"] == 3
    assert snapshot["completed_trial_count"] == 3
    assert call_count == 3

    repeated = DddFleetSweepRunner(executor=execute).run(
        config,
        output_root=tmp_path,
        live_store=store,
    )
    assert repeated["completed_trial_count"] == 3
    assert call_count == 3


def _config() -> DddFleetSweepConfig:
    return DddFleetSweepConfig(
        campaign_id="test",
        label="Test",
        policies=(
            DddFleetPolicyConfig(
                id="skip",
                label="Skip",
                example_id="example",
                reservoir_entry_state="A",
            ),
        ),
        fleet_counts=(18, 19, 20),
        service_targets=(128.0,),
        cabin_costs=(1.0,),
    )


def _trial(k: int, *, lower: float, upper: float) -> DddFleetTrialResult:
    return DddFleetTrialResult(
        policy_id="skip",
        available_fleet_count=k,
        status="time_limit",
        certified_lower_bound=lower,
        validated_upper_bound=upper,
        relative_gap=(upper - lower) / upper,
        root_lp_certified=False,
        elapsed_seconds=1.0,
    )
