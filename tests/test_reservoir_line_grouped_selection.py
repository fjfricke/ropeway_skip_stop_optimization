from types import SimpleNamespace as N
from collections import Counter
import numpy as np
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_lines.evolution.grouped_selection import (
    candidate_group, passenger_score, survivor_indices, parent_index, schedule_key)


def value(group, identity, score=1):
    trip = N(cabin_id=0, route_option_ids=('stop',), switch_ticks=(identity,), wait_ticks=(0,), return_tick=identity+10)
    plan = N(trips=(trip,))
    movement = N(genome=N(identity=str(identity), fleet_size=38), feasible=group=='valid',
                 plan=plan if group=='valid' else None,
                 relaxed_timetable=plan if group=='complete' else None,
                 conflicts=tuple(range(score)) if group=='complete' else (), total_overlap_ticks=score)
    return N(movement=movement, passengers=N(unserved=score, plan=plan) if group=='valid' else None,
             decoder={'status':'CONSTRUCTION_FAILED', 'completed_cabins':38-score} if group=='incomplete' else {})


def test_full_candidates_not_displaced_by_one_missing_cabin():
    values = [value('incomplete', i) for i in range(40)] + [value('complete', 100+i, 1200+i) for i in range(40)]
    selected = survivor_indices(values, 32)
    assert Counter(candidate_group(values[i]) for i in selected) == {'complete':24, 'incomplete':8}
    assert [len(values[i].movement.conflicts) for i in selected if candidate_group(values[i])=='complete'] == list(range(1200,1224))


def test_valid_quota_and_fill_when_a_group_is_empty():
    values = [value(g, 100*j+i, i) for j,g in enumerate(('valid','complete','incomplete')) for i in range(40)]
    selected = survivor_indices(values,32)
    assert Counter(candidate_group(values[i]) for i in selected)=={'valid':16,'complete':12,'incomplete':4}
    assert len(survivor_indices(values[:40],32))==32


def test_duplicates_keep_best_passenger_value_and_do_not_fill_with_clones():
    a,b=value('valid',1,10),value('valid',1,5)
    assert schedule_key(a)==schedule_key(b)
    assert survivor_indices([a,b],32)==[1]
    # Distinct Waiting schedules must remain distinct.
    b.passengers.plan.trips[0].wait_ticks=(1,)
    assert len(survivor_indices([a,b],32))==2


def test_service_then_journey_is_strictly_lexicographic():
    fewer_unserved = N(unserved=1, journey_time_tick=10_000)
    shorter_but_less_service = N(unserved=2, journey_time_tick=1)
    same_service_shorter = N(unserved=1, journey_time_tick=9_999)
    assert passenger_score(fewer_unserved) < passenger_score(shorter_but_less_service)
    assert passenger_score(same_service_shorter) < passenger_score(fewer_unserved)


def test_library_scalar_cannot_trade_away_one_passenger():
    from ropeway_skip_stop_optimization.optimization.ddd.reservoir_lines.evolution.search import passenger_scalar
    bound = 10_000
    better_service = N(unserved=1, journey_time_tick=bound)
    shorter_but_less_service = N(unserved=2, journey_time_tick=0)
    assert passenger_scalar(better_service, "service_then_journey", bound) < 2
    assert passenger_scalar(better_service, "service_then_journey", bound) < passenger_scalar(
        shorter_but_less_service, "service_then_journey", bound
    )


def test_parent_tournament_uses_only_its_chosen_group():
    values=[value('complete',100+i,1000+i) for i in range(24)]+[value('incomplete',i,1) for i in range(8)]
    rng=np.random.default_rng(1);groups=Counter()
    for _ in range(3000):
        i,g=parent_index(values,rng); assert candidate_group(values[i])==g;groups[g]+=1
    assert 2100<groups['complete']<2400
    assert 600<groups['incomplete']<900


def test_native_ga_grouped_path_runs_and_records_groups():
    from test_reservoir_line_evolution import _prepared
    from ropeway_skip_stop_optimization.optimization.ddd.reservoir_lines.evolution import EvolutionSearchConfig, run_search
    p, prepared = _prepared(fleet=2)
    events=[]
    result=run_search(p, prepared, EvolutionSearchConfig(selection_profile='grouped', fixed_k=1,
        seed_all_stop=False, population_size=2, offspring_size=1, time_limit_seconds=2), event_callback=events.append)
    assert result['selection']=='grouped'
    assert result['best'] is not None
    assert result['best'].movement.genome.fleet_size==1
    assert any(e['kind']=='population' and all('selection_group' in m for m in e['members']) for e in events)
    assert result['parent_selection_counts'].get('group_valid',0)>0
