from __future__ import annotations

from dataclasses import dataclass
import math

from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_round import (
    DddCpSatMasterCoupling,
)
from ropeway_skip_stop_optimization.optimization.ddd.network_time_space import (
    DddNetworkTimeProblem,
)
from ropeway_skip_stop_optimization.optimization.ddd.passenger_master import (
    DddPassengerMasterProblem,
)
from ropeway_skip_stop_optimization.optimization.ddd.primal_evaluation import (
    DddPrimalEvaluator,
)
from ropeway_skip_stop_optimization.optimization.ddd.resource_time import (
    DddResourceWindowCutMode,
)
from ropeway_skip_stop_optimization.optimization.ddd.trajectory_column_generation import (
    DddTrajectoryOptimizerMode,
)


@dataclass(frozen=True)
class DddNetworkTimeRefinementConfig:
    """Validated configuration shared by DDD refinement and runtime wiring."""

    max_iterations: int = 100
    tolerance_seconds: float = 1e-9
    bound_tolerance: float = 1e-9
    output_flag: bool = False
    max_new_cuts_per_iteration: int = 10_000
    max_new_time_splits_per_iteration: int = 1
    reuse_network_fragments: bool = True
    use_projected_warm_start: bool = True
    use_structural_earliest_times: bool = True
    use_mandatory_resource_rows: bool = True
    use_universal_resource_rows: bool = True
    resource_window_cut_mode: DddResourceWindowCutMode = DddResourceWindowCutMode.OFF
    max_resource_window_rows_per_resolve: int = 100
    max_resource_window_resolves_per_iteration: int = 10
    max_prefix_variable_count: int = 20_000
    max_tracked_prefix_cabin_count: int = 8
    max_prefix_visit_index: int = 3
    use_cp_sat_primal_oracle: bool = True
    cp_sat_time_limit_seconds: float = 5.0
    cp_sat_num_workers: int = 8
    cp_sat_retry_interval: int = 10
    cp_sat_max_candidate_count: int = 1
    cp_sat_minimum_hamming_distance: int = 1
    cp_sat_diversification_interval: int = 0
    cp_sat_master_coupling: DddCpSatMasterCoupling = (
        DddCpSatMasterCoupling.FREE_ROUTE_CHOICES
    )
    use_cp_sat_primal_bootstrap: bool = True
    use_cp_sat_nearest_support: bool = True
    use_cp_sat_timed_flow_covers: bool = False
    use_cp_sat_cabin_path_cuts: bool = False
    collect_cp_sat_local_explainability: bool = False
    cp_sat_local_explainability_time_limit_seconds: float = 0.5
    cp_sat_nearest_support_time_limit_seconds: float = 5.0
    # The restricted trajectory pool is a passenger-objective primal
    # heuristic. It must be enabled explicitly and is deliberately absent
    # from movement-only feasibility experiments.
    use_trajectory_slot_pool: bool = False
    trajectory_optimizer_mode: DddTrajectoryOptimizerMode = (
        DddTrajectoryOptimizerMode.OFF
    )
    trajectory_pricing_interval: int = 1
    trajectory_pricing_time_limit_seconds: float = 5.0
    trajectory_pricing_max_candidate_count: int = 1

    @property
    def trajectory_pool_enabled(self) -> bool:
        return (
            self.use_trajectory_slot_pool
            or self.trajectory_optimizer_mode is not DddTrajectoryOptimizerMode.OFF
        )

    @property
    def resolved_trajectory_optimizer_mode(self) -> DddTrajectoryOptimizerMode:
        if not self.trajectory_pool_enabled:
            return DddTrajectoryOptimizerMode.OFF
        if (
            self.use_trajectory_slot_pool
            and self.trajectory_optimizer_mode is DddTrajectoryOptimizerMode.OFF
        ):
            return DddTrajectoryOptimizerMode.RESTRICTED_PRIMAL
        return self.trajectory_optimizer_mode

    @property
    def trajectory_pricing_enabled(self) -> bool:
        return (
            self.resolved_trajectory_optimizer_mode
            is DddTrajectoryOptimizerMode.HEURISTIC_PRICING
        )

    @property
    def bootstrap_enabled(self) -> bool:
        return (
            self.use_cp_sat_primal_oracle
            and self.use_cp_sat_primal_bootstrap
            and self.cp_sat_master_coupling
            is DddCpSatMasterCoupling.FIXED_AGGREGATE_SUPPORT
        )

    def validate_solve_context(
        self,
        problem: DddNetworkTimeProblem,
        *,
        primal_evaluator: DddPrimalEvaluator | None,
        passenger_master_problem: DddPassengerMasterProblem | None,
    ) -> None:
        problem.validate()
        if not isinstance(self.trajectory_optimizer_mode, DddTrajectoryOptimizerMode):
            raise ValueError("DDD trajectory optimizer mode is invalid")
        if self.use_cp_sat_timed_flow_covers and self.cp_sat_master_coupling is not (
            DddCpSatMasterCoupling.FIXED_AGGREGATE_SUPPORT
        ):
            raise ValueError(
                "DDD timed-flow covers require fixed aggregate master coupling"
            )
        if self.use_cp_sat_cabin_path_cuts and not self.use_cp_sat_primal_oracle:
            raise ValueError("DDD cabin-path cuts require the CP-SAT primal oracle")
        if (
            self.collect_cp_sat_local_explainability
            and not self.use_cp_sat_timed_flow_covers
        ):
            raise ValueError(
                "DDD local CP-SAT explainability requires timed-flow covers"
            )
        if primal_evaluator is not None:
            primal_evaluator.validate_problem(problem)
        if passenger_master_problem is not None:
            self._validate_passenger_master_context(
                problem,
                primal_evaluator=primal_evaluator,
                passenger_master_problem=passenger_master_problem,
            )
        self._validate_numeric_limits()
        if self.cp_sat_diversification_interval > 0 and not (
            self.use_cp_sat_primal_oracle
        ):
            raise ValueError("DDD CP-SAT diversification requires the CP-SAT oracle")
        if self.trajectory_pricing_enabled and not self.use_cp_sat_primal_oracle:
            raise ValueError("DDD trajectory pricing requires the CP-SAT oracle")
        if self.trajectory_pricing_enabled and primal_evaluator is None:
            raise ValueError("DDD trajectory pricing requires a Passenger evaluator")

    def _validate_passenger_master_context(
        self,
        problem: DddNetworkTimeProblem,
        *,
        primal_evaluator: DddPrimalEvaluator | None,
        passenger_master_problem: DddPassengerMasterProblem,
    ) -> None:
        passenger_master_problem.validate()
        if passenger_master_problem.movement_problem != problem.movement_problem:
            raise ValueError(
                "DDD passenger master and refinement movement problems differ"
            )
        if primal_evaluator is None:
            raise ValueError(
                "DDD passenger master requires exact passenger primal evaluation"
            )
        evaluator_objective = getattr(primal_evaluator, "objective", None)
        if (
            evaluator_objective is not None
            and evaluator_objective != passenger_master_problem.objective
        ):
            raise ValueError(
                "DDD passenger master and primal evaluator objectives differ"
            )
        if any(
            not math.isclose(item.cost, 0.0, abs_tol=1e-12)
            for item in problem.objective.route_option_costs
        ):
            raise ValueError("DDD passenger master requires zero movement route costs")
        if self.cp_sat_master_coupling is not (
            DddCpSatMasterCoupling.FIXED_AGGREGATE_SUPPORT
        ):
            raise ValueError(
                "DDD passenger master requires fixed aggregate CP-SAT support"
            )

    def _validate_numeric_limits(self) -> None:
        if self.max_iterations <= 0:
            raise ValueError("DDD network refinement max_iterations must be positive")
        if self.max_new_cuts_per_iteration <= 0:
            raise ValueError(
                "DDD network refinement max_new_cuts_per_iteration must be positive"
            )
        if self.max_new_time_splits_per_iteration <= 0:
            raise ValueError(
                "DDD network refinement max_new_time_splits_per_iteration "
                "must be positive"
            )
        if not isinstance(self.resource_window_cut_mode, DddResourceWindowCutMode):
            raise ValueError("DDD resource-window cut mode is invalid")
        if self.max_resource_window_rows_per_resolve <= 0:
            raise ValueError("DDD resource-window row limit must be positive")
        if self.max_resource_window_resolves_per_iteration <= 0:
            raise ValueError("DDD resource-window resolve limit must be positive")
        if self.max_prefix_variable_count <= 0:
            raise ValueError("DDD prefix variable budget must be positive")
        if self.max_tracked_prefix_cabin_count <= 0:
            raise ValueError("DDD tracked-prefix cabin budget must be positive")
        if self.max_prefix_visit_index <= 0:
            raise ValueError("DDD prefix visit budget must be positive")
        if self.cp_sat_time_limit_seconds <= 0:
            raise ValueError("DDD CP-SAT time limit must be positive")
        if self.cp_sat_nearest_support_time_limit_seconds <= 0:
            raise ValueError("DDD nearest-support CP-SAT time limit must be positive")
        if self.cp_sat_local_explainability_time_limit_seconds <= 0:
            raise ValueError(
                "DDD local explainability CP-SAT time limit must be positive"
            )
        if self.cp_sat_num_workers <= 0:
            raise ValueError("DDD CP-SAT worker count must be positive")
        if self.cp_sat_retry_interval <= 0:
            raise ValueError("DDD CP-SAT retry interval must be positive")
        if self.cp_sat_max_candidate_count <= 0:
            raise ValueError("DDD CP-SAT candidate count must be positive")
        if self.cp_sat_minimum_hamming_distance <= 0:
            raise ValueError("DDD CP-SAT Hamming distance must be positive")
        if self.cp_sat_diversification_interval < 0:
            raise ValueError("DDD CP-SAT diversification interval must be nonnegative")
        if self.trajectory_pricing_interval <= 0:
            raise ValueError("DDD trajectory pricing interval must be positive")
        if self.trajectory_pricing_time_limit_seconds <= 0:
            raise ValueError("DDD trajectory pricing time limit must be positive")
        if self.trajectory_pricing_max_candidate_count <= 0:
            raise ValueError("DDD trajectory pricing candidate count must be positive")
        if self.tolerance_seconds < 0 or self.bound_tolerance < 0:
            raise ValueError("DDD network refinement tolerances must be nonnegative")
