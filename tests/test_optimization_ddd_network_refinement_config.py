from __future__ import annotations

from dataclasses import replace

import pytest

from ropeway_skip_stop_optimization.benchmarking.ddd_cases import (
    build_three_station_network_time_refinement_probe,
)
from ropeway_skip_stop_optimization.optimization.ddd import (
    DddNetworkTimeRefinementConfig,
)
from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_round import (
    DddCpSatMasterCoupling,
)
from ropeway_skip_stop_optimization.optimization.ddd.network_refinement import (
    DddNetworkTimeRefinementSolver,
)
from ropeway_skip_stop_optimization.optimization.ddd.network_refinement_runtime import (
    DddNetworkRefinementRuntime,
)
from ropeway_skip_stop_optimization.optimization.ddd.resource_time import (
    DddResourceWindowCutMode,
)
from ropeway_skip_stop_optimization.optimization.ddd.trajectory_column_generation import (
    DddTrajectoryOptimizerMode,
)


def test_solver_preserves_flat_configuration_constructor() -> None:
    solver = DddNetworkTimeRefinementSolver(
        max_iterations=7,
        cp_sat_num_workers=2,
        trajectory_pricing_interval=3,
    )

    assert isinstance(solver, DddNetworkTimeRefinementConfig)
    assert solver.max_iterations == 7
    assert solver.cp_sat_num_workers == 2
    assert solver.trajectory_pricing_interval == 3


def test_configuration_resolves_trajectory_and_bootstrap_modes() -> None:
    restricted = DddNetworkTimeRefinementConfig(use_trajectory_slot_pool=True)
    priced = DddNetworkTimeRefinementConfig(
        trajectory_optimizer_mode=DddTrajectoryOptimizerMode.HEURISTIC_PRICING
    )
    bootstrapped = DddNetworkTimeRefinementConfig(
        cp_sat_master_coupling=DddCpSatMasterCoupling.FIXED_AGGREGATE_SUPPORT
    )

    assert restricted.trajectory_pool_enabled
    assert (
        restricted.resolved_trajectory_optimizer_mode
        is DddTrajectoryOptimizerMode.RESTRICTED_PRIMAL
    )
    assert not restricted.trajectory_pricing_enabled
    assert priced.trajectory_pool_enabled
    assert priced.trajectory_pricing_enabled
    assert bootstrapped.bootstrap_enabled
    assert not replace(bootstrapped, use_cp_sat_primal_oracle=False).bootstrap_enabled


@pytest.mark.parametrize(
    ("config", "message"),
    (
        (
            DddNetworkTimeRefinementConfig(max_iterations=0),
            "max_iterations",
        ),
        (
            DddNetworkTimeRefinementConfig(
                use_cp_sat_timed_flow_covers=True,
            ),
            "fixed aggregate",
        ),
        (
            DddNetworkTimeRefinementConfig(
                use_cp_sat_primal_oracle=False,
                cp_sat_diversification_interval=1,
            ),
            "diversification",
        ),
    ),
)
def test_configuration_rejects_incompatible_settings(
    config: DddNetworkTimeRefinementConfig,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        config.validate_solve_context(
            build_three_station_network_time_refinement_probe(),
            primal_evaluator=None,
            passenger_master_problem=None,
        )


def test_runtime_wires_configuration_into_components() -> None:
    config = DddNetworkTimeRefinementConfig(
        tolerance_seconds=0.25,
        bound_tolerance=0.5,
        output_flag=True,
        use_mandatory_resource_rows=False,
        use_universal_resource_rows=False,
        resource_window_cut_mode=DddResourceWindowCutMode.ENTRY_AND_ENERGY,
        max_resource_window_rows_per_resolve=17,
        max_resource_window_resolves_per_iteration=4,
        max_new_cuts_per_iteration=23,
        max_new_time_splits_per_iteration=3,
        max_prefix_variable_count=101,
        max_tracked_prefix_cabin_count=5,
        max_prefix_visit_index=7,
        cp_sat_time_limit_seconds=2.5,
        cp_sat_num_workers=3,
        cp_sat_retry_interval=6,
        cp_sat_max_candidate_count=4,
        cp_sat_minimum_hamming_distance=2,
        cp_sat_master_coupling=(DddCpSatMasterCoupling.FIXED_AGGREGATE_SUPPORT),
        trajectory_optimizer_mode=DddTrajectoryOptimizerMode.HEURISTIC_PRICING,
        trajectory_pricing_interval=8,
    )

    runtime = DddNetworkRefinementRuntime.build(config)

    assert runtime.network_builder.tolerance_seconds == 0.25
    assert runtime.flow_master.output_flag
    assert not runtime.flow_master.include_mandatory_resource_rows
    assert (
        runtime.master_phase_solver.resource_window_cut_mode
        is DddResourceWindowCutMode.ENTRY_AND_ENERGY
    )
    assert runtime.master_phase_solver.max_resource_window_rows_per_resolve == 17
    assert runtime.master_phase_solver.max_resource_window_resolves == 4
    assert not runtime.resource_conflict_phase_solver.use_universal_resource_rows
    assert runtime.resource_conflict_phase_solver.max_new_constraints_per_type == 23
    assert runtime.resource_conflict_phase_solver.max_time_splits == 3
    assert runtime.primal_oracle.time_limit_seconds == 2.5
    assert runtime.primal_oracle.num_workers == 3
    assert runtime.primal_oracle.max_candidate_count == 4
    assert runtime.cp_sat_round_solver.retry_interval == 6
    assert runtime.cp_sat_round_solver.max_prefix_variable_count == 101
    assert runtime.cp_sat_round_solver.max_tracked_prefix_cabin_count == 5
    assert runtime.cp_sat_round_solver.max_prefix_visit_index == 7
    assert runtime.trajectory_phase_solver.pool_enabled
    assert runtime.trajectory_phase_solver.pricing_enabled
    assert runtime.trajectory_phase_solver.pricing_interval == 8
    assert runtime.bootstrap_phase_solver.enabled
