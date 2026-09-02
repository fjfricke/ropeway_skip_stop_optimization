from __future__ import annotations

import math

import pytest

from ropeway_skip_stop_optimization.optimization.ean import (
    EanCpSatMergeGateSolver,
    EanEnumeratedMergeGateSolver,
    EanLatticeMergeGateSolver,
    EanMergeGateEvent,
    EanMergeGateInstance,
    EanMergeGateSolveConfig,
    EanMergeStream,
    EanPairwiseMergeGateSolver,
    EanSlotMergeGateSolver,
    enumerate_stable_merge_sequences,
)


def _instance(service_count: int = 3, skip_count: int = 3) -> EanMergeGateInstance:
    events = tuple(
        EanMergeGateEvent(
            id=f"s_{index}",
            stream=EanMergeStream.SERVICE,
            stream_index=index,
            release_seconds=float(3 * index),
            weight=float(index + 1),
        )
        for index in range(service_count)
    ) + tuple(
        EanMergeGateEvent(
            id=f"p_{index}",
            stream=EanMergeStream.SKIP,
            stream_index=index,
            release_seconds=float(2 + 4 * index),
            weight=float(skip_count - index + 1),
        )
        for index in range(skip_count)
    )
    return EanMergeGateInstance(
        id=f"gate_{service_count}_{skip_count}",
        events=events,
        service_leader_headway_seconds=5.0,
        skip_leader_headway_seconds=3.0,
    )


@pytest.mark.parametrize(("service_count", "skip_count"), ((1, 1), (2, 3), (4, 4)))
def test_stable_merge_universe_has_binomial_cardinality(
    service_count: int,
    skip_count: int,
) -> None:
    instance = _instance(service_count, skip_count)
    sequences = enumerate_stable_merge_sequences(instance)

    assert len(sequences) == math.comb(service_count + skip_count, service_count)
    assert len(set(sequences)) == len(sequences)
    event_by_id = {event.id: event for event in instance.events}
    for sequence in sequences:
        for stream in (EanMergeStream.SERVICE, EanMergeStream.SKIP):
            assert tuple(
                event_by_id[event_id].stream_index
                for event_id in sequence
                if event_by_id[event_id].stream is stream
            ) == tuple(
                range(service_count if stream is EanMergeStream.SERVICE else skip_count)
            )


def test_all_isolated_formulations_match_complete_enumeration() -> None:
    instance = _instance()
    config = EanMergeGateSolveConfig(time_limit_seconds=30.0, threads=1, seed=7)
    solvers = (
        EanEnumeratedMergeGateSolver(),
        EanPairwiseMergeGateSolver(),
        EanLatticeMergeGateSolver(),
        EanSlotMergeGateSolver(),
        EanCpSatMergeGateSolver(),
    )

    solutions = tuple(solver.solve(instance, config) for solver in solvers)
    oracle = solutions[0]

    assert all(solution.status == "optimal" for solution in solutions)
    assert all(solution.objective == pytest.approx(oracle.objective) for solution in solutions)
    for solution in solutions:
        solution.validate_against(instance)


def test_leader_behavior_changes_adjacent_separation_exactly() -> None:
    instance = EanMergeGateInstance(
        id="leader_behavior",
        events=(
            EanMergeGateEvent("s", EanMergeStream.SERVICE, 0, 0.0),
            EanMergeGateEvent("p", EanMergeStream.SKIP, 0, 0.0),
        ),
        service_leader_headway_seconds=10.0,
        skip_leader_headway_seconds=2.0,
    )

    solution = EanEnumeratedMergeGateSolver().solve(instance)

    assert solution.sequence == ("p", "s")
    assert dict(solution.time_by_event_id) == pytest.approx({"p": 0.0, "s": 2.0})
    assert solution.objective == pytest.approx(2.0)


def test_gate_rejects_noncontiguous_stream_indices() -> None:
    instance = EanMergeGateInstance(
        id="invalid",
        events=(
            EanMergeGateEvent("s", EanMergeStream.SERVICE, 2, 0.0),
            EanMergeGateEvent("p", EanMergeStream.SKIP, 0, 0.0),
        ),
        service_leader_headway_seconds=1.0,
        skip_leader_headway_seconds=1.0,
    )

    with pytest.raises(ValueError, match="contiguous"):
        enumerate_stable_merge_sequences(instance)
