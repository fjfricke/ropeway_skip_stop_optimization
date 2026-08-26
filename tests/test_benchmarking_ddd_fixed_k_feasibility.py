from __future__ import annotations

from pathlib import Path
import json

import pytest

from ropeway_skip_stop_optimization.benchmarking.ddd_fixed_k_feasibility import (
    DddFixedKFeasibilityLivePublisher,
    DddFixedKFeasibilityTermination,
    DddFixedKFeasibilityProbeResult,
    DddFixedKFeasibilitySweepConfig,
    DddFixedKFeasibilitySweepResult,
    read_ddd_fixed_k_feasibility_sweep,
    run_ddd_fixed_k_feasibility_sweep,
    write_ddd_fixed_k_feasibility_sweep,
)
from ropeway_skip_stop_optimization.benchmarking.optimization_live_store import (
    OptimizationLivePaths,
    OptimizationLiveStore,
    reduce_optimization_events,
)
from ropeway_skip_stop_optimization.optimization.ddd import (
    DddFixedKSeedStatus,
)


def _probe(
    k: int,
    status: DddFixedKSeedStatus,
    *,
    attempt: int = 1,
    termination: DddFixedKFeasibilityTermination | None = None,
) -> DddFixedKFeasibilityProbeResult:
    if termination is None:
        termination = {
            DddFixedKSeedStatus.FEASIBLE: DddFixedKFeasibilityTermination.FEASIBLE,
            DddFixedKSeedStatus.MOVEMENT_INFEASIBLE: (
                DddFixedKFeasibilityTermination.PROVED_INFEASIBLE
            ),
            DddFixedKSeedStatus.UNKNOWN_NO_FEASIBLE_SEED: (
                DddFixedKFeasibilityTermination.TIME_LIMIT_UNKNOWN
            ),
            DddFixedKSeedStatus.INTERNAL_VALIDATION_ERROR: (
                DddFixedKFeasibilityTermination.INTERNAL_VALIDATION_ERROR
            ),
        }[status]
    return DddFixedKFeasibilityProbeResult(
        cabin_count=k,
        attempt_index=attempt,
        status=status,
        termination=termination,
        seed_kind="cp_sat" if status is DddFixedKSeedStatus.FEASIBLE else None,
        cp_sat_seconds=1.0,
        total_seconds=1.1,
        trajectory_count=k if status is DddFixedKSeedStatus.FEASIBLE else 0,
        problem_fingerprint=f"problem-{k}",
    )


def test_feasibility_sweep_stops_at_first_unknown_and_checkpoints(
    tmp_path: Path,
) -> None:
    config = DddFixedKFeasibilitySweepConfig("example", 23, 30)
    statuses = {
        23: DddFixedKSeedStatus.FEASIBLE,
        24: DddFixedKSeedStatus.FEASIBLE,
        25: DddFixedKSeedStatus.UNKNOWN_NO_FEASIBLE_SEED,
    }

    result = run_ddd_fixed_k_feasibility_sweep(
        config,
        probe=lambda _, k, _attempt: _probe(k, statuses[k]),
    )

    assert tuple(probe.cabin_count for probe in result.probes) == (23, 24, 25)
    assert result.largest_feasible_k == 24
    assert result.frontier_probe is not None
    assert result.frontier_probe.status is DddFixedKSeedStatus.UNKNOWN_NO_FEASIBLE_SEED
    path = tmp_path / "result.json"
    write_ddd_fixed_k_feasibility_sweep(result, path)
    assert read_ddd_fixed_k_feasibility_sweep(path, config=config) == result.probes


def test_feasibility_sweep_resumes_contiguously() -> None:
    config = DddFixedKFeasibilitySweepConfig(
        "example",
        23,
        26,
        stop_on_unknown=False,
    )
    existing = (_probe(23, DddFixedKSeedStatus.FEASIBLE),)

    result = run_ddd_fixed_k_feasibility_sweep(
        config,
        existing_probes=existing,
        probe=lambda _, k, _attempt: _probe(k, DddFixedKSeedStatus.FEASIBLE),
    )

    assert tuple(probe.cabin_count for probe in result.probes) == (23, 24, 25, 26)


def test_feasibility_checkpoint_rejects_changed_configuration(
    tmp_path: Path,
) -> None:
    config = DddFixedKFeasibilitySweepConfig("example", 23, 25)
    result = run_ddd_fixed_k_feasibility_sweep(
        config,
        probe=lambda _, k, _attempt: _probe(k, DddFixedKSeedStatus.FEASIBLE),
    )
    path = tmp_path / "result.json"
    write_ddd_fixed_k_feasibility_sweep(result, path)

    with pytest.raises(ValueError, match="configuration differs"):
        read_ddd_fixed_k_feasibility_sweep(
            path,
            config=DddFixedKFeasibilitySweepConfig("example", 23, 26),
        )


def test_premature_unknown_is_retried_once_before_advancing() -> None:
    config = DddFixedKFeasibilitySweepConfig("example", 23, 24)
    calls: list[tuple[int, int]] = []

    def probe(_, cabin_count: int, attempt: int):
        calls.append((cabin_count, attempt))
        if (cabin_count, attempt) == (23, 1):
            return _probe(
                23,
                DddFixedKSeedStatus.UNKNOWN_NO_FEASIBLE_SEED,
                termination=DddFixedKFeasibilityTermination.PREMATURE_UNKNOWN,
            )
        return _probe(cabin_count, DddFixedKSeedStatus.FEASIBLE, attempt=attempt)

    result = run_ddd_fixed_k_feasibility_sweep(config, probe=probe)

    assert calls == [(23, 1), (23, 2), (24, 1)]
    assert result.largest_feasible_k == 24


def test_resume_retries_legacy_premature_unknown_at_same_k() -> None:
    config = DddFixedKFeasibilitySweepConfig("example", 23, 25)
    existing = (
        _probe(23, DddFixedKSeedStatus.FEASIBLE),
        _probe(
            24,
            DddFixedKSeedStatus.UNKNOWN_NO_FEASIBLE_SEED,
            termination=DddFixedKFeasibilityTermination.PREMATURE_UNKNOWN,
        ),
    )
    calls: list[tuple[int, int]] = []

    result = run_ddd_fixed_k_feasibility_sweep(
        config,
        existing_probes=existing,
        probe=lambda _, k, attempt: (
            calls.append((k, attempt))
            or _probe(k, DddFixedKSeedStatus.FEASIBLE, attempt=attempt)
        ),
    )

    assert calls == [(24, 2), (25, 1)]
    assert result.largest_feasible_k == 25


def test_legacy_checkpoint_is_migrated_and_retries_frontier_unknown(
    tmp_path: Path,
) -> None:
    config = DddFixedKFeasibilitySweepConfig(
        "example",
        54,
        55,
        time_limit_seconds_per_k=600.0,
    )
    path = tmp_path / "legacy.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "config_fingerprint": config.legacy_fingerprint,
                "probes": [
                    {
                        "cabin_count": 54,
                        "status": "unknown_no_feasible_seed",
                        "seed_kind": None,
                        "cp_sat_seconds": 4.5,
                        "total_seconds": 5.0,
                        "trajectory_count": 0,
                        "problem_fingerprint": "legacy-54",
                        "detail": "CP-SAT seed search ended with unknown",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    existing = read_ddd_fixed_k_feasibility_sweep(path, config=config)
    calls: list[tuple[int, int]] = []
    result = run_ddd_fixed_k_feasibility_sweep(
        config,
        existing_probes=existing,
        probe=lambda _, k, attempt: (
            calls.append((k, attempt))
            or _probe(k, DddFixedKSeedStatus.FEASIBLE, attempt=attempt)
        ),
    )

    assert existing[0].termination is DddFixedKFeasibilityTermination.PREMATURE_UNKNOWN
    assert calls == [(54, 2), (55, 1)]
    assert result.largest_feasible_k == 55


def test_resume_does_not_repeat_exhausted_premature_unknown() -> None:
    config = DddFixedKFeasibilitySweepConfig("example", 23, 25)
    existing = (
        _probe(
            23,
            DddFixedKSeedStatus.UNKNOWN_NO_FEASIBLE_SEED,
            attempt=1,
            termination=DddFixedKFeasibilityTermination.PREMATURE_UNKNOWN,
        ),
        _probe(
            23,
            DddFixedKSeedStatus.UNKNOWN_NO_FEASIBLE_SEED,
            attempt=2,
            termination=DddFixedKFeasibilityTermination.PREMATURE_UNKNOWN,
        ),
    )
    calls: list[tuple[int, int]] = []

    result = run_ddd_fixed_k_feasibility_sweep(
        config,
        existing_probes=existing,
        probe=lambda _, k, attempt: (
            calls.append((k, attempt))
            or _probe(k, DddFixedKSeedStatus.FEASIBLE, attempt=attempt)
        ),
    )

    assert calls == []
    assert result.probes == existing


def test_live_publisher_imports_checkpoint_without_solving(
    tmp_path: Path,
) -> None:
    config = DddFixedKFeasibilitySweepConfig("example", 53, 54)
    probes = (
        _probe(53, DddFixedKSeedStatus.FEASIBLE),
        _probe(
            54,
            DddFixedKSeedStatus.UNKNOWN_NO_FEASIBLE_SEED,
            termination=DddFixedKFeasibilityTermination.PREMATURE_UNKNOWN,
        ),
    )
    store = OptimizationLiveStore(
        OptimizationLivePaths(tmp_path / "canonical", tmp_path / "frontend")
    )
    publisher = DddFixedKFeasibilityLivePublisher(
        store=store,
        campaign_id="feasibility",
        config=config,
        label="Feasibility",
    )

    result = DddFixedKFeasibilitySweepResult(config.fingerprint, probes)
    publisher.publish_checkpoint(result)

    snapshot = reduce_optimization_events(store.read_events())
    assert snapshot["status"] == "complete"
    assert snapshot["largest_certified_feasible_k"] == 53
    assert snapshot["frontier_k"] == 54
    assert snapshot["trials"]["skip_stop__k53"]["solver_status"] == "feasible"
    unknown = snapshot["trials"]["skip_stop__k54"]
    assert unknown["solver_status"] == "unknown_no_feasible_seed"
    assert unknown["termination"] == "premature_unknown"
    assert (tmp_path / "frontend" / "feasibility" / "snapshot.json").exists()
    index = json.loads((tmp_path / "frontend" / "index.json").read_text())
    summary = index["campaigns"][0]
    assert summary["campaign_kind"] == "movement_feasibility"
    assert summary["largest_certified_feasible_k"] == 53
    assert summary["frontier_k"] == 54
    assert summary["frontier_status"] == "unknown_no_feasible_seed"

    event_count = len(store.read_events())
    publisher.publish_checkpoint(result)
    assert len(store.read_events()) == event_count
