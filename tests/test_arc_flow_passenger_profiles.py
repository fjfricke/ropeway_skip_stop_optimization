from dataclasses import replace
import json
from collections import defaultdict
from itertools import product

import gurobipy as gp
from gurobipy import GRB
import pytest

from test_optimization_ddd_arc_flow import _fixed_problem
from ropeway_skip_stop_optimization.optimization.ddd.arc_flow_passenger_formulation import (
    PASSENGER_PROFILES, DddArcFlowPassengerFormulationConfig as Config,
    prepare_arc_flow_passengers,
)
from ropeway_skip_stop_optimization.optimization.ddd.arc_flow_passenger_model import DddArcFlowPassengerModelBuilder
from ropeway_skip_stop_optimization.optimization.ddd.arc_flow_preparation import DddArcFlowProblemPreparer
from ropeway_skip_stop_optimization.optimization.ddd.arc_flow_movement_master import DddArcFlowMovementMasterBuilder
from ropeway_skip_stop_optimization.optimization.ean.optimizers.fixed_movement_passenger_model import EanPassengerAssignmentDomain


@pytest.fixture(scope="module")
def prepared():
    return DddArcFlowProblemPreparer().build(_fixed_problem(2))


def solve(prepared, config=Config(), lp=False, fixed=None):
    encoding = prepare_arc_flow_passengers(prepared, config)
    model = gp.Model()
    model.Params.OutputFlag = 0
    model.Params.Threads = 1
    model.Params.TimeLimit = 30
    model.Params.MIPGap = 0
    movement = DddArcFlowMovementMasterBuilder().build(
        model=model, prepared=prepared, variable_type=GRB.CONTINUOUS if lp else GRB.BINARY,
    )
    passenger = DddArcFlowPassengerModelBuilder().build_integrated(
        model=model, domain=encoding.source, route_by_arc_id=movement.route_by_arc_id,
        encoding=encoding,
        assignment_domain=(EanPassengerAssignmentDomain.LP_RELAXATION if lp else EanPassengerAssignmentDomain.INTEGER),
    )
    if fixed is not None:
        for key, var in movement.route_by_arc_id.items():
            var.LB = var.UB = fixed[key]
    model.optimize()
    assert model.Status == GRB.OPTIMAL
    return model, movement, passenger, encoding


@pytest.mark.parametrize("profile", PASSENGER_PROFILES)
def test_integer_optimum_and_canonical_decomposition(prepared, profile):
    baseline, _, _, _ = solve(prepared)
    model, movement, passenger, encoding = solve(prepared, Config.from_profile(profile))
    assert model.ObjVal == pytest.approx(baseline.ObjVal, abs=1e-5)
    values = passenger.canonical_values()
    assert all(abs(v - round(v)) < 1e-5 for v in values.values())
    for row in encoding.source.equality_rows:
        assert sum(c * values[v] for v, c in row.coefficients) == pytest.approx(0, abs=1e-5)
    assert encoding.source.objective_constant + sum(
        v.objective_coefficient * values[v.id] for v in encoding.source.variables
    ) == pytest.approx(model.ObjVal, abs=1e-5)
    for row in encoding.source.capacity_rows:
        assert sum(values[v] for v in row.variable_ids) <= row.movement_coefficient * movement.route_by_arc_id[row.arc_id].X + 1e-5


@pytest.mark.parametrize("profile", PASSENGER_PROFILES)
def test_lp_relationship(prepared, profile):
    baseline, _, _, _ = solve(prepared, lp=True)
    model, _, _, _ = solve(prepared, Config.from_profile(profile), lp=True)
    if profile == "alight_links":
        assert model.ObjVal >= baseline.ObjVal - 1e-5
    elif profile == "destination_flows":
        assert model.ObjVal <= baseline.ObjVal + 1e-5
    else:
        assert model.ObjVal == pytest.approx(baseline.ObjVal, abs=1e-5)


@pytest.mark.parametrize("profile", PASSENGER_PROFILES)
def test_seed_round_trip(prepared, profile):
    baseline, movement, passenger, encoding = solve(prepared)
    values = passenger.canonical_values()
    meta = encoding.source.variable_by_id
    counts = {f.candidate_id: sum(values[v] for _, v in f.variable_ids_by_arc_id
                                 if meta[v].visit_index == f.board_visit_index)
              for f in encoding.source.flows}
    movement_values = {key: round(var.X) for key, var in movement.route_by_arc_id.items()}
    model, _, new_passenger, _ = solve(prepared, Config.from_profile(profile), fixed=movement_values)
    value = new_passenger.apply_seed(ride_counts_by_candidate_id=counts, movement_values_by_arc_id=movement_values)
    model.update()
    assert value == pytest.approx(baseline.ObjVal, abs=1e-5)
    assert all(var.Start < GRB.UNDEFINED for var in new_passenger.variable_by_id.values())


def test_combined_and_reduction_evidence(prepared):
    config = Config(True, True, True, True, True)
    model, _, passenger, encoding = solve(prepared, config)
    baseline, _, _, _ = solve(prepared)
    assert model.ObjVal == pytest.approx(baseline.ObjVal, abs=1e-5)
    assert passenger.canonical_values()
    assert len(encoding.algebra.variables) < len(encoding.source.variables)
    assert json.loads(encoding.audit_json)["dropped_links"]
    assert passenger.ride_variable_by_id


def test_destination_profile_does_not_implicitly_enable_alight_cuts(prepared):
    encoding = prepare_arc_flow_passengers(prepared, Config(destination_flows=True))
    source = encoding.source.variable_by_id
    originals = defaultdict(list)
    for old, new in encoding.projection:
        originals[new].append(old)
    assert not encoding.alight_rows
    shared_alight = False
    for variable in encoding.algebra.variables:
        assert variable.upper_bound == sum(source[v].upper_bound for v in originals[variable.id])
        if variable.visit_index == variable.alight_visit_index and len(originals[variable.id]) > 1:
            shared_alight = True
            assert variable.upper_bound > prepared.problem.artifact.config.cabin_capacity
    assert shared_alight


def test_profile_validation_and_fingerprints(prepared):
    with pytest.raises(ValueError):
        Config.from_profile("unknown")
    legacy = prepare_arc_flow_passengers(prepared)
    assert legacy.source.fingerprint == legacy.algebra.fingerprint
    changed = prepare_arc_flow_passengers(prepared, Config(ride_integrality=True))
    assert changed.source.fingerprint == legacy.source.fingerprint
    assert changed.fingerprint != legacy.fingerprint
    from ropeway_skip_stop_optimization.benchmarking.ddd_fixed_k_arc_flow import (
        DddFixedKArcFlowRunConfig, DddFixedKArcFlowFormulation,
    )
    cfg = DddFixedKArcFlowRunConfig("example", 1, prepared.problem.operating_mode)
    with pytest.raises(ValueError, match="only for labeled"):
        replace(cfg, formulation=DddFixedKArcFlowFormulation.EXACT_ANONYMOUS,
                passenger_formulation=Config(reachability=True)).validate()


def enumerate_integer_optimum(prepared):
    """Independent exhaustive path/quantity enumeration; no LP or MIP oracle."""
    assert len(prepared.networks) == 1
    network = prepared.networks[0]
    outgoing = defaultdict(list)
    for arc in network.arcs:
        outgoing[arc.source_node].append(arc)
    encoding = prepare_arc_flow_passengers(prepared)
    domain = encoding.source
    metadata = domain.variable_by_id
    demand = {g.id: g.count for g in prepared.problem.passenger_build.demand_groups}
    best = domain.objective_constant
    terminals = []
    stack = [((0, network.start.time_tick, True), ())]
    while stack:
        node, path = stack.pop()
        if node[0] == network.start.max_visit_count:
            if not node[2]:
                terminals.append(path)
            continue
        for arc in outgoing[node]:
            stack.append((arc.target_node, (*path, arc)))
    for path in terminals:
        selected = {a.id for a in path}
        if any(sum(c for a, c in clique.coefficients if a in selected) > 1
               for clique in prepared.resource_cliques):
            continue
        rides = []
        for flow in domain.flows:
            ids = [v for a, v in flow.variable_ids_by_arc_id if a in selected]
            if {metadata[v].visit_index for v in ids} == set(range(flow.board_visit_index, flow.alight_visit_index + 1)):
                rides.append((flow, ids))
        for amounts in product(*(range(min(int(prepared.problem.artifact.config.cabin_capacity),
                                             demand[f.demand_group_id]) + 1) for f, _ in rides)):
            used = defaultdict(int)
            loads = defaultdict(int)
            cost = domain.objective_constant
            for (flow, ids), count in zip(rides, amounts, strict=True):
                used[flow.demand_group_id] += count
                for v in ids:
                    variable = metadata[v]
                    cost += variable.objective_coefficient * count
                    if variable.visit_index < flow.alight_visit_index:
                        loads[variable.arc_id] += count
            if all(used[g] <= n for g, n in demand.items()) and all(
                load <= prepared.problem.artifact.config.cabin_capacity for load in loads.values()
            ):
                best = min(best, cost)
    return best


@pytest.mark.parametrize("waiting", [0, 0.000002])
def test_all_profiles_against_enumeration_with_waiting(waiting):
    from ropeway_skip_stop_optimization.benchmarking.ddd_fixed_k_didp import prepare_small
    _, problem = prepare_small(1, waiting=waiting, horizon=100)
    prepared = DddArcFlowProblemPreparer().build(problem)
    expected = enumerate_integer_optimum(prepared)
    for profile in PASSENGER_PROFILES:
        model, _, passenger, _ = solve(prepared, Config.from_profile(profile))
        assert model.ObjVal == pytest.approx(expected, abs=1e-5)
        assert all(abs(v - round(v)) < 1e-5 for v in passenger.canonical_values().values())


def test_positive_pruned_seed_is_rejected(prepared):
    _, _, passenger, encoding = solve(prepared, Config(reachability=True))
    projection = dict(encoding.projection)
    removed = next(v for v in encoding.source.variables if v.id not in projection)
    with pytest.raises(ValueError, match="pruned"):
        passenger.apply_seed(ride_counts_by_candidate_id={removed.candidate_id: 1},
                             movement_values_by_arc_id={removed.arc_id: 1})


@pytest.mark.parametrize("horizon", [56.272727, 56.272726])
def test_horizon_and_tail_all_profiles(horizon):
    from test_optimization_ddd_cp_sat_integrated import tiny_problem
    from ropeway_skip_stop_optimization.optimization.ean.models import EanDemandGroup
    _, problem = tiny_problem(horizon=horizon, tail=70, groups=(EanDemandGroup("ab", "A", "B", 0, 1),))
    _, larger = tiny_problem(groups=problem.passenger_build.demand_groups)
    problem = replace(problem, passenger_build=replace(problem.passenger_build,
                                                       ride_candidates=larger.passenger_build.ride_candidates))
    prepared = DddArcFlowProblemPreparer().build(problem)
    baseline, _, _, _ = solve(prepared)
    for profile in PASSENGER_PROFILES[1:]:
        model, _, _, _ = solve(prepared, Config.from_profile(profile))
        assert model.ObjVal == pytest.approx(baseline.ObjVal, abs=1e-6)


def test_release_during_waiting_and_same_visit_turnover():
    from test_optimization_ddd_cp_sat_integrated import tiny_problem
    from ropeway_skip_stop_optimization.optimization.ean.models import EanDemandGroup
    groups = (EanDemandGroup("early", "A", "B", 0, 2),
              EanDemandGroup("during", "A", "B", 22.090910, 1),
              EanDemandGroup("after", "A", "B", 131, 1),
              EanDemandGroup("bc", "B", "C", 0, 2))
    _, problem = tiny_problem(groups=groups, maximum_wait=.000002, waiting_step=.000001)
    prepared = DddArcFlowProblemPreparer().build(problem)
    expected = enumerate_integer_optimum(prepared)
    for profile in PASSENGER_PROFILES:
        model, _, _, _ = solve(prepared, Config.from_profile(profile))
        assert model.ObjVal == pytest.approx(expected, abs=1e-5)


def test_overtaking_all_profiles_against_independent_fixed_ip():
    from test_optimization_ddd_cp_sat_integrated import tiny_problem, fixed_ip
    from ropeway_skip_stop_optimization.optimization.ddd.reference import (
        DddReferenceTrajectoryGenerator, DddReferenceSolution, validate_ddd_reference_solution,
    )
    from ropeway_skip_stop_optimization.optimization.ddd.models import DddRouteDecision
    from ropeway_skip_stop_optimization.optimization.ddd.arc_flow_movement_master import build_ddd_arc_flow_movement_values
    scenario, problem = tiny_problem(horizon=80, starts=(0, 8))
    movement = problem.resolved_trajectory_problem.structural_movement_problem
    prepared = DddArcFlowProblemPreparer().build(problem)
    found = False
    for combo in product(*DddReferenceTrajectoryGenerator().generate(movement).by_cabin_id.values()):
        if not (combo[0].visits[0].decision is DddRouteDecision.STOP and combo[1].visits[0].decision is DddRouteDecision.SKIP):
            continue
        solution = DddReferenceSolution(combo)
        try:
            validate_ddd_reference_solution(movement, solution)
        except ValueError:
            continue
        expected, _ = fixed_ip(scenario, problem, solution)
        fixed = build_ddd_arc_flow_movement_values(prepared, solution)
        for profile in PASSENGER_PROFILES:
            model, _, _, _ = solve(prepared, Config.from_profile(profile), fixed=fixed)
            assert model.ObjVal == pytest.approx(expected, abs=1e-5)
        found = True
        break
    assert found


def test_ride_integrality_on_historical_odd_cycle():
    from test_optimization_ean_passenger_service import _odd_cycle_fixed_movement_case
    from ropeway_skip_stop_optimization.optimization.ean import EanPassengerCandidateBuilder, EanPassengerObjective
    from ropeway_skip_stop_optimization.optimization.ddd.models import (
        DddMovementCore, DddMovementState, DddRouteOption, DddRouteDecision,
        DddResource, DddResourceUsage, DddFixedStart,
    )
    from ropeway_skip_stop_optimization.optimization.ddd.trajectory_problem import DddTrajectoryProblem, DddFixedTrajectoryStartDomain
    from ropeway_skip_stop_optimization.optimization.ddd.fixed_k import DddFixedKTrajectoryProblem, DddFixedKOperatingMode, DddFixedKStartPolicy
    scenario, artifact, plan = _odd_cycle_fixed_movement_case()
    states = artifact.state_ids
    routes = tuple(DddRouteOption(
        id=f"{s}:{d.value}", from_state_id=s, to_state_id=states[(i+1) % 3], station_id=str(i),
        decision=d, duration_seconds=1, platform_entry_offset_seconds=.2 if d is DddRouteDecision.STOP else None,
        platform_exit_offset_seconds=.5 if d is DddRouteDecision.STOP else None,
        exit_switch_offset_seconds=.7, resource_usages=(DddResourceUsage(s, 0, 0),),
    ) for i, s in enumerate(states) for d in DddRouteDecision)
    core = DddMovementCore(scenario.id, 5, 5, tuple(DddMovementState(s) for s in states), routes,
                           tuple(DddResource(s, .1) for s in states))
    trajectory = DddTrajectoryProblem(core, DddFixedTrajectoryStartDomain(tuple(
        DddFixedStart(s.cabin_id, s.first_switch_id, 0, 6) for s in artifact.cabin_starts)))
    problem = DddFixedKTrajectoryProblem(trajectory, artifact,
        EanPassengerCandidateBuilder().build(scenario, artifact), EanPassengerObjective.WAITING_TIME,
        DddFixedKOperatingMode.SKIP_STOP, DddFixedKStartPolicy.LEGACY)
    prepared = DddArcFlowProblemPreparer().build(problem)
    decisions = {(t.cabin_id, v.visit_index): v.decision.value for t in plan.trajectories for v in t.visits}
    fixed = {a.id: float(a.option_id == f"{prepared.networks[a.cabin_id].state_ids[a.visit_index]}:{decisions[a.cabin_id,a.visit_index]}")
             for a in prepared.arcs}
    baseline, _, _, _ = solve(prepared, fixed=fixed)
    relaxed, _, _, _ = solve(prepared, fixed=fixed, lp=True)
    assert relaxed.ObjVal < baseline.ObjVal - 1e-5
    assert baseline.ObjVal == pytest.approx(12.5)
    assert relaxed.ObjVal == pytest.approx(12.25)
    for config in (Config(ride_integrality=True), Config(destination_flows=True), Config(ride_integrality=True, destination_flows=True)):
        model, _, passenger, _ = solve(prepared, config, fixed=fixed)
        assert model.ObjVal == pytest.approx(baseline.ObjVal, abs=1e-5)
        assert all(abs(v-round(v)) < 1e-5 for v in passenger.canonical_values().values())


@pytest.mark.parametrize("profile", ["legacy", "ride_integrality", "destination_flows"])
def test_native_incumbent_hook_exports_independent_certificate(profile):
    from test_optimization_ddd_cp_sat_integrated import tiny_problem
    from ropeway_skip_stop_optimization.optimization.ddd.arc_flow import DddFixedKArcFlowOptimizer, DddFixedKArcFlowSolveConfig
    from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_certificate import validate_ddd_cp_sat_incumbent
    _, problem = tiny_problem(horizon=80)
    objectives = []
    def hook(solution, counts, objective):
        assert all(abs(v-round(v)) < 1e-6 for v in counts.values())
        checked = validate_ddd_cp_sat_incumbent(problem, solution,
            {k: int(round(v)) for k, v in counts.items() if round(v) > 0}, provenance="callback_test")
        assert checked.objective == pytest.approx(objective, abs=1e-5)
        objectives.append(objective)
    result = DddFixedKArcFlowOptimizer(DddFixedKArcFlowSolveConfig(
        time_limit_seconds=10, threads=1, passenger_formulation=Config.from_profile(profile),
    )).solve(problem, incumbent_hook=hook)
    assert objectives
    assert min(objectives) == pytest.approx(result.validated_upper_bound, abs=1e-5)
