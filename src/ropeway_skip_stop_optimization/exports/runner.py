from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from ropeway_skip_stop_optimization.examples.base import ScenarioExample
from ropeway_skip_stop_optimization.examples.registry import get_example
from ropeway_skip_stop_optimization.exports.artifacts import (
    ArtifactBuilder,
    ArtifactSet,
    DiscreteScenarioArtifactBuilder,
    ExportArtifact,
    ExportContext,
    GreedyAllStopMovementPlanArtifactBuilder,
    GreedyAllStopPassengerReplayArtifactBuilder,
    GreedyAllStopReplayMetricsArtifactBuilder,
    MilpV0MovementPlanArtifactBuilder,
    MilpV1PassengerWaitingPlanArtifactBuilder,
    PhysicalScenarioArtifactBuilder,
)
from ropeway_skip_stop_optimization.exports.json_codec import write_json
from ropeway_skip_stop_optimization.exports.manifest import merge_and_write_manifest
from ropeway_skip_stop_optimization.optimization.discrete_time import (
    MilpV0VariableStrategy,
    MilpV1PassengerWaitingObjective,
)
from ropeway_skip_stop_optimization.progress import ProgressReporter


DEFAULT_OUTPUT_ROOT = Path("frontend/public/generated/examples")


@dataclass(frozen=True)
class ExportRunResult:
    example_id: str
    artifact_set_id: str
    artifact_paths: tuple[Path, ...]
    manifest_path: Path


def build_artifact_set(
    artifact_set_id: str,
    *,
    milp_horizon_steps: int = 60,
    milp_cabin_count: int = 23,
    milp_variable_strategy: MilpV0VariableStrategy = MilpV0VariableStrategy.DENSE,
) -> ArtifactSet:
    common: tuple[ArtifactBuilder, ...] = (
        PhysicalScenarioArtifactBuilder(),
        DiscreteScenarioArtifactBuilder(),
    )
    if artifact_set_id == "physical_only":
        return ArtifactSet("physical_only", "Physical scenario", (PhysicalScenarioArtifactBuilder(),))
    if artifact_set_id == "discrete_debug":
        return ArtifactSet("discrete_debug", "Discrete debug", common)
    if artifact_set_id == "greedy_all_stop":
        return ArtifactSet(
            "greedy_all_stop",
            "Greedy all-stop replay",
            (
                *common,
                GreedyAllStopMovementPlanArtifactBuilder(),
                GreedyAllStopPassengerReplayArtifactBuilder(),
                GreedyAllStopReplayMetricsArtifactBuilder(),
            ),
            is_default=True,
        )
    if artifact_set_id == "milp_v0_feasibility":
        return ArtifactSet(
            "milp_v0_feasibility",
            "MILP v0 feasibility",
            (
                *common,
                MilpV0MovementPlanArtifactBuilder(
                    horizon_steps=milp_horizon_steps,
                    cabin_count=milp_cabin_count,
                    variable_strategy=milp_variable_strategy,
                ),
            ),
        )
    if artifact_set_id == "milp_v1_passenger_feasibility":
        return ArtifactSet(
            "milp_v1_passenger_feasibility",
            "MILP v1 passenger feasibility",
            (
                *common,
                MilpV1PassengerWaitingPlanArtifactBuilder(
                    horizon_steps=milp_horizon_steps,
                    cabin_count=milp_cabin_count,
                    variable_strategy=milp_variable_strategy,
                    objective=MilpV1PassengerWaitingObjective.FEASIBILITY,
                ),
            ),
        )
    if artifact_set_id == "milp_v1_waiting_time":
        return ArtifactSet(
            "milp_v1_waiting_time",
            "MILP v1 waiting-time objective",
            (
                *common,
                MilpV1PassengerWaitingPlanArtifactBuilder(
                    horizon_steps=milp_horizon_steps,
                    cabin_count=milp_cabin_count,
                    variable_strategy=milp_variable_strategy,
                    objective=MilpV1PassengerWaitingObjective.WAITING_TIME,
                ),
            ),
        )

    known = ", ".join(known_artifact_set_ids())
    raise ValueError(f"Unknown artifact set id {artifact_set_id!r}. Known artifact sets: {known}")


def known_artifact_set_ids() -> tuple[str, ...]:
    return (
        "physical_only",
        "discrete_debug",
        "greedy_all_stop",
        "milp_v0_feasibility",
        "milp_v1_passenger_feasibility",
        "milp_v1_waiting_time",
    )


def export_artifact_set(
    *,
    example_id: str = "three_station_v0",
    artifact_set_id: str = "greedy_all_stop",
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    milp_horizon_steps: int = 60,
    milp_cabin_count: int = 23,
    milp_variable_strategy: MilpV0VariableStrategy = MilpV0VariableStrategy.DENSE,
    progress: bool | ProgressReporter = False,
    clean: bool = False,
) -> ExportRunResult:
    example = get_example(example_id)
    artifact_set = build_artifact_set(
        artifact_set_id,
        milp_horizon_steps=milp_horizon_steps,
        milp_cabin_count=milp_cabin_count,
        milp_variable_strategy=milp_variable_strategy,
    )
    reporter = _progress_reporter(progress)
    return run_artifact_set(
        example,
        artifact_set,
        output_root=output_root,
        progress=reporter,
        clean=clean,
    )


def run_artifact_set(
    example: ScenarioExample,
    artifact_set: ArtifactSet,
    *,
    output_root: Path,
    progress: ProgressReporter,
    clean: bool = False,
) -> ExportRunResult:
    if clean:
        example_dir = output_root / example.metadata.id
        if example_dir.exists():
            shutil.rmtree(example_dir)

    output_root.mkdir(parents=True, exist_ok=True)
    context = ExportContext(example=example, progress=progress)
    artifacts: list[ExportArtifact] = []
    artifact_paths: list[Path] = []

    for builder in artifact_set.builders:
        with progress.phase(f"export.artifact.{builder.id}"):
            artifact = builder.build(context)
        output_path = output_root / artifact.relative_path
        with progress.phase(f"write_json {artifact.relative_path.as_posix()}"):
            write_json(output_path, artifact.payload)
        artifacts.append(artifact)
        artifact_paths.append(output_path)

    with progress.phase("export.manifest"):
        manifest_path = merge_and_write_manifest(output_root, example, artifact_set, tuple(artifacts))
    return ExportRunResult(
        example_id=example.metadata.id,
        artifact_set_id=artifact_set.id,
        artifact_paths=tuple(artifact_paths),
        manifest_path=manifest_path,
    )


def _progress_reporter(progress: bool | ProgressReporter) -> ProgressReporter:
    if isinstance(progress, ProgressReporter):
        return progress
    return ProgressReporter(enabled=progress)
