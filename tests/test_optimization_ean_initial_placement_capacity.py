from __future__ import annotations

from dataclasses import replace
from datetime import time

import pytest

from ropeway_skip_stop_optimization.models import (
    Cabin,
    CabinInitialState,
    OperatingParameters,
    PhysicalNode,
    PhysicalNodeKind,
    Scenario,
    SpeedProfile,
    SpeedProfileKind,
    Station,
    StationKind,
    StationRoute,
    StationRouteKind,
    TrackSegment,
    TrackSegmentKind,
)
from ropeway_skip_stop_optimization.optimization.ean import (
    EanConfig,
    EanFleetCardinalityMode,
    EanFleetConfig,
    EanFleetPackingRegionKind,
    EanFleetMode,
    EanHorizonFormulation,
    EanInitialPlacementCapacityOptimizer,
    EanInitialPlacementCapacityCertificate,
    EanInitialPlacementCapacityOutputMode,
    EanInitialPlacementCapacityProbeResult,
    EanInitialPlacementCapacityProblem,
    EanInitialPlacementCapacitySearchConfig,
    EanInitialPlacementCapacitySolveConfig,
    EanInitialPlacementDelayedHeadwayConfig,
    EanInitialPlacementHeadwayGenerationMode,
    EanInitialPlacementFeasibilityOptimizer,
    EanInitialPlacementFeasibilityProblem,
    EanInitialPlacementFeasibilityStatus,
    EanInitialPlacementMipStart,
    EanInitialPlacementMipStartSource,
    EanInitialPlacementPackingBoundBuilder,
    HeadwayPairBuilder,
    RingEanBuildArtifactBuilder,
    SparseHeadwayPairBuilder,
    StationEanConfig,
    StationWaitingMode,
    segment_packing_capacity,
    solver_integer_upper_bound,
)
from ropeway_skip_stop_optimization.optimization.ean.optimization_config import (
    EanOptimizationConfig,
)
from ropeway_skip_stop_optimization.optimization.ean.optimizers.all_stop_mip_start import (
    EanAllStopMipStartSeedBuilder,
)
from ropeway_skip_stop_optimization.optimization.ean.optimizers.initial_placement_capacity import (
    _lift_initial_placement_mip_start,
    _search_fixed_k_capacity_interval,
)
from ropeway_skip_stop_optimization.optimization.ean.optimizers.movement_model import (
    EanMovementModelBuilder,
)


def test_segment_packing_capacity_uses_half_open_ceil() -> None:
    assert segment_packing_capacity(10.0, 5.0) == 2
    assert segment_packing_capacity(10.1, 5.0) == 3
    assert segment_packing_capacity(4.9, 5.0) == 1


def test_packing_bound_counts_unique_segments_and_no_switch_points() -> None:
    scenario = _single_station_ring(with_skip=True, shared_skip=True)
    bound = EanInitialPlacementPackingBoundBuilder().build(
        scenario=scenario,
        config=_config(),
        switch_cycle=("entry",),
    )

    track_regions = tuple(
        region
        for region in bound.regions
        if region.kind is EanFleetPackingRegionKind.TRACK_SEGMENT
    )
    assert bound.packing_upper_bound == 4
    assert len(track_regions) == 4
    assert all(region.half_open for region in track_regions)
    assert all(
        not region.physical_id.endswith(("entry", "exit")) for region in track_regions
    )
    assert all(
        any(role.startswith("service::") for role in region.source_roles)
        and any(role.startswith("skip::") for role in region.source_roles)
        for region in track_regions[:3]
    )


def test_packing_bound_adds_distinct_enabled_skip_segments() -> None:
    without_skip = EanInitialPlacementPackingBoundBuilder().build(
        scenario=_single_station_ring(),
        config=_config(),
        switch_cycle=("entry",),
    )
    with_skip = EanInitialPlacementPackingBoundBuilder().build(
        scenario=_single_station_ring(with_skip=True),
        config=_config(),
        switch_cycle=("entry",),
    )

    assert without_skip.packing_upper_bound == 4
    assert with_skip.packing_upper_bound == 5
    assert any(region.physical_id == "skip" for region in with_skip.regions)


def test_packing_bound_adds_one_end_wait_resource() -> None:
    bound = EanInitialPlacementPackingBoundBuilder().build(
        scenario=_single_station_ring(),
        config=_config(StationWaitingMode.END_OF_PLATFORM_WAIT),
        switch_cycle=("entry",),
    )

    wait_regions = tuple(
        region
        for region in bound.regions
        if region.kind is EanFleetPackingRegionKind.PLATFORM_WAIT
    )
    assert len(wait_regions) == 1
    assert wait_regions[0].capacity == 1
    assert bound.packing_upper_bound == 5


def test_packing_bound_keeps_fifo_unimplemented() -> None:
    with pytest.raises(NotImplementedError, match="packing bounds"):
        EanInitialPlacementPackingBoundBuilder().build(
            scenario=_single_station_ring(),
            config=_config(
                StationWaitingMode.STATION_FIFO_BUFFER,
                fifo_capacity=2,
            ),
            switch_cycle=("entry",),
        )


def test_solver_integer_upper_bound_is_integral_and_packing_limited() -> None:
    assert (
        solver_integer_upper_bound(
            packing_upper_bound=10,
            objective_bound=7.9999999,
            incumbent_lower_bound=6,
        )
        == 8
    )
    assert (
        solver_integer_upper_bound(
            packing_upper_bound=10,
            objective_bound=12.5,
            incumbent_lower_bound=6,
        )
        == 10
    )
    assert (
        solver_integer_upper_bound(
            packing_upper_bound=10,
            objective_bound=None,
            incumbent_lower_bound=6,
        )
        == 10
    )


def test_fixed_k_search_probes_clamped_packing_upper_bound() -> None:
    calls: list[int] = []

    def probe(k: int) -> EanInitialPlacementCapacityProbeResult:
        calls.append(k)
        return _probe_result(k, EanInitialPlacementFeasibilityStatus.FEASIBLE)

    lower, upper, _ = _search_fixed_k_capacity_interval(
        canonical_lower_bound=4,
        packing_upper_bound=10,
        probe=probe,
    )

    assert (lower, upper) == (10, 10)
    assert calls == [4, 5, 6, 8, 10]


def test_fixed_k_search_bisects_known_infeasible_bracket() -> None:
    calls: list[int] = []

    def probe(k: int) -> EanInitialPlacementCapacityProbeResult:
        calls.append(k)
        status = (
            EanInitialPlacementFeasibilityStatus.FEASIBLE
            if k <= 7
            else EanInitialPlacementFeasibilityStatus.INFEASIBLE
        )
        return _probe_result(k, status)

    lower, upper, _ = _search_fixed_k_capacity_interval(
        canonical_lower_bound=4,
        packing_upper_bound=10,
        probe=probe,
    )

    assert (lower, upper) == (7, 7)
    assert calls == [4, 5, 6, 8, 7]


def test_fixed_k_search_can_start_from_an_analytic_certificate() -> None:
    calls: list[int] = []

    def probe(k: int) -> EanInitialPlacementCapacityProbeResult:
        calls.append(k)
        return _probe_result(k, EanInitialPlacementFeasibilityStatus.INFEASIBLE)

    lower, upper, best = _search_fixed_k_capacity_interval(
        canonical_lower_bound=10,
        packing_upper_bound=20,
        probe=probe,
        probe_initial_lower_bound=False,
    )

    assert (lower, upper, best) == (10, 10, None)
    assert calls == [11]


def test_fixed_k_search_keeps_safe_interval_after_unknown_probe() -> None:
    finished: list[tuple[int, str, int, int]] = []

    def probe(k: int) -> EanInitialPlacementCapacityProbeResult:
        status = (
            EanInitialPlacementFeasibilityStatus.UNKNOWN
            if k == 8
            else EanInitialPlacementFeasibilityStatus.FEASIBLE
        )
        return _probe_result(k, status)

    lower, upper, _ = _search_fixed_k_capacity_interval(
        canonical_lower_bound=4,
        packing_upper_bound=10,
        probe=probe,
        on_probe_finished=lambda result, lower, upper: finished.append(
            (result.fleet_count, result.status.value, lower, upper)
        ),
    )

    assert (lower, upper) == (6, 10)
    assert finished == [
        (4, "feasible", 4, 10),
        (5, "feasible", 5, 10),
        (6, "feasible", 6, 10),
        (8, "unknown", 6, 10),
    ]


@pytest.mark.parametrize(
    ("exact_capacity", "lower", "upper"),
    ((4, 4, 5), (5, 4, 4)),
)
def test_capacity_certificate_rejects_invalid_exact_capacity(
    exact_capacity: int,
    lower: int,
    upper: int,
) -> None:
    certificate = _capacity_certificate(
        exact_capacity=exact_capacity,
        lower=lower,
        upper=upper,
    )

    with pytest.raises(ValueError, match="closed lower/upper interval"):
        certificate.validate()


def test_capacity_certificate_accepts_closed_exact_capacity() -> None:
    _capacity_certificate(exact_capacity=4, lower=4, upper=4).validate()


def test_capacity_certificate_distinguishes_analytic_and_solver_lower_bounds() -> None:
    unsupported = _capacity_certificate(exact_capacity=5, lower=5, upper=5)
    with pytest.raises(ValueError, match="needs a solver incumbent"):
        unsupported.validate()

    replace(unsupported, solver_incumbent_lower_bound=5).validate()


def test_capacity_certificate_rejects_incomplete_headway_pairs() -> None:
    scenario = _single_station_ring()
    problem = EanInitialPlacementCapacityProblem(
        scenario=scenario,
        config=_config(),
        artifact_builder=replace(
            RingEanBuildArtifactBuilder(switch_cycle=("entry",)),
            headway_pair_builder=_NoHeadwayPairBuilder(),
        ),
    )

    with pytest.raises(NotImplementedError, match="all-pairs"):
        problem.validate()


def test_capacity_optimizer_closes_small_ring_capacity() -> None:
    pytest.importorskip("gurobipy")
    scenario = _single_station_ring()
    config = _config()
    result = EanInitialPlacementCapacityOptimizer().solve(
        EanInitialPlacementCapacityProblem(
            scenario=scenario,
            config=config,
            artifact_builder=RingEanBuildArtifactBuilder(
                switch_cycle=("entry",),
            ),
        )
    )

    assert result.certificate.solver_status == "EXACT"
    assert result.certificate.packing_upper_bound == 4
    assert result.certificate.certified_lower_bound == 4
    assert result.certificate.solver_incumbent_lower_bound == 4
    assert result.certificate.solver_upper_bound == 4
    assert result.certificate.exact_capacity == 4
    assert result.certificate.recommended_available_fleet_count == 4
    assert result.fleet_plan is not None
    assert len(result.fleet_plan.active_cabin_ids) == 4
    assert len(result.probes) == 1


def test_fixed_k_feasibility_keeps_every_cabin_active() -> None:
    pytest.importorskip("gurobipy")
    capacity_problem = EanInitialPlacementCapacityProblem(
        scenario=_single_station_ring(),
        config=_config(),
        artifact_builder=RingEanBuildArtifactBuilder(switch_cycle=("entry",)),
    )

    result = EanInitialPlacementFeasibilityOptimizer().solve(
        EanInitialPlacementFeasibilityProblem(capacity_problem, fleet_count=4)
    )

    assert result.status is EanInitialPlacementFeasibilityStatus.FEASIBLE
    assert result.fleet_plan is not None
    assert result.fleet_plan.active_cabin_ids == (0, 1, 2, 3)
    assert result.artifact is not None
    assert result.artifact.fleet_cardinality_mode is EanFleetCardinalityMode.EXACT

    assert result.movement_plan is not None
    mip_start = EanInitialPlacementMipStart(
        movement_plan=result.movement_plan,
        fleet_plan=result.fleet_plan,
    )
    lifted = _lift_initial_placement_mip_start(
        mip_start,
        available_fleet_count=5,
    )
    assert lifted.fleet_plan.available_fleet_count == 5
    assert lifted.fleet_plan.active_cabin_ids == (0, 1, 2, 3)
    assert lifted.fleet_plan.inactive_cabin_ids == (4,)

    infeasible = EanInitialPlacementFeasibilityOptimizer().solve(
        EanInitialPlacementFeasibilityProblem(
            capacity_problem,
            fleet_count=5,
            mip_start=mip_start,
        )
    )
    assert infeasible.status is EanInitialPlacementFeasibilityStatus.INFEASIBLE
    assert infeasible.mip_start_fleet_count == 4
    assert infeasible.mip_start_source is EanInitialPlacementMipStartSource.PROVIDED


def test_fixed_k_feasibility_needs_no_periodic_certificate_for_short_horizon() -> None:
    pytest.importorskip("gurobipy")
    scenario = _single_station_ring()
    scenario = replace(
        scenario,
        operating=replace(
            scenario.operating,
            cabin_length_m=25.0,
            min_clearance_m=0.0,
        ),
    )
    scenario.validate()
    capacity_problem = EanInitialPlacementCapacityProblem(
        scenario=scenario,
        config=replace(_config(), horizon_seconds=1.0),
        artifact_builder=RingEanBuildArtifactBuilder(switch_cycle=("entry",)),
    )

    result = EanInitialPlacementFeasibilityOptimizer().solve(
        EanInitialPlacementFeasibilityProblem(
            capacity_problem=capacity_problem,
            fleet_count=1,
        )
    )

    assert result.status is EanInitialPlacementFeasibilityStatus.FEASIBLE
    assert result.mip_start_fleet_count is None
    assert result.mip_start_source is None


def test_delayed_fixed_k_matches_eager_and_certifies_full_separation() -> None:
    pytest.importorskip("gurobipy")
    capacity_problem = EanInitialPlacementCapacityProblem(
        scenario=_single_station_ring(),
        config=_config(),
        artifact_builder=RingEanBuildArtifactBuilder(switch_cycle=("entry",)),
    )
    optimizer = EanInitialPlacementFeasibilityOptimizer(
        EanInitialPlacementCapacitySolveConfig(
            headway_generation_mode=(
                EanInitialPlacementHeadwayGenerationMode.DELAYED_VIOLATIONS
            )
        )
    )

    feasible = optimizer.solve(
        EanInitialPlacementFeasibilityProblem(capacity_problem, fleet_count=4)
    )
    infeasible = optimizer.solve(
        EanInitialPlacementFeasibilityProblem(capacity_problem, fleet_count=5)
    )

    assert feasible.status is EanInitialPlacementFeasibilityStatus.FEASIBLE
    assert feasible.final_headway_separation_complete
    assert feasible.artifact is not None
    assert feasible.artifact.headway_pair_scope.value == "sparse"
    assert feasible.separation_round_count >= 1
    assert feasible.violations_found_per_round[-1] == 0
    assert infeasible.status is EanInitialPlacementFeasibilityStatus.INFEASIBLE


def test_delayed_fixed_k_total_budget_can_return_unknown() -> None:
    pytest.importorskip("gurobipy")
    capacity_problem = EanInitialPlacementCapacityProblem(
        scenario=_single_station_ring(),
        config=_config(),
        artifact_builder=RingEanBuildArtifactBuilder(switch_cycle=("entry",)),
    )
    optimizer = EanInitialPlacementFeasibilityOptimizer(
        EanInitialPlacementCapacitySolveConfig(
            headway_generation_mode=(
                EanInitialPlacementHeadwayGenerationMode.DELAYED_VIOLATIONS
            ),
            delayed_headway=EanInitialPlacementDelayedHeadwayConfig(
                total_time_limit_seconds=1e-9
            ),
        )
    )

    result = optimizer.solve(
        EanInitialPlacementFeasibilityProblem(capacity_problem, fleet_count=4)
    )

    assert result.status is EanInitialPlacementFeasibilityStatus.UNKNOWN
    assert not result.final_headway_separation_complete


def test_dynamic_headway_pool_adds_one_binary_and_two_constraints() -> None:
    gp = pytest.importorskip("gurobipy")
    scenario = _single_station_ring()
    config = _config()
    fleet_config = EanFleetConfig(
        mode=EanFleetMode.OPTIMIZED_INITIAL_PLACEMENT,
        available_fleet_count=2,
        cardinality_mode=EanFleetCardinalityMode.EXACT,
    )
    base_builder = RingEanBuildArtifactBuilder(
        switch_cycle=("entry",), fleet_config=fleet_config
    )
    complete = base_builder.build(scenario, config)
    sparse = replace(
        base_builder, headway_pair_builder=SparseHeadwayPairBuilder()
    ).build(scenario, config)
    model = gp.Model("dynamic_headway_pool_test")
    model.Params.OutputFlag = 0
    movement_model = EanMovementModelBuilder().build(
        model=model,
        binary_vtype=gp.GRB.BINARY,
        artifact=sparse,
        optimization_config=EanOptimizationConfig().resolved_for_fleet_mode(
            EanFleetMode.OPTIMIZED_INITIAL_PLACEMENT
        ),
    )
    before = (int(model.NumVars), int(model.NumConstrs))
    pair = complete.headway_pairs[0]

    movement_model.headway_constraint_pool.add_pairs((pair,))

    assert int(model.NumVars) == before[0] + 1
    assert int(model.NumConstrs) == before[1] + 2
    with pytest.raises(ValueError, match="already materialized"):
        movement_model.headway_constraint_pool.add_pairs((pair,))


def test_capacity_optimizer_reuses_previous_feasible_probe() -> None:
    pytest.importorskip("gurobipy")
    result = EanInitialPlacementCapacityOptimizer().solve(
        EanInitialPlacementCapacityProblem(
            scenario=_single_station_ring(with_skip=True),
            config=_config(),
            artifact_builder=RingEanBuildArtifactBuilder(switch_cycle=("entry",)),
        )
    )

    assert tuple(probe.fleet_count for probe in result.probes) == (4, 5)
    assert result.probes[0].mip_start_fleet_count == 4
    assert result.probes[1].mip_start_fleet_count == 4
    assert (
        result.probes[0].mip_start_source
        is EanInitialPlacementMipStartSource.PERIODIC_ROUTE
    )
    assert (
        result.probes[1].mip_start_source is EanInitialPlacementMipStartSource.PROVIDED
    )


def test_capacity_progress_mode_uses_tqdm_without_gurobi_log(capsys) -> None:
    pytest.importorskip("gurobipy")
    EanInitialPlacementCapacityOptimizer(
        config=EanInitialPlacementCapacitySearchConfig(
            output_mode=EanInitialPlacementCapacityOutputMode.PROGRESS
        )
    ).solve(
        EanInitialPlacementCapacityProblem(
            scenario=_single_station_ring(),
            config=_config(),
            artifact_builder=RingEanBuildArtifactBuilder(switch_cycle=("entry",)),
        )
    )

    captured = capsys.readouterr()
    assert "OIP capacity" in captured.err
    assert "Gurobi Optimizer" not in captured.out + captured.err


def test_fixed_k_partial_mip_start_leaves_added_cabins_unset() -> None:
    gp = pytest.importorskip("gurobipy")
    scenario = _single_station_ring()
    config = _config()
    artifact = RingEanBuildArtifactBuilder(
        switch_cycle=("entry",),
        fleet_config=EanFleetConfig(
            mode=EanFleetMode.OPTIMIZED_INITIAL_PLACEMENT,
            available_fleet_count=5,
            cardinality_mode=EanFleetCardinalityMode.EXACT,
        ),
    ).build(scenario, config)
    optimization_config = EanOptimizationConfig().resolved_for_fleet_mode(
        EanFleetMode.OPTIMIZED_INITIAL_PLACEMENT
    )
    model = gp.Model("partial_fixed_k_start")
    model.Params.OutputFlag = 0
    movement = EanMovementModelBuilder().build(
        model=model,
        binary_vtype=gp.GRB.BINARY,
        artifact=artifact,
        optimization_config=optimization_config,
    )
    seed = EanAllStopMipStartSeedBuilder().build(
        artifact,
        EanHorizonFormulation.EXACT_TIME_ACTIVATION,
    )
    assert seed.fleet_plan is not None
    assert seed.fleet_plan.active_cabin_ids == (0, 1, 2, 3)

    movement.apply_partial_mip_start(seed.movement_plan, seed.fleet_plan)
    model.update()

    assert movement.fleet_model is not None
    active = movement.fleet_model.variables.cabin_active
    assert all(active[cabin_id].Start == 1.0 for cabin_id in range(4))
    assert active[4].Start == gp.GRB.UNDEFINED
    added_cabin_keys = (
        key for key in movement.fleet_model.variables.route_active if key[0] == 4
    )
    assert all(
        movement.fleet_model.variables.route_active[key].Start == gp.GRB.UNDEFINED
        for key in added_cabin_keys
    )


class _NoHeadwayPairBuilder(HeadwayPairBuilder):
    def build(self, candidates, checkpoints):
        return ()


def _probe_result(
    fleet_count: int,
    status: EanInitialPlacementFeasibilityStatus,
) -> EanInitialPlacementCapacityProbeResult:
    return EanInitialPlacementCapacityProbeResult(
        fleet_count=fleet_count,
        status=status,
        solver_status=status.value.upper(),
        setup_runtime_seconds=0.0,
        solve_runtime_seconds=0.0,
        variable_count=0,
        constraint_count=0,
        model_nonzero_count=0,
        headway_pair_count=0,
    )


def _capacity_certificate(
    *,
    exact_capacity: int,
    lower: int,
    upper: int,
) -> EanInitialPlacementCapacityCertificate:
    return EanInitialPlacementCapacityCertificate(
        packing_upper_bound=5,
        canonical_all_stop_lower_bound=4,
        certified_lower_bound=lower,
        solver_upper_bound=upper,
        exact_capacity=exact_capacity,
        recommended_available_fleet_count=exact_capacity,
        solver_status="EXACT",
        runtime_seconds=0.0,
        mip_gap=None,
        variable_count=0,
        constraint_count=0,
        model_nonzero_count=0,
        passenger_service_end_seconds=40.0,
        tail_seconds=0.0,
        operational_end_seconds=40.0,
    )


def _config(
    waiting_mode: StationWaitingMode = StationWaitingMode.NO_WAITING,
    *,
    fifo_capacity: int | None = None,
) -> EanConfig:
    return EanConfig(
        horizon_seconds=40.0,
        tail_seconds=0.0,
        cabin_capacity=1,
        station_configs=(
            StationEanConfig(
                station_id="S",
                waiting_mode=waiting_mode,
                fifo_capacity=fifo_capacity,
            ),
        ),
    )


def _single_station_ring(
    *,
    with_skip: bool = False,
    shared_skip: bool = False,
) -> Scenario:
    speed = SpeedProfile(
        kind=SpeedProfileKind.CONSTANT,
        speed_m_per_s=1.0,
    )
    service_segment_ids = ("approach", "platform", "departure")
    segments = [
        TrackSegment(
            id="approach",
            kind=TrackSegmentKind.CONNECTOR,
            from_node_id="entry",
            to_node_id="platform_entry",
            length_m=5.0,
            speed_profile=speed,
        ),
        TrackSegment(
            id="platform",
            kind=TrackSegmentKind.STATION,
            from_node_id="platform_entry",
            to_node_id="platform_exit",
            length_m=5.0,
            speed_profile=speed,
        ),
        TrackSegment(
            id="departure",
            kind=TrackSegmentKind.CONNECTOR,
            from_node_id="platform_exit",
            to_node_id="exit",
            length_m=5.0,
            speed_profile=speed,
        ),
        TrackSegment(
            id="rope",
            kind=TrackSegmentKind.ROPE,
            from_node_id="exit",
            to_node_id="entry",
            length_m=5.0,
            speed_profile=speed,
        ),
    ]
    routes = [
        StationRoute(
            id="service",
            station_id="S",
            kind=StationRouteKind.SERVICE,
            segment_ids=service_segment_ids,
            allows_boarding=True,
            allows_alighting=True,
        )
    ]
    if with_skip:
        if shared_skip:
            skip_segment_ids = service_segment_ids
        else:
            segments.append(
                TrackSegment(
                    id="skip",
                    kind=TrackSegmentKind.SKIP,
                    from_node_id="entry",
                    to_node_id="exit",
                    length_m=5.0,
                    speed_profile=speed,
                )
            )
            skip_segment_ids = ("skip",)
        routes.append(
            StationRoute(
                id="skip_route",
                station_id="S",
                kind=StationRouteKind.SKIP,
                segment_ids=skip_segment_ids,
                allows_boarding=False,
                allows_alighting=False,
            )
        )

    scenario = Scenario(
        id="single_station_capacity_ring",
        service_start_time=time(8, 0),
        service_end_time=time(8, 1),
        stations=(
            Station(
                id="S",
                kind=StationKind.TERMINAL,
                route_ids=tuple(route.id for route in routes),
            ),
        ),
        physical_nodes=(
            PhysicalNode("entry", PhysicalNodeKind.ENTRY_SWITCH, "S"),
            PhysicalNode(
                "platform_entry",
                PhysicalNodeKind.PLATFORM,
                "S",
            ),
            PhysicalNode(
                "platform_exit",
                PhysicalNodeKind.PLATFORM,
                "S",
                allows_waiting=True,
            ),
            PhysicalNode("exit", PhysicalNodeKind.EXIT_SWITCH, "S"),
        ),
        track_segments=tuple(segments),
        station_routes=tuple(routes),
        cabins=(Cabin(0),),
        cabin_initial_states=(
            CabinInitialState(
                cabin_id=0,
                node_id="entry",
                available_from=time(8, 0),
            ),
        ),
        demands=(),
        operating=OperatingParameters(
            rope_speed_m_per_s=1.0,
            station_speed_m_per_s=1.0,
            cabin_capacity=1,
            cabin_length_m=5.0,
            min_clearance_m=0.0,
        ),
    )
    scenario.validate()
    return scenario
