from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Callable, Mapping


@dataclass(frozen=True, slots=True)
class DddRootCgTrialConfig:
    example_id: str
    available_fleet_count: int
    reservoir_entry_state: str
    objective: str = "journey_time"
    warmup_seconds: float = 300.0
    reservoir_entry_resource_ids: tuple[str, ...] = ()
    reservoir_boundary_mode: str = "ideal_non_limiting"
    reservoir_dispatch_resource_ids: tuple[str, ...] = ()
    reservoir_first_route_option_ids: tuple[str, ...] = ()
    dispatch_cardinality: str = "optional"
    waiting_step_seconds: float = 1.0
    max_iterations: int = 30
    total_time_limit_seconds: float | None = None
    pricing_time_limit_seconds: float = 5.0
    pricing_threads: int = 1
    master_dual_mode: str = "default"
    proof_pricing_mip_focus: int = 2
    extra_pricing_mip_focus: int = 1
    pricing_formulation: str | None = None
    max_pair_checks: int = 2_000_000
    conflict_row_mode: str = "pair_only"
    max_resource_window_rounds: int = 100
    columns_per_cabin_per_round: int = 1
    diversity_mode: str = "off"
    minimum_diversity_distance: int = 1
    extra_column_time_limit_seconds: float = 10.0
    reservoir_primal_pricing_time_limit_seconds: float = 0.0
    reservoir_primal_pricing_mode: str = "compact_dispatch_windows"
    reservoir_primal_maximum_cabin_calls_per_round: int = 4
    reservoir_dispatch_anchor_count: int = 32
    reservoir_primal_maximum_arc_count: int = 25_000
    reservoir_primal_maximum_passenger_arc_product: int = 250_000
    solver_output: bool = False
    force_all_stop: bool = False

    def __post_init__(self) -> None:
        if self.available_fleet_count < 1:
            raise ValueError("available_fleet_count must be positive")
        if not self.example_id or not self.reservoir_entry_state:
            raise ValueError("example_id and reservoir_entry_state are required")

    @property
    def fingerprint(self) -> str:
        encoded = json.dumps(
            asdict(self), sort_keys=True, separators=(",", ":")
        ).encode()
        return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class DddRootCgTrialResult:
    fingerprint: str
    payload: Mapping[str, Any]
    output_path: Path
    checkpoint_path: Path | None


class DddRootCgTrialRunner:
    """Typed in-process adapter around the established root-CG application."""

    def run(
        self,
        config: DddRootCgTrialConfig,
        *,
        output_dir: Path,
        checkpoint_path: Path,
        resume_checkpoint: Path | None = None,
        neighbor_k_checkpoint: Path | None = None,
        progress_callback: Callable[[Mapping[str, Any]], None] | None = None,
        console_progress: bool = False,
    ) -> DddRootCgTrialResult:
        if resume_checkpoint is not None and neighbor_k_checkpoint is not None:
            raise ValueError("resume and neighbor checkpoints are mutually exclusive")
        from ropeway_skip_stop_optimization.benchmarking.ddd_root_cg_application import (
            run_namespace,
        )

        namespace = argparse.Namespace(
            example=config.example_id,
            fleet_mode="reservoir_dispatch",
            cabins=config.available_fleet_count,
            horizon=250.0,
            warmup_seconds=config.warmup_seconds,
            reservoir_entry_state=config.reservoir_entry_state,
            reservoir_entry_resource=list(config.reservoir_entry_resource_ids),
            reservoir_boundary_mode=config.reservoir_boundary_mode,
            reservoir_dispatch_resource=list(
                config.reservoir_dispatch_resource_ids
            ),
            reservoir_first_route=list(config.reservoir_first_route_option_ids),
            dispatch_cardinality=config.dispatch_cardinality,
            force_all_stop=config.force_all_stop,
            objective=config.objective,
            max_iterations=config.max_iterations,
            total_time_limit=config.total_time_limit_seconds,
            pricing_time_limit=config.pricing_time_limit_seconds,
            waiting_step_seconds=config.waiting_step_seconds,
            pricing_threads=config.pricing_threads,
            master_dual_mode=config.master_dual_mode,
            proof_pricing_mip_focus=config.proof_pricing_mip_focus,
            extra_pricing_mip_focus=config.extra_pricing_mip_focus,
            pricing_formulation=config.pricing_formulation,
            max_pair_checks=config.max_pair_checks,
            conflict_row_mode=config.conflict_row_mode,
            max_resource_window_rounds=config.max_resource_window_rounds,
            columns_per_cabin_per_round=config.columns_per_cabin_per_round,
            diversity_mode=config.diversity_mode,
            minimum_diversity_distance=config.minimum_diversity_distance,
            extra_column_time_limit=config.extra_column_time_limit_seconds,
            oip_primal_pricing_time_limit=0.0,
            reservoir_primal_pricing_time_limit=(
                config.reservoir_primal_pricing_time_limit_seconds
            ),
            reservoir_primal_pricing_mode=config.reservoir_primal_pricing_mode,
            reservoir_primal_max_cabin_calls=(
                config.reservoir_primal_maximum_cabin_calls_per_round
            ),
            reservoir_dispatch_anchor_count=config.reservoir_dispatch_anchor_count,
            reservoir_primal_max_arcs=config.reservoir_primal_maximum_arc_count,
            reservoir_primal_max_passenger_arc_product=(
                config.reservoir_primal_maximum_passenger_arc_product
            ),
            solver_output=config.solver_output,
            no_progress=not console_progress,
            output_dir=output_dir,
            checkpoint_path=checkpoint_path,
            resume_checkpoint=resume_checkpoint,
            neighbor_k_checkpoint=neighbor_k_checkpoint,
            no_checkpoint=False,
        )
        raw = run_namespace(
            namespace,
            progress_hook=(
                None
                if progress_callback is None
                else lambda iteration: progress_callback(asdict(iteration))
            ),
        )
        return DddRootCgTrialResult(
            fingerprint=config.fingerprint,
            payload=dict(raw["payload"]),
            output_path=Path(raw["output_path"]),
            checkpoint_path=(
                None
                if raw["checkpoint_path"] is None
                else Path(raw["checkpoint_path"])
            ),
        )
