from dataclasses import replace
import sys

import numpy as np

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
from test_optimization_ddd_reservoir_cp_sat import problem  # noqa: E402

from ropeway_skip_stop_optimization.optimization.ddd.reservoir_lines import (  # noqa: E402
    ReservoirLineCatalogProfile,
    ReservoirLineConfig,
    ReservoirLineFormulation,
    ReservoirLineMode,
    ReservoirLinePreparation,
    ReservoirLineVariant,
    prepare_line_problem,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_lines.evolution import (  # noqa: E402
    DispatchSubproblem,
    EvolutionEngine,
    EvolutionSearchConfig,
    GenomeFactory,
    LineEvolutionEvaluator,
    LineGenome,
    OperatorProfile,
    PatternGenomeFactory,
    PatternOnlyEvaluator,
    PatternSequenceGenome,
    decode_no_wait,
    run_search,
)


def _prepared(*, fleet=2, dispatch_end=3):
    p = problem(
        available_fleet_count=fleet,
        dispatch_end_seconds=dispatch_end,
        dispatch_step_seconds=1,
    )
    c = ReservoirLineConfig(
        dispatch_window_end_seconds=dispatch_end,
        maximum_cabins=fleet,
        variant=ReservoirLineVariant.INTERVALS,
        preparation=ReservoirLinePreparation.ENCODING_SPECIFIC,
        formulation=ReservoirLineFormulation.SHARED_ROUNDS,
        mode=ReservoirLineMode.EXACT_SERVICE,
        catalog_profile=ReservoirLineCatalogProfile.RELEVANT,
        workers=1,
    )
    return p, prepare_line_problem(p, c)


def test_genome_encoding_handles_empty_single_and_full_dispatch_window():
    p, prepared = _prepared()
    factory = GenomeFactory(p, prepared)
    empty = LineGenome((), 0, ())
    empty.validate(
        maximum_cabins=2,
        minimum_gap_tick=factory.minimum_gap,
        window_tick=prepared.dispatch_window_end_tick,
        dispatch_step_tick=prepared.dispatch_step_tick,
    )
    assert empty.dispatch_ticks(factory.minimum_gap) == ()
    one = factory.from_dispatches(("all_stop",), (prepared.dispatch_window_end_tick,))
    assert one.dispatch_ticks(factory.minimum_gap) == (prepared.dispatch_window_end_tick,)
    full = factory.from_dispatches(("all_stop", "all_stop"), (0, prepared.dispatch_window_end_tick))
    assert full.dispatch_ticks(factory.minimum_gap)[-1] == prepared.dispatch_window_end_tick


def test_local_pattern_neighbour_changes_exactly_one_stop_when_available():
    p, prepared = _prepared()
    factory = GenomeFactory(p, prepared)
    rng = np.random.default_rng(7)
    for pattern in factory.patterns:
        neighbour = factory._neighbour_pattern(pattern, rng)
        if any(
            len(set(factory.pattern_stops[pattern]).symmetric_difference(factory.pattern_stops[x])) == 1
            for x in factory.patterns
        ):
            assert len(
                set(factory.pattern_stops[pattern]).symmetric_difference(factory.pattern_stops[neighbour])
            ) == 1


def test_no_wait_decoder_builds_and_independently_validates_a_trip():
    p, prepared = _prepared(fleet=1)
    factory = GenomeFactory(p, prepared)
    genome = factory.from_dispatches(("all_stop",), (0,))
    value = decode_no_wait(p, prepared, genome)
    assert value.feasible and value.plan is not None
    assert all(wait == 0 for trip in value.plan.trips for wait in trip.wait_ticks)


def test_fixed_movement_passenger_ip_reaches_tiny_optimum():
    p, prepared = _prepared(fleet=1)
    factory = GenomeFactory(p, prepared)
    value = LineEvolutionEvaluator(p, prepared, 2).evaluate(
        factory.from_dispatches(("all_stop",), (0,))
    )
    assert value.passengers is not None
    assert value.passengers.proven_optimal
    assert value.passengers.served == 1
    assert value.passengers.unserved == 0


def test_lexicographic_passenger_ip_never_sacrifices_service():
    from ropeway_skip_stop_optimization.optimization.ddd.reservoir_lines.evolution.passengers import (
        optimize_fixed_movement_passengers,
    )
    p, prepared = _prepared(fleet=1)
    factory = GenomeFactory(p, prepared)
    movement = decode_no_wait(
        p, prepared, factory.from_dispatches(("all_stop",), (0,))
    ).plan
    result = optimize_fixed_movement_passengers(
        p, movement, time_limit_seconds=2, objective="service_then_journey"
    )
    assert result.proven_optimal
    assert result.unserved == 0
    assert result.journey_time_tick is not None


def test_search_stops_after_independently_validated_full_service():
    p, prepared = _prepared(fleet=1)
    result = run_search(
        p,
        prepared,
        EvolutionSearchConfig(
            engine=EvolutionEngine.RANDOM,
            time_limit_seconds=5,
            population_size=4,
            offspring_size=2,
            objective="service_then_journey",
            stop_on_full_service=True,
        ),
    )
    assert result["termination_reason"] == "VALIDATED_FULL_SERVICE"
    assert result["best"].passengers.unserved == 0
    assert result["total_wall_seconds"] < 5


def test_lexicographic_search_does_not_stop_at_full_service():
    p, prepared = _prepared(fleet=1)
    result = run_search(
        p,
        prepared,
        EvolutionSearchConfig(
            engine=EvolutionEngine.RANDOM,
            time_limit_seconds=0.25,
            population_size=4,
            offspring_size=2,
            objective="service_then_journey",
            stop_on_full_service=False,
        ),
    )
    assert result["termination_reason"] == "TIME_LIMIT"
    assert result["best"].passengers.unserved == 0


def test_evaluator_cache_uses_canonical_genome_identity():
    p, prepared = _prepared(fleet=1)
    evaluator = LineEvolutionEvaluator(p, prepared, 2)
    genome = GenomeFactory(p, prepared).from_dispatches(("all_stop",), (0,))
    assert not evaluator.evaluate(genome).cached
    assert evaluator.evaluate(genome).cached
    assert evaluator.cache_size == 1


def test_all_operator_profiles_preserve_dispatch_algebra():
    p, prepared = _prepared(fleet=2)
    factory = GenomeFactory(p, prepared, seed=3)
    for profile in OperatorProfile:
        genome = factory.random(k=2)
        for _ in range(50):
            genome = factory.mutate(genome, profile)
            genome.validate(
                maximum_cabins=factory.maximum_k,
                minimum_gap_tick=factory.minimum_gap,
                window_tick=prepared.dispatch_window_end_tick,
                dispatch_step_tick=prepared.dispatch_step_tick,
            )


def test_search_finds_positive_service_without_a_reference_hint():
    events = []
    p, prepared = _prepared(fleet=1)
    result = run_search(
        p,
        prepared,
        EvolutionSearchConfig(
            engine=EvolutionEngine.RANDOM,
            operator_profile=OperatorProfile.MIXED_GLOBAL,
            time_limit_seconds=0.5,
            population_size=4,
            offspring_size=2,
            seed=5,
        ),
        event_callback=events.append,
    )
    assert result["best"] is not None
    assert result["best"].passengers.served == 1
    assert result["fleet_frontier"]["1"]["pattern_ids"] == ("all_stop",)
    assert any(event["kind"] == "evaluation_window" for event in events)


def test_exploration_parent_probability_is_validated():
    import pytest
    p, prepared = _prepared()
    with pytest.raises(ValueError, match='probability'):
        run_search(p, prepared, EvolutionSearchConfig(exploration_parent_probability=1.1))


def _operator_fixture():
    from types import SimpleNamespace
    factory = object.__new__(GenomeFactory)
    factory.fixed_k = None
    factory.minimum_gap = 2
    factory.dispatch_step = 1
    factory.maximum_k = 8
    factory.prepared = SimpleNamespace(dispatch_window_end_tick=100)
    factory.origin_by_identity = {}
    factory.rng = np.random.default_rng(0)
    return factory


def test_coupled_block_preserves_donor_internal_gaps_and_outside_dispatches():
    factory = _operator_fixture()
    base = factory.from_dispatches(('a', 'a', 'a', 'a'), (0, 10, 20, 40))
    donor = factory.from_dispatches(('b', 'c', 'd'), (5, 12, 30))
    child = factory.transplant(base, donor, 1, 0, 2)
    assert child.pattern_ids == ('a', 'b', 'c', 'a')
    assert child.dispatch_ticks(2) == (0, 10, 17, 40)


def test_coupled_block_rejects_boundary_collision_without_retiming():
    factory = _operator_fixture()
    base = factory.from_dispatches(('a', 'a', 'a', 'a'), (0, 10, 20, 25))
    donor = factory.from_dispatches(('b', 'c'), (0, 40))
    assert factory.transplant(base, donor, 1, 0, 2) == base


def test_local_profile_never_invokes_crossover():
    p, prepared = _prepared()
    factory = GenomeFactory(p, prepared)
    genome = factory.random(k=1)
    def forbidden(*args, **kwargs):
        raise AssertionError('local profile crossed a block')
    factory.crossover = forbidden
    for _ in range(50):
        genome = factory.variation(genome, genome, OperatorProfile.LOCAL)


def test_passenger_budget_reaches_search_evaluator(monkeypatch):
    from ropeway_skip_stop_optimization.optimization.ddd.reservoir_lines.evolution import search
    p, prepared = _prepared()
    original = search.LineEvolutionEvaluator
    seen = []
    def capture(problem, prepared, budget):
        seen.append(budget)
        return original(problem, prepared, budget)
    monkeypatch.setattr(search, 'LineEvolutionEvaluator', capture)
    search.run_search(p, prepared, EvolutionSearchConfig(engine=EvolutionEngine.RANDOM,
        time_limit_seconds=0.05, passenger_time_limit_seconds=0.125))
    assert seen == [0.125]


def test_fixed_k_all_variations_preserve_exact_fleet():
    p, prepared = _prepared(fleet=6, dispatch_end=10)
    factory = GenomeFactory(p, prepared, seed=71, fixed_k=4)
    # Synthetic catalog isolates variation algebra from movement feasibility.
    factory.patterns = ("all_stop", "stop_A_B", "stop_B_C")
    factory.pattern_stops = {"all_stop": ("A", "B", "C"), "stop_A_B": ("A", "B"), "stop_B_C": ("B", "C")}
    from ropeway_skip_stop_optimization.optimization.ddd.reservoir_lines.evolution.search import _initial
    initial = _initial(factory, None, 32, np.random.default_rng(8), seed_all_stop=False)
    assert all(g.fleet_size == 4 for g in initial)
    assert any(len(set(g.pattern_ids)) > 1 for g in initial)
    assert not any(set(g.pattern_ids) == {"all_stop"} for g in initial)
    for profile in OperatorProfile:
        genome = initial[0]
        for _ in range(200):
            genome = factory.variation(genome, factory.random(), profile)
            assert genome.fleet_size == 4
            genome.validate(maximum_cabins=6, minimum_gap_tick=factory.minimum_gap,
                            window_tick=prepared.dispatch_window_end_tick,
                            dispatch_step_tick=prepared.dispatch_step_tick)
    assert 'local_insert' not in factory.origin_by_identity.values()
    assert 'local_remove' not in factory.origin_by_identity.values()


def test_fixed_k_invalid_size_rejected_and_legacy_still_variable():
    import pytest
    p, prepared = _prepared(fleet=4, dispatch_end=10)
    for k in [0, 5]:
        with pytest.raises(ValueError):
            GenomeFactory(p, prepared, fixed_k=k)
    factory = GenomeFactory(p, prepared, fixed_k=3)
    with pytest.raises(ValueError):
        factory.random(k=2)
    assert len({GenomeFactory(p, prepared, seed=i).random().fleet_size for i in range(30)}) > 1


def test_fixed_k_search_records_only_exact_fleet():
    p, prepared = _prepared(fleet=2, dispatch_end=3)
    events = []
    result = run_search(p, prepared, EvolutionSearchConfig(
        fixed_k=1, seed_all_stop=False, time_limit_seconds=0.5,
        population_size=4, offspring_size=2), event_callback=events.append)
    assert result["config"]["fixed_k"] == 1
    observed = [e["fleet_size"] for e in events if "fleet_size" in e]
    assert observed and set(observed) == {1}
    if result["best"] is not None:
        assert len(result["best"].passengers.plan.trips) == 1


def test_pattern_genome_identity_keeps_order_and_contains_no_time_genes():
    first = PatternSequenceGenome(("a", "b"))
    second = PatternSequenceGenome(("b", "a"))
    assert first.identity != second.identity
    assert first.fleet_size == 2
    assert not hasattr(first, "phase_tick")
    assert not hasattr(first, "extra_gap_ticks")


def test_pattern_operators_preserve_fixed_length_and_can_change_large_blocks():
    p, prepared = _prepared(fleet=4, dispatch_end=10)
    factory = PatternGenomeFactory(p, prepared, fixed_k=4, seed=8)
    first, second = factory.random(), factory.random()
    for _ in range(100):
        child = factory.variation(first, second, OperatorProfile.MIXED_GLOBAL)
        assert child.fleet_size == 4
        assert all(pattern in factory.patterns for pattern in child.pattern_ids)
        first = child


def test_pattern_subproblems_match_tiny_dispatch_optimum():
    p, prepared = _prepared(fleet=1, dispatch_end=3)
    genome = PatternSequenceGenome(("all_stop",))
    values = [
        PatternOnlyEvaluator(
            p, prepared, subproblem=subproblem, evaluation_seconds=2, workers=1
        ).evaluate(genome)
        for subproblem in DispatchSubproblem
    ]
    assert {value.decoder["status"] for value in values} == {"PATTERN_VALID"}
    assert {value.passengers.served for value in values} == {1}
    assert all(not any(value.passengers.plan.trips[0].wait_ticks) for value in values)


def test_fixed_pattern_specialization_removes_other_pattern_selection_variables():
    from ropeway_skip_stop_optimization.optimization.ddd.reservoir_lines.cp_model import build_reservoir_line_model
    p, prepared = _prepared(fleet=2, dispatch_end=3)
    base = ReservoirLineConfig(
        dispatch_window_end_seconds=3, maximum_cabins=2,
        variant=ReservoirLineVariant.INTERVALS,
        preparation=ReservoirLinePreparation.ENCODING_SPECIFIC,
        formulation=ReservoirLineFormulation.SHARED_ROUNDS,
        mode=ReservoirLineMode.FEASIBILITY,
        catalog_profile=ReservoirLineCatalogProfile.RELEVANT,
        fixed_cabins=2, workers=1,
    )
    full = build_reservoir_line_model(p, prepared, base)
    specialized = build_reservoir_line_model(
        p, prepared, replace(base, fixed_pattern_sequence=("all_stop", "all_stop"))
    )
    assert specialized.stats["fixed_pattern_specialization"]
    all_stop_templates = sum(t.pattern_id == "all_stop" for t in prepared.templates)
    assert specialized.stats["line_selection_variables"] == 2 * all_stop_templates
    assert specialized.stats["line_selection_variables"] <= full.stats["line_selection_variables"]
    assert specialized.stats["variables"] <= full.stats["variables"]


def test_pattern_only_search_finds_a_valid_plan_without_hint():
    p, prepared = _prepared(fleet=1, dispatch_end=3)
    events = []
    result = run_search(
        p, prepared,
        EvolutionSearchConfig(
            representation="patterns_only", dispatch_subproblem="joint_service",
            selection_profile="pattern_status", fixed_k=1, seed_all_stop=False,
            time_limit_seconds=2, evaluation_time_limit_seconds=1,
            population_size=4, offspring_size=2, waiting_workers=1,
        ),
        event_callback=events.append,
    )
    assert result["best"] is not None
    assert result["best"].passengers.served == 1
    assert any(event["kind"] == "pattern_subproblem" for event in events)
