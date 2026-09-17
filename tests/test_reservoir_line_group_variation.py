from itertools import combinations
from types import SimpleNamespace

import numpy as np
import pytest

from test_reservoir_line_evolution import _prepared
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_lines.evolution.line_groups import LineGroupGenomeFactory
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_lines.evolution import (
    EvolutionSearchConfig, LineGenome, OperatorProfile,
    PatternLineGroupGenomeFactory, run_search,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_cp_sat_certificate import validate_reservoir_cp_plan


def factory():
    """Algebra-only five-station catalog, independent of timing solvers."""
    f = object.__new__(LineGroupGenomeFactory)
    f.rng = np.random.default_rng(10)
    f.pattern_stops = {"".join(mask): frozenset(mask)
                       for size in range(2, 6) for mask in combinations("ABCDE", size)}
    f.patterns = tuple(sorted(f.pattern_stops))
    f.od_weights = {frozenset(pair): 10 for pair in combinations("ABCDE", 2)}
    f.fixed_k = f.maximum_k = 38
    f.minimum_gap, f.dispatch_step = 10, 2
    f.prepared = SimpleNamespace(dispatch_window_end_tick=10000)
    f.origin_by_identity = {}
    return f


def test_group_sampler_is_reproducible_diverse_and_keeps_dispatch_grid():
    f, same = factory(), factory()
    seen = set()
    for _ in range(160):
        g = f.random()
        assert g == same.random()
        assert 1 <= len(set(g.pattern_ids)) <= 4
        assert g.fleet_size == 38
        g.validate(maximum_cabins=38, minimum_gap_tick=10, window_tick=10000, dispatch_step_tick=2)
        seen.update(g.pattern_ids)
    assert seen == set(f.patterns)  # Intermediate stop counts are reachable.


@pytest.mark.parametrize("operation", ["halt", "reallocate", "split"])
def test_line_operations_preserve_times_and_fixed_fleet(operation):
    f = factory()
    g = LineGenome(("AB",)*19 + ("CDE",)*19, 4, (2,)*37)
    h = f.change_line(g, operation)
    assert h.fleet_size == 38
    assert h.dispatch_ticks(10) == g.dispatch_ticks(10)
    assert h != g
    if operation == "halt":
        changes = {(old, new) for old, new in zip(g.pattern_ids, h.pattern_ids) if old != new}
        assert len(changes) == 1
        old, new = changes.pop()
        assert len(f.pattern_stops[old] ^ f.pattern_stops[new]) == 1
        assert old not in h.pattern_ids  # Every cabin of that line changed.
    elif operation == "reallocate":
        assert set(h.pattern_ids) <= set(g.pattern_ids)
    else:
        assert len(set(h.pattern_ids)) == 3
        assert set(g.pattern_ids) < set(h.pattern_ids)


def test_split_can_grow_beyond_initial_four_lines():
    f = factory()
    g = LineGenome(("AB",)*10 + ("AC",)*10 + ("AD",)*9 + ("AE",)*9, 0, (0,)*37)
    h = f.change_line(g, "split")
    assert len(set(h.pattern_ids)) == 5


def test_variations_use_all_line_operators_and_preserve_algebra():
    f = factory()
    g = LineGenome(("AB",)*19 + ("CDE",)*19, 4, (2,)*37)
    for _ in range(400):
        h = f.variation(g, f.random(), OperatorProfile.MIXED_GLOBAL)
        assert h.fleet_size == 38
        h.validate(maximum_cabins=38, minimum_gap_tick=10, window_tick=10000, dispatch_step_tick=2)
    assert {"line_halt", "line_split", "line_reallocate", "line_global_order",
            "line_global_dispatch", "line_global_restart"} <= set(f.origin_by_identity.values())


def test_free_small_search_finds_valid_service_without_timing_solver(monkeypatch):
    from ortools.sat.python import cp_model
    def forbidden(*args, **kwargs):
        raise AssertionError("No-Wait search invoked CP-SAT")
    monkeypatch.setattr(cp_model.CpSolver, "solve", forbidden)
    problem, prepared = _prepared(fleet=1)
    result = run_search(problem, prepared, EvolutionSearchConfig(
        fixed_k=1, seed_all_stop=False, dispatch_decoder="intervals", selection_profile="grouped",
        pattern_search="line_groups", objective="service_then_journey", population_size=4,
        offspring_size=2, time_limit_seconds=3, stop_on_full_service=True,
    ))
    assert result["best"] is not None
    check = validate_reservoir_cp_plan(problem, result["best"].passengers.plan)
    assert check.served > 0


def test_pattern_only_line_groups_preserve_fixed_fleet_and_use_few_families():
    problem, prepared = _prepared(fleet=1)
    factory = PatternLineGroupGenomeFactory(problem, prepared, fixed_k=1, seed=4)
    first = factory.random()
    second = factory.random()
    assert first.fleet_size == 1
    assert 1 <= len(set(first.pattern_ids)) <= 4
    for _ in range(20):
        first = factory.variation(first, second, OperatorProfile.MIXED_GLOBAL)
        assert first.fleet_size == 1


def test_pattern_only_line_groups_run_native_timing_subproblem():
    problem, prepared = _prepared(fleet=1)
    result = run_search(problem, prepared, EvolutionSearchConfig(
        fixed_k=1, representation="patterns_only", pattern_search="line_groups",
        operator_profile=OperatorProfile.MIXED_GLOBAL, selection_profile="pattern_status",
        seed_all_stop=False, population_size=2, offspring_size=1,
        evaluation_time_limit_seconds=1, time_limit_seconds=3,
        stop_on_full_service=True,
    ))
    assert result["best"] is not None
    assert result["best"].passengers.served > 0


def test_variable_pattern_fleet_operators_and_initialization():
    problem, prepared = _prepared(fleet=12)
    f = PatternLineGroupGenomeFactory(problem, prepared, seed=42)
    seeds = f.demand_cover_initial(8)
    assert len({g.fleet_size for g in seeds}) > 4
    first, second = f.random(k=1), f.random(k=12)
    seen = set()
    for intensified in (False, True):
        f.intensified = intensified
        for _ in range(500):
            child = f.variation(first, second, OperatorProfile.MIXED_GLOBAL)
            assert 1 <= child.fleet_size <= 12
            assert set(child.pattern_ids) <= set(f.patterns)
            seen.add(child.fleet_size)
            first, second = second, child
    assert len(seen) > 6
    shorter = f.resize(second, 1)
    longer = f.resize(shorter, 12)
    assert shorter.pattern_ids[0] in longer.pattern_ids
    with pytest.raises(ValueError):
        f.resize(longer, 13)


def test_variable_pattern_fleet_finds_valid_plan_without_hint():
    problem, prepared = _prepared(fleet=2)
    result = run_search(problem, prepared, EvolutionSearchConfig(
        representation="patterns_only", pattern_search="line_groups",
        operator_profile=OperatorProfile.MIXED_GLOBAL, selection_profile="pattern_status",
        seed_all_stop=False, population_size=4, offspring_size=2,
        evaluation_time_limit_seconds=1, time_limit_seconds=5,
        stop_on_full_service=True,
    ))
    assert result["best"] is not None
    check = validate_reservoir_cp_plan(problem, result["best"].passengers.plan)
    assert check.served > 0
