from __future__ import annotations

from dataclasses import dataclass

from ropeway_skip_stop_optimization.optimization.ddd.bootstrap_phase import (
    DddBootstrapPhaseSolver,
)
from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_primal import (
    DddCpSatPrimalOracle,
)
from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_round import (
    DddCpSatRoundSolver,
)
from ropeway_skip_stop_optimization.optimization.ddd.lifting_phase import (
    DddLiftingPhaseSolver,
)
from ropeway_skip_stop_optimization.optimization.ddd.local_resource_explainability import (
    DddCpSatLocalResourceAnalyzer,
)
from ropeway_skip_stop_optimization.optimization.ddd.network_master_phase import (
    DddNetworkMasterPhaseSolver,
)
from ropeway_skip_stop_optimization.optimization.ddd.network_refinement_config import (
    DddNetworkTimeRefinementConfig,
)
from ropeway_skip_stop_optimization.optimization.ddd.network_time_space import (
    DddAnonymousFlowDecomposer,
    DddAnonymousFlowMaster,
    DddAnonymousFlowWarmStartProjector,
    DddLayeredTimeNetworkBuilder,
    DddNetworkPathProblemAdapter,
)
from ropeway_skip_stop_optimization.optimization.ddd.recovery_phase import (
    DddRecoveryPhaseSolver,
)
from ropeway_skip_stop_optimization.optimization.ddd.resource_conflict_phase import (
    DddResourceConflictPhaseSolver,
)
from ropeway_skip_stop_optimization.optimization.ddd.termination_policy import (
    DddRoundTerminationPolicy,
)
from ropeway_skip_stop_optimization.optimization.ddd.time_refinement import (
    DddCellFreeSupportRecovery,
    DddStrictTimeCellLifter,
)
from ropeway_skip_stop_optimization.optimization.ddd.trajectory_phase import (
    DddTrajectoryPhaseSolver,
)


@dataclass(frozen=True)
class DddNetworkRefinementRuntime:
    """Concrete solver components derived from one validated configuration."""

    network_builder: DddLayeredTimeNetworkBuilder
    flow_master: DddAnonymousFlowMaster
    master_phase_solver: DddNetworkMasterPhaseSolver
    warm_start_projector: DddAnonymousFlowWarmStartProjector
    flow_decomposer: DddAnonymousFlowDecomposer
    path_problem_adapter: DddNetworkPathProblemAdapter
    lifting_phase_solver: DddLiftingPhaseSolver
    resource_conflict_phase_solver: DddResourceConflictPhaseSolver
    trajectory_phase_solver: DddTrajectoryPhaseSolver
    termination_policy: DddRoundTerminationPolicy
    recovery_phase_solver: DddRecoveryPhaseSolver
    primal_oracle: DddCpSatPrimalOracle
    nearest_support_oracle: DddCpSatPrimalOracle
    trajectory_pricing_oracle: DddCpSatPrimalOracle
    local_resource_analyzer: DddCpSatLocalResourceAnalyzer
    cp_sat_round_solver: DddCpSatRoundSolver
    bootstrap_phase_solver: DddBootstrapPhaseSolver

    @classmethod
    def build(
        cls,
        config: DddNetworkTimeRefinementConfig,
    ) -> DddNetworkRefinementRuntime:
        lifter = DddStrictTimeCellLifter(tolerance_seconds=config.tolerance_seconds)
        recovery = DddCellFreeSupportRecovery(
            tolerance_seconds=config.tolerance_seconds
        )
        return cls(
            network_builder=DddLayeredTimeNetworkBuilder(
                tolerance_seconds=config.tolerance_seconds,
                use_structural_earliest_times=config.use_structural_earliest_times,
            ),
            flow_master=DddAnonymousFlowMaster(
                output_flag=config.output_flag,
                include_mandatory_resource_rows=(config.use_mandatory_resource_rows),
            ),
            master_phase_solver=DddNetworkMasterPhaseSolver(
                resource_window_cut_mode=config.resource_window_cut_mode,
                max_resource_window_rows_per_resolve=(
                    config.max_resource_window_rows_per_resolve
                ),
                max_resource_window_resolves=(
                    config.max_resource_window_resolves_per_iteration
                ),
            ),
            warm_start_projector=DddAnonymousFlowWarmStartProjector(),
            flow_decomposer=DddAnonymousFlowDecomposer(),
            path_problem_adapter=DddNetworkPathProblemAdapter(),
            lifting_phase_solver=DddLiftingPhaseSolver(
                lifter=lifter,
                max_time_splits=config.max_new_time_splits_per_iteration,
                tolerance_seconds=config.tolerance_seconds,
            ),
            resource_conflict_phase_solver=DddResourceConflictPhaseSolver(
                use_universal_resource_rows=config.use_universal_resource_rows,
                max_new_constraints_per_type=config.max_new_cuts_per_iteration,
                max_time_splits=config.max_new_time_splits_per_iteration,
                max_prefix_variable_count=config.max_prefix_variable_count,
                max_tracked_prefix_cabin_count=(config.max_tracked_prefix_cabin_count),
                max_prefix_visit_index=config.max_prefix_visit_index,
                tolerance_seconds=config.tolerance_seconds,
            ),
            trajectory_phase_solver=DddTrajectoryPhaseSolver(
                pool_enabled=config.trajectory_pool_enabled,
                pricing_enabled=config.trajectory_pricing_enabled,
                pricing_interval=config.trajectory_pricing_interval,
            ),
            termination_policy=DddRoundTerminationPolicy(
                bound_tolerance=config.bound_tolerance
            ),
            recovery_phase_solver=DddRecoveryPhaseSolver(recovery=recovery),
            primal_oracle=DddCpSatPrimalOracle(
                time_limit_seconds=config.cp_sat_time_limit_seconds,
                num_workers=config.cp_sat_num_workers,
                log_search_progress=config.output_flag,
                max_candidate_count=config.cp_sat_max_candidate_count,
                minimum_hamming_distance=config.cp_sat_minimum_hamming_distance,
            ),
            nearest_support_oracle=DddCpSatPrimalOracle(
                time_limit_seconds=(config.cp_sat_nearest_support_time_limit_seconds),
                num_workers=config.cp_sat_num_workers,
                log_search_progress=config.output_flag,
                max_candidate_count=1,
                minimum_hamming_distance=1,
            ),
            trajectory_pricing_oracle=DddCpSatPrimalOracle(
                time_limit_seconds=config.trajectory_pricing_time_limit_seconds,
                num_workers=config.cp_sat_num_workers,
                log_search_progress=config.output_flag,
                max_candidate_count=config.trajectory_pricing_max_candidate_count,
                minimum_hamming_distance=config.cp_sat_minimum_hamming_distance,
            ),
            local_resource_analyzer=DddCpSatLocalResourceAnalyzer(
                time_limit_seconds=(
                    config.cp_sat_local_explainability_time_limit_seconds
                ),
                num_workers=config.cp_sat_num_workers,
            ),
            cp_sat_round_solver=DddCpSatRoundSolver(
                use_primal_oracle=config.use_cp_sat_primal_oracle,
                master_coupling=config.cp_sat_master_coupling,
                use_timed_flow_covers=config.use_cp_sat_timed_flow_covers,
                use_cabin_path_cuts=config.use_cp_sat_cabin_path_cuts,
                use_nearest_support=config.use_cp_sat_nearest_support,
                collect_local_explainability=(
                    config.collect_cp_sat_local_explainability
                ),
                retry_interval=config.cp_sat_retry_interval,
                diversification_interval=config.cp_sat_diversification_interval,
                max_prefix_variable_count=config.max_prefix_variable_count,
                max_tracked_prefix_cabin_count=(config.max_tracked_prefix_cabin_count),
                max_prefix_visit_index=config.max_prefix_visit_index,
            ),
            bootstrap_phase_solver=DddBootstrapPhaseSolver(
                enabled=config.bootstrap_enabled
            ),
        )
