"""Solver-free export of checked thesis incumbents to the existing EAN viewer."""
from __future__ import annotations
from dataclasses import fields, is_dataclass, replace
from datetime import time, datetime, date, timedelta
from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import get_args, get_origin, get_type_hints
import json

from ropeway_skip_stop_optimization.exports.json_codec import to_jsonable, decode_headway_design
from ropeway_skip_stop_optimization.models import Scenario
from ropeway_skip_stop_optimization.optimization.ean.plan import EanCabinVisit, EanRouteDecision
from ropeway_skip_stop_optimization.optimization.ean.models import StationWaitingMode
from ropeway_skip_stop_optimization.optimization.ean.projection import (
    _projection_routes_by_switch_id, _events_for_visit, _with_boundary_context_events,
)
from ropeway_skip_stop_optimization.benchmarking.frontend_results import atomic_json


def decode(cls, value):
    if value is None: return None
    if cls is time: return time.fromisoformat(value)
    origin, args = get_origin(cls), get_args(cls)
    if origin is tuple: return tuple(decode(args[0], x) for x in value)
    if origin is list: return [decode(args[0], x) for x in value]
    if origin is dict: return value
    if args:
        concrete = [a for a in args if a is not type(None)]
        if len(concrete) == 1: return decode(concrete[0], value)
    if isinstance(cls, type) and issubclass(cls, Enum): return cls(value)
    if is_dataclass(cls):
        hints = get_type_hints(cls)
        return cls(**{f.name: decode(hints[f.name], value[f.name]) for f in fields(cls) if f.name in value})
    return value


def read_scenario(data):
    data = dict(data)
    headway = data.pop('headway_design', None)
    scenario = decode(Scenario, data)
    if headway:
        from dataclasses import replace
        scenario = replace(scenario, headway_design=decode_headway_design(headway))
    scenario.validate()
    return scenario


@lru_cache(maxsize=1)
def oip_domain(family, demand, k, operation):
    from ropeway_skip_stop_optimization.benchmarking.oip_pattern_waiting import prepare_oip_pattern_waiting_pilot
    from ropeway_skip_stop_optimization.optimization.oip import OipOperation
    return prepare_oip_pattern_waiting_pilot(maximum_wait_seconds=0, demand_total=demand,
        cabin_count=k, demand_family=family, operation=OipOperation(operation)).domain


def scenario_json(scenario):
    data = to_jsonable(scenario)
    data["scenario_id"] = data.pop("id")
    data["service_start_time"] = scenario.service_start_time.isoformat()
    data["service_end_time"] = scenario.service_end_time.isoformat()
    for item, demand in zip(data["demands"], scenario.demands):
        item["arrival_time"] = demand.arrival_time.isoformat()
    return data


def journey_payload(source, result):
    native = result['run']
    if native.get('independent_validation_status') != 'feasible':
        raise ValueError('No independently validated Journey incumbent')
    manifest = native['fixed_k_problem_manifest']
    core = manifest['trajectory_problem']['movement_core']
    passengers = native.get('validated_passenger_plan')
    if not passengers: raise ValueError('Missing checked passenger certificate')
    scenario = read_scenario(json.loads((source / 'scenario.json').read_text()))
    options = {o['id']: o for o in core['route_options']}
    states = [s['id'] if isinstance(s, dict) else s for s in core['states']]
    routes = _projection_routes_by_switch_id(scenario, tuple(states))
    trajectories, events = [], []
    for trip in native['trajectory_supports']:
        visits = []
        for i, (oid, t, wait) in enumerate(zip(trip['route_option_ids'], trip['switch_times_seconds'], trip['wait_seconds'])):
            o = options[oid]
            def at(key, extra=0):
                return None if o.get(key) is None else (round(t*1e6) + round(o[key]*1e6) + round(extra*1e6))/1e6
            visit = EanCabinVisit(trip['cabin_id'], i, o['from_state_id'], o['station_id'],
                EanRouteDecision(o['decision']), t, at('platform_entry_offset_seconds'),
                at('platform_exit_offset_seconds', wait), at('exit_switch_offset_seconds', wait),
                at('duration_seconds', wait), wait)
            visit.validate()
            visits.append(visit)
            events.extend(_events_for_visit(visit, routes[visit.switch_id], StationWaitingMode.END_OF_PLATFORM_WAIT))
        if visits and visits[0].switch_time_seconds > 0:
            first = visits[0]
            previous = next(o for o in options.values() if o['to_state_id'] == first.switch_id and o['decision'] == 'stop')
            t = first.switch_time_seconds - previous['duration_seconds']
            context = EanCabinVisit(first.cabin_id, -1, previous['from_state_id'], previous['station_id'], EanRouteDecision.STOP,
                t, t+previous['platform_entry_offset_seconds'], t+previous['platform_exit_offset_seconds'],
                t+previous['exit_switch_offset_seconds'], first.switch_time_seconds, 0)
            events.extend(_events_for_visit(context, routes[context.switch_id], StationWaitingMode.END_OF_PLATFORM_WAIT))
        trajectories.append({'cabin_id': trip['cabin_id'], 'visits': to_jsonable(visits)})
    movement = dict(scenario_id=scenario.id, horizon_seconds=core['passenger_service_end_seconds'],
        model_end_seconds=core['operational_end_seconds'], fleet_mode='fixed_starts',
        horizon_formulation='horizon_exact_time_activation', trajectories=trajectories)
    # The solver manifest contains the actual prepared demand, unlike the base scenario file.
    from ropeway_skip_stop_optimization.models import Demand
    anchor = datetime.combine(date(2000,1,2), scenario.service_start_time)
    scenario = replace(scenario, demands=tuple(Demand(
        arrival_time=(anchor+timedelta(seconds=g['release_time_seconds'])).time(),
        origin=g['origin_station_id'], destination=g['destination_station_id'], count=g['count'])
        for g in manifest['demand_groups']), service_end_time=(anchor+timedelta(seconds=core['operational_end_seconds'])).time())
    ids = {g['id']: f'demand::{i}' for i,g in enumerate(manifest['demand_groups'])}
    passengers = {**passengers, 'served_rides': [{**r,'demand_group_id':ids[r['demand_group_id']]} for r in passengers['served_rides']],
        'unserved_counts_by_demand_group_id': {ids[k]:v for k,v in passengers['unserved_counts_by_demand_group_id'].items()}}
    replay = dict(scenario_id=scenario.id, horizon_seconds=movement['horizon_seconds'], model_end_seconds=movement['model_end_seconds'],
        events=to_jsonable(sorted(_with_boundary_context_events(events,movement['model_end_seconds']), key=lambda e:(e.time_seconds,e.cabin_id,e.visit_index,e.event_kind.value))))
    return scenario_json(scenario), movement, passengers, replay, None


@lru_cache(maxsize=1)
def physical_policy_template():
    # Single-cabin preparation derives the same physical rules without building a solver.
    from ropeway_skip_stop_optimization.benchmarking.oip_pattern_waiting import prepare_oip_pattern_waiting_pilot
    domain=prepare_oip_pattern_waiting_pilot(maximum_wait_seconds=0,demand_total=1,cabin_count=1,demand_family='f2').domain
    return scenario_json(domain.scenario), domain.artifact


def safety_input(scenario,movement):
    template,artifact=physical_policy_template()
    for key in ('stations','physical_nodes','track_segments','station_routes','operating','headway_design'):
        if scenario[key]!=template[key]: raise ValueError(f'Physical replay policy differs in {key}')
    return dict(scenario_id=scenario['scenario_id'], config=to_jsonable(artifact.config),
        switch_cycle=list(artifact.circulation_state_ids),timings=to_jsonable(artifact.timings),
        cabin_starts=[],switch_visits=[],switch_transitions=[],headway_checkpoints=[],headway_candidates=[],headway_pairs=[],
        fleet_mode=movement['fleet_mode'],headway_policy=to_jsonable(artifact.headway_policy),
        safety_schema_version='frontend_replay_safety_v1')


def repair_initial_context(scenario,movement,replay,fleet):
    """Use physical bracketing events, not logical t=0 placement markers."""
    if not fleet: return replay
    events=[{**e,'time_seconds':round(e['time_seconds']*1000)/1000} for e in replay['events'] if e['event_kind']!='initial_placement']
    trajectories={t['cabin_id']:t['visits'] for t in movement['trajectories']}
    for state in fleet['initial_states']:
        cabin=state['cabin_id']
        if state['kind']!='rope' or any(e['cabin_id']==cabin and e['time_seconds']<0 for e in events): continue
        first=trajectories[cabin][0]
        rope=next(s for s in scenario['track_segments'] if s['kind']=='rope' and s['to_node_id']==first['switch_id'])
        base=dict(cabin_id=cabin,visit_index=first['visit_index']-1,switch_id=state['switch_id'],station_id=next(n['station_id'] for n in scenario['physical_nodes'] if n['id']==rope['from_node_id']))
        events.append(dict(**base,event_kind='exit_switch',time_seconds=round(state['previous_event_time_seconds']*1000)/1000,physical_node_id=rope['from_node_id'],source_segment_ids=[]))
        events.append(dict(**base,event_kind='reach_next_switch',time_seconds=first['switch_time_seconds'],physical_node_id=rope['to_node_id'],source_segment_ids=[rope['id']]))
    return {**replay,'events':sorted(events,key=lambda e:(e['time_seconds'],e['cabin_id'],e['visit_index'],e['event_kind']))}


def export_replay(source: Path, target: Path, public_base: str, *, family=None, demand=None, k=None):
    result_path = source/'result.json'
    if not result_path.exists(): return None
    result = json.loads(result_path.read_text())
    if 'run' in result:
        if result['run'].get('independent_validation_status') != 'feasible': return None
        scenario, movement, passengers, replay, fleet = journey_payload(source,result)
    else:
        if not all(result.get(x) for x in ('movement_plan','passenger_plan','fleet_plan')): return None
        from ropeway_skip_stop_optimization.optimization.oip.runner import _read_portable_checkpoint
        from ropeway_skip_stop_optimization.optimization.ean.projection import project_ean_movement_plan_to_physical_replay
        manifest=json.loads((source/'manifest.json').read_text())
        domain=oip_domain(family,demand,k,manifest['operation'])
        move,fleet,passengers=_read_portable_checkpoint(source,domain)
        replay=project_ean_movement_plan_to_physical_replay(domain.scenario,domain.artifact,move)
        movement,passengers,replay,fleet=map(to_jsonable,(move,passengers,replay,fleet))
        scenario=scenario_json(domain.scenario)
    replay=repair_initial_context(scenario,movement,replay,fleet)
    if fleet: movement['fleet_plan']=fleet
    visits={(t['cabin_id'],v['visit_index']):v for t in movement['trajectories'] for v in t['visits']}
    for r in passengers['served_rides']:
        if isinstance(r['count'],bool) or not isinstance(r['count'],int) or r['count']<0: raise ValueError('Invalid ride quantity')
        board=visits[r['cabin_id'],r['board_visit_index']]; alight=visits[r['cabin_id'],r['alight_visit_index']]
        if board['decision']!='stop' or alight['decision']!='stop' or abs(board['platform_exit_time_seconds']-r['boarding_time_seconds'])>1e-5 or abs(alight['platform_entry_time_seconds']-r['alighting_time_seconds'])>1e-5:
            raise ValueError('Passenger timing differs from physical visits')
    served=sum(r['count'] for r in passengers['served_rides']); unserved=sum(passengers['unserved_counts_by_demand_group_id'].values())
    service=dict(movement_plan=movement,passenger_plan=passengers,fleet_plan=fleet,metadata=dict(status='validated',objective_kind='journey_time',objective_value_seconds=None,
        objective_passenger_hours=None,demand_group_count=len(scenario['demands']),ride_candidate_count=len(passengers['served_rides']),slot_variable_count=0,
        served_passenger_count=served,unserved_passenger_count=unserved,variable_count=0,constraint_count=0,skipped_visit_count=sum(v['decision']=='skip' for v in visits.values()),visible_skipped_visit_count=0))
    artifacts={}
    for name,payload in [('scenario',scenario),('ean_input',safety_input(scenario,movement)),('ean_result',movement),('ean_replay',replay),('milp_result',service)]:
        atomic_json(target/f'{name}.json',payload); artifacts[name]=f'{public_base}/{name}.json'
    return dict(id='best',label='Best validated incumbent',backend='ean',artifacts=artifacts,artifact_metadata=[])
