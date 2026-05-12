from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from ropeway_skip_stop_optimization.baselines import (
    build_all_stop_cycle_path,
    build_maximal_greedy_all_stop_circulation_plan,
    greedy_place_max_cabins_on_cycle,
)
from ropeway_skip_stop_optimization.examples.base import ScenarioExample
from ropeway_skip_stop_optimization.mapping import discretize_scenario
from ropeway_skip_stop_optimization.models import DiscreteScenario, MovementPlan, ReplayMetrics, ReplayResult, Scenario
from ropeway_skip_stop_optimization.optimization.discrete_time import (
    FixedCabinStart,
    MilpV0Config,
    MilpV0VariableStrategy,
    MilpV1PassengerWaitingConfig,
    MilpV1PassengerWaitingObjective,
    solve_milp_v0,
    solve_milp_v1_passenger_waiting,
)
from ropeway_skip_stop_optimization.progress import ProgressReporter
from ropeway_skip_stop_optimization.replay import build_replay_metrics, replay_passenger_boarding
from ropeway_skip_stop_optimization.validation import validate_scenario


class ArtifactKind(StrEnum):
    SCENARIO = "scenario"
    DISCRETE_SCENARIO = "discrete_scenario"
    MOVEMENT_PLAN = "movement_plan"
    PASSENGER_REPLAY = "passenger_replay"
    REPLAY_METRICS = "replay_metrics"
    MILP_RESULT = "milp_result"
    EAN_INPUT = "ean_input"
    EAN_RESULT = "ean_result"


@dataclass(frozen=True)
class ExportArtifact:
    id: str
    kind: ArtifactKind
    relative_path: Path
    payload: Any
    label: str | None = None


@dataclass
class ExportContext:
    example: ScenarioExample
    progress: ProgressReporter

    _scenario: Scenario | None = None
    _discrete_scenario: DiscreteScenario | None = None
    _greedy_plan: MovementPlan | None = None
    _greedy_passenger_replay: ReplayResult | None = None
    _greedy_replay_metrics: ReplayMetrics | None = None

    def scenario(self) -> Scenario:
        if self._scenario is None:
            with self.progress.phase("export.context.scenario"):
                scenario = self.example.build_scenario()
                validate_scenario(scenario).raise_for_errors()
                self._scenario = scenario
        return self._scenario

    def discrete_scenario(self) -> DiscreteScenario:
        if self._discrete_scenario is None:
            with self.progress.phase("export.context.discrete_scenario"):
                self._discrete_scenario = discretize_scenario(self.scenario())
        return self._discrete_scenario

    def greedy_all_stop_plan(self) -> MovementPlan:
        if self._greedy_plan is None:
            with self.progress.phase("export.context.greedy_all_stop_plan"):
                discrete = self.discrete_scenario()
                self._greedy_plan = build_maximal_greedy_all_stop_circulation_plan(
                    discrete,
                    horizon_steps=discrete.horizon_steps,
                )
        return self._greedy_plan

    def greedy_passenger_replay(self) -> ReplayResult:
        if self._greedy_passenger_replay is None:
            with self.progress.phase("export.context.greedy_passenger_replay"):
                self._greedy_passenger_replay = replay_passenger_boarding(
                    self.discrete_scenario(),
                    self.greedy_all_stop_plan(),
                )
        return self._greedy_passenger_replay

    def greedy_replay_metrics(self) -> ReplayMetrics:
        if self._greedy_replay_metrics is None:
            with self.progress.phase("export.context.greedy_replay_metrics"):
                self._greedy_replay_metrics = build_replay_metrics(
                    self.discrete_scenario(),
                    self.greedy_passenger_replay(),
                )
        return self._greedy_replay_metrics


class ArtifactBuilder(ABC):
    id: str
    kind: ArtifactKind
    label: str | None = None

    @abstractmethod
    def build(self, context: ExportContext) -> ExportArtifact:
        raise NotImplementedError

    def _path(self, context: ExportContext, filename: str) -> Path:
        return Path(context.example.metadata.id) / filename


@dataclass(frozen=True)
class ArtifactSet:
    id: str
    label: str
    builders: tuple[ArtifactBuilder, ...]
    is_default: bool = False


class PhysicalScenarioArtifactBuilder(ArtifactBuilder):
    id = "scenario"
    kind = ArtifactKind.SCENARIO
    label = "Physical scenario"

    def build(self, context: ExportContext) -> ExportArtifact:
        scenario = context.scenario()
        payload = {"scenario_id": scenario.id, **{key: value for key, value in scenario.__dict__.items() if key != "id"}}
        return ExportArtifact(self.id, self.kind, self._path(context, "scenario.json"), payload, self.label)


class DiscreteScenarioArtifactBuilder(ArtifactBuilder):
    id = "discrete_scenario"
    kind = ArtifactKind.DISCRETE_SCENARIO
    label = "Discrete scenario"

    def build(self, context: ExportContext) -> ExportArtifact:
        discrete = context.discrete_scenario()
        return ExportArtifact(
            self.id,
            self.kind,
            self._path(context, f"discrete_dt_{_format_delta(discrete.delta_seconds)}.json"),
            discrete,
            self.label,
        )


class GreedyAllStopMovementPlanArtifactBuilder(ArtifactBuilder):
    id = "greedy_all_stop_movement_plan"
    kind = ArtifactKind.MOVEMENT_PLAN
    label = "Greedy all-stop movement plan"

    def build(self, context: ExportContext) -> ExportArtifact:
        return ExportArtifact(
            self.id,
            self.kind,
            self._path(context, "greedy_all_stop_movement_plan.json"),
            context.greedy_all_stop_plan(),
            self.label,
        )


class GreedyAllStopPassengerReplayArtifactBuilder(ArtifactBuilder):
    id = "greedy_all_stop_passenger_replay"
    kind = ArtifactKind.PASSENGER_REPLAY
    label = "Greedy all-stop passenger replay"

    def build(self, context: ExportContext) -> ExportArtifact:
        return ExportArtifact(
            self.id,
            self.kind,
            self._path(context, "greedy_all_stop_passenger_replay.json"),
            context.greedy_passenger_replay(),
            self.label,
        )


class GreedyAllStopReplayMetricsArtifactBuilder(ArtifactBuilder):
    id = "greedy_all_stop_replay_metrics"
    kind = ArtifactKind.REPLAY_METRICS
    label = "Greedy all-stop replay metrics"

    def build(self, context: ExportContext) -> ExportArtifact:
        return ExportArtifact(
            self.id,
            self.kind,
            self._path(context, "greedy_all_stop_replay_metrics.json"),
            context.greedy_replay_metrics(),
            self.label,
        )


@dataclass(frozen=True)
class MilpV0MovementPlanArtifactBuilder(ArtifactBuilder):
    horizon_steps: int = 60
    cabin_count: int = 23
    variable_strategy: MilpV0VariableStrategy = MilpV0VariableStrategy.DENSE

    id = "milp_v0_movement_plan"
    kind = ArtifactKind.MILP_RESULT
    label = "MILP v0 movement result"

    def build(self, context: ExportContext) -> ExportArtifact:
        discrete = context.discrete_scenario()
        if self.horizon_steps > discrete.horizon_steps:
            raise ValueError("MILP v0 export horizon_steps exceeds discrete scenario horizon")
        fixed_starts = _fixed_starts(discrete, self.cabin_count)
        with context.progress.phase(
            f"export.artifact.milp_v0.solve strategy={self.variable_strategy.value} "
            f"cabins={self.cabin_count} horizon={self.horizon_steps}"
        ):
            result = solve_milp_v0(
                discrete,
                MilpV0Config(
                    horizon_steps=self.horizon_steps,
                    fixed_starts=fixed_starts,
                    variable_strategy=self.variable_strategy,
                ),
                progress=context.progress,
            )
        if result.movement_plan is None:
            raise ValueError(f"MILP v0 did not produce a movement plan; status={result.metadata.status}")
        strategy_label = _strategy_label(self.variable_strategy)
        return ExportArtifact(
            self.id,
            self.kind,
            self._path(context, f"milp_v0_{strategy_label}_movement_plan_c{self.cabin_count}_h{self.horizon_steps}.json"),
            {
                "movement_plan": result.movement_plan,
                "metadata": result.metadata,
            },
            self.label,
        )


@dataclass(frozen=True)
class MilpV1PassengerWaitingPlanArtifactBuilder(ArtifactBuilder):
    horizon_steps: int = 60
    cabin_count: int = 23
    variable_strategy: MilpV0VariableStrategy = MilpV0VariableStrategy.SPARSE_REACHABILITY
    objective: MilpV1PassengerWaitingObjective = MilpV1PassengerWaitingObjective.FEASIBILITY

    id = "milp_v1_passenger_waiting_plan"
    kind = ArtifactKind.MILP_RESULT
    label = "MILP v1 passenger waiting result"

    def build(self, context: ExportContext) -> ExportArtifact:
        discrete = context.discrete_scenario()
        if self.horizon_steps > discrete.horizon_steps:
            raise ValueError("MILP v1 passenger export horizon_steps exceeds discrete scenario horizon")
        fixed_starts = _fixed_starts(discrete, self.cabin_count)
        with context.progress.phase(
            f"export.artifact.milp_v1_passenger_waiting.solve strategy={self.variable_strategy.value} "
            f"objective={self.objective.value} cabins={self.cabin_count} horizon={self.horizon_steps}"
        ):
            result = solve_milp_v1_passenger_waiting(
                discrete,
                MilpV1PassengerWaitingConfig(
                    horizon_steps=self.horizon_steps,
                    fixed_starts=fixed_starts,
                    variable_strategy=self.variable_strategy,
                    objective=self.objective,
                ),
                progress=context.progress,
            )
        if result.movement_plan is None:
            raise ValueError(f"MILP v1 passenger waiting did not produce a movement plan; status={result.metadata.status}")
        strategy_label = _strategy_label(self.variable_strategy)
        return ExportArtifact(
            self.id,
            self.kind,
            self._path(
                context,
                (
                    f"milp_v1_passenger_waiting_{self.objective.value}_{strategy_label}"
                    f"_movement_plan_c{self.cabin_count}_h{self.horizon_steps}.json"
                ),
            ),
            {
                "movement_plan": result.movement_plan,
                "metadata": result.metadata,
            },
            self.label,
        )


def _fixed_starts(discrete: DiscreteScenario, cabin_count: int) -> tuple[FixedCabinStart, ...]:
    path = build_all_stop_cycle_path(discrete)
    start_indices = greedy_place_max_cabins_on_cycle(discrete, path.node_ids)
    if cabin_count > len(start_indices):
        raise ValueError(f"MILP export requested {cabin_count} cabins, but only {len(start_indices)} fit")
    return tuple(
        FixedCabinStart(cabin_id=cabin_id, node_id=path.node_ids[start_index])
        for cabin_id, start_index in enumerate(start_indices[:cabin_count])
    )


def _format_delta(delta_seconds: float) -> str:
    return f"{delta_seconds:g}".replace(".", "p")


def _strategy_label(variable_strategy: MilpV0VariableStrategy) -> str:
    return "sparse" if variable_strategy is MilpV0VariableStrategy.SPARSE_REACHABILITY else "dense"
