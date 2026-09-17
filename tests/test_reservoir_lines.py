from dataclasses import replace
import sys
from time import perf_counter

from ortools.sat.python import cp_model
import pytest

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
from test_optimization_ddd_reservoir_cp_sat import problem, trip  # noqa: E402

from ropeway_skip_stop_optimization.optimization.ddd.reservoir_cp_sat_certificate import (  # noqa: E402
    DddReservoirCpPlan,
    DddReservoirCpTrip,
    validate_reservoir_cp_plan,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_lines import (  # noqa: E402
    ReservoirLineCatalogProfile,
    ReservoirLineConfig,
    ReservoirLineFormulation,
    ReservoirLineMode,
    ReservoirLineOptimizer,
    ReservoirLinePreparation,
    ReservoirLineVariant,
    UniformLengthScaling,
    prepare_line_problem,
    saturated_all_stop_reference,
    scale_uniform_rope_length,
    with_saturation_time_contract,
)
from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_integrated import (  # noqa: E402
    DddIntegratedCpSatConfig,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_cp_sat import (  # noqa: E402
    DddReservoirCpObjective,
    DddReservoirCpSatOptimizer,
)
from ropeway_skip_stop_optimization.optimization.ddd.trajectory_column_generation import (  # noqa: E402
    DddTrajectoryWaitingDomain,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_lines.certificate import (  # noqa: E402
    add_line_plan_hint,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_lines.cp_model import (  # noqa: E402
    build_reservoir_line_model,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_lines.dispatch_domains import (  # noqa: E402
    TickInterval,
    complement_closed,
    forbidden_delta_for_half_open_intervals,
    merge_closed,
)
from ropeway_skip_stop_optimization.optimization.ean.models import EanDemandGroup  # noqa: E402
from ropeway_skip_stop_optimization.optimization.ddd.time_ticks import (  # noqa: E402
    ddd_seconds_to_tick,
)

T = 1_000_000


def config(**kwargs):
    return ReservoirLineConfig(
        dispatch_window_end_seconds=kwargs.pop("dispatch_window_end_seconds", 3),
        maximum_cabins=kwargs.pop("maximum_cabins", None),
        time_limit_seconds=kwargs.pop("time_limit_seconds", 5),
        workers=kwargs.pop("workers", 1),
        **kwargs,
    )


def _direct_pair_conflict(first, second, delta):
    for a in first.resource_intervals:
        for b in second.resource_intervals:
            if a.resource_id == b.resource_id and (
                a.start_tick < delta + b.end_tick
                and delta + b.start_tick < a.end_tick
            ):
                return True
    for state_a, tick_a in first.state_event_offsets:
        for state_b, tick_b in second.state_event_offsets:
            if state_a == state_b and tick_a == delta + tick_b:
                return True
    return False


def test_integer_interval_algebra_keeps_touching_boundaries_feasible():
    assert forbidden_delta_for_half_open_intervals(0, 3, 0, 2) == TickInterval(-1, 2)
    assert merge_closed(((3, 4), (1, 2), (7, 7))) == (
        TickInterval(1, 4), TickInterval(7, 7)
    )


def test_od_endpoint_catalog_is_deterministic_and_contains_only_demand_masks():
    from ropeway_skip_stop_optimization.optimization.ddd.reservoir_lines.catalog import line_patterns

    p = replace(
        problem(),
        demand_groups=(
            EanDemandGroup("ab", "A", "B", 0, 1),
        ),
    )
    first = line_patterns(p, ReservoirLineCatalogProfile.OD_ENDPOINTS_V1)
    second = line_patterns(p, ReservoirLineCatalogProfile.OD_ENDPOINTS_V1)
    assert first == second
    # The tiny fixture contains only A and B, so its sole OD-endpoint mask is
    # identical to All-Stop and must be deduplicated.
    assert [item.id for item in first] == ["all_stop"]
    assert complement_closed(((2, 3), (6, 9)), 1, 7) == (
        TickInterval(1, 1), TickInterval(4, 5)
    )


def test_positive_dispatch_delta_allows_reversed_downstream_resource_order():
    from types import SimpleNamespace
    from ropeway_skip_stop_optimization.optimization.ddd.reservoir_lines.preparation import (
        RelativeResourceInterval, _pair_domain,
    )
    # The first cabin enters the port first, then takes the slower STOP path.
    # The later cabin uses the bypass and reaches the shared merge first.
    def template(name, merge_start):
        return SimpleNamespace(
            id=name, state_event_offsets=(),
            resource_intervals=(
                RelativeResourceInterval("port", 0, 2, 0, name),
                RelativeResourceInterval("merge", merge_start, merge_start+2, 0, name),
            ),
        )
    stop, skip = template("stop", 10), template("skip", 3)
    allowed = _pair_domain(stop, skip, 20).allowed_delta
    for delta in range(1, 21):
        assert any(i.lower <= delta <= i.upper for i in allowed) == (
            not _direct_pair_conflict(stop, skip, delta)
        )
    assert any(i.lower <= 2 <= i.upper for i in allowed)
    assert 2 + 3 + 2 <= 10  # second cabin clears merge before first enters
    assert not any(i.lower <= 7 <= i.upper for i in allowed)  # actual collision


def test_prepared_delta_domains_equal_direct_resource_and_state_enumeration():
    p = problem(dispatch_end_seconds=0.000005, dispatch_step_seconds=0.000001)
    prepared = prepare_line_problem(
        p,
        config(
            dispatch_window_end_seconds=0.000005,
            variant=ReservoirLineVariant.DISPATCH_DOMAINS,
            preparation=ReservoirLinePreparation.LEGACY_EAGER,
            formulation=ReservoirLineFormulation.LEGACY_TEMPLATES,
        ),
    )
    for first in prepared.templates:
        for second in prepared.templates:
            allowed = prepared.pair_domains_by_id[first.id, second.id].allowed_delta
            for delta in range(1, prepared.dispatch_window_end_tick + 1):
                in_domain = any(item.lower <= delta <= item.upper for item in allowed)
                assert in_domain is (not _direct_pair_conflict(first, second, delta))


def test_reservoir_line_defaults_use_shared_rounds_interval_model():
    c = ReservoirLineConfig(dispatch_window_end_seconds=3)
    assert c.variant is ReservoirLineVariant.INTERVALS
    assert c.preparation is ReservoirLinePreparation.ENCODING_SPECIFIC
    assert c.formulation is ReservoirLineFormulation.SHARED_ROUNDS


def test_hard_deadline_accounts_for_preparation_and_model_build():
    result, plan = ReservoirLineOptimizer(config()).solve(
        problem(), hard_deadline=perf_counter() - 1
    )
    assert result["solver_status"] == "NOT_RUN"
    assert result["termination_reason"] == "BUILD_TIME_LIMIT"
    assert result["solve_seconds"] == 0
    assert plan is None


def test_elapsed_deadline_preserves_a_validated_line_reference():
    p = problem()
    reference = DddReservoirCpPlan(
        (trip(routes=("A_stop", "B_stop") * 4),), {}
    )
    result, plan = ReservoirLineOptimizer(config()).solve(
        p, reference_plan=reference, hard_deadline=perf_counter() - 1
    )
    assert result["solver_status"] == "NOT_RUN"
    assert result["reference_status"] == "hinted"
    assert plan == reference


def test_uniform_length_scaling_changes_only_route_durations_and_identity():
    p = problem()
    scaled = scale_uniform_rope_length(
        p, UniformLengthScaling(1.0, 2.0, 1.0)
    )
    assert scaled.fingerprint != p.fingerprint
    assert scaled.movement_core.scenario_id.endswith("__rope_2m")
    for before, after in zip(
        p.resolved_core.route_options, scaled.resolved_core.route_options, strict=True
    ):
        assert after.duration_tick == before.duration_tick + T
        assert after.resource_usages == before.resource_usages
        assert (
            after.platform_entry_offset_seconds
            == before.platform_entry_offset_seconds
        )
        assert (
            after.platform_exit_offset_seconds
            == before.platform_exit_offset_seconds
        )
        assert after.exit_switch_offset_seconds == before.exit_switch_offset_seconds


def test_saturation_contract_scales_fleet_and_preserves_service_deadline():
    p = problem()
    scaled = scale_uniform_rope_length(
        p, UniformLengthScaling(1.0, 2.0, 1.0)
    )
    reference = saturated_all_stop_reference(scaled)
    assert reference.cycle_tick == 6 * T
    assert reference.binding_headway_tick == T
    assert reference.saturated_cabins == 6
    assert reference.experimental_fleet_cap == 8
    contracted = with_saturation_time_contract(scaled, reference)
    assert contracted.available_fleet_count == 8
    assert contracted.dispatch_end_seconds == 6
    assert (
        contracted.resolved_core.passenger_service_end_tick
        == p.resolved_core.passenger_service_end_tick
    )
    assert contracted.resolved_core.operational_end_tick == (
        p.resolved_core.passenger_service_end_tick + 6 * T
    )


def test_encoding_specific_interval_preparation_omits_unused_pair_domains():
    p = problem(dispatch_end_seconds=3, available_fleet_count=2)
    legacy_config = config(
        maximum_cabins=2,
        variant=ReservoirLineVariant.INTERVALS,
        preparation=ReservoirLinePreparation.LEGACY_EAGER,
    )
    compact_config = replace(
        legacy_config, preparation=ReservoirLinePreparation.ENCODING_SPECIFIC
    )
    legacy = prepare_line_problem(p, legacy_config)
    compact = prepare_line_problem(p, compact_config)
    assert legacy.pair_domains
    assert not compact.pair_domains
    assert compact.stats["potential_template_pairs"] == len(compact.templates) ** 2
    assert compact.stats["pair_domains_materialized"] is False
    assert legacy.templates == compact.templates
    legacy_model = build_reservoir_line_model(p, legacy, legacy_config)
    compact_model = build_reservoir_line_model(p, compact, compact_config)
    assert str(legacy_model.model.proto) == str(compact_model.model.proto)


@pytest.mark.parametrize(
    "formulation",
    (
        ReservoirLineFormulation.LEGACY_TEMPLATES,
        ReservoirLineFormulation.SHARED_ROUNDS,
        ReservoirLineFormulation.SHARED_RIDES,
    ),
)
def test_line_formulations_have_same_tiny_optimum_and_validate(formulation):
    p = problem(
        dispatch_end_seconds=3,
        dispatch_step_seconds=1,
        available_fleet_count=2,
    )
    result, plan = ReservoirLineOptimizer(
        config(
            maximum_cabins=2,
            fixed_cabins=2,
            variant=ReservoirLineVariant.INTERVALS,
            preparation=ReservoirLinePreparation.ENCODING_SPECIFIC,
            formulation=formulation,
        )
    ).solve(p)
    assert result["proven_optimal"]
    assert result["validated_served"] == 1
    assert validate_reservoir_cp_plan(p, plan).served == 1


@pytest.mark.parametrize(
    "formulation",
    (
        ReservoirLineFormulation.SHARED_ROUNDS,
        ReservoirLineFormulation.SHARED_RIDES,
    ),
)
def test_shared_formulations_reproduce_fixed_multilap_movement(formulation):
    p = problem(available_fleet_count=1)
    movement = DddReservoirCpPlan(
        (trip(routes=("A_stop", "B_stop") * 4),), {}
    )
    result, plan = ReservoirLineOptimizer(
        config(
            maximum_cabins=1,
            variant=ReservoirLineVariant.INTERVALS,
            preparation=ReservoirLinePreparation.ENCODING_SPECIFIC,
            formulation=formulation,
        )
    ).solve(p, fixed_movement_plan=movement)
    assert result["proven_optimal"]
    assert result["validated_served"] == 1
    assert plan.trips == movement.trips


def test_shared_formulations_match_legacy_for_every_tiny_single_cabin_template():
    p = problem(available_fleet_count=1)
    base_config = config(
        maximum_cabins=1,
        variant=ReservoirLineVariant.INTERVALS,
        preparation=ReservoirLinePreparation.ENCODING_SPECIFIC,
        formulation=ReservoirLineFormulation.LEGACY_TEMPLATES,
    )
    prepared = prepare_line_problem(p, base_config)
    for template in prepared.templates:
        dispatch = template.minimum_dispatch_tick
        movement = DddReservoirCpPlan(
            (
                DddReservoirCpTrip(
                    0,
                    template.route_option_ids,
                    tuple(dispatch + visit.start_tick for visit in template.visits),
                    (0,) * len(template.visits),
                    dispatch + template.duration_tick,
                ),
            ),
            {},
        )
        expected = None
        for formulation in (
            ReservoirLineFormulation.LEGACY_TEMPLATES,
            ReservoirLineFormulation.SHARED_ROUNDS,
            ReservoirLineFormulation.SHARED_RIDES,
        ):
            result, plan = ReservoirLineOptimizer(
                replace(base_config, formulation=formulation)
            ).solve(p, fixed_movement_plan=movement)
            assert result["proven_optimal"]
            assert plan.trips == movement.trips
            observed = result["validated_served"]
            expected = observed if expected is None else expected
            assert observed == expected


def test_shared_rounds_reduce_tiny_interval_and_passenger_copies():
    p = problem(available_fleet_count=1)
    base_config = config(
        maximum_cabins=1,
        variant=ReservoirLineVariant.INTERVALS,
        preparation=ReservoirLinePreparation.ENCODING_SPECIFIC,
        formulation=ReservoirLineFormulation.LEGACY_TEMPLATES,
    )
    prepared = prepare_line_problem(p, base_config)
    legacy = build_reservoir_line_model(p, prepared, base_config)
    compact = build_reservoir_line_model(
        p,
        prepared,
        replace(
            base_config, formulation=ReservoirLineFormulation.SHARED_ROUNDS
        ),
    )
    assert compact.stats["native_resource_intervals"] < legacy.stats[
        "native_resource_intervals"
    ]
    assert compact.stats["integer_ride_variables"] < legacy.stats[
        "integer_ride_variables"
    ]


def test_shared_formulations_require_interval_resources():
    with pytest.raises(ValueError, match="require intervals"):
        config(
            formulation=ReservoirLineFormulation.SHARED_ROUNDS,
            variant=ReservoirLineVariant.DISPATCH_DOMAINS,
        ).validate(2)


def test_exact_line_model_matches_tiny_capacity_optimum_and_validates():
    p = problem(
        dispatch_end_seconds=3,
        dispatch_step_seconds=1,
        available_fleet_count=2,
    )
    result, plan = ReservoirLineOptimizer(
        config(maximum_cabins=2, fixed_cabins=2)
    ).solve(p)
    assert result["solver_status"] == "OPTIMAL"
    assert result["validated_served"] == 1
    assert result["validated_unserved"] == 0
    assert result["used_fleet"] == 2
    assert validate_reservoir_cp_plan(p, plan).served == 1
    dispatches = [trip_.switch_ticks[0] for trip_ in plan.trips]
    assert 0 <= dispatches[0] < dispatches[1] <= 3 * T


def test_first_dispatch_is_a_free_phase_within_warmup():
    p = problem(
        dispatch_end_seconds=3,
        dispatch_step_seconds=1,
        available_fleet_count=1,
    )
    movement = DddReservoirCpPlan(
        (trip(dispatch=1, routes=("A_stop", "B_stop") * 4),), {}
    )
    result, plan = ReservoirLineOptimizer(
        config(maximum_cabins=1, fixed_cabins=1)
    ).solve(p, fixed_movement_plan=movement)
    assert result["proven_optimal"]
    assert plan.trips == movement.trips
    assert plan.trips[0].switch_ticks[0] == T


@pytest.mark.parametrize(
    "variant",
    (ReservoirLineVariant.DISPATCH_DOMAINS, ReservoirLineVariant.INTERVALS),
)
def test_both_exact_resource_encodings_have_the_same_tiny_optimum(variant):
    p = problem(
        dispatch_end_seconds=3,
        dispatch_step_seconds=1,
        available_fleet_count=2,
    )
    result, plan = ReservoirLineOptimizer(
        config(
            maximum_cabins=2,
            fixed_cabins=2,
            variant=variant,
            preparation=ReservoirLinePreparation.LEGACY_EAGER,
            formulation=ReservoirLineFormulation.LEGACY_TEMPLATES,
        )
    ).solve(p)
    assert result["proven_optimal"] and result["validated_served"] == 1
    validate_reservoir_cp_plan(p, plan)


def test_free_fleet_uses_prefix_and_can_leave_cabins_in_reservoir():
    p = problem(
        dispatch_end_seconds=3,
        dispatch_step_seconds=1,
        available_fleet_count=3,
        demand_groups=(),
    )
    result, plan = ReservoirLineOptimizer(config(maximum_cabins=3)).solve(p)
    assert result["proven_optimal"]
    assert result["used_fleet"] == 0
    assert plan == DddReservoirCpPlan((), {})


def test_exact_service_does_not_use_optimistically_attractive_late_boarding():
    p = problem(
        dispatch_end_seconds=0,
        available_fleet_count=1,
        demand_groups=(EanDemandGroup("late", "A", "B", 14, 1),),
    )
    exact, _ = ReservoirLineOptimizer(
        config(
            dispatch_window_end_seconds=0,
            maximum_cabins=1,
            fixed_cabins=1,
            mode=ReservoirLineMode.EXACT_SERVICE,
        )
    ).solve(p)
    optimistic, _ = ReservoirLineOptimizer(
        config(
            dispatch_window_end_seconds=0,
            maximum_cabins=1,
            fixed_cabins=1,
            mode=ReservoirLineMode.OPTIMISTIC_SERVICE,
        )
    ).solve(p)
    assert exact["validated_served"] == 0
    # The optimistic model deliberately drops release/horizon links. Its native
    # score is an upper bound and its extracted assignment must not be certified.
    assert optimistic["native_optimistic_served"] == 1
    assert optimistic["validated_served"] is None


def test_representable_checkpoint_is_a_hint_and_not_a_fixing():
    p = problem(
        dispatch_end_seconds=3,
        dispatch_step_seconds=1,
        available_fleet_count=2,
    )
    c = config(maximum_cabins=2)
    prepared = prepare_line_problem(p, c)
    built = build_reservoir_line_model(p, prepared, c)
    seed = DddReservoirCpPlan(
        (trip(routes=("A_stop", "B_stop") * 4),), {}
    )
    add_line_plan_hint(p, prepared, built, seed)
    assert not built.model.validate()
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 5
    solver.parameters.num_search_workers = 1
    assert solver.solve(built.model) == cp_model.OPTIMAL


def test_fixed_pattern_sequence_activates_its_slots():
    p = problem(available_fleet_count=2, demand_groups=())
    result, plan = ReservoirLineOptimizer(
        config(maximum_cabins=2, fixed_pattern_sequence=("all_stop",))
    ).solve(p)
    assert result["used_fleet"] == 1
    assert len(plan.trips) == 1


def test_fixed_pattern_counts_leave_dispatch_order_to_solver():
    p = problem(available_fleet_count=2, demand_groups=())
    c = config(
        maximum_cabins=2,
        fixed_cabins=2,
        fixed_pattern_counts=(("all_stop", 2),),
        mode=ReservoirLineMode.FEASIBILITY,
        variant=ReservoirLineVariant.DISPATCH_DOMAINS,
    )
    result, plan = ReservoirLineOptimizer(c).solve(p)
    assert result["solver_status"] == "OPTIMAL"
    assert len(plan.trips) == 2
    assert result["model_stats"]["fixed_pattern_count_classes"] == 1


def test_dispatch_ticks_are_hints_and_do_not_fix_the_timing():
    p = problem(available_fleet_count=2, demand_groups=())
    c = config(
        maximum_cabins=2,
        fixed_cabins=2,
        fixed_pattern_sequence=("all_stop", "all_stop"),
        mode=ReservoirLineMode.FEASIBILITY,
        variant=ReservoirLineVariant.DISPATCH_DOMAINS,
    )
    result, plan = ReservoirLineOptimizer(c).solve(
        p, dispatch_hint_ticks=(0, 2 * T)
    )
    assert result["solver_status"] == "OPTIMAL"
    assert result["dispatch_hint_used"] is True
    assert len(plan.trips) == 2


def test_dispatch_hint_must_match_slots_and_grid():
    p = problem(available_fleet_count=2, demand_groups=())
    c = config(
        maximum_cabins=2,
        fixed_cabins=2,
        fixed_pattern_sequence=("all_stop", "all_stop"),
        mode=ReservoirLineMode.FEASIBILITY,
        variant=ReservoirLineVariant.DISPATCH_DOMAINS,
    )
    with pytest.raises(ValueError, match="one tick per cabin"):
        ReservoirLineOptimizer(c).solve(p, dispatch_hint_ticks=(0,))


def test_fixed_pattern_counts_validate_total_and_conflicts():
    with pytest.raises(ValueError, match="differs"):
        config(
            maximum_cabins=2,
            fixed_cabins=2,
            fixed_pattern_counts=(("all_stop", 1),),
        ).validate(2)
    with pytest.raises(ValueError, match="conflict"):
        config(
            maximum_cabins=2,
            fixed_cabins=2,
            fixed_pattern_sequence=("all_stop", "all_stop"),
            fixed_pattern_counts=(("all_stop", 2),),
        ).validate(2)


def test_fixed_line_movement_optimizes_passengers_without_fixing_ride_counts():
    p = problem(available_fleet_count=1)
    movement = DddReservoirCpPlan(
        (trip(routes=("A_stop", "B_stop") * 4),), {}
    )
    result, plan = ReservoirLineOptimizer(
        config(maximum_cabins=1)
    ).solve(p, fixed_movement_plan=movement)
    assert result["proof_scope"] == "FIXED_LINE_MOVEMENT"
    assert result["proven_optimal"]
    assert result["validated_served"] == 1
    assert plan.trips == movement.trips


def test_deployed_cabin_cannot_return_while_another_round_can_serve():
    p = problem(available_fleet_count=1)
    c = config(maximum_cabins=1)
    prepared = prepare_line_problem(p, c)
    service_end = p.resolved_core.passenger_service_end_tick
    for template in prepared.templates:
        cycle = template.duration_tick // template.laps
        for dispatch in (
            template.minimum_dispatch_tick,
            template.maximum_dispatch_tick,
        ):
            assert dispatch + template.duration_tick >= service_end
            assert dispatch + template.duration_tick - cycle < service_end

    early_return = DddReservoirCpPlan(
        (trip(routes=("A_stop", "B_stop") * 3),), {}
    )
    with pytest.raises(ValueError, match="continuous-service"):
        ReservoirLineOptimizer(c).solve(p, fixed_movement_plan=early_return)


def test_passengers_board_only_after_dispatch_phase():
    p = problem(
        available_fleet_count=1,
        demand_groups=(EanDemandGroup("warmup_release", "A", "B", 0, 1),),
    )
    c = config(maximum_cabins=1, fixed_cabins=1)
    result, plan = ReservoirLineOptimizer(c).solve(p)
    assert result["proven_optimal"] and result["validated_served"] == 1
    trip_ = plan.trips[0]
    candidate_by_id = {item.id: item for item in p.passenger_build.ride_candidates}
    option_by_id = {item.id: item for item in p.resolved_core.route_options}
    for ride_id, count in plan.ride_counts.items():
        if not count:
            continue
        candidate = candidate_by_id[ride_id]
        option = option_by_id[
            trip_.route_option_ids[candidate.board_visit_index]
        ]
        departure = trip_.switch_ticks[candidate.board_visit_index] + ddd_seconds_to_tick(
            option.platform_exit_offset_seconds
        )
        assert departure >= c.service_start_tick


def test_reference_with_warmup_boarding_is_rejected():
    p = problem(
        available_fleet_count=1,
        demand_groups=(EanDemandGroup("warmup_release", "A", "B", 0, 1),),
    )
    c = config(maximum_cabins=1)
    prepared = prepare_line_problem(p, c)
    built = build_reservoir_line_model(p, prepared, c)
    first_ride = next(
        item for item in p.passenger_build.ride_candidates
        if item.board_visit_index == 0
    )
    warmup_plan = DddReservoirCpPlan(
        (trip(routes=("A_stop", "B_stop") * 4),),
        {first_ride.id: 1},
    )
    with pytest.raises(ValueError, match="before passenger service"):
        add_line_plan_hint(p, prepared, built, warmup_plan)


def test_unknown_before_search_does_not_export_default_zero_as_bound():
    p = problem(available_fleet_count=2)
    result, _ = ReservoirLineOptimizer(
        config(maximum_cabins=2, time_limit_seconds=1e-9)
    ).solve(p)
    assert result["solver_status"] == "UNKNOWN"
    assert result["native_objective_upper_bound_raw"] is None
    assert result["native_served_upper_bound"] is None
    assert result["line_domain_unserved_lower_bound"] is None


def test_zero_maximum_fleet_is_rejected_instead_of_using_available_fleet():
    with pytest.raises(ValueError, match="maximum cabins"):
        config(maximum_cabins=0).validate(2)


def test_bounded_wait_source_is_explicitly_restricted_to_zero_waiting():
    base = problem()
    waiting = replace(
        base,
        waiting_policy=replace(
            base.waiting_policy,
            domain=__import__(
                "ropeway_skip_stop_optimization.optimization.ddd.trajectory_column_generation",
                fromlist=["DddTrajectoryWaitingDomain"],
            ).DddTrajectoryWaitingDomain.BOUNDED_WAIT,
            step_seconds=1,
            maximum_wait_seconds_by_station_id=(("A", 1), ("B", 1)),
        ),
    )
    prepared = prepare_line_problem(waiting, config(maximum_cabins=1))
    assert prepared.stats["source_waiting_domain"] == "bounded_wait"
    assert prepared.stats["waiting_fixed_to_zero"] is True


def test_fixed_route_timing_can_use_waiting_to_serve_a_late_release():
    base = problem(available_fleet_count=1)
    p = replace(
        base,
        movement_core=replace(
            base.movement_core,
            passenger_service_end_seconds=11,
            operational_end_seconds=15,
        ),
        waiting_policy=replace(
            base.waiting_policy,
            domain=DddTrajectoryWaitingDomain.BOUNDED_WAIT,
            step_seconds=1,
            maximum_wait_seconds_by_station_id=(("A", 2), ("B", 2)),
            earliest_wait_time_seconds=5,
        ),
        demand_groups=(EanDemandGroup("late", "A", "B", 9, 1),),
    )
    no_wait = DddReservoirCpPlan(
        (trip(routes=("A_stop", "B_stop") * 3),), {}
    )
    assert validate_reservoir_cp_plan(p, no_wait).unserved == 1
    result = DddReservoirCpSatOptimizer(
        DddIntegratedCpSatConfig(total_time_limit_seconds=5, num_workers=1),
        DddReservoirCpObjective.UNSERVED,
    ).solve(p, primal_seed=no_wait, fixed_route_plan=no_wait)
    timed = DddReservoirCpPlan(
        tuple(DddReservoirCpTrip(**item) for item in result["plan"]["trips"]),
        result["plan"]["ride_counts"],
    )
    assert result["proof_scope"] == "FIXED_ROUTE_SEQUENCE"
    assert validate_reservoir_cp_plan(p, timed).unserved == 0
    assert sum(sum(trip_.wait_ticks) for trip_ in timed.trips) == T


def test_relevant_catalog_contains_specialized_and_all_stop_patterns():
    p = problem(
        demand_groups=(
            EanDemandGroup("ab", "A", "B", 0, 1),
        )
    )
    prepared = prepare_line_problem(
        p, config(catalog_profile=ReservoirLineCatalogProfile.RELEVANT)
    )
    assert {template.pattern_id for template in prepared.templates} == {"all_stop"}
