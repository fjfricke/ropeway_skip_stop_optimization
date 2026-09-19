"""Boundary and certificate regressions for the independent No-Wait builder."""

from pathlib import Path

import pytest
from ortools.sat.python import cp_model
from test_oip_pattern_waiting import _small_domain

from ropeway_skip_stop_optimization.optimization.oip.cp_sat import (
    _apply_oip_cp_sat_hint,
    _extract_movement,
    _extract_passengers,
    build_oip_cp_sat_model,
)
from ropeway_skip_stop_optimization.optimization.oip.validation import (
    validate_oip_certificate,
)


@pytest.mark.parametrize(
    "type_id", ["all_stop", "alternating_phase_0", "alternating_phase_1"]
)
@pytest.mark.parametrize("boundary", ["entry", "exit", "rope_first", "rope_last"])
def test_template_initial_boundaries(type_id, boundary):
    domain = _small_domain(0.0)
    built = build_oip_cp_sat_model(
        domain,
        type_catalog="all_stop_alternating",
        formulation="nowait_templates",
        objective="served",
    )
    built.model.add(built.movement.cabin_type[0, type_id] == 1)
    timing = {t.switch_id: t for t in domain.artifact.timings}
    previous = timing[domain.artifact.circulation_state_ids[-1]]
    key = (0, 0)
    if boundary == "entry":
        built.model.add(built.movement.switch_time[key] == 0)
    elif boundary == "exit":
        built.model.add(built.movement.exit_time[key] == 0)
    else:
        tick = (
            1
            if boundary == "rope_last"
            else domain.grid.lower_tick(previous.rope_to_next_switch_seconds) - 1
        )
        built.model.add(built.movement.switch_time[key] == tick)
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 5
    solver.parameters.num_search_workers = 1
    assert solver.solve(built.model) in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    movement, fleet = _extract_movement(built, solver)
    validate_oip_certificate(
        domain, movement, fleet, _extract_passengers(built, solver)
    )


@pytest.mark.parametrize(
    "family,total,catalog,served",
    [
        ("f2", 2266, "all_stop_bd_ce", 1902),
        ("f3", 5430, "all_stop_alternating", 4549),
    ],
)
def test_saved_k62_reference_is_representable(family, total, catalog, served):
    """Optional local integration test; saved run artifacts are not source fixtures."""
    from ropeway_skip_stop_optimization.benchmarking.oip_pattern_waiting import (
        prepare_oip_pattern_waiting_pilot,
    )
    from ropeway_skip_stop_optimization.optimization.oip.runner import (
        _read_portable_checkpoint,
    )

    path = (
        Path(__file__).resolve().parents[1]
        / "results/oip_nowait_formulation_comparison_f2_f3_20260918_v2/references"
        / family
    )
    if not (path / "result.json").exists():
        pytest.skip("Local saved reference is unavailable")
    domain = prepare_oip_pattern_waiting_pilot(
        maximum_wait_seconds=0, cabin_count=62, demand_total=total, demand_family=family,
        legacy_headways=True
    ).domain
    certificate = _read_portable_checkpoint(path, domain)
    built = build_oip_cp_sat_model(
        domain, type_catalog=catalog, formulation="nowait_templates", objective="served"
    )
    _apply_oip_cp_sat_hint(built, *certificate)
    # Test-only fixation: prove that the *entire* seed is in the model domain.
    # Production hints remain nonbinding.
    hint = built.model.proto.solution_hint
    for index, value in zip(list(hint.vars), list(hint.values)):
        built.model.add(built.model.get_int_var_from_proto_index(index) == value)
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 30
    solver.parameters.num_search_workers = 1
    assert solver.solve(built.model) in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    movement, fleet = _extract_movement(built, solver)
    metrics = validate_oip_certificate(
        domain, movement, fleet, _extract_passengers(built, solver)
    )
    assert metrics.served == served
