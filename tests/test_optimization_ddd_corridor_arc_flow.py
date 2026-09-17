from __future__ import annotations

import pytest

from ropeway_skip_stop_optimization.benchmarking.ddd_fixed_k_didp import prepare_small
from ropeway_skip_stop_optimization.optimization.ddd.corridor_arc_flow import (
    CorridorArcFlowConfig,
    CorridorAdaptiveConfig,
    CorridorAdaptiveOptimizer,
    anchor_corridor_partitions,
    CorridorArcFlowMode,
    CorridorArcFlowOptimizer,
    CorridorArcFlowSolveConfig,
    CorridorArcFlowStatus,
    build_cycle_spacing_waiting_policy,
    prepare_corridor_problem,
    optimize_corridor_seed_passengers,
    refine_corridor_partition,
)
from ropeway_skip_stop_optimization.optimization.ddd.reference import (
    validate_ddd_reference_solution,
)


def _problem(k=1, waiting=10):
    return prepare_small(k, waiting=waiting, step=1e-6)[1]


def test_cycle_spacing_waiting_cap_is_rounded_once_and_uses_microsecond_ticks():
    problem = _problem(2)
    policy = build_cycle_spacing_waiting_policy(problem)
    maxima = {value for _, value in policy.maximum_wait_seconds_by_station_id}
    assert len(maxima) == 1
    assert next(iter(maxima)) == int(next(iter(maxima)))
    assert policy.step_seconds == 0.000001


def test_waiting_cap_definitions_are_mutually_exclusive():
    with pytest.raises(ValueError, match="exactly one"):
        CorridorArcFlowConfig(explicit_maximum_wait_seconds=3).validate()


def test_corridor_preparation_does_not_enumerate_wait_ticks():
    problem = _problem()
    short = prepare_corridor_problem(
        problem,
        config=CorridorArcFlowConfig(waiting_cap_multiplier=None, explicit_maximum_wait_seconds=1),
    )
    long = prepare_corridor_problem(
        problem,
        config=CorridorArcFlowConfig(waiting_cap_multiplier=None, explicit_maximum_wait_seconds=1_000),
    )
    assert len(short.arcs) == len(long.arcs)
    assert any(cell.width_ticks > 100_000_000 for p in long.wait_partitions for cell in p.cells)


def test_refinement_preserves_tick_coverage_and_changes_only_one_partition():
    prepared = prepare_corridor_problem(
        _problem(),
        config=CorridorArcFlowConfig(waiting_cap_multiplier=None, explicit_maximum_wait_seconds=3),
    )
    target = next(
        p for p in prepared.wait_partitions if any(c.width_ticks > 1 for c in p.cells)
    )
    cell = max(target.cells, key=lambda item: item.width_ticks)
    boundary = cell.lower_tick + cell.width_ticks // 2
    refined = refine_corridor_partition(
        prepared,
        partition_key=target.key,
        boundary_tick=boundary,
        config=CorridorArcFlowConfig(waiting_cap_multiplier=None, explicit_maximum_wait_seconds=3),
    )
    old = prepared.wait_partition_by_key[target.key]
    new = refined.wait_partition_by_key[target.key]
    assert new.lower_tick == old.lower_tick
    assert new.upper_tick == old.upper_tick
    assert boundary in new.boundaries
    assert len(new.cells) == len(old.cells) + 1
    assert refined.model_fingerprint != prepared.model_fingerprint


def test_targeted_anchor_makes_exact_tick_a_singleton_without_losing_coverage():
    config = CorridorArcFlowConfig(
        waiting_cap_multiplier=None, explicit_maximum_wait_seconds=3
    )
    prepared = prepare_corridor_problem(_problem(), config=config)
    target = next(
        p for p in prepared.wait_partitions if any(c.width_ticks > 2 for c in p.cells)
    )
    cell = max(target.cells, key=lambda item: item.width_ticks)
    value = cell.lower_tick + cell.width_ticks // 2
    refined = anchor_corridor_partitions(
        prepared, anchors=((target.key, value),), config=config
    )
    partition = refined.wait_partition_by_key[target.key]
    assert any(c.lower_tick == value and c.width_ticks == 1 for c in partition.cells)
    assert partition.lower_tick == target.lower_tick
    assert partition.upper_tick == target.upper_tick


def test_outer_hull_contains_and_mandatory_core_is_contained_in_every_realization():
    prepared = prepare_corridor_problem(
        _problem(),
        config=CorridorArcFlowConfig(waiting_cap_multiplier=None, explicit_maximum_wait_seconds=0.000003),
    )
    movement = prepared.problem.resolved_trajectory_problem.structural_movement_problem
    options = {option.id: option for option in movement.route_options}
    checked = 0
    for arc in prepared.arcs:
        if arc.source_interval.width_ticks > 10:
            continue
        option = options[arc.option_id]
        for window, usage in zip(arc.resources, option.resource_usages, strict=True):
            resource = movement.resources_by_id[usage.resource_id]
            actual = []
            for source in range(arc.source_interval.lower_tick, arc.source_interval.upper_tick):
                for wait in range(arc.wait_interval.lower_tick, arc.wait_interval.upper_tick):
                    entry = source + usage.follower_enter_offset_tick + usage.follower_enter_wait_coefficient * wait
                    if entry > movement.operational_end_tick:
                        continue
                    clear = (
                        source + usage.leader_clear_offset_tick
                        + usage.leader_clear_wait_coefficient * wait
                        + usage.separation_after_tick(resource.minimum_headway_tick)
                    )
                    actual.append((entry, clear))
            if not actual:
                assert window.outer is None
                assert window.mandatory_core is None
                continue
            assert window.outer is not None
            assert all(
                window.outer.lower_tick <= entry and clear <= window.outer.upper_tick
                for entry, clear in actual
            )
            if window.mandatory_core is not None:
                assert all(
                    entry <= window.mandatory_core.lower_tick
                    and window.mandatory_core.upper_tick <= clear
                    for entry, clear in actual
                )
            checked += 1
    assert checked


def test_inner_and_outer_models_solve_and_respect_bound_order_on_tiny_case():
    prepared = prepare_corridor_problem(
        _problem(),
        config=CorridorArcFlowConfig(waiting_cap_multiplier=None, explicit_maximum_wait_seconds=3),
    )
    inner = CorridorArcFlowOptimizer(CorridorArcFlowSolveConfig(
        mode=CorridorArcFlowMode.INNER, time_limit_seconds=10, threads=1,
    )).solve(prepared)
    outer = CorridorArcFlowOptimizer(CorridorArcFlowSolveConfig(
        mode=CorridorArcFlowMode.OUTER, time_limit_seconds=10, threads=1,
    )).solve(prepared)
    assert inner.status is CorridorArcFlowStatus.OPTIMAL
    assert inner.solution is not None
    validate_ddd_reference_solution(
        prepared.problem.resolved_trajectory_problem.structural_movement_problem,
        inner.solution,
        waiting_policy=prepared.waiting_policy,
    )
    assert outer.certified_global_lower_bound is not None
    assert outer.certified_global_lower_bound <= inner.objective_value
    seed_passengers = optimize_corridor_seed_passengers(
        prepared, inner.solution, time_limit_seconds=2, threads=1
    )
    assert seed_passengers.optimal
    assert seed_passengers.unserved == inner.objective_value


def test_adaptive_conflict_refinement_recovers_plan_excluded_by_coarse_inner_model():
    problem = _problem(k=2, waiting=2)
    config = CorridorArcFlowConfig(waiting_cap_multiplier=None, explicit_maximum_wait_seconds=2)
    prepared = prepare_corridor_problem(problem, config=config)
    coarse = CorridorArcFlowOptimizer(CorridorArcFlowSolveConfig(
        mode=CorridorArcFlowMode.INNER, time_limit_seconds=2, threads=1,
    )).solve(prepared)
    assert coarse.status is CorridorArcFlowStatus.INFEASIBLE
    adaptive = CorridorAdaptiveOptimizer(
        CorridorAdaptiveConfig(
            total_time_limit_seconds=7,
            threads=1,
            maximum_rounds=3,
            inner_slice_seconds=1,
            outer_slice_seconds=1,
        ),
        config,
    ).solve(prepared)
    assert adaptive.best_inner is not None
    assert adaptive.best_inner.solution is not None
    assert adaptive.best_global_lower_bound is not None
    assert adaptive.best_global_lower_bound <= adaptive.best_inner.objective_value
    assert any(round_.split_boundaries for round_ in adaptive.rounds)
