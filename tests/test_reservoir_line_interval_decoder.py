from collections import defaultdict
from dataclasses import replace
from itertools import combinations, product

import pytest

from test_reservoir_line_evolution import _prepared
from test_reservoir_line_waiting_repair import fixture
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_lines import (
    prepare_line_problem, ReservoirLineConfig, ReservoirLineVariant,
    ReservoirLinePreparation, ReservoirLineCatalogProfile,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_lines.evolution import (
    LineGenome, GenomeFactory, LineEvolutionEvaluator, EvolutionSearchConfig,
    EvolutionEngine, decode_no_wait, run_search,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_lines.evolution.interval_decoder import (
    IntervalDispatchDecoder, grid_intervals, select_tick,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_lines.evolution.evaluator import EvaluationDeadline
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_lines.dispatch_domains import TickInterval
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_cp_sat_certificate import validate_reservoir_cp_plan


def prep_for(p, end):
    return prepare_line_problem(p, ReservoirLineConfig(dispatch_window_end_seconds=end,
        maximum_cabins=p.available_fleet_count, variant=ReservoirLineVariant.INTERVALS,
        preparation=ReservoirLinePreparation.ENCODING_SPECIFIC,
        catalog_profile=ReservoirLineCatalogProfile.RELEVANT))


def test_every_enumerated_valid_no_wait_plan_is_a_fixed_point():
    p, prepared = _prepared(fleet=2)
    factory = GenomeFactory(p, prepared)
    decoder = IntervalDispatchDecoder(p, prepared)
    valid = 0
    for k in (0, 1, 2):
        for patterns in product(factory.patterns, repeat=k):
            for ds in combinations(range(0, 3_000_001, 1_000_000), k):
                g = factory.from_dispatches(patterns, ds)
                old = decode_no_wait(p, prepared, g)
                if old.feasible:
                    value, stats = decoder.decode(g)
                    assert value.feasible and value.genome == g
                    assert value.plan == old.plan and stats['changed_dispatches'] == 0
                    valid += 1
    assert valid >= 10


def test_dispatch_domains_match_independent_decoder_at_every_small_grid_point():
    p, prepared = _prepared(fleet=2)
    f = GenomeFactory(p, prepared); decoder = IntervalDispatchDecoder(p, prepared)
    for first, second in product(f.patterns, repeat=2):
        for d0 in (0, 1_000_000, 2_000_000):
            t = next(t for t in prepared.templates if t.pattern_id == first and t.minimum_dispatch_tick <= d0 <= t.maximum_dispatch_tick)
            reservations = defaultdict(list)
            decoder.reserve(reservations, decoder.full[t.id], d0)
            allowed = decoder.allowed(second, d0+f.minimum_gap, 3_000_000, reservations)
            for d1 in range(d0+f.minimum_gap, 3_000_001, 1_000_000):
                expected = decode_no_wait(p, prepared, f.from_dispatches((first, second), (d0, d1)))
                assert any(x.lower <= d1 <= x.upper for x in allowed) == expected.feasible


def test_grid_keeps_adjacent_tick_boundaries_and_every_tick_is_selectable():
    intervals = grid_intervals((TickInterval(1, 4), TickInterval(6, 9)), 2)
    assert intervals == (TickInterval(2, 4), TickInterval(6, 8))
    for d in (2,4,6,8):
        assert select_tick(intervals, d) == d
    assert select_tick(intervals, 0) == 2 and select_tick(intervals, 10) == 2


def test_interval_insertion_does_not_use_a_timing_solver(monkeypatch):
    from ortools.sat.python import cp_model
    def forbidden(*args, **kwargs):
        raise AssertionError('no-wait decoder used a timing solver')
    monkeypatch.setattr(cp_model.CpSolver, 'solve', forbidden)
    p, prepared = _prepared(fleet=2)
    value, _ = IntervalDispatchDecoder(p, prepared).decode(LineGenome(('all_stop',), 0, ()))
    assert value.feasible


def test_waiting_fallback_repairs_whole_candidate_with_fixed_decoded_dispatch():
    p, _ = fixture(); prepared = prep_for(p, 1)
    g = GenomeFactory(p, prepared).from_dispatches(('all_stop',)*2, (0, 1_000_000))
    decoder = IntervalDispatchDecoder(p, prepared)
    failed, stats = decoder.decode(g)
    assert not failed.feasible and stats['status'] == 'CONSTRUCTION_FAILED'
    candidate, stats = decoder.decode(g, allow_waiting_candidate=True)
    assert stats['status'] == 'WAITING_CANDIDATE' and candidate.relaxed_timetable is not None
    e = LineEvolutionEvaluator(p, prepared, dispatch_decoder='intervals', waiting_repair_seconds=3,
                               waiting_budget_seconds=3, waiting_workers=1)
    result = e.evaluate(g)
    assert result.passengers is not None and result.passengers.served == 1
    assert result.repair['status'] == 'REPAIRED'
    assert [t.switch_ticks[0] for t in result.passengers.plan.trips] == [0, 1_000_000]
    assert sum(sum(t.wait_ticks) for t in result.passengers.plan.trips) > 0
    assert result.movement.genome == g and result.movement.feasible
    assert validate_reservoir_cp_plan(p, result.passengers.plan).served == 1


def test_immutable_prefix_rejects_before_cp_instead_of_silently_dropping_cabin(monkeypatch):
    p, _ = fixture(early_conflict=True); prepared = prep_for(p, 1)
    g = GenomeFactory(p, prepared).from_dispatches(('all_stop',)*2, (0, 1_000_000))
    import ropeway_skip_stop_optimization.optimization.ddd.reservoir_lines.evolution.waiting_repair as repair
    monkeypatch.setattr(repair, 'solve_waiting_only_repair', lambda *a, **k: pytest.fail('must reject prefix first'))
    result = LineEvolutionEvaluator(p, prepared, dispatch_decoder='intervals', waiting_repair_seconds=3,
                                   waiting_budget_seconds=3).evaluate(g)
    assert result.passengers is None and result.movement.plan is None
    assert result.decoder['status'] == 'CONSTRUCTION_FAILED'
    assert result.movement.genome.fleet_size == 2
    assert result.decoder['global_infeasibility_proof'] is False


def test_waiting_release_changes_necessary_prefix_domain():
    p, _ = fixture(earliest_wait=5); prepared = prep_for(p, 1)
    g = GenomeFactory(p, prepared).from_dispatches(('all_stop',)*2, (0, 1_000_000))
    value, stats = IntervalDispatchDecoder(p, prepared).decode(g, allow_waiting_candidate=True)
    assert not value.feasible and stats['status'] == 'CONSTRUCTION_FAILED'


def test_total_repair_budget_and_cache_do_not_claim_infeasibility():
    p, _ = fixture(); prepared = prep_for(p, 1)
    g = GenomeFactory(p, prepared).from_dispatches(('all_stop',)*2, (0, 1_000_000))
    evaluator = LineEvolutionEvaluator(p, prepared, dispatch_decoder='intervals',
                                      waiting_repair_seconds=3, waiting_budget_seconds=0)
    value = evaluator.evaluate(g)
    assert value.passengers is None
    assert value.repair['status'] == 'REPAIR_BUDGET_EXHAUSTED'
    assert evaluator.repair_spent_seconds == 0 and evaluator.evaluate(g).cached


def test_decoder_timeout_does_not_become_an_infeasibility_proof():
    p, prepared = _prepared(fleet=1)
    with pytest.raises(EvaluationDeadline):
        IntervalDispatchDecoder(p, prepared).decode(LineGenome(('all_stop',), 0, ()), deadline=0)


def test_search_integrates_decoder_and_reports_actual_dispatch_times():
    p, prepared = _prepared(fleet=2)
    result = run_search(p, prepared, EvolutionSearchConfig(engine=EvolutionEngine.GA,
        time_limit_seconds=0.5, population_size=4, offspring_size=2, dispatch_decoder='intervals'))
    assert result['best'] is not None and result['best'].passengers.served == 1
    for event in result['fleet_frontier'].values():
        assert event['decoder_status'] == 'NO_WAIT_VALID'
        ds = event['dispatch_ticks']
        g = GenomeFactory(p, prepared).from_dispatches(event['pattern_ids'], ds)
        assert decode_no_wait(p, prepared, g).feasible


def test_legacy_defaults_are_preserved_and_incompatible_modes_rejected():
    p, prepared = _prepared()
    assert EvolutionSearchConfig().dispatch_decoder == 'legacy'
    assert EvolutionSearchConfig().waiting_repair_seconds == 0
    with pytest.raises(ValueError, match='requires the interval decoder'):
        run_search(p, prepared, EvolutionSearchConfig(waiting_repair_seconds=1))


def test_failed_prefix_does_not_imply_the_pattern_sequence_is_infeasible():
    p, _ = fixture(); prepared = prep_for(p, 3)
    f = GenomeFactory(p, prepared); decoder = IntervalDispatchDecoder(p, prepared)
    bad, stats = decoder.decode(f.from_dispatches(('all_stop',)*2, (2_000_000, 3_000_000)))
    good, _ = decoder.decode(f.from_dispatches(('all_stop',)*2, (0, 2_000_000)))
    assert stats['status'] == 'CONSTRUCTION_FAILED' and not bad.feasible
    assert good.feasible


def test_distinct_proposals_mapping_to_same_dispatch_use_same_passenger_cache():
    p, _ = fixture(); prepared = prep_for(p, 3); f = GenomeFactory(p, prepared)
    evaluator = LineEvolutionEvaluator(p, prepared, dispatch_decoder='intervals')
    first = evaluator.evaluate(f.from_dispatches(('all_stop',)*2, (0, 1_000_000)))
    second = evaluator.evaluate(f.from_dispatches(('all_stop',)*2, (0, 2_000_000)))
    assert first.passengers is not None and second.cached
    assert first.passengers.plan == second.passengers.plan
    assert first.decoder['changed_dispatches'] == 1 and second.decoder['changed_dispatches'] == 0


def test_late_resource_entry_and_multiple_previous_reservations_keep_holes():
    p, prepared = _prepared(fleet=1)
    prepared = replace(prepared, dispatch_step_tick=1,
                       templates=(replace(prepared.templates[0], minimum_dispatch_tick=0, maximum_dispatch_tick=20),))
    decoder = IntervalDispatchDecoder(p, prepared); t = prepared.templates[0]
    decoder.full[t.id] = {'resource': ((0, 2),)}
    allowed = decoder.allowed(t.pattern_id, 0, 20, {'resource': [(10,12), (16,18)]})
    assert allowed == (TickInterval(0,8), TickInterval(12,14), TickInterval(18,20))
    # The earliest inserted movement enters late; free space before it remains
    # available. A 'last free' scalar would incorrectly remove that space.
    assert select_tick(allowed, 8) == 8 and select_tick(allowed, 12) == 12


def test_waiting_unknown_is_never_exported_as_infeasible_or_feasible(monkeypatch):
    p, _ = fixture(); prepared = prep_for(p, 1)
    g = GenomeFactory(p, prepared).from_dispatches(('all_stop',)*2, (0,1_000_000))
    import ropeway_skip_stop_optimization.optimization.ddd.reservoir_lines.evolution.waiting_repair as repair
    monkeypatch.setattr(repair, 'solve_waiting_only_repair', lambda *a, **k:
        {'status':'UNKNOWN', 'plan':None, 'total_wall_seconds':0.1})
    e = LineEvolutionEvaluator(p, prepared, dispatch_decoder='intervals',
                              waiting_repair_seconds=1, waiting_budget_seconds=1)
    result = e.evaluate(g)
    assert result.repair['status'] == 'UNKNOWN' and result.passengers is None
    assert result.movement.plan is None and result.movement.relaxed_timetable is not None
    assert e.repair_spent_seconds == 0.1


@pytest.mark.parametrize('already_spent', [0.0, 60.0, 900.0])
def test_each_new_repair_gets_its_own_budget_even_late_in_the_run(monkeypatch, already_spent):
    p, _ = fixture(); prepared = prep_for(p, 1)
    g = GenomeFactory(p, prepared).from_dispatches(('all_stop',)*2, (0,1_000_000))
    import ropeway_skip_stop_optimization.optimization.ddd.reservoir_lines.evolution.waiting_repair as repair
    budgets = []
    def native(*args, **kwargs):
        budgets.append(kwargs['time_limit_seconds'])
        return {'status':'UNKNOWN', 'plan':None, 'total_wall_seconds':0.1}
    monkeypatch.setattr(repair, 'solve_waiting_only_repair', native)
    e = LineEvolutionEvaluator(p, prepared, dispatch_decoder='intervals', waiting_repair_seconds=5)
    e.repair_spent_seconds = already_spent
    assert e.waiting_budget_seconds is None
    assert e.evaluate(g).repair['status'] == 'UNKNOWN'
    assert budgets == [5.0]
    assert e.evaluate(g).cached and budgets == [5.0]  # Same candidate is not a new repair.


def test_individual_repair_budget_still_respects_remaining_total_time(monkeypatch):
    from time import perf_counter
    p, _ = fixture(); prepared = prep_for(p, 1)
    g = GenomeFactory(p, prepared).from_dispatches(('all_stop',)*2, (0,1_000_000))
    import ropeway_skip_stop_optimization.optimization.ddd.reservoir_lines.evolution.waiting_repair as repair
    budgets = []
    def native(*args, **kwargs):
        budgets.append(kwargs['time_limit_seconds'])
        return {'status':'UNKNOWN', 'plan':None, 'total_wall_seconds':0.1}
    monkeypatch.setattr(repair, 'solve_waiting_only_repair', native)
    e = LineEvolutionEvaluator(p, prepared, dispatch_decoder='intervals', waiting_repair_seconds=5,
                               deadline=perf_counter()+1.0)
    assert e.evaluate(g).repair['status'] == 'UNKNOWN'
    assert 0 < budgets[0] <= 1.0


@pytest.mark.parametrize('fraction, expected', [(None, None), (0.2, 2.0)])
def test_search_passes_optional_aggregate_repair_limit_correctly(monkeypatch, fraction, expected):
    import ropeway_skip_stop_optimization.optimization.ddd.reservoir_lines.evolution.search as search
    p, prepared = _prepared()
    observed = []
    def run(factory, evaluator, recorder, reference, deadline):
        observed.append(evaluator.waiting_budget_seconds)
    monkeypatch.setattr(search, '_random_search', run)
    search.run_search(p, prepared, EvolutionSearchConfig(engine=EvolutionEngine.RANDOM,
        dispatch_decoder='intervals', waiting_repair_seconds=5,
        time_limit_seconds=10, waiting_budget_fraction=fraction))
    assert observed == [expected]
    assert EvolutionSearchConfig().waiting_budget_fraction is None


def test_prefix_first_keeps_earlier_dispatch_even_when_later_no_wait_slot_exists():
    p, _ = fixture(); prepared = prep_for(p, 3)
    g = GenomeFactory(p, prepared).from_dispatches(('all_stop',)*2, (0, 1_000_000))
    decoder = IntervalDispatchDecoder(p, prepared)
    old, _ = decoder.decode(g, allow_waiting_candidate=True)
    new, stats = decoder.decode(g, allow_waiting_candidate=True, waiting_construction='prefix_first')
    assert old.feasible
    assert old.genome.dispatch_ticks(decoder.gap)[1] > 1_000_000
    assert new.genome == g and new.relaxed_timetable is not None
    assert stats['status'] == 'WAITING_CANDIDATE'
    assert all(s['kind'] == 'necessary_prefix' for s in stats['steps'])
    result = LineEvolutionEvaluator(p, prepared, dispatch_decoder='intervals', waiting_repair_seconds=3,
                                   waiting_workers=1, waiting_construction='prefix_first').evaluate(g)
    assert result.repair['status'] == 'REPAIRED'
    assert [t.switch_ticks[0] for t in result.passengers.plan.trips] == [0, 1_000_000]
    assert validate_reservoir_cp_plan(p, result.passengers.plan).served == 1


@pytest.mark.parametrize('options', [dict(early_conflict=True), dict(earliest_wait=5)])
def test_prefix_first_still_rejects_immutable_conflicts(options):
    p, _ = fixture(**options); prepared = prep_for(p, 1)
    g = GenomeFactory(p, prepared).from_dispatches(('all_stop',)*2, (0, 1_000_000))
    value, stats = IntervalDispatchDecoder(p, prepared).decode(
        g, allow_waiting_candidate=True, waiting_construction='prefix_first')
    assert stats['status'] == 'CONSTRUCTION_FAILED'
    assert stats['global_infeasibility_proof'] is False
    assert value.genome.fleet_size == 2 and value.plan is None


def test_prefix_first_requires_waiting_and_preserves_valid_no_wait_genome():
    p, prepared = _prepared(fleet=2)
    g = GenomeFactory(p, prepared).from_dispatches(('all_stop',)*2, (0, 2_000_000))
    decoder = IntervalDispatchDecoder(p, prepared)
    with pytest.raises(ValueError, match='requires waiting'):
        decoder.decode(g, waiting_construction='prefix_first')
    value, stats = decoder.decode(g, allow_waiting_candidate=True, waiting_construction='prefix_first')
    assert value.feasible and value.genome == g
    assert EvolutionSearchConfig().waiting_construction == 'no_wait_first'


def test_prefix_first_without_repair_preserves_full_conflicting_proposal(monkeypatch):
    p, _ = fixture(); prepared = prep_for(p, 3)
    g = GenomeFactory(p, prepared).from_dispatches(('all_stop',)*2, (0, 1_000_000))
    expected, _ = IntervalDispatchDecoder(p, prepared).decode(
        g, allow_waiting_candidate=True, waiting_construction='prefix_first')
    import ropeway_skip_stop_optimization.optimization.ddd.reservoir_lines.evolution.waiting_repair as repair
    import ropeway_skip_stop_optimization.optimization.ddd.reservoir_lines.evolution.evaluator as evaluation
    def forbidden(*args, **kwargs):
        pytest.fail('conflicting proposal must not invoke timing or passenger optimization')
    monkeypatch.setattr(repair, 'solve_waiting_only_repair', forbidden)
    monkeypatch.setattr(evaluation, 'optimize_fixed_movement_passengers', forbidden)
    monkeypatch.setattr(evaluation, 'evaluate_passenger_potential', forbidden)
    e = LineEvolutionEvaluator(p, prepared, dispatch_decoder='intervals',
                              waiting_construction='prefix_first', waiting_repair_seconds=0)
    value = e.evaluate(g)
    assert value.movement.genome == expected.genome == g
    assert value.movement.relaxed_timetable == expected.relaxed_timetable
    assert value.movement.conflicts == expected.conflicts and len(value.movement.conflicts) > 0
    assert not value.movement.feasible and value.passengers is None and value.repair is None
    assert e.repair_spent_seconds == 0 and e.evaluate(g).cached


def test_search_records_direct_conflicts_when_prefix_repair_is_disabled(monkeypatch):
    import ropeway_skip_stop_optimization.optimization.ddd.reservoir_lines.evolution.search as search
    p, _ = fixture(); prepared = prep_for(p, 3)
    g = GenomeFactory(p, prepared).from_dispatches(('all_stop',)*2, (0, 1_000_000))
    def single_evaluation(factory, evaluator, recorder, reference, deadline):
        value = evaluator.evaluate(g)
        recorder.record(g, value, 'test')
        recorder.record(g, evaluator.evaluate(g), 'cached_test')
    monkeypatch.setattr(search, '_random_search', single_evaluation)
    events = []
    search.run_search(p, prepared, EvolutionSearchConfig(engine=EvolutionEngine.RANDOM,
        dispatch_decoder='intervals', waiting_construction='prefix_first',
        waiting_repair_seconds=0, time_limit_seconds=2), event_callback=events.append)
    direct = [e for e in events if e['kind'] == 'unrepaired_candidate']
    assert len(direct) == 1 and direct[0]['conflicts'] > 0 and direct[0]['served'] is None
    assert not any(e['kind'] in ('waiting_repair', 'incumbent') for e in events)


def test_prefix_first_without_interval_decoder_is_rejected():
    p, prepared = _prepared(fleet=2)
    with pytest.raises(ValueError, match='interval decoder'):
        run_search(p, prepared, EvolutionSearchConfig(waiting_construction='prefix_first'))
