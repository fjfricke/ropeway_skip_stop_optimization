"""NSGA-II search semantics: optimistic assignments never become certificates."""
from dataclasses import replace
from time import perf_counter

import numpy as np
import pytest

from test_reservoir_line_evolution import _prepared
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_lines import (
    ReservoirLineConfig, ReservoirLineVariant, ReservoirLinePreparation,
    ReservoirLineFormulation, ReservoirLineMode, ReservoirLineCatalogProfile,
    prepare_line_problem,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_lines.evolution import (
    EvolutionEngine, EvolutionSearchConfig, GenomeFactory, LineEvolutionEvaluator,
    run_search,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_lines.evolution.evaluator import EvaluationDeadline
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_lines.evolution.passengers import (
    evaluate_passenger_potential, optimize_fixed_movement_passengers,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_lines.evolution.search import (
    nsga_objectives, SearchRecorder,
)


def _collision_fixture():
    p, _ = _prepared(fleet=2)
    p = replace(p, movement_core=replace(p.movement_core,
        resources=tuple(replace(r, headway_seconds=1.5, maximum_headway_seconds=1.5) for r in p.movement_core.resources)))
    cfg = ReservoirLineConfig(dispatch_window_end_seconds=3, maximum_cabins=2,
        variant=ReservoirLineVariant.INTERVALS,
        preparation=ReservoirLinePreparation.ENCODING_SPECIFIC,
        formulation=ReservoirLineFormulation.SHARED_ROUNDS,
        mode=ReservoirLineMode.EXACT_SERVICE,
        catalog_profile=ReservoirLineCatalogProfile.RELEVANT)
    prepared = prepare_line_problem(p, cfg)
    factory = GenomeFactory(p, prepared)
    return p, prepared, factory.from_dispatches(('all_stop', 'all_stop'), (0, 1_000_000))


def test_collision_potential_is_not_a_valid_assignment_or_checkpoint():
    p, prepared, genome = _collision_fixture()
    evaluator = LineEvolutionEvaluator(p, prepared, evaluate_infeasible_potential=True)
    v = evaluator.evaluate(genome)
    assert v.movement.conflicts and not v.movement.feasible
    assert v.movement.plan is None and v.movement.relaxed_timetable is not None
    assert v.passengers is None and v.valid_served is None
    assert v.potential.proven_optimal and v.potential.assigned == 1
    assert v.potential.native_assigned_upper_bound == 1
    with pytest.raises(ValueError, match='conflict'):
        optimize_fixed_movement_passengers(p, v.movement.relaxed_timetable)
    saved = []
    recorder = SearchRecorder(perf_counter(), 1_000_000, incumbent_callback=saved.append)
    recorder.record(genome, v, 'test')
    assert recorder.best is None and not saved
    assert not any(e['kind'] == 'incumbent' for e in recorder.events)
    assert any(e['kind'] == 'potential_frontier' for e in recorder.events)
    assert evaluator.evaluate(genome).cached


def test_legacy_skips_collision_passenger_evaluation():
    p, prepared, genome = _collision_fixture()
    v = LineEvolutionEvaluator(p, prepared).evaluate(genome)
    assert v.potential is None and v.passengers is None


def test_potential_matches_valid_passenger_ip_when_no_conflicts():
    p, prepared = _prepared(fleet=1)
    genome = GenomeFactory(p, prepared).from_dispatches(('all_stop',), (0,))
    v = LineEvolutionEvaluator(p, prepared).evaluate(genome)
    potential = evaluate_passenger_potential(p, v.movement.plan)
    assert potential.assigned == v.passengers.served
    assert potential.unassigned == v.passengers.unserved
    assert potential.proven_optimal


def test_relaxation_does_not_remove_individual_trajectory_rules():
    p, prepared, genome = _collision_fixture()
    v = LineEvolutionEvaluator(p, prepared).evaluate(genome)
    timetable = v.movement.relaxed_timetable
    bad = replace(timetable, trips=(replace(timetable.trips[0], return_tick=1),))
    with pytest.raises(ValueError, match='return'):
        evaluate_passenger_potential(p, bad)
    bad_wait = replace(timetable, trips=(replace(timetable.trips[0],
        wait_ticks=(1,) + timetable.trips[0].wait_ticks[1:]),))
    with pytest.raises(ValueError, match='no-wait'):
        evaluate_passenger_potential(p, bad_wait)


def test_conflicts_are_objectives_not_feasibility_first_constraints():
    p, prepared, genome = _collision_fixture()
    v = LineEvolutionEvaluator(p, prepared, evaluate_infeasible_potential=True).evaluate(genome)
    f, g = nsga_objectives(v, 1)
    assert g == 0 and f[0] == 0 and f[1] > 0 and f[2] > 0
    rejected = replace(v, potential=None)
    assert nsga_objectives(rejected, 1)[1] == 1


def test_native_pareto_selection_keeps_high_potential_conflicting_candidate():
    from pymoo.algorithms.moo.nsga2 import RankAndCrowding
    from pymoo.core.problem import Problem
    from pymoo.core.population import Population
    # First two are tradeoffs, third is dominated by both. G is structural only.
    pop = Population.new(F=np.array([[578., 0., 0.], [174., 2., 0.1], [600., 3., 1.]]),
                         G=np.zeros((3, 1)))
    selected = RankAndCrowding().do(Problem(n_var=1, n_obj=3, n_ieq_constr=1),
                                   pop, n_survive=2, random_state=np.random.default_rng(0))
    assert {tuple(x.F) for x in selected} == {(578., 0., 0.), (174., 2., 0.1)}


def test_nsga2_without_seed_finds_valid_positive_service_and_records_population():
    p, prepared = _prepared(fleet=2)
    saved = []
    result = run_search(p, prepared, EvolutionSearchConfig(engine=EvolutionEngine.NSGA2,
        population_size=4, offspring_size=2, time_limit_seconds=0.5, seed=7),
        incumbent_callback=saved.append)
    assert result['best'].passengers.served == 1 and saved
    assert result['selection'] == 'native_nsga2_rank_crowding_tournament'
    assert result['parent_selection_counts'] == {}  # No custom selector in NSGA-II.
    pops = [e for e in result['events'] if e['kind'] == 'population']
    assert pops and all(len(m['search_objectives']) == 3 for m in pops[-1]['members'])


def test_deadline_stops_evaluations_even_for_cache_hits():
    p, prepared = _prepared(fleet=1)
    genome = GenomeFactory(p, prepared).from_dispatches(('all_stop',), (0,))
    evaluator = LineEvolutionEvaluator(p, prepared)
    evaluator.evaluate(genome)
    evaluator.deadline = perf_counter() - 1
    with pytest.raises(EvaluationDeadline):
        evaluator.evaluate(genome)


def test_nsga_counts_only_the_attained_potential_not_native_bound_on_timeout():
    p, prepared, genome = _collision_fixture()
    v = LineEvolutionEvaluator(p, prepared, evaluate_infeasible_potential=True).evaluate(genome)
    v = replace(v, potential=replace(v.potential, assigned=0, unassigned=1,
        proven_optimal=False, native_assigned_upper_bound=1, status='TIME_LIMIT'))
    assert nsga_objectives(v, 1)[0][0] == 1
    assert v.valid_served is None
