
import pytest
from ortools.sat.python import cp_model
from test_oip_pattern_waiting import _small_domain

from ropeway_skip_stop_optimization.optimization.oip.cp_sat import (
    OipCpSatConfig,
    _extract_cabin_types,
    _extract_movement,
    build_oip_cp_sat_model,
    solve_oip_cp_sat,
)


def _solve_catalog(catalog: str, cabins: int = 1):
    domain = _small_domain(0.0, cabin_count=cabins)
    built = build_oip_cp_sat_model(domain, movement_only=True, type_catalog=catalog)
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 5
    solver.parameters.num_search_workers = 1
    return domain, built, solver


def test_catalog_and_fixed_patterns_are_exclusive() -> None:
    domain = _small_domain(0.0)
    stations = tuple(dict.fromkeys(t.station_id for t in domain.artifact.timings))
    with pytest.raises(ValueError, match="mutually exclusive"):
        build_oip_cp_sat_model(
            domain, movement_only=True, fixed_stop_patterns=(stations,),
            type_catalog="all_stop_alternating",
        )
    with pytest.raises(ValueError, match="mutually exclusive"):
        OipCpSatConfig(
            fixed_stop_patterns=(stations,), type_catalog="all_stop_alternating"
        ).validate()


def test_all_stop_member_reproduces_all_stop_visits() -> None:
    _, built, solver = _solve_catalog("all_stop_alternating")
    built.model.add(built.movement.cabin_type[0, "all_stop"] == 1)
    assert solver.solve(built.model) in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    movement, _ = _extract_movement(built, solver)
    assert all(v.decision.value == "stop" for t in movement.trajectories for v in t.visits)
    assert _extract_cabin_types(built, solver) == {0: "all_stop"}


@pytest.mark.parametrize("phase,expected", [(0, 0), (1, 1)])
def test_alternating_type_uses_global_visit_parity(phase: int, expected: int) -> None:
    _, built, solver = _solve_catalog("all_stop_alternating")
    type_id = f"alternating_phase_{phase}"
    built.model.add(built.movement.cabin_type[0, type_id] == 1)
    assert solver.solve(built.model) in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    movement, _ = _extract_movement(built, solver)
    skippable = {
        (v.cabin_id, v.visit_index)
        for v in built.domain.artifact.switch_visits
        if next(t for t in built.domain.artifact.timings if t.switch_id == v.switch_id).skip_allowed
    }
    visits = [v for t in movement.trajectories for v in t.visits if (v.cabin_id, v.visit_index) in skippable]
    assert visits
    assert all((v.decision.value == "stop") == (v.visit_index % 2 == expected) for v in visits)


@pytest.mark.parametrize("phase", [0, 1])
def test_alternating_phase_controls_the_pre_boundary_rope_visit(phase: int) -> None:
    domain, built, solver = _solve_catalog("all_stop_alternating")
    key = next(iter(built.movement.rope_selected))
    built.model.add(built.movement.rope_selected[key] == 1)
    built.model.add(built.movement.cabin_type[0, f"alternating_phase_{phase}"] == 1)
    assert solver.solve(built.model) in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    previous_index = key[1] - 1
    previous_switch = domain.artifact.circulation_state_ids[
        previous_index % len(domain.artifact.circulation_state_ids)
    ]
    previous_timing = next(
        item for item in domain.artifact.timings if item.switch_id == previous_switch
    )
    expected_service = (
        True
        if not previous_timing.skip_allowed
        else previous_index % 2 == phase
    )
    _, fleet = _extract_movement(built, solver)
    assert fleet.initial_states[0].previous_service is expected_service


def test_bd_ce_catalog_counts_are_solver_decisions() -> None:
    domain, built, solver = _solve_catalog("all_stop_bd_ce", cabins=2)
    built.model.add(built.movement.cabin_type[0, "bd"] == 1)
    built.model.add(built.movement.cabin_type[1, "ce"] == 1)
    assert solver.solve(built.model) in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    assert _extract_cabin_types(built, solver) == {0: "bd", 1: "ce"}
    movement, _ = _extract_movement(built, solver)
    timing = {item.switch_id: item for item in domain.artifact.timings}
    allowed = {0: {"S1", "S3"}, 1: {"S2", "S4"}}
    for trajectory in movement.trajectories:
        for visit in trajectory.visits:
            if timing[visit.switch_id].skip_allowed:
                assert (visit.decision.value == "stop") == (
                    visit.station_id in allowed[trajectory.cabin_id]
                )


def test_all_stop_hint_does_not_fix_the_cabin_type() -> None:
    domain = _small_domain(0.0)
    stations = tuple(dict.fromkeys(t.station_id for t in domain.artifact.timings))
    seed = solve_oip_cp_sat(
        domain,
        OipCpSatConfig(
            time_limit_seconds=5,
            workers=1,
            fixed_stop_patterns=(stations,),
        ),
    )
    assert seed.movement_plan is not None and seed.passenger_plan is not None
    built = build_oip_cp_sat_model(
        domain, movement_only=False, type_catalog="all_stop_alternating"
    )
    from ropeway_skip_stop_optimization.optimization.oip.cp_sat import (
        _apply_oip_cp_sat_hint,
    )
    _apply_oip_cp_sat_hint(
        built, seed.movement_plan, seed.fleet_plan, seed.passenger_plan
    )
    built.model.add(built.movement.cabin_type[0, "alternating_phase_0"] == 1)
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 5
    assert solver.solve(built.model) in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    assert _extract_cabin_types(built, solver) == {0: "alternating_phase_0"}


@pytest.mark.parametrize("encoding", ["od_inventory", "groups"])
def test_type_catalog_supports_both_passenger_encodings(encoding: str) -> None:
    domain = _small_domain(0.0)
    result = solve_oip_cp_sat(
        domain,
        OipCpSatConfig(
            time_limit_seconds=5,
            workers=1,
            type_catalog="all_stop_alternating",
            passenger_encoding=encoding,
        ),
    )
    assert result.movement_plan is not None
    assert result.passenger_plan is not None
    assert sum(result.type_counts.values()) == 1


def test_lexicographic_bounds_hide_journey_bound_until_primary_is_closed() -> None:
    from ropeway_skip_stop_optimization.optimization.oip.runner import (
        _lexicographic_bound_fields,
    )

    domain = _small_domain(0.0)
    total = sum(item.count for item in domain.scenario.demands)
    horizon = domain.grid.upper_tick(domain.artifact.config.horizon_seconds)
    weight = total * horizon + 1
    open_primary = _lexicographic_bound_fields(
        domain, {"lb": 0, "unserved": 1}
    )
    assert open_primary["journey_time_lower_bound"] is None
    closed_primary = _lexicographic_bound_fields(
        domain, {"lb": weight, "unserved": 1}
    )
    assert closed_primary["served_lower_bound"] == total - 1
    assert closed_primary["served_upper_bound"] == total - 1
    assert closed_primary["journey_time_lower_bound"] == 0


@pytest.mark.parametrize("encoding", ["od_inventory", "groups"])
def test_served_objective_builds_no_time_quantity_products(encoding: str) -> None:
    domain = _small_domain(0.0)
    served = build_oip_cp_sat_model(
        domain,
        type_catalog="all_stop_alternating",
        passenger_encoding=encoding,
        objective="served",
    )
    lexicographic = build_oip_cp_sat_model(
        domain,
        type_catalog="all_stop_alternating",
        passenger_encoding=encoding,
        objective="lexicographic",
    )
    assert not any(item.has_int_prod() for item in served.model.proto.constraints)
    assert any(item.has_int_prod() for item in lexicographic.model.proto.constraints)


@pytest.mark.parametrize("encoding", ["od_inventory", "groups"])
def test_nowait_templates_and_ean_have_same_small_served_optimum(encoding: str) -> None:
    domain = _small_domain(0.0)
    results = []
    for formulation in ("ean", "nowait_templates"):
        result = solve_oip_cp_sat(
            domain,
            OipCpSatConfig(
                time_limit_seconds=10,
                workers=1,
                type_catalog="all_stop_alternating",
                passenger_encoding=encoding,
                formulation=formulation,
                objective="served",
            ),
        )
        assert result.solver_status == "OPTIMAL"
        assert result.presolved_model_stats is not None
        assert "Presolved optimization model" in result.presolved_model_stats
        results.append(result.served_passengers)
    assert results[0] == results[1]


def test_nowait_template_is_smaller_and_keeps_global_alternation() -> None:
    domain = _small_domain(0.0)
    ean = build_oip_cp_sat_model(
        domain,
        type_catalog="all_stop_alternating",
        formulation="ean",
        objective="served",
    )
    template = build_oip_cp_sat_model(
        domain,
        type_catalog="all_stop_alternating",
        formulation="nowait_templates",
        objective="served",
    )
    assert len(template.model.proto.variables) < len(ean.model.proto.variables)
    assert len(template.model.proto.constraints) < len(ean.model.proto.constraints)
    template.model.add(
        template.movement.cabin_type[0, "alternating_phase_1"] == 1
    )
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 5
    assert solver.solve(template.model) in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    movement, _ = _extract_movement(template, solver)
    timing = {item.switch_id: item for item in domain.artifact.timings}
    visits = [
        visit
        for trajectory in movement.trajectories
        for visit in trajectory.visits
        if timing[visit.switch_id].skip_allowed
    ]
    assert visits
    assert all(
        (visit.decision.value == "stop") == (visit.visit_index % 2 == 1)
        for visit in visits
    )


def test_ean_and_template_certificates_are_mutual_nonbinding_hints() -> None:
    domain = _small_domain(0.0)
    seeds = {}
    for formulation in ("ean", "nowait_templates"):
        seeds[formulation] = solve_oip_cp_sat(
            domain,
            OipCpSatConfig(
                time_limit_seconds=5,
                workers=1,
                type_catalog="all_stop_alternating",
                formulation=formulation,
                objective="served",
            ),
        )
    for source, target in (("ean", "nowait_templates"), ("nowait_templates", "ean")):
        seed = seeds[source]
        result = solve_oip_cp_sat(
            domain,
            OipCpSatConfig(
                time_limit_seconds=5,
                workers=1,
                type_catalog="all_stop_alternating",
                formulation=target,
                objective="served",
                initial_movement_plan=seed.movement_plan,
                initial_fleet_plan=seed.fleet_plan,
                initial_passenger_plan=seed.passenger_plan,
            ),
        )
        assert result.solver_status == "OPTIMAL"
        assert result.served_passengers == seed.served_passengers


def test_nowait_template_rejects_unsupported_contracts() -> None:
    with pytest.raises(ValueError, match="No-Wait templates"):
        solve_oip_cp_sat(
            _small_domain(120.0),
            OipCpSatConfig(
                time_limit_seconds=1,
                type_catalog="all_stop_alternating",
                formulation="nowait_templates",
                objective="served",
            ),
        )
    with pytest.raises(ValueError, match="require a type catalog"):
        OipCpSatConfig(
            formulation="nowait_templates", objective="served"
        ).validate()


def test_template_fixed_counts_are_exact_and_positions_remain_free():
    domain = _small_domain(0.0, cabin_count=2)
    counts = {'all_stop': 0, 'alternating_phase_0': 1, 'alternating_phase_1': 1}
    built = build_oip_cp_sat_model(domain, type_catalog='all_stop_alternating',
        fixed_type_counts=counts, formulation='nowait_templates', objective='served')
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 5
    solver.parameters.num_search_workers = 1
    assert solver.solve(built.model) in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    actual = _extract_cabin_types(built, solver)
    assert {p: list(actual.values()).count(p) for p in counts} == counts
    with pytest.raises(ValueError, match='sum to K'):
        build_oip_cp_sat_model(domain, type_catalog='all_stop_alternating',
            fixed_type_counts={**counts, 'all_stop': 1},
            formulation='nowait_templates', objective='served')
