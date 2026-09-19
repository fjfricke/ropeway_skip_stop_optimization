"""Small equivalence gates for the new physical domain and fixed templates."""

from itertools import product
import json
from pathlib import Path

import pytest
from ortools.sat.python import cp_model

from ropeway_skip_stop_optimization.benchmarking.oip_pattern_waiting import (
    prepare_oip_pattern_waiting_pilot,
)
from ropeway_skip_stop_optimization.benchmarking.oip_calibration_reuse import (
    validate_evidence,
)
from ropeway_skip_stop_optimization.models import HeadwayRouteBehavior
from ropeway_skip_stop_optimization.optimization.oip.cp_sat import (
    build_oip_cp_sat_model,
    _extract_movement,
    _extract_passengers,
    _extract_cabin_types,
)
from ropeway_skip_stop_optimization.optimization.oip.validation import (
    validate_oip_certificate,
)


@pytest.fixture(scope="module")
def domain():
    return prepare_oip_pattern_waiting_pilot(
        maximum_wait_seconds=0, cabin_count=2, demand_total=12
    ).domain


def build(domain, specialize=True, reduce=True):
    return build_oip_cp_sat_model(
        domain,
        formulation="nowait_templates",
        objective="served",
        type_catalog="all_stop_bd_ce",
        fixed_type_counts={"all_stop": 1, "bd": 1, "ce": 0},
        specialize_fixed_types=specialize,
        reduce_headways=reduce,
    )


def solve(built):
    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = 1
    solver.parameters.max_time_in_seconds = 5
    status = solver.solve(built.model)
    assert status in (cp_model.OPTIMAL, cp_model.INFEASIBLE)
    if status == cp_model.OPTIMAL:
        movement, fleet = _extract_movement(built, solver)
        validate_oip_certificate(
            built.domain, movement, fleet, _extract_passengers(built, solver)
        )
    return solver, status


def test_geometric_checkpoints_and_removed_mechanisms(domain):
    for c in domain.artifact.headway_checkpoints:
        rule = domain.artifact.headway_rule_for_checkpoint(c)
        seconds = {
            rule.required_seconds(a, b)
            for a in HeadwayRouteBehavior
            for b in HeadwayRouteBehavior
        }
        assert len(seconds) == 1
        ticks = domain.grid.lower_tick(seconds.pop())
        assert ticks == (11667 if c.kind.value.startswith("platform") else 1053)
    assert (
        sum(
            c.kind.value == "platform_exit" for c in domain.artifact.headway_checkpoints
        )
        == 5
    )
    assert all(
        domain.artifact.initial_boundary_service_resource(s) is None
        for s in domain.artifact.circulation_state_ids
    )
    assert not any(
        c.kind.value == "service_mechanism" for c in domain.artifact.headway_checkpoints
    )


def test_same_served_optimum_and_smaller_fixed_build(domain):
    models = [
        build(domain, False, False),
        build(domain, True, False),
        build(domain, True, True),
    ]
    results = [solve(b) for b in models]
    assert len({s.objective_value for s, status in results}) == 1
    assert not models[-1].movement.cabin_type
    assert _extract_cabin_types(models[-1], results[-1][0]) == {0: "all_stop", 1: "bd"}
    assert len(models[-1].model.proto.variables) < len(models[0].model.proto.variables)
    assert models[-1].reduction_stats["shared_intervals"] > 0
    assert (
        models[-1].reduction_stats["passenger_candidates_after"]
        < models[0].reduction_stats["passenger_candidates_after"]
    )
    assert not any(c.has_int_prod() for m in models for c in m.model.proto.constraints)


def test_enumerated_boundary_positions_have_identical_feasibility(domain):
    """Exhaust every combination in a finite boundary-rich two-cabin domain."""
    models = [
        build(domain, False, False),
        build(domain, True, False),
        build(domain, True, True),
    ]
    states = []
    for b in models:
        results = {}
        for positions in product(
            (-83332, -1, 0, 1, 1052, 1053, 11666, 11667), repeat=2
        ):
            model = b.model.clone()
            for cabin, position in enumerate(positions):
                index = next(
                    i
                    for i, v in enumerate(model.proto.variables)
                    if v.name == f"shift[{cabin}]"
                )
                model.add(model.get_int_var_from_proto_index(index) == position)
            solver = cp_model.CpSolver()
            solver.parameters.num_search_workers = 1
            solver.parameters.max_time_in_seconds = 2
            status = solver.solve(model)
            assert status in (cp_model.OPTIMAL, cp_model.INFEASIBLE)
            results[positions] = status == cp_model.OPTIMAL
        states.append(results)
    assert states[0] == states[1] == states[2]
    assert set(states[0].values()) == {False, True}


@pytest.mark.parametrize(
    "field,value",
    [
        ("load_120", 2265),
        ("proven_infeasible_demand", 1890),
        ("capacity_proven", False),
        ("job_id", "oip_f2_k50"),
        ("contract_id", "unknown"),
        ("ticks_per_second", 1),
    ],
)
def test_calibration_rejects_wrong_contract_or_bracket(field, value):
    path = (
        Path(__file__).parents[1]
        / "results/oip_exact_phase_short_k62_20260918/references.json"
    )
    if not path.exists():
        pytest.skip("local historical proof absent")
    data = json.loads(path.read_text())
    data["evidence"][0][field] = value
    with pytest.raises(ValueError):
        validate_evidence(data, "f2")


def test_new_reference_and_trial_share_comparison_identity():
    from ropeway_skip_stop_optimization.optimization.oip import OipOperation
    from ropeway_skip_stop_optimization.optimization.oip.phase_reference import (
        regular_movement,
    )

    trial = prepare_oip_pattern_waiting_pilot(
        maximum_wait_seconds=0, cabin_count=2, demand_total=12
    ).domain
    reference = prepare_oip_pattern_waiting_pilot(
        maximum_wait_seconds=0,
        cabin_count=2,
        demand_total=12,
        operation=OipOperation.ALL_STOP,
    ).domain
    assert trial.comparison_fingerprint == reference.comparison_fingerprint
    assert trial.fingerprint != reference.fingerprint
    assert regular_movement(reference, 0) == regular_movement(trial, 0)


def test_early_stop_is_inside_wall_budget(tmp_path, monkeypatch):
    from test_oip_fixed_mix_campaign import runner
    from types import SimpleNamespace

    m = runner()
    captured = {}

    def supervise(command, directory, **kwargs):
        captured.update(kwargs)
        captured["command"] = command
        return {"exit_code": 0}

    monkeypatch.setattr(m, "supervise", supervise)
    monkeypatch.setattr(m.time, "time", lambda: 1000)
    m._run_one(
        ["python", "trial.py"], tmp_path, 300, SimpleNamespace(memory_limit_gib=32)
    )
    assert captured["seconds"] == 300
    assert captured["global_deadline"] == 1300
    assert captured["command"][-2:] == ["--deadline-unix", "1300"]


def test_expired_preparation_does_not_invoke_solver(domain, monkeypatch):
    import ropeway_skip_stop_optimization.optimization.oip.runner as r

    def forbidden(*args, **kwargs):
        raise AssertionError("solver must not run")

    monkeypatch.setattr(r, "solve_oip_cp_sat", forbidden)
    monkeypatch.setattr(r.time, "time", lambda: 1000)
    with pytest.raises(TimeoutError, match="no feasibility conclusion"):
        r.run_oip(domain, r.OipRunConfig(time_limit_seconds=300, deadline_unix=1009))


def test_stop_skip_same_headway_can_use_removed_special_protection(domain):
    """Two mixed passages two seconds apart pass geometry but not old STOP headway."""
    old = prepare_oip_pattern_waiting_pilot(
        maximum_wait_seconds=0, cabin_count=2, demand_total=12, legacy_headways=True
    ).domain
    new_c = next(
        c for c in domain.artifact.headway_checkpoints if c.kind.value == "exit_switch"
    )
    old_c = next(c for c in old.artifact.headway_checkpoints if c.id == new_c.id)
    a, b = HeadwayRouteBehavior.SERVICE, HeadwayRouteBehavior.BYPASS
    assert (
        domain.artifact.headway_rule_for_checkpoint(new_c).required_seconds(a, b) <= 2
    )
    assert old.artifact.headway_rule_for_checkpoint(old_c).required_seconds(a, b) > 2
    assert (
        domain.artifact.headway_rule_for_checkpoint(new_c).required_seconds(a, b)
        > 1.052
    )
    platform = next(
        c
        for c in domain.artifact.headway_checkpoints
        if c.kind.value == "platform_entry"
    )
    assert (
        domain.artifact.headway_rule_for_checkpoint(platform).required_seconds(a, a)
        > 11.666
    )


def test_mixed_timetable_admitted_only_by_new_headways(domain):
    from ropeway_skip_stop_optimization.optimization.oip.validation import (
        validate_oip_movement_certificate,
    )

    built = build_oip_cp_sat_model(
        domain,
        formulation="nowait_templates",
        objective="served",
        type_catalog="all_stop_bd_ce",
        fixed_type_counts={"all_stop": 0, "bd": 1, "ce": 1},
    )
    for cabin, position in ((0, 0), (1, -2000)):
        index = next(
            i
            for i, v in enumerate(built.model.proto.variables)
            if v.name == f"shift[{cabin}]"
        )
        built.model.add(built.model.get_int_var_from_proto_index(index) == position)
    solver, status = solve(built)
    assert status == cp_model.OPTIMAL
    movement, fleet = _extract_movement(built, solver)
    old = prepare_oip_pattern_waiting_pilot(
        maximum_wait_seconds=0, cabin_count=2, demand_total=12, legacy_headways=True
    ).domain
    with pytest.raises(ValueError):
        validate_oip_movement_certificate(old, movement, fleet)


def test_absolute_deadline_expires_during_build(domain, monkeypatch):
    import ropeway_skip_stop_optimization.optimization.oip.cp_sat as cp

    monkeypatch.setattr(cp, "time", lambda: 2000)
    result = cp.solve_oip_cp_sat(
        domain,
        cp.OipCpSatConfig(
            time_limit_seconds=300,
            search_deadline_unix=1999,
            formulation="nowait_templates",
            objective="served",
            type_catalog="all_stop_bd_ce",
            fixed_type_counts={"all_stop": 1, "bd": 1, "ce": 0},
        ),
    )
    assert result.status == "unknown"
    assert result.solver_status == "BUILD_TIME_LIMIT"
    assert result.best_bound is None and result.served_passengers is None


def test_operational_end_neighbors_match_full_protection(domain):
    """Cross the final passage activation by one tick; recheck exported movement."""
    full, reduced = build(domain, True, False), build(domain, True, True)
    original, status = solve(full)
    assert status == cp_model.OPTIMAL
    shift_index = next(i for i, v in enumerate(full.model.proto.variables) if v.name == 'shift[0]')
    shift = original.value(full.model.get_int_var_from_proto_index(shift_index))
    movement, _ = _extract_movement(full, original)
    last = next(t for t in movement.trajectories if t.cabin_id == 0).visits[-1]
    event_offset = round(last.switch_time_seconds * 1000) + shift
    boundary = event_offset - domain.grid.upper_tick(domain.artifact.config.operational_end_seconds)
    for delta in (-1, 0, 1, 1052, 1053):
        answers = []
        for template in (full, reduced):
            b = replace_built_model(template)
            index = next(i for i, v in enumerate(b.model.proto.variables) if v.name == 'shift[0]')
            b.model.add(b.model.get_int_var_from_proto_index(index) == boundary + delta)
            solver, result = solve(b)
            answers.append((result, solver.objective_value if result == cp_model.OPTIMAL else None))
        assert answers[0] == answers[1]


def replace_built_model(built):
    from dataclasses import replace
    return replace(built, model=built.model.clone())
