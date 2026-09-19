"""Geometric thesis parameters, explicit legacy import and model boundaries."""
from copy import deepcopy
from dataclasses import replace

import pytest

from ropeway_skip_stop_optimization.examples.registry import get_example
from ropeway_skip_stop_optimization.examples.artificial_headway_cases import with_architecture_b_headways
from ropeway_skip_stop_optimization.exports.json_codec import decode_headway_design, to_jsonable
from ropeway_skip_stop_optimization.models import GeometricSharedBoundaryDesign
from ropeway_skip_stop_optimization.benchmarking.oip_pattern_waiting import prepare_oip_pattern_waiting_pilot
from ropeway_skip_stop_optimization.optimization.oip.cp_sat import build_oip_cp_sat_model

FAULT = {"merge_clearance_m", "emergency_merge_sway_angle_rad", "control_delay_seconds",
         "emergency_deceleration_m_per_s2", "mechanical_service_cycle_seconds"}


def scenario():
    return get_example('thesis_t5r_g500_b_v1').build_scenario()


def all_keys(value):
    if isinstance(value, dict):
        return set(value) | set().union(*(all_keys(v) for v in value.values()))
    if isinstance(value, (list, tuple)):
        return set().union(*(all_keys(v) for v in value))
    return set()


def test_geometric_export_and_roundtrip_need_no_fault_parameters():
    design = scenario().headway_design
    design.validate()
    payload = to_jsonable(design)
    assert payload['schema_version'] == 2
    assert not (all_keys(payload) & FAULT)
    assert not any(p['parameter_name'] in FAULT for p in payload['physical']['provenance'])
    assert decode_headway_design(payload) == design


def test_direct_geometry_matches_previous_replace_path():
    current = scenario()
    old = with_architecture_b_headways(current, scenario_id=current.id)
    old = replace(old, headway_design=replace(old.headway_design,
        station_mechanisms=tuple(replace(a, design=GeometricSharedBoundaryDesign())
                                 for a in old.headway_design.station_mechanisms)))
    example = get_example(current.id)
    config = example.build_ean_config(current)
    builder = example.build_ean_artifact_builder(current, config)
    new_policy = builder.build(current, config).headway_policy
    old_policy = builder.build(old, config).headway_policy
    assert replace(new_policy, provenance=()) == replace(old_policy, provenance=())


def legacy_payload():
    legacy = get_example('thesis_t5r_g500_b_v1').build_scenario(legacy_headways=True)
    payload = to_jsonable(legacy.headway_design)
    payload.pop('schema_version')
    for assignment in payload['station_mechanisms']:
        mechanism = assignment['design']
        for name in FAULT - {'mechanical_service_cycle_seconds'}:
            payload['physical'][name] = mechanism.pop(name)
        provenance = mechanism.pop('provenance')
    payload['physical']['provenance'].extend(provenance)
    return legacy.headway_design, payload


def test_unversioned_fault_parameters_are_moved_without_changing_values():
    expected, payload = legacy_payload()
    snapshot = deepcopy(payload)
    decoded = decode_headway_design(payload)
    assert decoded == expected
    assert payload == snapshot
    assert decode_headway_design(to_jsonable(decoded)) == decoded


def test_unused_old_fault_inputs_are_reported_explicitly():
    _, payload = legacy_payload()
    for assignment in payload['station_mechanisms']:
        assignment['design'] = {}
    with pytest.warns(UserWarning, match='Unused legacy fault inputs'):
        migrated = decode_headway_design(payload)
    assert not (all_keys(to_jsonable(migrated)) & FAULT)


@pytest.mark.parametrize('edit', ['version', 'unknown', 'conflict', 'invalid'])
def test_import_rejects_ambiguous_or_invalid_legacy_data(edit):
    _, payload = legacy_payload()
    if edit == 'version': payload['schema_version'] = 99
    elif edit == 'unknown': payload['unexpected'] = 1
    elif edit == 'conflict': payload['station_mechanisms'][0]['design']['control_delay_seconds'] = 999
    else: payload['physical']['emergency_deceleration_m_per_s2'] = 0
    with pytest.raises(ValueError): decode_headway_design(payload)


@pytest.mark.parametrize('formulation', ['ean', 'nowait_templates'])
def test_geometric_solver_has_no_fault_or_history_auxiliaries(formulation):
    domain = prepare_oip_pattern_waiting_pilot(maximum_wait_seconds=0, cabin_count=2, demand_total=12).domain
    built = build_oip_cp_sat_model(domain, formulation=formulation, objective='served', type_catalog='all_stop_bd_ce')
    assert not built.movement.previous_service
    assert not built.model.validate()
    assert not any(any(token in v.name for token in (
        'previous_service[', 'prior_service[', 'headway_size[', 'boundary_service_presence[',
        'boundary_service_end[', 'regular_service_end[')) for v in built.model.proto.variables)
    assert not any('service_mechanism' in c.name for c in built.model.proto.constraints)


def test_gurobi_geometric_builder_creates_no_fault_history_variables():
    import gurobipy as gp
    from gurobipy import GRB
    from ropeway_skip_stop_optimization.optimization.ean.optimizers.movement_model import EanMovementModelBuilder
    from ropeway_skip_stop_optimization.optimization.ean.optimization_config import EanOptimizationConfig
    from ropeway_skip_stop_optimization.optimization.ean import EanFormulationConfig, EanHorizonFormulation, EanTimeBoundFormulation
    domain = prepare_oip_pattern_waiting_pilot(maximum_wait_seconds=0, cabin_count=2, demand_total=12).domain
    with gp.Env(empty=True) as env:
        env.setParam('OutputFlag', 0)
        env.start()
        with gp.Model(env=env) as model:
            built = EanMovementModelBuilder().build(model=model, binary_vtype=GRB.BINARY,
                artifact=domain.artifact, optimization_config=EanOptimizationConfig(
                    formulation=EanFormulationConfig(
                        horizon=EanHorizonFormulation.EXACT_TIME_ACTIVATION,
                        time_bounds=EanTimeBoundFormulation.INITIAL_PLACEMENT_SAFE)))
            model.update()
            assert not built.fleet_model.variables.initial_previous_service
            assert not any('initial_service_resource' in c.ConstrName for c in model.getConstrs())
            # Geometric conflict ordering still exists and must not be removed.
            assert built.variables.headway_order


def test_thesis_prepared_graph_rejects_old_fault_contract():
    from ropeway_skip_stop_optimization.benchmarking.ddd_fixed_k_arc_flow import (
        DddFixedKArcFlowRunConfig, prepare_ddd_fixed_k_arc_flow_run,
        _validate_prepared_run_compatibility,
    )
    from ropeway_skip_stop_optimization.optimization.ddd import DddFixedKOperatingMode
    config = DddFixedKArcFlowRunConfig('thesis_t5r_g500_b_v1', 2,
        DddFixedKOperatingMode.SKIP_STOP, horizon_seconds=250, tail_seconds=30,
        use_primal_start=False)
    prepared = prepare_ddd_fixed_k_arc_flow_run(config)
    _validate_prepared_run_compatibility(config, prepared)
    old_scenario = with_architecture_b_headways(prepared.scenario, scenario_id=config.example_id)
    with pytest.raises(ValueError, match='headway design'):
        _validate_prepared_run_compatibility(config, replace(prepared, scenario=old_scenario))


def test_arc_flow_network_is_unchanged_by_direct_geometric_construction(monkeypatch):
    from types import SimpleNamespace
    from ropeway_skip_stop_optimization.benchmarking import ddd_fixed_k_arc_flow as runner
    from ropeway_skip_stop_optimization.optimization.ddd import DddFixedKOperatingMode
    from ropeway_skip_stop_optimization.optimization.ddd.arc_flow_preparation import DddArcFlowProblemPreparer
    config = runner.DddFixedKArcFlowRunConfig('thesis_t5r_g500_b_v1', 2,
        DddFixedKOperatingMode.SKIP_STOP, horizon_seconds=250, tail_seconds=30,
        use_primal_start=False)
    current = runner.prepare_ddd_fixed_k_arc_flow_run(config)
    example = get_example(config.example_id)
    old = with_architecture_b_headways(current.scenario, scenario_id=config.example_id)
    old = replace(old, headway_design=replace(old.headway_design,
        station_mechanisms=tuple(replace(a, design=GeometricSharedBoundaryDesign())
                                 for a in old.headway_design.station_mechanisms)))
    monkeypatch.setattr(runner, 'get_example', lambda _: SimpleNamespace(
        build_scenario=lambda: old, build_ean_config=example.build_ean_config,
        build_ean_artifact_builder=example.build_ean_artifact_builder))
    before = runner.prepare_ddd_fixed_k_arc_flow_run(config)
    assert before.problem.fingerprint == current.problem.fingerprint
    a, b = (DddArcFlowProblemPreparer().build(r.problem) for r in (before, current))
    assert a.arcs == b.arcs
    assert a.boundary_intervals == b.boundary_intervals
    assert a.resource_cliques == b.resource_cliques
