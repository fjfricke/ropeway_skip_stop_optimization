from __future__ import annotations

import math
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import Any, Callable

from tqdm.auto import tqdm

from ropeway_skip_stop_optimization.models import Scenario
from ropeway_skip_stop_optimization.optimization.ean.artifact import EanBuildArtifact
from ropeway_skip_stop_optimization.optimization.ean.builders.artifact_builder import (
    RingEanBuildArtifactBuilder,
)
from ropeway_skip_stop_optimization.optimization.ean.builders.network_artifact_builder import (
    NetworkEanBuildArtifactBuilder,
)
from ropeway_skip_stop_optimization.optimization.ean.builders.headway_candidate_builder import (
    SwitchVisitHeadwayCandidateBuilder,
)
from ropeway_skip_stop_optimization.optimization.ean.builders.headway_pair_builder import (
    AllPairsHeadwayPairBuilder,
    SparseHeadwayPairBuilder,
)
from ropeway_skip_stop_optimization.optimization.ean.builders.timing_builder import (
    PhysicalSkipStopTimingBuilder,
)
from ropeway_skip_stop_optimization.optimization.ean.capacity_preparation import (
    EanPreparedRingBuilder,
)
from ropeway_skip_stop_optimization.optimization.ean.fleet import EanFleetPlan
from ropeway_skip_stop_optimization.optimization.ean.models import (
    EanConfig,
    EanFleetCardinalityMode,
    EanFleetConfig,
    EanFleetMode,
    EanHeadwayPairScope,
)
from ropeway_skip_stop_optimization.optimization.ean.headway_separator import (
    select_headway_violation_batch,
    separate_all_headway_violations,
)
from ropeway_skip_stop_optimization.optimization.ean.optimization_config import (
    EanOptimizationConfig,
)
from ropeway_skip_stop_optimization.optimization.ean.optimizers.all_stop_mip_start import (
    EanPeriodicRouteMipStartSeedBuilder,
)
from ropeway_skip_stop_optimization.optimization.ean.optimizers.movement_model import (
    EanMovementModelBuilder,
)
from ropeway_skip_stop_optimization.optimization.ean.optimizers.solver_policy import (
    GurobiSolverPolicy,
    apply_gurobi_solver_policy,
)
from ropeway_skip_stop_optimization.optimization.ean.packing_capacity import (
    EanInitialPlacementPackingBound,
    EanInitialPlacementPackingBoundBuilder,
)
from ropeway_skip_stop_optimization.optimization.ean.plan import EanMovementPlan
from ropeway_skip_stop_optimization.optimization.ean.periodic_route import (
    EanPeriodicRouteCapacityBound,
    EanPeriodicRouteCapacityBoundBuilder,
)
from ropeway_skip_stop_optimization.optimization.ean.validation import (
    validate_ean_movement_plan_against_artifact,
)


INTEGER_BOUND_EPSILON = 1e-6
FINITE_HORIZON_CAPACITY_STATEMENT = (
    "The certified interval applies to the current optimized-initial-placement "
    "movement model through operational horizon H. It does not prove "
    "indefinite cyclic operation or sink/depot recovery."
)


class EanInitialPlacementFeasibilityStatus(StrEnum):
    FEASIBLE = "feasible"
    INFEASIBLE = "infeasible"
    UNKNOWN = "unknown"


class EanInitialPlacementCapacityOutputMode(StrEnum):
    SILENT = "silent"
    PROGRESS = "progress"
    GUROBI_LOG = "gurobi_log"


class EanInitialPlacementMipStartSource(StrEnum):
    ALL_STOP = "all_stop"
    PERIODIC_ROUTE = "periodic_route"
    PROVIDED = "provided"


class EanInitialPlacementHeadwayGenerationMode(StrEnum):
    EAGER_ALL_PAIRS = "eager_all_pairs"
    DELAYED_VIOLATIONS = "delayed_violations"


@dataclass(frozen=True)
class EanInitialPlacementDelayedHeadwayConfig:
    total_time_limit_seconds: float = 300.0
    max_new_pairs_per_round: int = 10_000
    violation_tolerance_seconds: float = 1e-5

    def validate(self) -> None:
        if self.total_time_limit_seconds <= 0:
            raise ValueError("delayed total time limit must be positive")
        if self.max_new_pairs_per_round <= 0:
            raise ValueError("delayed pair batch size must be positive")
        if self.violation_tolerance_seconds < 0:
            raise ValueError("delayed headway tolerance must be nonnegative")


@dataclass(frozen=True)
class EanInitialPlacementHeadwayGenerationRound:
    round_index: int
    violations_found: int
    pairs_added: int
    total_materialized_pairs: int
    variable_count: int
    constraint_count: int
    remaining_budget_seconds: float


@dataclass(frozen=True)
class EanInitialPlacementMipStart:
    movement_plan: EanMovementPlan
    fleet_plan: EanFleetPlan


@dataclass(frozen=True)
class EanInitialPlacementCapacityProblem:
    scenario: Scenario
    config: EanConfig
    artifact_builder: RingEanBuildArtifactBuilder | NetworkEanBuildArtifactBuilder

    def validate(self) -> None:
        self.scenario.validate()
        self.config.validate()
        if isinstance(self.artifact_builder, RingEanBuildArtifactBuilder) and not isinstance(
            self.artifact_builder.timing_builder, PhysicalSkipStopTimingBuilder
        ):
            raise NotImplementedError(
                "initial placement capacity certification currently requires "
                "physical legacy timing or the canonical network builder"
            )
        if not isinstance(
            self.artifact_builder.headway_candidate_builder,
            SwitchVisitHeadwayCandidateBuilder,
        ):
            raise NotImplementedError(
                "initial placement capacity certification requires the "
                "complete switch-visit headway candidate builder"
            )
        if not isinstance(
            self.artifact_builder.headway_pair_builder, AllPairsHeadwayPairBuilder
        ):
            raise NotImplementedError(
                "initial placement capacity certification requires the "
                "complete all-pairs headway builder"
            )


@dataclass(frozen=True)
class EanInitialPlacementFeasibilityProblem:
    capacity_problem: EanInitialPlacementCapacityProblem
    fleet_count: int
    mip_start: EanInitialPlacementMipStart | None = None

    def validate(self) -> None:
        self.capacity_problem.validate()
        if self.fleet_count <= 0:
            raise ValueError("fixed fleet count must be positive")
        if self.mip_start is not None:
            self.mip_start.movement_plan.validate()
            self.mip_start.fleet_plan.validate()
            if self.mip_start.fleet_plan.available_fleet_count > self.fleet_count:
                raise ValueError("fixed-K MIP start cannot use a larger source fleet")


@dataclass(frozen=True)
class EanInitialPlacementCapacitySolveConfig:
    """Per-probe solver configuration for the fixed-K capacity search."""

    solver_policy: GurobiSolverPolicy = field(
        default_factory=lambda: GurobiSolverPolicy(time_limit_seconds=300.0)
    )
    optimization_config: EanOptimizationConfig = field(
        default_factory=EanOptimizationConfig
    )
    log_to_console: bool = False
    headway_generation_mode: EanInitialPlacementHeadwayGenerationMode = (
        EanInitialPlacementHeadwayGenerationMode.EAGER_ALL_PAIRS
    )
    delayed_headway: EanInitialPlacementDelayedHeadwayConfig = field(
        default_factory=EanInitialPlacementDelayedHeadwayConfig
    )

    def validate(self) -> None:
        self.solver_policy.validate()
        self.delayed_headway.validate()


@dataclass(frozen=True)
class EanInitialPlacementCapacitySearchConfig:
    solve_config: EanInitialPlacementCapacitySolveConfig = field(
        default_factory=EanInitialPlacementCapacitySolveConfig
    )
    output_mode: EanInitialPlacementCapacityOutputMode = (
        EanInitialPlacementCapacityOutputMode.SILENT
    )

    def validate(self) -> None:
        self.solve_config.validate()
        if (
            self.solve_config.log_to_console
            and self.output_mode is not EanInitialPlacementCapacityOutputMode.GUROBI_LOG
        ):
            raise ValueError(
                "select gurobi_log output mode instead of enabling the nested "
                "probe console log"
            )


@dataclass(frozen=True)
class EanInitialPlacementCapacityProbeResult:
    fleet_count: int
    status: EanInitialPlacementFeasibilityStatus
    solver_status: str
    setup_runtime_seconds: float
    solve_runtime_seconds: float
    variable_count: int
    constraint_count: int
    model_nonzero_count: int
    headway_pair_count: int
    headway_generation_mode: EanInitialPlacementHeadwayGenerationMode = (
        EanInitialPlacementHeadwayGenerationMode.EAGER_ALL_PAIRS
    )
    resolve_count: int = 0
    separation_round_count: int = 0
    violations_found_per_round: tuple[int, ...] = ()
    separation_runtime_seconds: float = 0.0
    augmentation_runtime_seconds: float = 0.0
    final_headway_separation_complete: bool = False
    mip_start_fleet_count: int | None = None
    mip_start_source: EanInitialPlacementMipStartSource | None = None
    artifact: EanBuildArtifact | None = None
    movement_plan: EanMovementPlan | None = None
    fleet_plan: EanFleetPlan | None = None

    def validate(self) -> None:
        if self.fleet_count <= 0:
            raise ValueError("probe fleet count must be positive")
        if min(
            self.setup_runtime_seconds,
            self.solve_runtime_seconds,
            self.separation_runtime_seconds,
            self.augmentation_runtime_seconds,
        ) < 0:
            raise ValueError("probe runtimes must be nonnegative")
        if self.resolve_count < 0 or self.separation_round_count < 0:
            raise ValueError("probe round counts must be nonnegative")
        if len(self.violations_found_per_round) != self.separation_round_count:
            raise ValueError("probe separation metrics must have one value per round")
        if (
            min(
                self.variable_count,
                self.constraint_count,
                self.model_nonzero_count,
                self.headway_pair_count,
            )
            < 0
        ):
            raise ValueError("probe model sizes must be nonnegative")
        if self.mip_start_fleet_count is not None and not (
            0 < self.mip_start_fleet_count <= self.fleet_count
        ):
            raise ValueError("probe MIP-start fleet count lies outside fixed K")
        if (self.mip_start_fleet_count is None) != (self.mip_start_source is None):
            raise ValueError("probe MIP-start source and fleet count must coexist")
        has_solution = self.movement_plan is not None or self.fleet_plan is not None
        if self.status is EanInitialPlacementFeasibilityStatus.FEASIBLE:
            if (
                self.artifact is None
                or self.movement_plan is None
                or self.fleet_plan is None
            ):
                raise ValueError("feasible probe needs artifact and extracted plans")
            if len(self.fleet_plan.active_cabin_ids) != self.fleet_count:
                raise ValueError("feasible fixed-K probe must activate every cabin")
            if (
                self.headway_generation_mode
                is EanInitialPlacementHeadwayGenerationMode.DELAYED_VIOLATIONS
                and not self.final_headway_separation_complete
            ):
                raise ValueError("feasible delayed probe needs a complete final separation")
        elif has_solution:
            raise ValueError("non-feasible probe must not expose a solution")


@dataclass(frozen=True)
class EanInitialPlacementCapacityCertificate:
    packing_upper_bound: int
    canonical_all_stop_lower_bound: int
    certified_lower_bound: int
    solver_upper_bound: int
    exact_capacity: int | None
    recommended_available_fleet_count: int
    solver_status: str
    runtime_seconds: float
    mip_gap: float | None
    variable_count: int
    constraint_count: int
    model_nonzero_count: int
    passenger_service_end_seconds: float
    tail_seconds: float
    operational_end_seconds: float
    periodic_route_bound: EanPeriodicRouteCapacityBound | None = None
    solver_incumbent_lower_bound: int | None = None
    finite_horizon_statement: str = FINITE_HORIZON_CAPACITY_STATEMENT

    def validate(self) -> None:
        if not 0 < self.canonical_all_stop_lower_bound <= self.packing_upper_bound:
            raise ValueError("invalid canonical all-stop lower bound")
        if self.periodic_route_bound is not None:
            self.periodic_route_bound.validate()
            if not (
                self.canonical_all_stop_lower_bound
                <= self.periodic_route_bound.fleet_lower_bound
            ):
                raise ValueError("periodic route must dominate the all-stop bound")
        analytic_lower_bound = max(
            self.canonical_all_stop_lower_bound,
            min(
                self.packing_upper_bound,
                self.periodic_route_bound.fleet_lower_bound,
            )
            if self.periodic_route_bound is not None
            else self.canonical_all_stop_lower_bound,
        )
        if (
            not analytic_lower_bound
            <= self.certified_lower_bound
            <= self.solver_upper_bound
            <= self.packing_upper_bound
        ):
            raise ValueError("invalid initial placement capacity interval")
        if self.exact_capacity is not None and (
            self.exact_capacity != self.certified_lower_bound
            or self.certified_lower_bound != self.solver_upper_bound
        ):
            raise ValueError("exact capacity requires a closed lower/upper interval")
        if self.solver_incumbent_lower_bound is not None and not (
            self.canonical_all_stop_lower_bound
            <= self.solver_incumbent_lower_bound
            <= self.certified_lower_bound
        ):
            raise ValueError("solver incumbent lies outside certified bounds")
        if (
            self.certified_lower_bound > analytic_lower_bound
            and self.solver_incumbent_lower_bound != self.certified_lower_bound
        ):
            raise ValueError(
                "a lower bound above the analytic certificates needs a solver incumbent"
            )
        if self.recommended_available_fleet_count != (
            self.exact_capacity
            if self.exact_capacity is not None
            else self.solver_upper_bound
        ):
            raise ValueError(
                "recommended fleet count must use exact capacity or upper bound"
            )
        if (
            min(
                self.runtime_seconds,
                self.passenger_service_end_seconds,
                self.tail_seconds,
            )
            < 0
        ):
            raise ValueError("certificate times must be nonnegative")
        if (
            self.operational_end_seconds
            != self.passenger_service_end_seconds + self.tail_seconds
        ):
            raise ValueError("capacity operational horizon must equal T + tail")


@dataclass(frozen=True)
class EanInitialPlacementCapacityResult:
    packing_bound: EanInitialPlacementPackingBound
    certificate: EanInitialPlacementCapacityCertificate
    probes: tuple[EanInitialPlacementCapacityProbeResult, ...]
    artifact: EanBuildArtifact | None
    movement_plan: EanMovementPlan | None
    fleet_plan: EanFleetPlan | None


@dataclass(frozen=True)
class EanInitialPlacementFeasibilityOptimizer:
    config: EanInitialPlacementCapacitySolveConfig = field(
        default_factory=EanInitialPlacementCapacitySolveConfig
    )
    headway_probe_strategies: tuple[EanHeadwayProbeStrategy, ...] = field(
        default_factory=lambda: (
            EanEagerHeadwayProbeStrategy(),
            EanDelayedHeadwayProbeStrategy(),
        )
    )

    def solve(
        self,
        problem: EanInitialPlacementFeasibilityProblem,
        *,
        on_headway_round: Callable[[EanInitialPlacementHeadwayGenerationRound], None]
        | None = None,
    ) -> EanInitialPlacementCapacityProbeResult:
        try:
            import gurobipy as gp
            from gurobipy import GRB
        except ImportError as error:
            raise RuntimeError(
                "gurobipy is required for EAN capacity optimization"
            ) from error

        problem.validate()
        self.config.validate()
        started = time.monotonic()
        capacity_problem = problem.capacity_problem
        artifact_builder = replace(
            capacity_problem.artifact_builder,
            fleet_config=EanFleetConfig(
                mode=EanFleetMode.OPTIMIZED_INITIAL_PLACEMENT,
                available_fleet_count=problem.fleet_count,
                cardinality_mode=EanFleetCardinalityMode.EXACT,
            ),
            headway_pair_builder=(
                SparseHeadwayPairBuilder()
                if self.config.headway_generation_mode
                is EanInitialPlacementHeadwayGenerationMode.DELAYED_VIOLATIONS
                else capacity_problem.artifact_builder.headway_pair_builder
            ),
        )
        artifact = artifact_builder.build(
            capacity_problem.scenario, capacity_problem.config
        )
        optimization_config = self.config.optimization_config.resolved_for_fleet_mode(
            EanFleetMode.OPTIMIZED_INITIAL_PLACEMENT
        )
        model = gp.Model(f"ean_initial_placement_feasibility_{problem.fleet_count}")
        model.Params.OutputFlag = 1 if self.config.log_to_console else 0
        apply_gurobi_solver_policy(model, self.config.solver_policy)
        movement_model = EanMovementModelBuilder().build(
            model=model,
            binary_vtype=GRB.BINARY,
            artifact=artifact,
            optimization_config=optimization_config,
        )
        if movement_model.fleet_model is None:
            raise RuntimeError("fixed-K capacity probe requires fleet variables")
        mip_start = problem.mip_start
        mip_start_source: EanInitialPlacementMipStartSource | None = (
            EanInitialPlacementMipStartSource.PROVIDED
            if mip_start is not None
            else None
        )
        if mip_start is None:
            route_seed_builder = EanPeriodicRouteMipStartSeedBuilder()
            route_bound = route_seed_builder.route_bound_builder.build_optional(artifact)
            if route_bound is not None:
                mip_start_source = EanInitialPlacementMipStartSource.PERIODIC_ROUTE
                periodic_seed = route_seed_builder.build(
                    artifact,
                    optimization_config.formulation.horizon,
                    route_bound=route_bound,
                )
                if periodic_seed.fleet_plan is None:
                    raise RuntimeError(
                        "initial-placement periodic seed needs a fleet plan"
                    )
                mip_start = EanInitialPlacementMipStart(
                    movement_plan=periodic_seed.movement_plan,
                    fleet_plan=periodic_seed.fleet_plan,
                )
        mip_start_fleet_count: int | None = None
        if mip_start is not None:
            lifted_mip_start = _lift_initial_placement_mip_start(
                mip_start,
                available_fleet_count=problem.fleet_count,
            )
            mip_start_fleet_count = len(
                lifted_mip_start.fleet_plan.active_cabin_ids
            )
            if mip_start_fleet_count == problem.fleet_count:
                movement_model.apply_mip_start(
                    lifted_mip_start.movement_plan,
                    lifted_mip_start.fleet_plan,
                )
            else:
                movement_model.apply_partial_mip_start(
                    lifted_mip_start.movement_plan,
                    lifted_mip_start.fleet_plan,
                )
        model.setObjective(0.0, GRB.MINIMIZE)
        model.update()
        setup_runtime = time.monotonic() - started
        variable_count = int(model.NumVars)
        constraint_count = int(model.NumConstrs)
        nonzero_count = int(model.NumNZs)
        context = EanHeadwayProbeContext(
            problem=problem,
            config=self.config,
            artifact=artifact,
            movement_model=movement_model,
            model=model,
            grb=GRB,
            started=started,
            setup_runtime=setup_runtime,
            initial_variable_count=variable_count,
            initial_constraint_count=constraint_count,
            initial_nonzero_count=nonzero_count,
            mip_start_fleet_count=mip_start_fleet_count,
            mip_start_source=mip_start_source,
            on_headway_round=on_headway_round,
        )
        return _select_headway_probe_strategy(
            self.headway_probe_strategies,
            self.config.headway_generation_mode,
        ).solve(context)


@dataclass(frozen=True)
class EanHeadwayProbeContext:
    problem: EanInitialPlacementFeasibilityProblem
    config: EanInitialPlacementCapacitySolveConfig
    artifact: EanBuildArtifact
    movement_model: Any
    model: Any
    grb: Any
    started: float
    setup_runtime: float
    initial_variable_count: int
    initial_constraint_count: int
    initial_nonzero_count: int
    mip_start_fleet_count: int | None
    mip_start_source: EanInitialPlacementMipStartSource | None
    on_headway_round: Callable[[EanInitialPlacementHeadwayGenerationRound], None] | None


class EanHeadwayProbeStrategy(ABC):
    """Solve one prepared fixed-K model under one headway-generation policy."""

    @property
    @abstractmethod
    def mode(self) -> EanInitialPlacementHeadwayGenerationMode:
        """Generation mode implemented by this strategy."""

    @abstractmethod
    def solve(
        self, context: EanHeadwayProbeContext
    ) -> EanInitialPlacementCapacityProbeResult:
        """Solve and return a fully validated probe result."""


@dataclass(frozen=True)
class EanEagerHeadwayProbeStrategy(EanHeadwayProbeStrategy):
    @property
    def mode(self) -> EanInitialPlacementHeadwayGenerationMode:
        return EanInitialPlacementHeadwayGenerationMode.EAGER_ALL_PAIRS

    def solve(
        self, context: EanHeadwayProbeContext
    ) -> EanInitialPlacementCapacityProbeResult:
        return _solve_eager_headway_probe(context)


@dataclass(frozen=True)
class EanDelayedHeadwayProbeStrategy(EanHeadwayProbeStrategy):
    @property
    def mode(self) -> EanInitialPlacementHeadwayGenerationMode:
        return EanInitialPlacementHeadwayGenerationMode.DELAYED_VIOLATIONS

    def solve(
        self, context: EanHeadwayProbeContext
    ) -> EanInitialPlacementCapacityProbeResult:
        return _solve_delayed_headway_probe(
            problem=context.problem,
            config=context.config,
            artifact=context.artifact,
            movement_model=context.movement_model,
            model=context.model,
            grb=context.grb,
            started=context.started,
            setup_runtime=context.setup_runtime,
            mip_start_fleet_count=context.mip_start_fleet_count,
            mip_start_source=context.mip_start_source,
            on_headway_round=context.on_headway_round,
        )


def _select_headway_probe_strategy(
    strategies: tuple[EanHeadwayProbeStrategy, ...],
    mode: EanInitialPlacementHeadwayGenerationMode,
) -> EanHeadwayProbeStrategy:
    matches = tuple(strategy for strategy in strategies if strategy.mode is mode)
    if len(matches) != 1:
        raise ValueError(
            f"headway generation mode {mode.value!r} needs exactly one strategy"
        )
    return matches[0]


def _solve_eager_headway_probe(
    context: EanHeadwayProbeContext,
) -> EanInitialPlacementCapacityProbeResult:
    model = context.model
    grb = context.grb
    artifact = context.artifact
    model.optimize()
    solver_status = _solver_status_name(int(model.Status), grb)
    solve_runtime = float(model.Runtime)
    status = EanInitialPlacementFeasibilityStatus.UNKNOWN
    movement_plan = None
    fleet_plan = None
    if int(model.Status) == int(grb.INFEASIBLE):
        status = EanInitialPlacementFeasibilityStatus.INFEASIBLE
    elif int(model.SolCount) > 0:
        movement_plan = context.movement_model.extract_plan()
        validate_ean_movement_plan_against_artifact(
            artifact,
            movement_plan,
            tolerance_seconds=1e-5,
        ).raise_for_errors()
        fleet_plan = context.movement_model.fleet_model.extract_plan()
        status = EanInitialPlacementFeasibilityStatus.FEASIBLE
    result = EanInitialPlacementCapacityProbeResult(
        fleet_count=context.problem.fleet_count,
        status=status,
        solver_status=solver_status,
        setup_runtime_seconds=context.setup_runtime,
        solve_runtime_seconds=solve_runtime,
        variable_count=context.initial_variable_count,
        constraint_count=context.initial_constraint_count,
        model_nonzero_count=context.initial_nonzero_count,
        headway_pair_count=len(artifact.headway_pairs),
        headway_generation_mode=context.config.headway_generation_mode,
        mip_start_fleet_count=context.mip_start_fleet_count,
        mip_start_source=context.mip_start_source,
        artifact=(
            artifact
            if status is EanInitialPlacementFeasibilityStatus.FEASIBLE
            else None
        ),
        movement_plan=movement_plan,
        fleet_plan=fleet_plan,
    )
    result.validate()
    return result


def _solve_delayed_headway_probe(
    *,
    problem: EanInitialPlacementFeasibilityProblem,
    config: EanInitialPlacementCapacitySolveConfig,
    artifact: EanBuildArtifact,
    movement_model: Any,
    model: Any,
    grb: Any,
    started: float,
    setup_runtime: float,
    mip_start_fleet_count: int | None,
    mip_start_source: EanInitialPlacementMipStartSource | None,
    on_headway_round: Callable[[EanInitialPlacementHeadwayGenerationRound], None]
    | None,
) -> EanInitialPlacementCapacityProbeResult:
    if artifact.headway_pair_scope is not EanHeadwayPairScope.SPARSE:
        raise RuntimeError("delayed headway solve requires a sparse artifact")
    delayed = config.delayed_headway
    pool = movement_model.headway_constraint_pool
    # The OIP Big-M rows amplify near-integral binary deviations. Certification
    # therefore needs an integrality tolerance materially below the physical
    # headway tolerance to exclude trickle-flow incumbents.
    model.Params.IntFeasTol = 1e-9
    model.Params.FeasibilityTol = 1e-8
    solve_runtime = 0.0
    separation_runtime = 0.0
    augmentation_runtime = 0.0
    solve_count = 0
    violations_per_round: list[int] = []
    solver_status = "TOTAL_TIME_LIMIT"

    def remaining() -> float:
        return max(0.0, delayed.total_time_limit_seconds - (time.monotonic() - started))

    def result(
        status: EanInitialPlacementFeasibilityStatus,
        *,
        movement_plan: EanMovementPlan | None = None,
        fleet_plan: EanFleetPlan | None = None,
        final_separation: bool = False,
    ) -> EanInitialPlacementCapacityProbeResult:
        model.update()
        probe = EanInitialPlacementCapacityProbeResult(
            fleet_count=problem.fleet_count,
            status=status,
            solver_status=solver_status,
            setup_runtime_seconds=setup_runtime,
            solve_runtime_seconds=solve_runtime,
            variable_count=int(model.NumVars),
            constraint_count=int(model.NumConstrs),
            model_nonzero_count=int(model.NumNZs),
            headway_pair_count=len(pool.materialized_pair_ids),
            headway_generation_mode=EanInitialPlacementHeadwayGenerationMode.DELAYED_VIOLATIONS,
            resolve_count=max(0, solve_count - 1),
            separation_round_count=len(violations_per_round),
            violations_found_per_round=tuple(violations_per_round),
            separation_runtime_seconds=separation_runtime,
            augmentation_runtime_seconds=augmentation_runtime,
            final_headway_separation_complete=final_separation,
            mip_start_fleet_count=mip_start_fleet_count,
            mip_start_source=mip_start_source,
            artifact=artifact if status is EanInitialPlacementFeasibilityStatus.FEASIBLE else None,
            movement_plan=movement_plan,
            fleet_plan=fleet_plan,
        )
        probe.validate()
        return probe

    while remaining() > 0.0:
        per_solve_limit = remaining()
        if config.solver_policy.time_limit_seconds is not None:
            per_solve_limit = min(
                per_solve_limit, config.solver_policy.time_limit_seconds
            )
        model.Params.TimeLimit = max(1e-6, per_solve_limit)
        model.optimize()
        solve_count += 1
        solve_runtime += float(model.Runtime)
        solver_status = _solver_status_name(int(model.Status), grb)
        if int(model.Status) == int(grb.INFEASIBLE):
            return result(EanInitialPlacementFeasibilityStatus.INFEASIBLE)
        if int(model.SolCount) <= 0:
            return result(EanInitialPlacementFeasibilityStatus.UNKNOWN)

        try:
            movement_plan = movement_model.extract_plan()
            fleet_plan = movement_model.fleet_model.extract_plan()
        except ValueError:
            if int(model.Status) == int(grb.OPTIMAL):
                raise
            return result(EanInitialPlacementFeasibilityStatus.UNKNOWN)
        # Suppress only headways here; sparse artifacts are otherwise validated
        # exactly like complete artifacts. The separator below is exhaustive.
        non_headway_artifact = replace(
            artifact,
            headway_pairs=(),
            headway_pair_scope=EanHeadwayPairScope.COMPLETE,
        )
        non_headway_report = validate_ean_movement_plan_against_artifact(
            non_headway_artifact,
            movement_plan,
            tolerance_seconds=delayed.violation_tolerance_seconds,
        )
        if non_headway_report.errors:
            if int(model.Status) == int(grb.OPTIMAL):
                non_headway_report.raise_for_errors()
            return result(EanInitialPlacementFeasibilityStatus.UNKNOWN)

        separation_started = time.monotonic()
        violations = separate_all_headway_violations(
            artifact,
            movement_plan,
            tolerance_seconds=delayed.violation_tolerance_seconds,
        )
        separation_runtime += time.monotonic() - separation_started
        violations_per_round.append(len(violations))
        materialized_violations = {
            item.pair.id for item in violations
        } & pool.materialized_pair_ids
        if materialized_violations:
            raise RuntimeError(
                "materialized headway pairs remain violated: "
                f"{sorted(materialized_violations)[:10]!r}"
            )
        if not violations:
            if remaining() <= 0.0:
                return result(EanInitialPlacementFeasibilityStatus.UNKNOWN)
            if on_headway_round is not None:
                on_headway_round(
                    _headway_round_metric(
                        len(violations_per_round), 0, 0, pool, model, remaining()
                    )
                )
            return result(
                EanInitialPlacementFeasibilityStatus.FEASIBLE,
                movement_plan=movement_plan,
                fleet_plan=fleet_plan,
                final_separation=True,
            )
        if remaining() <= 0.0:
            if on_headway_round is not None:
                on_headway_round(
                    _headway_round_metric(
                        len(violations_per_round),
                        len(violations),
                        0,
                        pool,
                        model,
                        remaining(),
                    )
                )
            return result(EanInitialPlacementFeasibilityStatus.UNKNOWN)

        batch = select_headway_violation_batch(
            violations,
            limit=delayed.max_new_pairs_per_round,
            excluded_pair_ids=pool.materialized_pair_ids,
        )
        if not batch:
            raise RuntimeError("violated headway pairs could not be augmented")
        augmentation_started = time.monotonic()
        pool.add_pairs(tuple(item.pair for item in batch))
        augmentation_runtime += time.monotonic() - augmentation_started
        if on_headway_round is not None:
            on_headway_round(
                _headway_round_metric(
                    len(violations_per_round),
                    len(violations),
                    len(batch),
                    pool,
                    model,
                    remaining(),
                )
            )
        if remaining() <= 0.0:
            return result(EanInitialPlacementFeasibilityStatus.UNKNOWN)
        # Structural changes invalidate the previous incumbent. Explicitly
        # discard Gurobi's solution state before installing it as a fresh,
        # partial MIP start for the augmented model.
        model.reset()
        movement_model.apply_mip_start(movement_plan, fleet_plan)

    return result(EanInitialPlacementFeasibilityStatus.UNKNOWN)


def _headway_round_metric(
    round_index: int,
    violations_found: int,
    pairs_added: int,
    pool: Any,
    model: Any,
    remaining_budget_seconds: float,
) -> EanInitialPlacementHeadwayGenerationRound:
    model.update()
    return EanInitialPlacementHeadwayGenerationRound(
        round_index=round_index,
        violations_found=violations_found,
        pairs_added=pairs_added,
        total_materialized_pairs=len(pool.materialized_pair_ids),
        variable_count=int(model.NumVars),
        constraint_count=int(model.NumConstrs),
        remaining_budget_seconds=remaining_budget_seconds,
    )


@dataclass(frozen=True)
class EanInitialPlacementCapacityOptimizer:
    """Find a finite-horizon OIP fleet capacity through exact fixed-K probes."""

    config: EanInitialPlacementCapacitySearchConfig = field(
        default_factory=EanInitialPlacementCapacitySearchConfig
    )
    packing_bound_builder: EanInitialPlacementPackingBoundBuilder = field(
        default_factory=EanInitialPlacementPackingBoundBuilder
    )
    periodic_route_bound_builder: EanPeriodicRouteCapacityBoundBuilder = field(
        default_factory=EanPeriodicRouteCapacityBoundBuilder
    )

    def solve(
        self, problem: EanInitialPlacementCapacityProblem
    ) -> EanInitialPlacementCapacityResult:
        problem.validate()
        self.config.validate()
        prepared = EanPreparedRingBuilder(
            packing_bound_builder=self.packing_bound_builder,
            periodic_route_bound_builder=self.periodic_route_bound_builder,
        ).build(
            scenario=problem.scenario,
            config=problem.config,
            artifact_builder=problem.artifact_builder,
        )
        packing_bound = prepared.packing_bound
        canonical_lower_bound = prepared.canonical_all_stop_lower_bound
        periodic_route_bound = prepared.periodic_route_bound
        certified_initial_lower_bound = prepared.certified_lower_bound
        feasibility_optimizer = EanInitialPlacementFeasibilityOptimizer(
            replace(
                self.config.solve_config,
                log_to_console=(
                    self.config.output_mode
                    is EanInitialPlacementCapacityOutputMode.GUROBI_LOG
                ),
            )
        )
        probes: list[EanInitialPlacementCapacityProbeResult] = []
        best_mip_start: EanInitialPlacementMipStart | None = None

        def probe(k: int) -> EanInitialPlacementCapacityProbeResult:
            nonlocal best_mip_start
            result = feasibility_optimizer.solve(
                EanInitialPlacementFeasibilityProblem(
                    problem,
                    k,
                    mip_start=best_mip_start,
                ),
                on_headway_round=progress.headway_round,
            )
            probes.append(result)
            if result.status is EanInitialPlacementFeasibilityStatus.FEASIBLE:
                if result.movement_plan is None or result.fleet_plan is None:
                    raise RuntimeError("validated feasible probe lost its plans")
                best_mip_start = EanInitialPlacementMipStart(
                    movement_plan=result.movement_plan,
                    fleet_plan=result.fleet_plan,
                )
            return result

        progress = _CapacitySearchProgress(
            enabled=(
                self.config.output_mode
                is EanInitialPlacementCapacityOutputMode.PROGRESS
            ),
            canonical_lower_bound=certified_initial_lower_bound,
            packing_upper_bound=packing_bound.packing_upper_bound,
        )
        with progress:
            lower_bound, upper_bound, best_probe = _search_fixed_k_capacity_interval(
                canonical_lower_bound=certified_initial_lower_bound,
                packing_upper_bound=packing_bound.packing_upper_bound,
                probe=probe,
                probe_initial_lower_bound=(
                    certified_initial_lower_bound == canonical_lower_bound
                ),
                on_probe_started=progress.probe_started,
                on_probe_finished=progress.probe_finished,
            )

        exact_capacity = lower_bound if lower_bound == upper_bound else None
        certificate = EanInitialPlacementCapacityCertificate(
            packing_upper_bound=packing_bound.packing_upper_bound,
            canonical_all_stop_lower_bound=canonical_lower_bound,
            certified_lower_bound=lower_bound,
            solver_upper_bound=upper_bound,
            exact_capacity=exact_capacity,
            recommended_available_fleet_count=(
                exact_capacity if exact_capacity is not None else upper_bound
            ),
            solver_status="EXACT" if exact_capacity is not None else "OPEN_INTERVAL",
            runtime_seconds=sum(
                item.setup_runtime_seconds
                + item.solve_runtime_seconds
                + item.separation_runtime_seconds
                + item.augmentation_runtime_seconds
                for item in probes
            ),
            mip_gap=None,
            variable_count=best_probe.variable_count if best_probe is not None else 0,
            constraint_count=(
                best_probe.constraint_count if best_probe is not None else 0
            ),
            model_nonzero_count=(
                best_probe.model_nonzero_count if best_probe is not None else 0
            ),
            passenger_service_end_seconds=problem.config.passenger_service_end_seconds,
            tail_seconds=problem.config.tail_seconds,
            operational_end_seconds=problem.config.operational_end_seconds,
            periodic_route_bound=periodic_route_bound,
            solver_incumbent_lower_bound=(
                best_probe.fleet_count if best_probe is not None else None
            ),
        )
        certificate.validate()
        return EanInitialPlacementCapacityResult(
            packing_bound=packing_bound,
            certificate=certificate,
            probes=tuple(probes),
            artifact=best_probe.artifact if best_probe is not None else None,
            movement_plan=(best_probe.movement_plan if best_probe is not None else None),
            fleet_plan=(best_probe.fleet_plan if best_probe is not None else None),
        )


def _search_fixed_k_capacity_interval(
    *,
    canonical_lower_bound: int,
    packing_upper_bound: int,
    probe: Callable[[int], EanInitialPlacementCapacityProbeResult],
    probe_initial_lower_bound: bool = True,
    on_probe_started: Callable[[int, int, int], None] | None = None,
    on_probe_finished: Callable[
        [EanInitialPlacementCapacityProbeResult, int, int], None
    ]
    | None = None,
) -> tuple[int, int, EanInitialPlacementCapacityProbeResult | None]:
    """Bracket and tighten the largest feasible fixed fleet count."""

    lower_bound = canonical_lower_bound
    best_probe: EanInitialPlacementCapacityProbeResult | None = None
    if probe_initial_lower_bound:
        _notify_probe_started(
            on_probe_started,
            canonical_lower_bound,
            canonical_lower_bound,
            packing_upper_bound,
        )
        first = probe(canonical_lower_bound)
        if first.status is not EanInitialPlacementFeasibilityStatus.FEASIBLE:
            _notify_probe_finished(
                on_probe_finished,
                first,
                canonical_lower_bound,
                packing_upper_bound,
            )
            raise RuntimeError(
                "the configured initial capacity lower bound must be feasible "
                f"when probed; received {first.status.value}"
            )
        best_probe = first
        _notify_probe_finished(
            on_probe_finished,
            first,
            lower_bound,
            packing_upper_bound,
        )
    first_infeasible: int | None = None
    step = 1
    while lower_bound < packing_upper_bound:
        next_k = min(canonical_lower_bound + step, packing_upper_bound)
        _notify_probe_started(
            on_probe_started,
            next_k,
            lower_bound,
            packing_upper_bound,
        )
        current = probe(next_k)
        if current.status is EanInitialPlacementFeasibilityStatus.FEASIBLE:
            lower_bound = next_k
            best_probe = current
            _notify_probe_finished(
                on_probe_finished,
                current,
                lower_bound,
                packing_upper_bound,
            )
            if lower_bound == packing_upper_bound:
                break
            step *= 2
            continue
        if current.status is EanInitialPlacementFeasibilityStatus.INFEASIBLE:
            first_infeasible = next_k
            _notify_probe_finished(
                on_probe_finished,
                current,
                lower_bound,
                first_infeasible - 1,
            )
        else:
            _notify_probe_finished(
                on_probe_finished,
                current,
                lower_bound,
                packing_upper_bound,
            )
        break

    if first_infeasible is None:
        return lower_bound, packing_upper_bound, best_probe

    low = lower_bound
    high = first_infeasible
    while high - low > 1:
        midpoint = (low + high) // 2
        _notify_probe_started(on_probe_started, midpoint, low, high - 1)
        current = probe(midpoint)
        if current.status is EanInitialPlacementFeasibilityStatus.FEASIBLE:
            low = midpoint
            best_probe = current
        elif current.status is EanInitialPlacementFeasibilityStatus.INFEASIBLE:
            high = midpoint
        else:
            # A timeout cannot tighten a mathematical capacity interval.
            _notify_probe_finished(on_probe_finished, current, low, high - 1)
            break
        _notify_probe_finished(on_probe_finished, current, low, high - 1)
    return low, high - 1, best_probe


@dataclass
class _CapacitySearchProgress:
    enabled: bool
    canonical_lower_bound: int
    packing_upper_bound: int
    _bar: Any | None = field(init=False, default=None)

    def __enter__(self) -> _CapacitySearchProgress:
        if self.enabled:
            self._bar = tqdm(
                total=max(
                    1,
                    self.packing_upper_bound - self.canonical_lower_bound,
                ),
                desc="OIP capacity",
                unit="bound",
                dynamic_ncols=True,
            )
        return self

    def __exit__(self, *_: object) -> None:
        if self._bar is not None:
            self._bar.close()

    def probe_started(self, fleet_count: int, lower: int, upper: int) -> None:
        if self._bar is None:
            return
        self._bar.set_postfix_str(
            f"K={fleet_count} solving interval=[{lower},{upper}]",
            refresh=True,
        )

    def probe_finished(
        self,
        result: EanInitialPlacementCapacityProbeResult,
        lower: int,
        upper: int,
    ) -> None:
        if self._bar is None:
            return
        initial_width = self.packing_upper_bound - self.canonical_lower_bound
        if initial_width == 0:
            completed = self._bar.total
        else:
            completed = initial_width - (upper - lower)
        self._bar.update(max(0, completed - self._bar.n))
        warm_start_count = (
            "none"
            if result.mip_start_fleet_count is None
            else str(result.mip_start_fleet_count)
        )
        warm_start_source = (
            "none" if result.mip_start_source is None else result.mip_start_source.value
        )
        self._bar.set_postfix_str(
            " ".join(
                (
                    f"K={result.fleet_count}",
                    result.status.value,
                    f"interval=[{lower},{upper}]",
                    f"setup={result.setup_runtime_seconds:.1f}s",
                    f"solve={result.solve_runtime_seconds:.1f}s",
                    f"vars={result.variable_count}",
                    f"pairs={result.headway_pair_count}",
                    f"warm={warm_start_source}:{warm_start_count}",
                )
            ),
            refresh=True,
        )

    def headway_round(
        self, metric: EanInitialPlacementHeadwayGenerationRound
    ) -> None:
        if self._bar is None:
            return
        self._bar.set_postfix_str(
            " ".join(
                (
                    f"round={metric.round_index}",
                    f"violations={metric.violations_found}",
                    f"added={metric.pairs_added}",
                    f"pairs={metric.total_materialized_pairs}",
                    f"vars={metric.variable_count}",
                    f"rows={metric.constraint_count}",
                    f"remaining={metric.remaining_budget_seconds:.1f}s",
                )
            ),
            refresh=True,
        )


def _lift_initial_placement_mip_start(
    mip_start: EanInitialPlacementMipStart,
    *,
    available_fleet_count: int,
) -> EanInitialPlacementMipStart:
    """Lift a smaller feasible fleet solution into a larger fixed-K model."""

    source_fleet = mip_start.fleet_plan
    if source_fleet.available_fleet_count > available_fleet_count:
        raise ValueError("cannot lift a MIP start from a larger fleet")
    active_ids = frozenset(source_fleet.active_cabin_ids)
    if any(cabin_id >= available_fleet_count for cabin_id in active_ids):
        raise ValueError("MIP-start cabin id lies outside the target fleet")
    lifted_fleet = replace(
        source_fleet,
        available_fleet_count=available_fleet_count,
        inactive_cabin_ids=tuple(
            cabin_id
            for cabin_id in range(available_fleet_count)
            if cabin_id not in active_ids
        ),
    )
    lifted_fleet.validate()
    return replace(mip_start, fleet_plan=lifted_fleet)


def _notify_probe_started(
    callback: Callable[[int, int, int], None] | None,
    fleet_count: int,
    lower: int,
    upper: int,
) -> None:
    if callback is not None:
        callback(fleet_count, lower, upper)


def _notify_probe_finished(
    callback: Callable[[EanInitialPlacementCapacityProbeResult, int, int], None] | None,
    result: EanInitialPlacementCapacityProbeResult,
    lower: int,
    upper: int,
) -> None:
    if callback is not None:
        callback(result, lower, upper)


def solver_integer_upper_bound(
    *,
    packing_upper_bound: int,
    objective_bound: float | None,
    incumbent_lower_bound: int,
) -> int:
    """Legacy helper retained for historical max-active benchmark fixtures."""
    if packing_upper_bound <= 0:
        raise ValueError("packing upper bound must be positive")
    if not 0 <= incumbent_lower_bound <= packing_upper_bound:
        raise ValueError("incumbent lower bound lies outside packing bound")
    if objective_bound is None:
        return packing_upper_bound
    rounded_bound = math.floor(objective_bound + INTEGER_BOUND_EPSILON)
    return max(incumbent_lower_bound, min(packing_upper_bound, rounded_bound))


def _solver_status_name(status: int, grb: Any) -> str:
    names = {
        int(grb.OPTIMAL): "OPTIMAL",
        int(grb.TIME_LIMIT): "TIME_LIMIT",
        int(grb.INFEASIBLE): "INFEASIBLE",
        int(grb.INF_OR_UNBD): "INF_OR_UNBD",
        int(grb.UNBOUNDED): "UNBOUNDED",
        int(grb.NUMERIC): "NUMERIC",
        int(grb.INTERRUPTED): "INTERRUPTED",
    }
    return names.get(status, f"STATUS_{status}")
