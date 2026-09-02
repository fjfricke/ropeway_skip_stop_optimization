from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest

import ropeway_skip_stop_optimization.optimization.ddd.fixed_k_seed as fixed_k_seed

from ropeway_skip_stop_optimization.benchmarking.ddd_fixed_k_campaign import (
    DddFixedKCampaignConfig,
    derive_available_fleet_intervals,
    derive_skip_stop_benefit_interval,
)
from ropeway_skip_stop_optimization.examples.registry import get_example
from ropeway_skip_stop_optimization.models import DerivedSpatialRole
from ropeway_skip_stop_optimization.optimization.ddd import (
    DddCpSatPrimalResult,
    DddCpSatPrimalStatus,
    DddFixedKExperimentProfile,
    DddFixedKOperatingMode,
    DddFixedKProfileConfig,
    DddFixedKSeedCoordinator,
    DddFixedKSeedStatus,
    DddFixedKStartPolicy,
    DddFixedKTrajectoryProblem,
    DddRouteDecision,
    EanArtifactToDddMovementProblemAdapter,
)
from ropeway_skip_stop_optimization.benchmarking.ddd_scaling import (
    build_initial_ddd_network_problem,
)
from ropeway_skip_stop_optimization.benchmarking.ddd_root_cg_application import (
    _format_compact_progress,
    _format_compact_result,
)
from ropeway_skip_stop_optimization.optimization.ean import (
    CanonicalFixedKRopeCabinStartBuilder,
    EanPassengerCandidateBuilder,
    EanPassengerObjective,
    SparseHeadwayPairBuilder,
)


EXAMPLE_ID = "five_station_circle_cw_half_skip_no_wait_v0"


def _fixed_problem(
    mode: DddFixedKOperatingMode,
    *,
    cabin_count: int = 5,
) -> DddFixedKTrajectoryProblem:
    example = get_example(EXAMPLE_ID)
    scenario = example.build_scenario()
    config = example.build_ean_config(scenario)
    builder = example.build_ean_artifact_builder(scenario, config)
    artifact = replace(
        builder,
        start_builder=CanonicalFixedKRopeCabinStartBuilder(cabin_count),
        headway_pair_builder=SparseHeadwayPairBuilder(),
    ).build(scenario, config)
    trajectory_problem = EanArtifactToDddMovementProblemAdapter().build_trajectory_problem(
        artifact
    )
    result = DddFixedKTrajectoryProblem(
        trajectory_problem=trajectory_problem,
        artifact=artifact,
        passenger_build=EanPassengerCandidateBuilder().build(scenario, artifact),
        objective=EanPassengerObjective.JOURNEY_TIME,
        operating_mode=mode,
        start_policy=DddFixedKStartPolicy.CANONICAL_ROPE,
    )
    result.validate()
    return result


def test_canonical_rope_starts_are_deterministic_and_support_large_fixed_k() -> None:
    first = _fixed_problem(DddFixedKOperatingMode.SKIP_STOP, cabin_count=38)
    second = _fixed_problem(DddFixedKOperatingMode.SKIP_STOP, cabin_count=38)

    assert first.trajectory_problem.start_domain == second.trajectory_problem.start_domain
    assert first.fleet_cardinality == 38
    assert first.trajectory_problem.cabin_ids == tuple(range(38))


def test_canonical_rope_slots_respect_physical_spacing() -> None:
    example = get_example(EXAMPLE_ID)
    scenario = example.build_scenario()
    config = example.build_ean_config(scenario)
    artifact = replace(
        example.build_ean_artifact_builder(scenario, config),
        start_builder=CanonicalFixedKRopeCabinStartBuilder(1),
        headway_pair_builder=SparseHeadwayPairBuilder(),
    ).build(scenario, config)
    assert artifact.movement_network is not None
    assert artifact.headway_policy is not None
    pattern = artifact.movement_network.pattern(artifact.circulation_pattern_ids[0])
    slots = CanonicalFixedKRopeCabinStartBuilder.slots(
        scenario=scenario,
        network=artifact.movement_network,
        pattern=pattern,
        headway_policy=artifact.headway_policy,
    )
    spacing = artifact.headway_policy.spatial_spacing(DerivedSpatialRole.ROPE)
    segments = {segment.id: segment for segment in scenario.track_segments}
    groups: dict[tuple[int, str], list[float]] = {}
    for slot in slots:
        groups.setdefault(
            (slot.pattern_position, slot.segment_id), []
        ).append(slot.remaining_seconds)
    for (_, segment_id), times in groups.items():
        speed = segments[segment_id].speed_profile
        assert speed is not None and speed.speed_m_per_s is not None
        expected_seconds = spacing / speed.speed_m_per_s
        ordered = sorted(times)
        assert all(
            second - first == pytest.approx(expected_seconds)
            for first, second in zip(ordered, ordered[1:], strict=False)
        )
    assert CanonicalFixedKRopeCabinStartBuilder.canonical_start_slot_capacity(
        scenario=scenario,
        network=artifact.movement_network,
        pattern=pattern,
        headway_policy=artifact.headway_policy,
    ) == len(slots)
    with pytest.raises(ValueError, match="rope-slot capacity"):
        CanonicalFixedKRopeCabinStartBuilder(len(slots) + 1).build(
            scenario,
            config,
            artifact.movement_network,
            pattern,
            artifact.headway_policy,
        )


def test_all_stop_and_skip_stop_share_starts_but_not_route_domain() -> None:
    skip_stop = _fixed_problem(DddFixedKOperatingMode.SKIP_STOP)
    all_stop = replace(
        skip_stop,
        operating_mode=DddFixedKOperatingMode.ALL_STOP,
    )
    all_stop.validate()

    assert all_stop.trajectory_problem.start_domain == skip_stop.trajectory_problem.start_domain
    assert {
        option.decision
        for option in all_stop.resolved_trajectory_problem.movement_core.route_options
    } == {DddRouteDecision.STOP}
    assert any(
        option.decision is DddRouteDecision.SKIP
        for option in skip_stop.resolved_trajectory_problem.movement_core.route_options
    )
    assert all_stop.fingerprint != skip_stop.fingerprint


def test_fixed_k_profiles_match_campaign_budgets() -> None:
    assert DddFixedKProfileConfig.for_profile(
        DddFixedKExperimentProfile.SCREENING
    ).pricing_time_limit_tiers_seconds == (5.0, 15.0)
    assert DddFixedKProfileConfig.for_profile(
        DddFixedKExperimentProfile.REGULAR
    ).total_time_limit_seconds == 3600.0
    assert DddFixedKProfileConfig.for_profile(
        DddFixedKExperimentProfile.HEADLINE
    ).final_mip_time_limit_seconds == 1800.0


def test_available_fleet_and_skip_stop_intervals_are_proof_safe() -> None:
    assert derive_available_fleet_intervals(
        {1: (10.0, 13.0), 2: (8.0, 12.0), 3: (9.0, None)}
    ) == {
        1: (10.0, 13.0),
        2: (8.0, 12.0),
        3: (8.0, 12.0),
    }
    assert derive_skip_stop_benefit_interval(
        all_stop_lower=100.0,
        all_stop_upper=110.0,
        skip_stop_lower=70.0,
        skip_stop_upper=80.0,
    ) == pytest.approx((20.0, 40.0))


def test_campaign_config_rejects_nonpositive_k() -> None:
    with pytest.raises(ValueError, match="positive K"):
        DddFixedKCampaignConfig.from_dict(
            {
                "campaign_id": "bad",
                "example_id": EXAMPLE_ID,
                "k_values": [0],
            }
        )


def test_campaign_config_parses_coordinated_primal_settings() -> None:
    config = DddFixedKCampaignConfig.from_dict(
        {
            "campaign_id": "hybrid",
            "example_id": EXAMPLE_ID,
            "k_values": [39],
            "coordinated_primal_time_limit_seconds": 20,
            "coordinated_primal_interval": 5,
            "coordinated_primal_workers": 4,
            "coordinated_primal_candidate_count": 2,
            "coordinated_primal_maximum_preference_count": 300,
            "neighborhood_primal_time_limit_seconds": 30,
            "neighborhood_primal_interval": 4,
            "neighborhood_primal_cabin_counts": [4, 8],
            "neighborhood_primal_workers": 3,
            "neighborhood_primal_candidate_count": 2,
            "neighborhood_primal_maximum_preference_count": 250,
            "primal_package_evaluation_time_limit_seconds": 12,
        }
    )

    assert config.coordinated_primal_time_limit_seconds == pytest.approx(20.0)
    assert config.coordinated_primal_interval == 5
    assert config.coordinated_primal_workers == 4
    assert config.coordinated_primal_candidate_count == 2
    assert config.coordinated_primal_maximum_preference_count == 300
    assert config.neighborhood_primal_time_limit_seconds == pytest.approx(30.0)
    assert config.neighborhood_primal_interval == 4
    assert config.neighborhood_primal_cabin_counts == (4, 8)
    assert config.neighborhood_primal_workers == 3
    assert config.neighborhood_primal_candidate_count == 2
    assert config.neighborhood_primal_maximum_preference_count == 250
    assert config.primal_package_evaluation_time_limit_seconds == pytest.approx(12.0)


def test_seed_coordinator_maps_complete_cp_infeasibility(monkeypatch: pytest.MonkeyPatch) -> None:
    fixed_problem = _fixed_problem(DddFixedKOperatingMode.SKIP_STOP, cabin_count=2)
    network_problem = build_initial_ddd_network_problem(
        fixed_problem.resolved_trajectory_problem.structural_movement_problem
    )

    def no_all_stop(*args: object, **kwargs: object) -> tuple[()]:
        del args, kwargs
        raise ValueError("all-stop seed is invalid")

    class InfeasibleOracle:
        def solve(self, problem: object) -> DddCpSatPrimalResult:
            del problem
            return DddCpSatPrimalResult(
                status=DddCpSatPrimalStatus.INFEASIBLE,
                schedules=(),
                wall_seconds=0.25,
                conflict_count=1,
                branch_count=2,
                search_complete=True,
            )

    monkeypatch.setattr(
        fixed_k_seed,
        "build_ddd_all_stop_seed_trajectories",
        no_all_stop,
    )
    result = DddFixedKSeedCoordinator(
        cp_sat_time_limit_seconds=1.0,
        cp_sat_oracle=InfeasibleOracle(),  # type: ignore[arg-type]
    ).solve(network_problem)

    assert result.status is DddFixedKSeedStatus.MOVEMENT_INFEASIBLE
    assert result.cp_sat_seconds == pytest.approx(0.25)


def test_compact_fixed_k_progress_omits_irrelevant_diagnostics() -> None:
    iteration = SimpleNamespace(
        exact_pricing_cabin_count=17,
        nonexact_certified_nonnegative_pricing_count=1,
        restricted_mip_solution_count=2,
        restricted_mip_ran=True,
        round_index=5,
        global_lower_bound=560_244.9915,
        restricted_lp_value=575_000.0,
        global_upper_bound=683_915.7799,
        trajectory_count=90,
        added_trajectory_count=18,
        incompatibility_pair_count=784,
        pricing_seconds=7.34,
        pricing_tier_seconds=5.0,
        unresolved_pricing_count=0,
        remaining_budget_seconds=558.4,
    )

    output = _format_compact_progress(
        iteration,
        mode="skip_stop",
        cabin_count=18,
        max_iterations=30,
    )

    assert output.startswith(" SS K=018 r=005/030")
    assert "gap= 18.08%" in output
    assert "price=18/18" in output
    assert "reservoir" not in output
    assert "starts=" not in output
    assert "wait=" not in output


def test_compact_result_clamps_numerical_zero_gap() -> None:
    result = SimpleNamespace(
        status=SimpleNamespace(value="integer_optimal"),
        certified_lower_bound=683_915.7798719998,
        best_upper_bound=683_915.7798719999,
        total_seconds=1.95,
    )

    output = _format_compact_result(result, column_count=18)

    assert "gap=  0.00%" in output
    assert "time=00:02" in output
