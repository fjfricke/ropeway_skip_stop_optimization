from dataclasses import replace
import sys

from ortools.sat.python import cp_model
import pytest

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
from test_optimization_ddd_reservoir_cp_sat import problem, trip  # noqa: E402

from ropeway_skip_stop_optimization.optimization.ddd.reservoir_cp_sat_certificate import (  # noqa: E402
    DddReservoirCpPlan,
    validate_reservoir_cp_plan,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_lines import (  # noqa: E402
    ReservoirLineCatalogProfile,
    ReservoirLineConfig,
    ReservoirLineMode,
    ReservoirLineOptimizer,
    ReservoirLineVariant,
    prepare_line_problem,
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
    assert complement_closed(((2, 3), (6, 9)), 1, 7) == (
        TickInterval(1, 1), TickInterval(4, 5)
    )


def test_prepared_delta_domains_equal_direct_resource_and_state_enumeration():
    p = problem(dispatch_end_seconds=0.000005, dispatch_step_seconds=0.000001)
    prepared = prepare_line_problem(
        p, config(dispatch_window_end_seconds=0.000005)
    )
    for first in prepared.templates:
        for second in prepared.templates:
            allowed = prepared.pair_domains_by_id[first.id, second.id].allowed_delta
            for delta in range(1, prepared.dispatch_window_end_tick + 1):
                in_domain = any(item.lower <= delta <= item.upper for item in allowed)
                assert in_domain is (not _direct_pair_conflict(first, second, delta))


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
    assert plan.trips[0].switch_ticks[0] == 0
    assert plan.trips[1].switch_ticks[0] > 0


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
        config(maximum_cabins=2, fixed_cabins=2, variant=variant)
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
    seed = DddReservoirCpPlan((trip(),), {})
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


def test_fixed_line_movement_optimizes_passengers_without_fixing_ride_counts():
    p = problem(available_fleet_count=1)
    movement = DddReservoirCpPlan(
        (trip(routes=("A_stop", "B_stop") * 3),), {}
    )
    result, plan = ReservoirLineOptimizer(
        config(maximum_cabins=1)
    ).solve(p, fixed_movement_plan=movement)
    assert result["proof_scope"] == "FIXED_LINE_MOVEMENT"
    assert result["proven_optimal"]
    assert result["validated_served"] == 1
    assert plan.trips == movement.trips


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
