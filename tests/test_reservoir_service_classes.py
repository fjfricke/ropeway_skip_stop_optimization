from dataclasses import replace
import sys

import pytest

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
from test_optimization_ddd_reservoir_cp_sat import problem  # noqa: E402

from ropeway_skip_stop_optimization.optimization.ddd.reservoir_cp_sat_certificate import (  # noqa: E402
    validate_reservoir_cp_plan,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_lines import (  # noqa: E402
    ReservoirLineConfig,
    ReservoirLineMode,
    ReservoirPatternMasterConfig,
    prepare_line_problem,
    prepare_line_service_classes,
    project_line_plan_to_service_classes,
    solve_service_class_master,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_lines.service_class_timing import (  # noqa: E402
    solve_service_class_timing,
)
from ropeway_skip_stop_optimization.optimization.ddd.time_ticks import (  # noqa: E402
    ddd_seconds_to_tick,
)
from ropeway_skip_stop_optimization.optimization.ean.models import EanDemandGroup  # noqa: E402


def _config(**kwargs):
    return ReservoirLineConfig(
        dispatch_window_end_seconds=kwargs.pop("dispatch_window_end_seconds", 3),
        maximum_cabins=kwargs.pop("maximum_cabins", None),
        mode=kwargs.pop("mode", ReservoirLineMode.FEASIBILITY),
        time_limit_seconds=kwargs.pop("time_limit_seconds", 5),
        workers=kwargs.pop("workers", 1),
        **kwargs,
    )


def test_service_classes_match_every_dispatch_tick_and_boundary():
    p = problem(
        dispatch_end_seconds=3,
        dispatch_step_seconds=1,
        movement_core=replace(
            problem().movement_core,
            passenger_service_end_seconds=7,
            operational_end_seconds=12,
        ),
        demand_groups=(
            EanDemandGroup("early", "A", "B", 3, 1),
            EanDemandGroup("late", "A", "B", 5, 1),
        ),
    )
    line = _config(dispatch_window_end_seconds=3)
    prepared = prepare_line_problem(p, line)
    classes = prepare_line_service_classes(p, prepared)
    groups = {item.id: item for item in p.demand_groups}
    horizon = p.resolved_core.passenger_service_end_tick
    step = prepared.dispatch_step_tick
    by_template = {}
    for item in classes.classes:
        by_template.setdefault(item.template_id, []).append(item)
    for template in prepared.templates:
        for dispatch in range(
            template.minimum_dispatch_tick,
            template.maximum_dispatch_tick + 1,
            step,
        ):
            matching = [
                item
                for item in by_template[template.id]
                if item.minimum_dispatch_tick <= dispatch <= item.maximum_dispatch_tick
            ]
            assert len(matching) == 1
            actual = matching[0].ride_keys
            expected = set()
            for ride in p.passenger_build.ride_candidates:
                if ride.cabin_id != 0 or ride.alight_visit_index >= len(template.visits):
                    continue
                board = template.visits[ride.board_visit_index]
                alight = template.visits[ride.alight_visit_index]
                if board.platform_exit_tick is None or alight.platform_entry_tick is None:
                    continue
                release = max(
                    prepared.service_start_tick,
                    ddd_seconds_to_tick(groups[ride.demand_group_id].release_time_seconds),
                )
                if (
                    dispatch + board.platform_exit_tick >= release
                    and dispatch + board.platform_exit_tick <= horizon
                    and dispatch + alight.platform_entry_tick <= horizon
                ):
                    expected.add(
                        (
                            ride.demand_group_id,
                            ride.board_visit_index,
                            ride.alight_visit_index,
                        )
                    )
            assert actual == expected


def test_fixed_service_classes_validate_public_contract():
    with pytest.raises(ValueError, match="feasibility"):
        _config(
            mode=ReservoirLineMode.EXACT_SERVICE,
            fixed_service_class_counts=(("c", 1),),
        ).validate(1)
    with pytest.raises(ValueError, match="unique"):
        _config(
            fixed_service_class_counts=(("c", 1), ("c", 1))
        ).validate(2)


def test_master_timing_and_integer_expansion_round_trip():
    pytest.importorskip("gurobipy")
    p = problem(dispatch_end_seconds=0.000005, dispatch_step_seconds=0.000001)
    line = _config(dispatch_window_end_seconds=0.000005, maximum_cabins=1)
    prepared = prepare_line_problem(p, line)
    classes = prepare_line_service_classes(p, prepared)
    master = solve_service_class_master(
        p,
        classes,
        1,
        ReservoirPatternMasterConfig(
            time_limit_seconds=2,
            threads=1,
            candidate_limit=2,
            output_flag=False,
        ),
    )
    assert master.status == "OPTIMAL"
    assert master.candidates and master.candidates[0].served == 1
    timing = solve_service_class_timing(
        p,
        prepared,
        classes,
        master.candidates[0],
        line,
        time_limit_seconds=2,
    )
    assert timing.status == "OPTIMAL"
    assert timing.plan is not None and timing.validated_served == 1
    assert validate_reservoir_cp_plan(p, timing.plan).served == 1
    projected = project_line_plan_to_service_classes(
        p, prepared, classes, timing.plan
    )
    assert projected.served == 1
    replay = solve_service_class_timing(
        p, prepared, classes, projected, line, time_limit_seconds=2
    )
    assert replay.plan is not None and replay.validated_served == 1


def test_master_build_only_does_not_report_solution_or_bound():
    pytest.importorskip("gurobipy")
    p = problem()
    line = _config()
    prepared = prepare_line_problem(p, line)
    classes = prepare_line_service_classes(p, prepared)
    result = solve_service_class_master(
        p,
        classes,
        1,
        ReservoirPatternMasterConfig(time_limit_seconds=2, threads=1),
        build_only=True,
    )
    assert result.status == "NOT_RUN"
    assert result.objective_bound is None and not result.candidates
    assert result.stats["variables"] > 0
