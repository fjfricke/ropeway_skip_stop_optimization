from __future__ import annotations

from dataclasses import replace

import pytest

from ropeway_skip_stop_optimization.benchmarking.thesis_cases import (
    ExperimentCaseSpec,
    ThesisDemandFamily,
    ThesisDemandProfile,
    ThesisGeometry,
    ThesisObjective,
    ThesisTopology,
    build_demand_groups,
    core_thesis_experiment_groups,
    thesis_g500_experiment_groups,
    geometric_fleet_caps,
    prepare_experiment_case,
)
from ropeway_skip_stop_optimization.benchmarking.thesis_all_stop_capacity import (
    AllStopCapacitySearchConfig,
    search_all_stop_capacity,
    search_fixed_k_all_stop_capacity,
)
from ropeway_skip_stop_optimization.examples.registry import get_example
from ropeway_skip_stop_optimization.optimization.ddd.all_stop_phase import (
    AllStopPhaseConfig,
    prepare_all_stop_phase,
    solve_all_stop_phase,
)
from ropeway_skip_stop_optimization.optimization.ddd.all_stop_phase_cells import (
    phase_cell_index,
    prepare_all_stop_phase_cells,
    solve_all_stop_phase_cells,
)
from ropeway_skip_stop_optimization.optimization.ddd.time_ticks import (
    ddd_seconds_to_tick,
)


def _spec(
    *,
    topology: ThesisTopology = ThesisTopology.T5R,
    geometry: ThesisGeometry = ThesisGeometry.G300,
    family: ThesisDemandFamily = ThesisDemandFamily.F0,
    profile: ThesisDemandProfile = ThesisDemandProfile.P0,
    demand: int = 40,
) -> ExperimentCaseSpec:
    return ExperimentCaseSpec(
        topology,
        geometry,
        family,
        profile,
        ThesisObjective.UNSERVED,
        demand,
    )


@pytest.mark.parametrize(
    ("example_id", "station_count", "rope_lengths"),
    (
        ("thesis_t5r_g300_b_v1", 5, (300.0,) * 5),
        ("thesis_t5r_g500_b_v1", 5, (500.0,) * 5),
        ("thesis_t6r_g500_b_v1", 6, (500.0,) * 6),
        ("thesis_t6r_g800_b_v1", 6, (800.0,) * 6),
        (
            "thesis_t6r_guneq_v2_b_v1",
            6,
            (500.0, 1100.0, 900.0, 600.0, 700.0, 1000.0),
        ),
    ),
)
def test_thesis_geometry_is_registered_and_uses_calibrated_station_paths(
    example_id, station_count, rope_lengths
):
    scenario = get_example(example_id).build_scenario()
    assert len(scenario.stations) == station_count
    assert tuple(
        segment.length_m
        for segment in scenario.track_segments
        if segment.kind.value == "rope"
    ) == rope_lengths
    assert scenario.operating.cabin_capacity == 10
    assert scenario.operating.rope_speed_m_per_s == 6.0
    assert scenario.operating.station_speed_m_per_s == 0.3

    segments = {segment.id: segment for segment in scenario.track_segments}
    stop = next(route for route in scenario.station_routes if route.id == "S0_service_cw")
    skip = next(route for route in scenario.station_routes if route.id == "S0_skip_cw")

    def length(route):
        return sum(segments[segment_id].length_m for segment_id in route.segment_ids)

    def duration(route):
        value = 0.0
        for segment_id in route.segment_ids:
            segment = segments[segment_id]
            profile = segment.speed_profile
            if profile.kind.value == "constant":
                value += segment.length_m / profile.speed_m_per_s
            else:
                value += 2 * segment.length_m / (
                    profile.start_speed_m_per_s + profile.end_speed_m_per_s
                )
        return value

    assert length(stop) == pytest.approx(60.91)
    assert length(skip) == pytest.approx(60.91)
    assert duration(stop) == pytest.approx(63.06666666666666)
    assert duration(skip) == pytest.approx(10.151666666666666)


def test_unequal_geometry_is_rejected_for_t5r():
    with pytest.raises(ValueError, match="only for T6R"):
        _spec(geometry=ThesisGeometry.GUNEQ_V2).validate()


def test_core_catalog_contains_six_capacity_and_three_journey_curves():
    groups = core_thesis_experiment_groups()
    assert len(groups) == 9
    assert len({group.group_id for group in groups}) == 9
    assert sum(group.objective is ThesisObjective.UNSERVED for group in groups) == 6
    assert sum(group.objective is ThesisObjective.JOURNEY_TIME for group in groups) == 3


def test_g500_catalog_contains_eight_capacity_and_four_journey_groups():
    groups = thesis_g500_experiment_groups()
    assert len(groups) == 12
    assert len({group.group_id for group in groups}) == 12
    assert {group.geometry for group in groups} == {ThesisGeometry.G500}
    assert {group.demand_profile for group in groups} == {ThesisDemandProfile.P0}
    assert sum(group.objective is ThesisObjective.UNSERVED for group in groups) == 8
    assert sum(group.objective is ThesisObjective.JOURNEY_TIME for group in groups) == 4
    assert {
        group.demand_family for group in groups
        if group.objective is ThesisObjective.JOURNEY_TIME
    } == set(ThesisDemandFamily)


def test_g500_f2_od_endpoint_line_catalog_has_three_stable_masks():
    from ropeway_skip_stop_optimization.optimization.ddd.reservoir_lines import (
        ReservoirLineCatalogProfile,
    )
    from ropeway_skip_stop_optimization.optimization.ddd.reservoir_lines.catalog import (
        line_patterns,
    )

    prepared = prepare_experiment_case(
        _spec(geometry=ThesisGeometry.G500, family=ThesisDemandFamily.F2, demand=40),
        fleet_cap=2,
    )
    patterns = line_patterns(
        prepared.problem, ReservoirLineCatalogProfile.OD_ENDPOINTS_V1
    )
    assert [pattern.id for pattern in patterns] == [
        "all_stop",
        "stop_S1_S3",
        "stop_S2_S4",
    ]


def test_five_geometric_fleet_caps_include_derived_endpoints():
    caps = geometric_fleet_caps(84, 933)
    assert caps[0] == 84
    assert caps[-1] == 933
    assert len(caps) == 5
    assert all(left < right for left, right in zip(caps, caps[1:]))


@pytest.mark.parametrize("family", list(ThesisDemandFamily))
@pytest.mark.parametrize("profile", list(ThesisDemandProfile))
def test_demand_is_nested_and_release_times_are_aligned(family, profile):
    spec = _spec(family=family, profile=profile, demand=99)
    kwargs = dict(
        station_ids=tuple(f"S{i}" for i in range(5)),
        free_rope_lengths=(300.0,) * 5,
        service_start_tick=ddd_seconds_to_tick(100),
        demand_window_tick=ddd_seconds_to_tick(2700),
    )
    groups_99 = build_demand_groups(spec, **kwargs)
    groups_100 = build_demand_groups(replace(spec, demand_total=100), **kwargs)
    by_key_99 = {
        (g.origin_station_id, g.destination_station_id, g.release_time_seconds): g.count
        for g in groups_99
    }
    by_key_100 = {
        (g.origin_station_id, g.destination_station_id, g.release_time_seconds): g.count
        for g in groups_100
    }
    assert sum(by_key_99.values()) == 99
    assert sum(by_key_100.values()) == 100
    assert all(by_key_100.get(key, 0) >= count for key, count in by_key_99.items())
    for group in groups_100:
        release_tick = ddd_seconds_to_tick(group.release_time_seconds)
        assert (release_tick - kwargs["service_start_tick"]) % ddd_seconds_to_tick(30) == 0
        assert kwargs["service_start_tick"] <= release_tick <= sum(
            (kwargs["service_start_tick"], kwargs["demand_window_tick"])
        )


def test_direction_filter_removes_counterclockwise_pairs_before_normalization():
    groups = build_demand_groups(
        _spec(family=ThesisDemandFamily.F2, demand=40),
        station_ids=tuple(f"S{i}" for i in range(5)),
        free_rope_lengths=(300.0,) * 5,
        service_start_tick=0,
        demand_window_tick=ddd_seconds_to_tick(2700),
    )
    assert {(g.origin_station_id, g.destination_station_id) for g in groups} == {
        ("S1", "S3"),
        ("S2", "S4"),
    }
    assert sum(g.count for g in groups) == 40


def test_prepared_case_uses_cycle_warmup_and_safe_completion():
    prepared = prepare_experiment_case(_spec(demand=20))
    assert ddd_seconds_to_tick(prepared.problem.dispatch_end_seconds) == prepared.all_stop_cycle_tick
    assert prepared.completion_tick >= ddd_seconds_to_tick(15 * 60)
    assert prepared.recovery_tick == prepared.all_stop_cycle_tick
    assert prepared.all_stop_reference_cabins <= prepared.physical_dispatch_bound
    assert prepared.all_stop_reference_cabins == prepared.all_stop_unconstrained_saturation_cabins
    assert prepared.configured_fleet_cap == prepared.all_stop_reference_cabins
    assert prepared.problem.available_fleet_count == prepared.configured_fleet_cap
    assert sum(group.count for group in prepared.problem.demand_groups) == 20


def test_common_phase_reference_solves_small_full_service_case():
    prepared = prepare_experiment_case(_spec(demand=5))
    phase = prepare_all_stop_phase(
        prepared.problem,
        AllStopPhaseConfig(
            cabins=prepared.all_stop_reference_cabins,
            require_full_service=True,
            time_limit_seconds=30,
            workers=1,
        ),
    )
    result, plan = solve_all_stop_phase(phase)
    assert result["solver_status"] == "OPTIMAL"
    assert result["proven_optimal"] is True
    assert plan is not None
    assert result["metrics"]["unserved"] == 0
    assert max(phase.offsets[index + 1] - phase.offsets[index] for index in range(len(phase.offsets) - 1)) - min(
        phase.offsets[index + 1] - phase.offsets[index] for index in range(len(phase.offsets) - 1)
    ) <= 1


def test_phase_cells_cover_the_integer_phase_domain_and_reproduce_small_reference():
    prepared = prepare_experiment_case(_spec(demand=5))
    phase = prepare_all_stop_phase(
        prepared.problem,
        AllStopPhaseConfig(
            cabins=prepared.all_stop_reference_cabins,
            require_full_service=True,
            time_limit_seconds=30,
            workers=1,
        ),
    )
    cells = prepare_all_stop_phase_cells(phase)
    assert cells.cells[0].first_tick == 0
    assert cells.cells[-1].last_tick == phase.maximum_phase_tick
    assert all(
        left.last_tick + 1 == right.first_tick
        for left, right in zip(cells.cells, cells.cells[1:])
    )
    for index, cell in enumerate(cells.cells):
        assert phase_cell_index(cells, cell.first_tick) == index
        assert phase_cell_index(cells, cell.last_tick) == index

    result, plan = solve_all_stop_phase_cells(
        cells, time_limit_seconds=30, workers=1
    )
    assert result["solver_status"] == "OPTIMAL"
    assert result["proven_feasible"] is True
    assert plan is not None
    assert result["metrics"]["served"] == 5
    assert result["metrics"]["unserved"] == 0


def test_capacity_search_keeps_an_open_upper_interval_when_ceiling_is_feasible():
    result, plan, prepared = search_all_stop_capacity(
        _spec(demand=5),
        AllStopCapacitySearchConfig(
            maximum_demand=5,
            initial_demand=2,
            time_limit_seconds=30,
            workers=1,
        ),
    )
    assert result["proven_feasible_demand"] == 5
    assert result["proven_infeasible_demand"] is None
    assert result["capacity_proven"] is False
    assert result["capacity"] is None
    assert plan is not None
    assert prepared.spec.demand_total == 5


def test_requested_capacity_probes_are_solved_not_assumed():
    saved = []
    result, plan, _ = search_all_stop_capacity(
        _spec(demand=5),
        AllStopCapacitySearchConfig(maximum_demand=5, initial_demand=2,
                                    probe_demands=(4, 5), time_limit_seconds=10, workers=1),
        incumbent_callback=lambda plan, case: saved.append((plan, case.spec.demand_total)),
    )
    assert [probe["demand"] for probe in result["probes"][:2]] == [4, 5]
    assert all(probe["outcome"] == "feasible" for probe in result["probes"])
    assert plan is not None and result["proven_feasible_demand"] == 5
    assert not result["capacity_proven"]
    assert [demand for _, demand in saved] == [4, 5]


def test_compact_reference_links_preserve_capacity():
    from dataclasses import replace
    config = AllStopCapacitySearchConfig(maximum_demand=8, initial_demand=4, time_limit_seconds=20, workers=1)
    old, _, _ = search_all_stop_capacity(_spec(demand=8), config)
    new, _, _ = search_all_stop_capacity(_spec(demand=8), replace(config, compact_time_links=True))
    assert (old["proven_feasible_demand"], old["proven_infeasible_demand"]) == (new["proven_feasible_demand"], new["proven_infeasible_demand"])


def test_phase_cell_capacity_search_matches_integrated_small_reference():
    config = AllStopCapacitySearchConfig(
        maximum_demand=8,
        initial_demand=4,
        time_limit_seconds=30,
        workers=1,
    )
    integrated, _, _ = search_all_stop_capacity(_spec(demand=8), config)
    decomposed, _, _ = search_all_stop_capacity(
        _spec(demand=8), replace(config, encoding="phase_cells")
    )
    assert (
        integrated["proven_feasible_demand"],
        integrated["proven_infeasible_demand"],
    ) == (
        decomposed["proven_feasible_demand"],
        decomposed["proven_infeasible_demand"],
    )


def test_fixed_k_capacity_search_proves_adjacent_nested_threshold():
    result = search_fixed_k_all_stop_capacity(
        replace(
            _spec(demand=100),
            objective=ThesisObjective.JOURNEY_TIME,
            demand_family=ThesisDemandFamily.F3,
        ),
        AllStopCapacitySearchConfig(
            maximum_demand=100,
            initial_demand=50,
            time_limit_seconds=30,
            workers=1,
        ),
        cabins=1,
    )
    assert result["capacity_proven"] is True
    assert result["capacity"] == 62
    assert result["proven_infeasible_demand"] == 63
