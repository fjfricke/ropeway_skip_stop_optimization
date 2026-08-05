from __future__ import annotations

import math
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any

import gurobipy as gp
import numpy as np
from scipy import sparse

from ropeway_skip_stop_optimization.optimization.ean.artifact import EanBuildArtifact
from ropeway_skip_stop_optimization.optimization.ean.build_profile import (
    EanBuildProgressCallback,
    EanBuildProgressKind,
    EanBuildStage,
    EanMovementBuildMetrics,
    emit_build_progress,
)
from ropeway_skip_stop_optimization.optimization.ean.formulation_config import (
    HORIZON_ACTIVATION_EPSILON_SECONDS,
    EanHorizonFormulation,
    EanStopSkipTimingFormulation,
    EanTimeBoundFormulation,
)
from ropeway_skip_stop_optimization.optimization.ean.fleet import EanFleetPlan
from ropeway_skip_stop_optimization.optimization.ean.headway_semantics import (
    PLATFORM_EXIT_WAIT_OCCUPANCY_SEMANTICS,
    POINT_HEADWAY_SEMANTICS,
    uses_platform_exit_wait_occupancy,
)
from ropeway_skip_stop_optimization.optimization.ean.headway_classification import (
    EanFixedStartHeadwayClassifier,
    EanHeadwayPairClassifier,
    EanHeadwayPairClassification,
    EanOipInitialHeadwayClassifier,
)
from ropeway_skip_stop_optimization.optimization.ean.headway_order_families import (
    EanHeadwayOrderFamilyIndex,
)
from ropeway_skip_stop_optimization.optimization.ean.headway_merge_relaxation import (
    EanDirectMergeHeadwayRelaxationIndex,
)
from ropeway_skip_stop_optimization.optimization.ean.horizon import (
    add_visit_horizon_activation,
    visit_is_active_in_solution,
)
from ropeway_skip_stop_optimization.optimization.ean.models import (
    EanActivationReference,
    EanCabinStartKind,
    EanFleetMode,
    EanHeadwayPairScope,
    EanTimeReference,
    HeadwayCandidate,
    HeadwayCheckpointDefinition,
    HeadwayPair,
    SkipStopTiming,
    StationEanConfig,
    StationWaitingMode,
    SwitchVisitDefinition,
)
from ropeway_skip_stop_optimization.optimization.ean.optimization_config import (
    EanOptimizationConfig,
)
from ropeway_skip_stop_optimization.optimization.ean.optimizers.fleet_model import (
    EanFleetModel,
    EanFleetModelBuilder,
)
from ropeway_skip_stop_optimization.optimization.ean.plan import (
    EanCabinTrajectory,
    EanCabinVisit,
    EanMovementPlan,
    EanRouteDecision,
)
from ropeway_skip_stop_optimization.optimization.ean.time_bounds import (
    EanModelTimeBounds,
    build_ean_model_time_bounds,
)
from ropeway_skip_stop_optimization.optimization.ean.timing_formulation import (
    add_affine_stop_skip_timing_constraint,
)


VisitKey = tuple[int, int]
DEFAULT_HEADWAY_MATRIX_PAIR_BATCH_SIZE = 100_000


@dataclass(frozen=True)
class StopSkipBigMBounds:
    service_exit_ub: float
    service_exit_lb: float
    skip_exit_ub: float
    skip_exit_lb: float


@dataclass(frozen=True)
class HeadwayTimeExpressions:
    leader_clear_time: Any
    follower_enter_time: Any
    semantics_label: str


@dataclass(frozen=True)
class EanMovementVariables:
    switch_time: dict[VisitKey, Any]
    exit_switch_time: dict[VisitKey, Any]
    wait_time: dict[VisitKey, Any]
    stop: dict[VisitKey, Any]
    visit_active: dict[VisitKey, Any]
    route_active: dict[VisitKey, Any]
    checkpoint_within_horizon: dict[str, Any]
    headway_order: dict[str, Any]

    def all_variables(self) -> tuple[Any, ...]:
        groups = [
            self.switch_time,
            self.exit_switch_time,
            self.wait_time,
            self.stop,
            self.visit_active,
            self.checkpoint_within_horizon,
            self.headway_order,
        ]
        if self.route_active is not self.visit_active:
            groups.append(self.route_active)
        return tuple(variable for group in groups for variable in group.values())


@dataclass
class EanHeadwayConstraintPool:
    """Mutable pool for adding original headway disjunctions after a solve."""

    model: Any
    binary_vtype: Any
    candidate_by_id: dict[str, HeadwayCandidate]
    candidate_times_by_id: dict[str, HeadwayTimeExpressions]
    candidate_inactive_by_id: dict[str, Any]
    candidate_within_horizon: dict[str, Any]
    horizon_formulation: EanHorizonFormulation
    big_m: float
    headway_order: dict[str, Any]
    classifier: EanHeadwayPairClassifier | None = None
    order_family_index: EanHeadwayOrderFamilyIndex | None = None
    materialized_pair_id_set: set[str] = field(default_factory=set)
    order_pair_count_by_key: dict[str, int] = field(default_factory=dict)
    diagnostically_omitted_pair_ids: frozenset[str] = frozenset()
    diagnostically_omitted_checkpoint_count: int = 0
    fixed_pair_count: int = 0
    disjunctive_pair_count: int = 0
    redundant_pair_count: int = 0
    accepts_augmentation: bool = True
    progress_callback: EanBuildProgressCallback | None = None
    progress_started: float | None = None
    checkpoint_count: int | None = None
    matrix_pair_batch_size: int = DEFAULT_HEADWAY_MATRIX_PAIR_BATCH_SIZE

    @property
    def materialized_pair_ids(self) -> frozenset[str]:
        return frozenset(self.materialized_pair_id_set)

    @property
    def order_variable_count(self) -> int:
        return len(self.headway_order)

    @property
    def shared_headway_pair_count(self) -> int:
        return sum(
            pair_count
            for pair_count in self.order_pair_count_by_key.values()
            if pair_count > 1
        )

    @property
    def headway_order_variable_savings(self) -> int:
        return self.disjunctive_pair_count - self.order_variable_count

    @property
    def singleton_headway_order_family_count(self) -> int:
        return sum(
            pair_count == 1
            for pair_count in self.order_pair_count_by_key.values()
        )

    def add_pairs(self, pairs: tuple[HeadwayPair, ...]) -> None:
        if pairs and not self.accepts_augmentation:
            raise ValueError("complete headway pool does not accept augmentation")
        pair_ids = [pair.id for pair in pairs]
        if len(pair_ids) != len(set(pair_ids)):
            raise ValueError("headway augmentation batch contains duplicate pairs")
        duplicates = set(pair_ids) & self.materialized_pair_id_set
        if duplicates:
            raise ValueError(f"headway pairs already materialized: {sorted(duplicates)!r}")
        report_started = self.progress_started or perf_counter()
        initial_pair_count = len(self.materialized_pair_id_set)
        initial_fixed_pair_count = self.fixed_pair_count
        initial_disjunctive_pair_count = self.disjunctive_pair_count
        initial_order_variable_count = self.order_variable_count
        self.model.update()
        base_variable_count = int(self.model.NumVars)
        base_constraint_count = int(self.model.NumConstrs)
        if self.matrix_pair_batch_size <= 0:
            raise ValueError("headway matrix pair batch size must be positive")
        seen_checkpoint_ids: set[str] = set()
        for batch_start in range(0, len(pairs), self.matrix_pair_batch_size):
            batch = pairs[batch_start : batch_start + self.matrix_pair_batch_size]
            seen_checkpoint_ids.update(pair.checkpoint_id for pair in batch)
            self._add_pair_batch(batch)
            index = batch_start + len(batch)
            materialized = initial_pair_count + index
            emit_build_progress(
                self.progress_callback,
                stage=EanBuildStage.HEADWAY_CONSTRAINTS,
                kind=EanBuildProgressKind.PROGRESS,
                started=report_started,
                checkpoint_count=self.checkpoint_count,
                processed_checkpoint_count=(
                    len(seen_checkpoint_ids)
                    if index == len(pairs)
                    else max(0, len(seen_checkpoint_ids) - 1)
                ),
                candidate_count=len(self.candidate_by_id),
                pair_count=materialized,
                fixed_pair_count=self.fixed_pair_count,
                disjunctive_pair_count=self.disjunctive_pair_count,
                redundant_pair_count=self.redundant_pair_count,
                order_variable_count=self.order_variable_count,
                order_variable_savings=self.headway_order_variable_savings,
                variable_count=(
                    base_variable_count
                    + self.order_variable_count
                    - initial_order_variable_count
                ),
                constraint_count=(
                    base_constraint_count
                    + self.fixed_pair_count
                    - initial_fixed_pair_count
                    + 2
                    * (
                        self.disjunctive_pair_count
                        - initial_disjunctive_pair_count
                    )
                ),
            )
        self.model.update()

    def _add_pair_batch(self, pairs: tuple[HeadwayPair, ...]) -> None:
        classified: list[tuple[HeadwayPair, EanHeadwayPairClassification]] = []
        disjunctive_pairs: list[HeadwayPair] = []
        for pair in pairs:
            classification = self._validate_and_classify_pair(pair)
            self.materialized_pair_id_set.add(pair.id)
            classified.append((pair, classification))
            if classification is EanHeadwayPairClassification.REDUNDANT:
                self.redundant_pair_count += 1
            elif classification in {
                EanHeadwayPairClassification.FIXED_FORWARD,
                EanHeadwayPairClassification.FIXED_REVERSE,
            }:
                self.fixed_pair_count += 1
            else:
                self.disjunctive_pair_count += 1
                disjunctive_pairs.append(pair)

        order_reference_by_pair_id: dict[str, tuple[str, bool]] = {}
        if disjunctive_pairs:
            for pair in disjunctive_pairs:
                if self.order_family_index is None:
                    order_key = pair.id
                    pair_forward_is_order_forward = True
                else:
                    reference = self.order_family_index.reference_for_pair(pair.id)
                    order_key = reference.family_id
                    pair_forward_is_order_forward = (
                        reference.pair_forward_is_family_forward
                    )
                order_reference_by_pair_id[pair.id] = (
                    order_key,
                    pair_forward_is_order_forward,
                )
                self.order_pair_count_by_key[order_key] = (
                    self.order_pair_count_by_key.get(order_key, 0) + 1
                )

            new_order_keys = tuple(
                sorted(
                    {
                        order_key
                        for order_key, _ in order_reference_by_pair_id.values()
                        if order_key not in self.headway_order
                    }
                )
            )
            if new_order_keys:
                order_variables = self.model.addMVar(
                    len(new_order_keys),
                    vtype=self.binary_vtype,
                    name=np.asarray(
                        [f"order_{order_key}" for order_key in new_order_keys],
                        dtype=object,
                    ),
                )
                self.headway_order.update(
                    zip(new_order_keys, order_variables.tolist(), strict=True)
                )
                # Sparse-matrix columns use the stable indices assigned at update.
                self.model.update()

        row_indices: list[int] = []
        column_indices: list[int] = []
        coefficients: list[float] = []
        rhs_values: list[float] = []
        names: list[str] = []

        def append_row(expression: Any, rhs: float, name: str) -> None:
            row = len(rhs_values)
            linear = gp.LinExpr(expression)
            for term_index in range(linear.size()):
                row_indices.append(row)
                column_indices.append(int(linear.getVar(term_index).index))
                coefficients.append(float(linear.getCoeff(term_index)))
            rhs_values.append(float(rhs) - float(linear.getConstant()))
            names.append(name)

        for pair, classification in classified:
            if classification is EanHeadwayPairClassification.REDUNDANT:
                continue
            first_times, second_times, inactive = self._pair_expressions(pair)
            first_inactive, second_inactive = inactive
            semantics = first_times.semantics_label
            if classification is EanHeadwayPairClassification.FIXED_FORWARD:
                append_row(
                    first_times.leader_clear_time
                    - second_times.follower_enter_time
                    - self.big_m * (first_inactive + second_inactive),
                    -pair.headway_seconds,
                    f"headway_fixed_forward_{pair.id}_{semantics}",
                )
                continue
            if classification is EanHeadwayPairClassification.FIXED_REVERSE:
                append_row(
                    second_times.leader_clear_time
                    - first_times.follower_enter_time
                    - self.big_m * (first_inactive + second_inactive),
                    -pair.headway_seconds,
                    f"headway_fixed_reverse_{pair.id}_{semantics}",
                )
                continue
            order_key, pair_forward_is_order_forward = (
                order_reference_by_pair_id[pair.id]
            )
            order_variable = self.headway_order[order_key]
            order = (
                order_variable
                if pair_forward_is_order_forward
                else 1 - order_variable
            )
            append_row(
                first_times.leader_clear_time
                - second_times.follower_enter_time
                + self.big_m * order
                - self.big_m * (first_inactive + second_inactive),
                self.big_m - pair.headway_seconds,
                f"headway_forward_{pair.id}_{semantics}",
            )
            append_row(
                second_times.leader_clear_time
                - first_times.follower_enter_time
                - self.big_m * order
                - self.big_m * (first_inactive + second_inactive),
                -pair.headway_seconds,
                f"headway_reverse_{pair.id}_{semantics}",
            )

        if rhs_values:
            matrix = sparse.coo_matrix(
                (coefficients, (row_indices, column_indices)),
                shape=(len(rhs_values), int(self.model.NumVars)),
                dtype=np.float64,
            ).tocsr()
            self.model.addMConstr(
                matrix,
                None,
                "<",
                np.asarray(rhs_values, dtype=np.float64),
                name=names,
            )

    def _validate_and_classify_pair(
        self,
        pair: HeadwayPair,
    ) -> EanHeadwayPairClassification:
        pair.validate()
        first_candidate = self.candidate_by_id.get(pair.first_candidate_id)
        second_candidate = self.candidate_by_id.get(pair.second_candidate_id)
        if first_candidate is None or second_candidate is None:
            raise ValueError(f"headway pair {pair.id!r} references unknown candidate")
        if (
            first_candidate.checkpoint_id != pair.checkpoint_id
            or second_candidate.checkpoint_id != pair.checkpoint_id
        ):
            raise ValueError(f"headway pair {pair.id!r} checkpoint mismatch")
        return (
            self.classifier.classify(pair)
            if self.classifier is not None
            else EanHeadwayPairClassification.DISJUNCTIVE
        )

    def _pair_expressions(
        self,
        pair: HeadwayPair,
    ) -> tuple[HeadwayTimeExpressions, HeadwayTimeExpressions, tuple[Any, Any]]:
        first_candidate = self.candidate_by_id[pair.first_candidate_id]
        second_candidate = self.candidate_by_id[pair.second_candidate_id]
        first_times = self.candidate_times_by_id[first_candidate.id]
        second_times = self.candidate_times_by_id[second_candidate.id]
        # LinExpr.__iadd__ mutates its receiver; copy the cached expressions.
        first_inactive = gp.LinExpr(
            self.candidate_inactive_by_id[first_candidate.id]
        )
        second_inactive = gp.LinExpr(
            self.candidate_inactive_by_id[second_candidate.id]
        )
        if self.horizon_formulation is EanHorizonFormulation.EXACT_TIME_ACTIVATION:
            first_inactive += 1 - self.candidate_within_horizon[first_candidate.id]
            second_inactive += 1 - self.candidate_within_horizon[second_candidate.id]
        return (
            first_times,
            second_times,
            (first_inactive, second_inactive),
        )


@dataclass(frozen=True)
class EanMovementModel:
    model: Any
    artifact: EanBuildArtifact
    optimization_config: EanOptimizationConfig
    variables: EanMovementVariables
    headway_constraint_pool: EanHeadwayConstraintPool
    fleet_model: EanFleetModel | None
    visits_by_key: dict[VisitKey, SwitchVisitDefinition]
    visits_by_cabin_id: dict[int, tuple[SwitchVisitDefinition, ...]]
    timing_by_switch_id: dict[str, SkipStopTiming]
    model_time_bounds: EanModelTimeBounds
    big_m: float
    variable_count: int
    constraint_count: int
    nonzero_count: int
    build_metrics: EanMovementBuildMetrics

    def extract_plan(self) -> EanMovementPlan:
        return extract_movement_plan(self)

    def fix_to_plan(self, plan: EanMovementPlan) -> None:
        """Fix operational movement decisions to an extracted movement plan.

        Headway-order and checkpoint-activation binaries are not part of the
        public movement plan. Once visit times, route decisions, waiting, and
        visit activation are fixed, those auxiliary decisions are implied and
        can be eliminated by presolve.
        """

        fix_movement_model_to_plan(self, plan)

    def apply_mip_start(
        self,
        plan: EanMovementPlan,
        fleet_plan: EanFleetPlan | None = None,
    ) -> None:
        """Apply route and timing decisions as a partial Gurobi MIP start."""

        if self.fleet_model is not None:
            if fleet_plan is None:
                raise ValueError(
                    "optimized initial placement MIP start needs a fleet plan"
                )
            self.fleet_model.apply_mip_start(fleet_plan, plan)
        elif fleet_plan is not None:
            raise ValueError("fixed-start MIP start must not define a fleet plan")
        apply_movement_plan_mip_start(self, plan)

    def apply_partial_mip_start(
        self,
        plan: EanMovementPlan,
        fleet_plan: EanFleetPlan,
    ) -> None:
        """Apply a MIP start only for the active cabins in ``fleet_plan``."""

        if self.fleet_model is None:
            raise ValueError("partial fleet MIP starts require fleet variables")
        cabin_ids = frozenset(fleet_plan.active_cabin_ids)
        self.fleet_model.apply_partial_mip_start(fleet_plan, plan)
        apply_movement_plan_mip_start(self, plan, cabin_ids=cabin_ids)


@dataclass(frozen=True)
class EanMovementModelBuilder:
    """Build the canonical EAN movement, timing, horizon, and headway layer."""

    headway_matrix_pair_batch_size: int = DEFAULT_HEADWAY_MATRIX_PAIR_BATCH_SIZE

    def build(
        self,
        *,
        model: Any,
        binary_vtype: Any,
        artifact: EanBuildArtifact,
        optimization_config: EanOptimizationConfig,
        progress_callback: EanBuildProgressCallback | None = None,
    ) -> EanMovementModel:
        base_started = perf_counter()
        emit_build_progress(
            progress_callback,
            stage=EanBuildStage.MOVEMENT_VARIABLES,
            kind=EanBuildProgressKind.STARTED,
            started=base_started,
        )
        artifact.validate()
        require_supported_waiting_modes(artifact)

        timing_by_switch_id = {timing.switch_id: timing for timing in artifact.timings}
        station_config_by_id = {
            station_config.station_id: station_config
            for station_config in artifact.config.station_configs
        }
        visits_by_key = visits_by_key_for(artifact.switch_visits)
        visits_by_cabin_id = visits_by_cabin_id_for(artifact.switch_visits)
        starts_by_cabin_id = {start.cabin_id: start for start in artifact.cabin_starts}
        checkpoint_by_id = {
            checkpoint.id: checkpoint for checkpoint in artifact.headway_checkpoints
        }
        candidate_by_id = {
            candidate.id: candidate for candidate in artifact.headway_candidates
        }
        model_time_bounds = build_ean_model_time_bounds(
            artifact,
            optimization_config.formulation.time_bounds,
        )
        big_m = model_time_bounds.global_upper + max_headway_seconds(artifact) + 1.0

        switch_time: dict[VisitKey, Any] = {}
        exit_switch_time: dict[VisitKey, Any] = {}
        wait_time: dict[VisitKey, Any] = {}
        stop: dict[VisitKey, Any] = {}
        for key in visits_by_key:
            bounds = model_time_bounds.by_visit[key]
            switch_time[key] = model.addVar(
                lb=bounds.switch_lower,
                ub=bounds.switch_upper,
                name=f"t_{key[0]}_{key[1]}",
            )
            exit_switch_time[key] = model.addVar(
                lb=bounds.exit_lower,
                ub=bounds.exit_upper,
                name=f"x_{key[0]}_{key[1]}",
            )
            wait_time[key] = model.addVar(
                lb=0.0,
                ub=bounds.wait_upper,
                name=f"w_{key[0]}_{key[1]}",
            )
            stop[key] = model.addVar(
                vtype=binary_vtype,
                name=f"stop_{key[0]}_{key[1]}",
            )
        model.update()

        visit_active = add_visit_horizon_activation(
            model=model,
            binary_vtype=binary_vtype,
            artifact=artifact,
            formulation=optimization_config.formulation.horizon,
            switch_time=switch_time,
            visits_by_cabin_id=visits_by_cabin_id,
            selected_time_bounds=model_time_bounds,
            big_m=big_m,
        )
        fleet_model = None
        route_active = visit_active
        if artifact.fleet_mode is EanFleetMode.OPTIMIZED_INITIAL_PLACEMENT:
            if (
                optimization_config.formulation.horizon
                is not EanHorizonFormulation.EXACT_TIME_ACTIVATION
            ):
                raise ValueError(
                    "optimized initial placement requires horizon_exact_time_activation"
                )
            if (
                optimization_config.formulation.time_bounds
                is not EanTimeBoundFormulation.INITIAL_PLACEMENT_SAFE
            ):
                raise ValueError(
                    "optimized initial placement requires time_bounds_initial_placement_safe"
                )
            fleet_model = EanFleetModelBuilder().build_activation(
                model=model,
                binary_vtype=binary_vtype,
                artifact=artifact,
                switch_time=switch_time,
                exit_switch_time=exit_switch_time,
                wait_time=wait_time,
                stop=stop,
                visit_reached=visit_active,
                visits_by_cabin_id=visits_by_cabin_id,
                timing_by_switch_id=timing_by_switch_id,
                big_m=big_m,
                enable_full_initial_state_symmetry=(
                    optimization_config.enable_oip_full_initial_state_symmetry
                ),
                enable_inactive_variable_canonicalization=(
                    optimization_config.enable_oip_inactive_variable_canonicalization
                ),
            )
            route_active = fleet_model.variables.route_active
        for key, visit in visits_by_key.items():
            timing = timing_by_switch_id[visit.switch_id]
            if timing.skip_allowed:
                model.addConstr(
                    stop[key] <= route_active[key],
                    name=f"stop_only_active_{key[0]}_{key[1]}",
                )
            else:
                model.addConstr(
                    stop[key] == route_active[key],
                    name=f"force_stop_if_active_{key[0]}_{key[1]}",
                )

        if fleet_model is None:
            _add_start_constraints(
                model,
                switch_time,
                starts_by_cabin_id,
                visits_by_cabin_id,
            )
        _add_timing_constraints(
            model=model,
            switch_time=switch_time,
            exit_switch_time=exit_switch_time,
            wait_time=wait_time,
            stop=stop,
            visits_by_key=visits_by_key,
            timing_by_switch_id=timing_by_switch_id,
            station_config_by_id=station_config_by_id,
            model_time_bounds=model_time_bounds,
            big_m=big_m,
            enable_tight_big_m_bounds=optimization_config.enable_tight_big_m_bounds,
            visit_active=route_active,
            formulation=optimization_config.formulation.stop_skip_timing,
        )
        _add_chain_constraints(
            model=model,
            switch_time=switch_time,
            exit_switch_time=exit_switch_time,
            visits_by_cabin_id=visits_by_cabin_id,
            timing_by_switch_id=timing_by_switch_id,
            visit_active=route_active,
            big_m=big_m,
        )
        model.update()
        base_seconds = perf_counter() - base_started
        emit_build_progress(
            progress_callback,
            stage=EanBuildStage.MOVEMENT_VARIABLES,
            kind=EanBuildProgressKind.FINISHED,
            started=base_started,
            candidate_count=len(artifact.headway_candidates),
            pair_count=0,
            variable_count=int(model.NumVars),
            constraint_count=int(model.NumConstrs),
            nonzero_count=int(model.NumNZs),
        )

        headway_started = perf_counter()
        emit_build_progress(
            progress_callback,
            stage=EanBuildStage.HEADWAY_CONSTRAINTS,
            kind=EanBuildProgressKind.STARTED,
            started=headway_started,
            checkpoint_count=len(artifact.headway_checkpoints),
            candidate_count=len(artifact.headway_candidates),
            pair_count=0,
            variable_count=int(model.NumVars),
            constraint_count=int(model.NumConstrs),
            nonzero_count=int(model.NumNZs),
        )
        headway_constraint_pool = _add_headway_constraints(
            model=model,
            binary_vtype=binary_vtype,
            switch_time=switch_time,
            exit_switch_time=exit_switch_time,
            wait_time=wait_time,
            stop=stop,
            artifact=artifact,
            checkpoint_by_id=checkpoint_by_id,
            candidate_by_id=candidate_by_id,
            station_config_by_id=station_config_by_id,
            visits_by_key=visits_by_key,
            timing_by_switch_id=timing_by_switch_id,
            big_m=big_m,
            visit_active=route_active,
            horizon_formulation=optimization_config.formulation.horizon,
            enable_fixed_start_headway_precedence=(
                optimization_config.enable_fixed_start_headway_precedence
            ),
            enable_oip_initial_headway_precedence=(
                optimization_config.enable_oip_initial_headway_precedence
            ),
            enable_shared_merge_headway_order=(
                optimization_config.enable_shared_merge_headway_order
            ),
            enable_diagnostic_relax_merge_headways=(
                optimization_config.enable_diagnostic_relax_merge_headways
            ),
            progress_callback=progress_callback,
            progress_started=headway_started,
            matrix_pair_batch_size=self.headway_matrix_pair_batch_size,
        )
        headway_seconds = perf_counter() - headway_started
        emit_build_progress(
            progress_callback,
            stage=EanBuildStage.HEADWAY_CONSTRAINTS,
            kind=EanBuildProgressKind.FINISHED,
            started=headway_started,
            checkpoint_count=len(artifact.headway_checkpoints),
            processed_checkpoint_count=len(artifact.headway_checkpoints),
            candidate_count=len(artifact.headway_candidates),
            pair_count=len(headway_constraint_pool.materialized_pair_ids),
            fixed_pair_count=headway_constraint_pool.fixed_pair_count,
            disjunctive_pair_count=(
                headway_constraint_pool.disjunctive_pair_count
            ),
            redundant_pair_count=headway_constraint_pool.redundant_pair_count,
            order_variable_count=headway_constraint_pool.order_variable_count,
            order_variable_savings=(
                headway_constraint_pool.headway_order_variable_savings
            ),
            variable_count=int(model.NumVars),
            constraint_count=int(model.NumConstrs),
            nonzero_count=int(model.NumNZs),
        )
        final_update_started = perf_counter()
        model.update()
        final_update_seconds = perf_counter() - final_update_started
        checkpoint_within_horizon = headway_constraint_pool.candidate_within_horizon
        headway_order = headway_constraint_pool.headway_order
        variables = EanMovementVariables(
            switch_time=switch_time,
            exit_switch_time=exit_switch_time,
            wait_time=wait_time,
            stop=stop,
            visit_active=visit_active,
            route_active=route_active,
            checkpoint_within_horizon=checkpoint_within_horizon,
            headway_order=headway_order,
        )
        return EanMovementModel(
            model=model,
            artifact=artifact,
            optimization_config=optimization_config,
            variables=variables,
            headway_constraint_pool=headway_constraint_pool,
            fleet_model=fleet_model,
            visits_by_key=visits_by_key,
            visits_by_cabin_id=visits_by_cabin_id,
            timing_by_switch_id=timing_by_switch_id,
            model_time_bounds=model_time_bounds,
            big_m=big_m,
            variable_count=int(model.NumVars),
            constraint_count=int(model.NumConstrs),
            nonzero_count=int(model.NumNZs),
            build_metrics=EanMovementBuildMetrics(
                variables_and_base_constraints_seconds=base_seconds,
                headway_constraints_seconds=headway_seconds,
                final_update_seconds=final_update_seconds,
                fixed_headway_pair_count=headway_constraint_pool.fixed_pair_count,
                disjunctive_headway_pair_count=(
                    headway_constraint_pool.disjunctive_pair_count
                ),
                redundant_headway_pair_count=(
                    headway_constraint_pool.redundant_pair_count
                ),
                headway_order_family_count=(
                    headway_constraint_pool.order_variable_count
                ),
                shared_headway_pair_count=(
                    headway_constraint_pool.shared_headway_pair_count
                ),
                headway_order_variable_savings=(
                    headway_constraint_pool.headway_order_variable_savings
                ),
                singleton_headway_order_family_count=(
                    headway_constraint_pool.singleton_headway_order_family_count
                ),
                diagnostically_omitted_headway_checkpoint_count=(
                    headway_constraint_pool.diagnostically_omitted_checkpoint_count
                ),
                diagnostically_omitted_headway_pair_count=len(
                    headway_constraint_pool.diagnostically_omitted_pair_ids
                ),
            ),
        )


def _add_start_constraints(
    model: Any,
    switch_time: dict[VisitKey, Any],
    starts_by_cabin_id: dict[int, Any],
    visits_by_cabin_id: dict[int, tuple[SwitchVisitDefinition, ...]],
) -> None:
    for cabin_id, visits in visits_by_cabin_id.items():
        start = starts_by_cabin_id[cabin_id]
        first_key = (cabin_id, visits[0].visit_index)
        if start.kind is EanCabinStartKind.FIXED:
            model.addConstr(
                switch_time[first_key] == start.time_seconds,
                name=f"fixed_start_{cabin_id}",
            )
        else:
            model.addConstr(
                switch_time[first_key] >= start.time_seconds,
                name=f"earliest_start_{cabin_id}",
            )


def _add_timing_constraints(
    *,
    model: Any,
    switch_time: dict[VisitKey, Any],
    exit_switch_time: dict[VisitKey, Any],
    wait_time: dict[VisitKey, Any],
    stop: dict[VisitKey, Any],
    visits_by_key: dict[VisitKey, SwitchVisitDefinition],
    timing_by_switch_id: dict[str, SkipStopTiming],
    station_config_by_id: dict[str, StationEanConfig],
    model_time_bounds: EanModelTimeBounds,
    big_m: float,
    enable_tight_big_m_bounds: bool,
    visit_active: dict[VisitKey, Any],
    formulation: EanStopSkipTimingFormulation,
) -> None:
    for key, visit in visits_by_key.items():
        timing = timing_by_switch_id[visit.switch_id]
        station_config = station_config_by_id[timing.station_id]
        bounds = model_time_bounds.by_visit[key]
        active = visit_active[key]
        service_seconds = service_entry_to_exit_switch_seconds(timing)
        skip_seconds = timing.skip_entry_to_exit_switch_seconds

        if station_config.waiting_mode is StationWaitingMode.NO_WAITING:
            model.addConstr(
                wait_time[key] == 0.0,
                name=f"no_wait_{key[0]}_{key[1]}",
            )
        elif station_config.waiting_mode is StationWaitingMode.END_OF_PLATFORM_WAIT:
            model.addConstr(
                wait_time[key] <= bounds.wait_upper * stop[key],
                name=f"wait_only_active_stop_{key[0]}_{key[1]}",
            )
        else:
            raise NotImplementedError(
                f"unsupported EAN waiting mode: {station_config.waiting_mode.value}"
            )

        if formulation is EanStopSkipTimingFormulation.AFFINE:
            add_affine_stop_skip_timing_constraint(
                model=model,
                switch_time=switch_time[key],
                exit_switch_time=exit_switch_time[key],
                wait_time=wait_time[key],
                stop=stop[key],
                active=active,
                service_seconds=service_seconds,
                skip_seconds=skip_seconds,
                name=f"affine_exit_{key[0]}_{key[1]}",
            )
            continue
        if formulation is not EanStopSkipTimingFormulation.BIG_M:
            raise ValueError(
                f"unsupported EAN stop/skip timing formulation: {formulation}"
            )

        bounds_for_branch = stop_skip_big_m_bounds(
            timing=timing,
            station_config=station_config,
            time_upper_bound=model_time_bounds.global_upper,
            global_big_m=big_m,
            enable_tight_big_m_bounds=enable_tight_big_m_bounds,
        )
        model.addConstr(
            exit_switch_time[key] - switch_time[key] - service_seconds - wait_time[key]
            <= bounds_for_branch.service_exit_ub * (1 - stop[key])
            + big_m * (1 - active),
            name=f"service_exit_ub_{key[0]}_{key[1]}",
        )
        model.addConstr(
            exit_switch_time[key] - switch_time[key] - service_seconds - wait_time[key]
            >= -bounds_for_branch.service_exit_lb * (1 - stop[key])
            - big_m * (1 - active),
            name=f"service_exit_lb_{key[0]}_{key[1]}",
        )
        model.addConstr(
            exit_switch_time[key] - switch_time[key] - skip_seconds
            <= bounds_for_branch.skip_exit_ub * stop[key] + big_m * (1 - active),
            name=f"skip_exit_ub_{key[0]}_{key[1]}",
        )
        model.addConstr(
            exit_switch_time[key] - switch_time[key] - skip_seconds
            >= -bounds_for_branch.skip_exit_lb * stop[key] - big_m * (1 - active),
            name=f"skip_exit_lb_{key[0]}_{key[1]}",
        )


def stop_skip_big_m_bounds(
    *,
    timing: SkipStopTiming,
    station_config: StationEanConfig,
    time_upper_bound: float,
    global_big_m: float,
    enable_tight_big_m_bounds: bool,
) -> StopSkipBigMBounds:
    if not enable_tight_big_m_bounds:
        return StopSkipBigMBounds(
            service_exit_ub=global_big_m,
            service_exit_lb=global_big_m,
            skip_exit_ub=global_big_m,
            skip_exit_lb=global_big_m,
        )

    if station_config.waiting_mode is StationWaitingMode.NO_WAITING:
        wait_upper_bound = 0.0
    elif station_config.waiting_mode is StationWaitingMode.END_OF_PLATFORM_WAIT:
        wait_upper_bound = time_upper_bound
    else:
        raise NotImplementedError(
            f"unsupported EAN waiting mode: {station_config.waiting_mode.value}"
        )

    service_seconds = service_entry_to_exit_switch_seconds(timing)
    skip_seconds = timing.skip_entry_to_exit_switch_seconds
    return StopSkipBigMBounds(
        service_exit_ub=max(0.0, skip_seconds - service_seconds),
        service_exit_lb=max(0.0, service_seconds - skip_seconds),
        skip_exit_ub=max(
            0.0,
            min(
                service_seconds + wait_upper_bound - skip_seconds,
                time_upper_bound - skip_seconds,
            ),
        ),
        skip_exit_lb=max(0.0, skip_seconds - service_seconds),
    )


def _add_chain_constraints(
    *,
    model: Any,
    switch_time: dict[VisitKey, Any],
    exit_switch_time: dict[VisitKey, Any],
    visits_by_cabin_id: dict[int, tuple[SwitchVisitDefinition, ...]],
    timing_by_switch_id: dict[str, SkipStopTiming],
    visit_active: dict[VisitKey, Any],
    big_m: float,
) -> None:
    for cabin_id, visits in visits_by_cabin_id.items():
        for previous, current in zip(visits, visits[1:]):
            previous_key = (cabin_id, previous.visit_index)
            current_key = (cabin_id, current.visit_index)
            timing = timing_by_switch_id[previous.switch_id]
            difference = (
                switch_time[current_key]
                - exit_switch_time[previous_key]
                - timing.rope_to_next_switch_seconds
            )
            model.addConstr(
                difference <= big_m * (1 - visit_active[previous_key]),
                name=f"chain_ub_{cabin_id}_{previous.visit_index}_{current.visit_index}",
            )
            model.addConstr(
                difference >= -big_m * (1 - visit_active[previous_key]),
                name=f"chain_lb_{cabin_id}_{previous.visit_index}_{current.visit_index}",
            )


def _add_headway_constraints(
    *,
    model: Any,
    binary_vtype: Any,
    switch_time: dict[VisitKey, Any],
    exit_switch_time: dict[VisitKey, Any],
    wait_time: dict[VisitKey, Any],
    stop: dict[VisitKey, Any],
    artifact: EanBuildArtifact,
    checkpoint_by_id: dict[str, HeadwayCheckpointDefinition],
    candidate_by_id: dict[str, HeadwayCandidate],
    station_config_by_id: dict[str, StationEanConfig],
    visits_by_key: dict[VisitKey, SwitchVisitDefinition],
    timing_by_switch_id: dict[str, SkipStopTiming],
    big_m: float,
    visit_active: dict[VisitKey, Any],
    horizon_formulation: EanHorizonFormulation,
    enable_fixed_start_headway_precedence: bool,
    enable_oip_initial_headway_precedence: bool,
    enable_shared_merge_headway_order: bool,
    enable_diagnostic_relax_merge_headways: bool,
    progress_callback: EanBuildProgressCallback | None,
    progress_started: float,
    matrix_pair_batch_size: int,
) -> EanHeadwayConstraintPool:
    candidate_times_by_id: dict[str, HeadwayTimeExpressions] = {}
    candidate_inactive_by_id: dict[str, Any] = {}
    candidate_within_horizon: dict[str, Any] = {}
    headway_order: dict[str, Any] = {}
    for candidate in artifact.headway_candidates:
        checkpoint = checkpoint_by_id[candidate.checkpoint_id]
        station_config = station_config_by_id.get(checkpoint.station_id)
        times = headway_time_expressions(
            candidate=candidate,
            checkpoint=checkpoint,
            station_config=station_config,
            switch_time=switch_time,
            exit_switch_time=exit_switch_time,
            wait_time=wait_time,
            visits_by_key=visits_by_key,
            timing_by_switch_id=timing_by_switch_id,
        )
        path_inactive = candidate_inactive_expr(
            candidate,
            checkpoint,
            stop,
            visit_active,
        )
        candidate_times_by_id[candidate.id] = times
        candidate_inactive_by_id[candidate.id] = path_inactive
        if horizon_formulation is EanHorizonFormulation.EXACT_TIME_ACTIVATION:
            within = model.addVar(
                vtype=binary_vtype,
                name=f"checkpoint_within_horizon_{candidate.id}",
            )
            candidate_within_horizon[candidate.id] = within
            model.addConstr(
                within <= 1 - path_inactive,
                name=f"checkpoint_within_requires_active_path_{candidate.id}",
            )
            model.addConstr(
                times.follower_enter_time
                <= artifact.config.operational_end_seconds + big_m * (1 - within),
                name=f"checkpoint_before_horizon_if_active_{candidate.id}",
            )
            model.addConstr(
                times.follower_enter_time
                >= artifact.config.operational_end_seconds
                + HORIZON_ACTIVATION_EPSILON_SECONDS
                - big_m * (within + path_inactive),
                name=f"checkpoint_after_horizon_if_inactive_{candidate.id}",
            )

    pool = EanHeadwayConstraintPool(
        model=model,
        binary_vtype=binary_vtype,
        candidate_by_id=candidate_by_id,
        candidate_times_by_id=candidate_times_by_id,
        candidate_inactive_by_id=candidate_inactive_by_id,
        candidate_within_horizon=candidate_within_horizon,
        horizon_formulation=horizon_formulation,
        big_m=big_m,
        headway_order=headway_order,
        classifier=_headway_classifier(
            artifact,
            enable_fixed_start_headway_precedence=(
                enable_fixed_start_headway_precedence
            ),
            enable_oip_initial_headway_precedence=(
                enable_oip_initial_headway_precedence
            ),
        ),
        order_family_index=(
            EanHeadwayOrderFamilyIndex.build(artifact)
            if enable_shared_merge_headway_order
            else None
        ),
        progress_callback=progress_callback,
        progress_started=progress_started,
        checkpoint_count=len(artifact.headway_checkpoints),
        matrix_pair_batch_size=matrix_pair_batch_size,
    )
    merge_relaxation_index = (
        EanDirectMergeHeadwayRelaxationIndex.build(artifact)
        if enable_diagnostic_relax_merge_headways
        else None
    )
    if merge_relaxation_index is None:
        materialized_pairs = artifact.headway_pairs
    else:
        materialized_pairs = tuple(
            pair
            for pair in artifact.headway_pairs
            if pair.id not in merge_relaxation_index.pair_ids
        )
        pool.diagnostically_omitted_pair_ids = merge_relaxation_index.pair_ids
        pool.diagnostically_omitted_checkpoint_count = len(
            merge_relaxation_index.checkpoint_ids
        )
    pool.add_pairs(materialized_pairs)
    if artifact.headway_pair_scope is EanHeadwayPairScope.COMPLETE:
        # Complete models never augment. Drop temporary expression indexes so
        # the long-lived movement model has the same memory shape as before.
        pool.accepts_augmentation = False
        pool.candidate_by_id.clear()
        pool.candidate_times_by_id.clear()
        pool.candidate_inactive_by_id.clear()
    return pool


def _headway_classifier(
    artifact: EanBuildArtifact,
    *,
    enable_fixed_start_headway_precedence: bool,
    enable_oip_initial_headway_precedence: bool,
) -> EanHeadwayPairClassifier | None:
    if enable_fixed_start_headway_precedence:
        classifier = EanFixedStartHeadwayClassifier.build(artifact)
        if classifier is not None:
            return classifier
    if enable_oip_initial_headway_precedence:
        return EanOipInitialHeadwayClassifier.build(artifact)
    return None


def headway_time_expressions(
    *,
    candidate: HeadwayCandidate,
    checkpoint: HeadwayCheckpointDefinition,
    station_config: StationEanConfig | None,
    switch_time: dict[VisitKey, Any],
    exit_switch_time: dict[VisitKey, Any],
    wait_time: dict[VisitKey, Any],
    visits_by_key: dict[VisitKey, SwitchVisitDefinition],
    timing_by_switch_id: dict[str, SkipStopTiming],
) -> HeadwayTimeExpressions:
    if uses_platform_exit_wait_occupancy(checkpoint, station_config):
        key = (candidate.cabin_id, candidate.visit_index)
        return HeadwayTimeExpressions(
            leader_clear_time=platform_exit_time_expr(
                key,
                switch_time,
                wait_time,
                visits_by_key,
                timing_by_switch_id,
            ),
            follower_enter_time=platform_exit_wait_entry_time_expr(
                key,
                switch_time,
                visits_by_key,
                timing_by_switch_id,
            ),
            semantics_label=PLATFORM_EXIT_WAIT_OCCUPANCY_SEMANTICS,
        )
    candidate_time = candidate_time_expr(
        candidate,
        switch_time,
        exit_switch_time,
        wait_time,
        visits_by_key,
        timing_by_switch_id,
    )
    return HeadwayTimeExpressions(
        leader_clear_time=candidate_time,
        follower_enter_time=candidate_time,
        semantics_label=POINT_HEADWAY_SEMANTICS,
    )


def candidate_time_expr(
    candidate: HeadwayCandidate,
    switch_time: dict[VisitKey, Any],
    exit_switch_time: dict[VisitKey, Any],
    wait_time: dict[VisitKey, Any],
    visits_by_key: dict[VisitKey, SwitchVisitDefinition],
    timing_by_switch_id: dict[str, SkipStopTiming],
) -> Any:
    key = (candidate.cabin_id, candidate.visit_index)
    if candidate.time_reference is EanTimeReference.PLATFORM_ENTRY_TIME:
        return platform_entry_time_expr(
            key,
            switch_time,
            visits_by_key,
            timing_by_switch_id,
        )
    if candidate.time_reference is EanTimeReference.PLATFORM_EXIT_TIME:
        return platform_exit_time_expr(
            key,
            switch_time,
            wait_time,
            visits_by_key,
            timing_by_switch_id,
        )
    if candidate.time_reference is EanTimeReference.EXIT_SWITCH_TIME:
        return exit_switch_time[key]
    if candidate.time_reference is EanTimeReference.ENTRY_TIME:
        return switch_time[key]
    raise ValueError(
        f"unsupported candidate time reference: {candidate.time_reference}"
    )


def candidate_inactive_expr(
    candidate: HeadwayCandidate,
    checkpoint: HeadwayCheckpointDefinition,
    stop: dict[VisitKey, Any],
    visit_active: dict[VisitKey, Any],
) -> Any:
    key = (candidate.cabin_id, candidate.visit_index)
    if candidate.activation_reference is EanActivationReference.SERVE:
        return 1 - stop[key]
    if candidate.activation_reference is EanActivationReference.SKIP:
        return stop[key] + 1 - visit_active[key]
    if candidate.activation_reference is EanActivationReference.ACTIVE:
        if checkpoint.applies_to_serve and checkpoint.applies_to_skip:
            return 1 - visit_active[key]
        if checkpoint.applies_to_serve:
            return 1 - stop[key]
        if checkpoint.applies_to_skip:
            return stop[key] + 1 - visit_active[key]
    raise ValueError(
        f"unsupported candidate activation reference: {candidate.activation_reference}"
    )


def platform_entry_time_expr(
    key: VisitKey,
    switch_time: dict[VisitKey, Any],
    visits_by_key: dict[VisitKey, SwitchVisitDefinition],
    timing_by_switch_id: dict[str, SkipStopTiming],
) -> Any:
    timing = timing_by_switch_id[visits_by_key[key].switch_id]
    return switch_time[key] + timing.entry_to_platform_entry_seconds


def platform_exit_time_expr(
    key: VisitKey,
    switch_time: dict[VisitKey, Any],
    wait_time: dict[VisitKey, Any],
    visits_by_key: dict[VisitKey, SwitchVisitDefinition],
    timing_by_switch_id: dict[str, SkipStopTiming],
) -> Any:
    return (
        platform_exit_wait_entry_time_expr(
            key,
            switch_time,
            visits_by_key,
            timing_by_switch_id,
        )
        + wait_time[key]
    )


def platform_exit_wait_entry_time_expr(
    key: VisitKey,
    switch_time: dict[VisitKey, Any],
    visits_by_key: dict[VisitKey, SwitchVisitDefinition],
    timing_by_switch_id: dict[str, SkipStopTiming],
) -> Any:
    timing = timing_by_switch_id[visits_by_key[key].switch_id]
    return (
        switch_time[key]
        + timing.entry_to_platform_entry_seconds
        + timing.min_platform_entry_to_platform_exit_seconds
    )


def extract_movement_plan(movement_model: EanMovementModel) -> EanMovementPlan:
    artifact = movement_model.artifact
    variables = movement_model.variables
    trajectories: list[EanCabinTrajectory] = []
    for cabin_id in sorted(movement_model.visits_by_cabin_id):
        cabin_visits: list[EanCabinVisit] = []
        active_visits = tuple(
            visit
            for visit in movement_model.visits_by_cabin_id[cabin_id]
            if visit_is_active_in_solution(
                variables.route_active[(visit.cabin_id, visit.visit_index)]
            )
        )
        for visit in active_visits:
            key = (visit.cabin_id, visit.visit_index)
            timing = movement_model.timing_by_switch_id[visit.switch_id]
            switch_seconds = variable_value(variables.switch_time[key])
            exit_seconds = variable_value(variables.exit_switch_time[key])
            next_visit = next(
                (
                    candidate
                    for candidate in movement_model.visits_by_cabin_id[cabin_id]
                    if candidate.visit_index == visit.visit_index + 1
                    and visit_is_active_in_solution(
                        variables.route_active[
                            (candidate.cabin_id, candidate.visit_index)
                        ]
                    )
                ),
                None,
            )
            if next_visit is not None:
                next_seconds = variable_value(
                    variables.switch_time[(next_visit.cabin_id, next_visit.visit_index)]
                )
            else:
                next_seconds = exit_seconds + timing.rope_to_next_switch_seconds
            is_stop = variable_value(variables.stop[key]) >= 0.5
            wait_seconds = (
                nonnegative_variable_value(
                    variables.wait_time[key], label=f"wait_time[{key!r}]"
                )
                if is_stop
                else 0.0
            )
            if is_stop:
                platform_entry = switch_seconds + timing.entry_to_platform_entry_seconds
                platform_exit = (
                    platform_entry
                    + timing.min_platform_entry_to_platform_exit_seconds
                    + wait_seconds
                )
                decision = EanRouteDecision.STOP
            else:
                platform_entry = None
                platform_exit = None
                decision = EanRouteDecision.SKIP
            cabin_visit = EanCabinVisit(
                cabin_id=visit.cabin_id,
                visit_index=visit.visit_index,
                switch_id=visit.switch_id,
                station_id=timing.station_id,
                decision=decision,
                switch_time_seconds=switch_seconds,
                platform_entry_time_seconds=platform_entry,
                platform_exit_time_seconds=platform_exit,
                exit_switch_time_seconds=exit_seconds,
                next_switch_time_seconds=next_seconds,
                wait_seconds=wait_seconds,
            )
            cabin_visit.validate()
            cabin_visits.append(cabin_visit)
        trajectories.append(
            EanCabinTrajectory(cabin_id=cabin_id, visits=tuple(cabin_visits))
        )

    plan = EanMovementPlan(
        scenario_id=artifact.scenario_id,
        horizon_seconds=artifact.config.horizon_seconds,
        model_end_seconds=artifact.config.model_end_seconds,
        trajectories=tuple(trajectories),
        horizon_formulation=movement_model.optimization_config.formulation.horizon,
        fleet_mode=artifact.fleet_mode,
    )
    plan.validate()
    return plan


def fix_movement_model_to_plan(
    movement_model: EanMovementModel,
    plan: EanMovementPlan,
) -> None:
    plan.validate()
    artifact = movement_model.artifact
    if plan.scenario_id != artifact.scenario_id:
        raise ValueError(
            "fixed EAN movement plan scenario does not match the build "
            f"artifact: {plan.scenario_id!r} != {artifact.scenario_id!r}"
        )
    if plan.horizon_formulation is not (
        movement_model.optimization_config.formulation.horizon
    ):
        raise ValueError(
            "fixed EAN movement plan horizon formulation does not match the "
            "optimization configuration"
        )

    plan_visits = {
        (visit.cabin_id, visit.visit_index): visit
        for trajectory in plan.trajectories
        for visit in trajectory.visits
    }
    unknown_keys = set(plan_visits) - set(movement_model.visits_by_key)
    if unknown_keys:
        raise ValueError(
            f"fixed EAN movement plan contains unknown visits: {sorted(unknown_keys)}"
        )

    variables = movement_model.variables
    for key, visit_definition in movement_model.visits_by_key.items():
        plan_visit = plan_visits.get(key)
        if plan_visit is None:
            _fix_variable(variables.stop[key], 0.0, label=f"stop[{key}]")
            _fix_variable(
                variables.visit_active[key],
                0.0,
                label=f"visit_active[{key}]",
            )
            continue
        if plan_visit.switch_id != visit_definition.switch_id:
            raise ValueError(
                "fixed EAN movement plan switch does not match artifact for "
                f"visit {key}: {plan_visit.switch_id!r} != "
                f"{visit_definition.switch_id!r}"
            )
        _fix_variable(
            variables.switch_time[key],
            plan_visit.switch_time_seconds,
            label=f"switch_time[{key}]",
        )
        _fix_variable(
            variables.exit_switch_time[key],
            plan_visit.exit_switch_time_seconds,
            label=f"exit_switch_time[{key}]",
        )
        _fix_variable(
            variables.wait_time[key],
            plan_visit.wait_seconds,
            label=f"wait_time[{key}]",
        )
        _fix_variable(
            variables.stop[key],
            1.0 if plan_visit.decision is EanRouteDecision.STOP else 0.0,
            label=f"stop[{key}]",
        )
        _fix_variable(
            variables.visit_active[key],
            1.0,
            label=f"visit_active[{key}]",
        )
    movement_model.model.update()


def apply_movement_plan_mip_start(
    movement_model: EanMovementModel,
    plan: EanMovementPlan,
    *,
    cabin_ids: frozenset[int] | None = None,
) -> None:
    """Transfer an extracted movement plan without fixing model variables.

    Headway-order and checkpoint-activation auxiliaries are omitted. Gurobi can
    complete them from the supplied route, timing, waiting, and visit decisions.
    """

    plan.validate()
    artifact = movement_model.artifact
    if plan.scenario_id != artifact.scenario_id:
        raise ValueError(
            "EAN movement MIP start scenario does not match the build "
            f"artifact: {plan.scenario_id!r} != {artifact.scenario_id!r}"
        )
    if plan.horizon_formulation is not (
        movement_model.optimization_config.formulation.horizon
    ):
        raise ValueError(
            "EAN movement MIP start horizon formulation does not match the "
            "optimization configuration"
        )

    plan_visits = {
        (visit.cabin_id, visit.visit_index): visit
        for trajectory in plan.trajectories
        for visit in trajectory.visits
    }
    variables = movement_model.variables
    for key, visit_definition in movement_model.visits_by_key.items():
        if cabin_ids is not None and key[0] not in cabin_ids:
            continue
        plan_visit = plan_visits.get(key)
        if plan_visit is None:
            variables.stop[key].Start = 0.0
            if movement_model.fleet_model is None and not isinstance(
                variables.visit_active[key], int | float
            ):
                variables.visit_active[key].Start = 0.0
            continue
        if plan_visit.switch_id != visit_definition.switch_id:
            raise ValueError(
                "EAN movement MIP start switch does not match artifact for "
                f"visit {key}: {plan_visit.switch_id!r} != "
                f"{visit_definition.switch_id!r}"
            )
        variables.switch_time[key].Start = plan_visit.switch_time_seconds
        variables.exit_switch_time[key].Start = plan_visit.exit_switch_time_seconds
        variables.wait_time[key].Start = plan_visit.wait_seconds
        variables.stop[key].Start = float(plan_visit.decision is EanRouteDecision.STOP)
        if not isinstance(variables.visit_active[key], int | float):
            variables.visit_active[key].Start = 1.0


def _fix_variable(variable: Any, value: float, *, label: str) -> None:
    if hasattr(variable, "LB") and hasattr(variable, "UB"):
        variable.LB = value
        variable.UB = value
        return
    if not math.isclose(float(variable), value, abs_tol=1e-8):
        raise ValueError(f"cannot fix constant {label}={float(variable)} to {value}")


def visits_by_key_for(
    visits: tuple[SwitchVisitDefinition, ...],
) -> dict[VisitKey, SwitchVisitDefinition]:
    return {(visit.cabin_id, visit.visit_index): visit for visit in visits}


def visits_by_cabin_id_for(
    visits: tuple[SwitchVisitDefinition, ...],
) -> dict[int, tuple[SwitchVisitDefinition, ...]]:
    grouped: dict[int, list[SwitchVisitDefinition]] = {}
    for visit in visits:
        grouped.setdefault(visit.cabin_id, []).append(visit)
    return {
        cabin_id: tuple(sorted(cabin_visits, key=lambda visit: visit.visit_index))
        for cabin_id, cabin_visits in grouped.items()
    }


def service_entry_to_exit_switch_seconds(timing: SkipStopTiming) -> float:
    return (
        timing.entry_to_platform_entry_seconds
        + timing.min_platform_entry_to_platform_exit_seconds
        + timing.platform_exit_to_exit_switch_seconds
    )


def service_entry_to_next_switch_seconds(timing: SkipStopTiming) -> float:
    return (
        service_entry_to_exit_switch_seconds(timing)
        + timing.rope_to_next_switch_seconds
    )


def max_headway_seconds(artifact: EanBuildArtifact) -> float:
    if not artifact.headway_checkpoints:
        return 0.0
    return max(checkpoint.headway_seconds for checkpoint in artifact.headway_checkpoints)


def require_supported_waiting_modes(artifact: EanBuildArtifact) -> None:
    unsupported_modes = {
        station_config.waiting_mode
        for station_config in artifact.config.station_configs
        if station_config.waiting_mode
        not in {
            StationWaitingMode.NO_WAITING,
            StationWaitingMode.END_OF_PLATFORM_WAIT,
        }
    }
    if unsupported_modes:
        labels = ", ".join(sorted(mode.value for mode in unsupported_modes))
        # Adding FIFO requires both physical occupancy constraints here and a
        # matching q_a term in the OIP packing upper-bound certificate.
        raise NotImplementedError(
            "EAN optimization only supports no-waiting and end-of-platform "
            f"waiting stations, got: {labels}"
        )


def variable_value(variable: Any) -> float:
    value = float(variable.X)
    if math.isclose(value, round(value), abs_tol=1e-8):
        return float(round(value))
    return value


def nonnegative_variable_value(
    variable: Any, *, label: str, tolerance: float = 1e-5
) -> float:
    value = variable_value(variable)
    if value < -tolerance:
        raise ValueError(f"solver returned materially negative {label}: {value}")
    return max(0.0, value)
