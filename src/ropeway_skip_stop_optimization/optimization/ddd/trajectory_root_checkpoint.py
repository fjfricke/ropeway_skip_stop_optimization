from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
from typing import Any

from ropeway_skip_stop_optimization.optimization.ddd.models import DddRouteDecision
from ropeway_skip_stop_optimization.optimization.ddd.reference import (
    DddReferenceResourceOccurrence,
    DddReferenceTrajectory,
    DddReferenceVisit,
)
from ropeway_skip_stop_optimization.optimization.ddd.trajectory_column_generation import (
    DddTrajectoryWaitingDomain,
)
from ropeway_skip_stop_optimization.optimization.ddd.trajectory_exact_pricing import (
    DddTrajectoryExactPricingStatus,
)
from ropeway_skip_stop_optimization.optimization.ddd.trajectory_resource_windows import (
    DddTrajectoryConflictRowMode,
    DddTrajectoryResourceWindow,
)
from ropeway_skip_stop_optimization.optimization.ddd.trajectory_root_column_generation import (
    DddTrajectoryRootCgIteration,
    DddTrajectoryRootCgPricingDiagnostic,
    DddTrajectoryRootCgState,
)
from ropeway_skip_stop_optimization.optimization.ean.passenger_objective import (
    EanPassengerObjective,
)


DDD_TRAJECTORY_ROOT_CHECKPOINT_SCHEMA_VERSION = 1


def write_ddd_trajectory_root_cg_checkpoint(
    path: Path,
    state: DddTrajectoryRootCgState,
) -> None:
    """Atomically persist a completed root-CG round."""

    payload = {
        "schema_version": DDD_TRAJECTORY_ROOT_CHECKPOINT_SCHEMA_VERSION,
        "state": asdict(state),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(f".{path.name}.tmp")
    temporary_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary_path.replace(path)


def read_ddd_trajectory_root_cg_checkpoint(
    path: Path,
) -> DddTrajectoryRootCgState:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(
            f"cannot read trajectory checkpoint {path}: {error}"
        ) from error
    if payload.get("schema_version") != DDD_TRAJECTORY_ROOT_CHECKPOINT_SCHEMA_VERSION:
        raise ValueError("unsupported trajectory checkpoint schema version")
    state = payload.get("state")
    if not isinstance(state, dict):
        raise ValueError("trajectory checkpoint state is missing")
    try:
        return _state_from_dict(state)
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError(f"invalid trajectory checkpoint {path}: {error}") from error


def _state_from_dict(payload: dict[str, Any]) -> DddTrajectoryRootCgState:
    iterations = tuple(_iteration_from_dict(item) for item in payload["iterations"])
    root_lp_certified = payload.get("root_lp_certified")
    if root_lp_certified is None:
        root_lp_certified = bool(
            iterations
            and iterations[-1].added_trajectory_count == 0
            and iterations[-1].minimum_reduced_cost is not None
            and iterations[-1].minimum_reduced_cost >= -1e-7
            and iterations[-1].exact_pricing_cabin_count > 0
        )
    return DddTrajectoryRootCgState(
        instance_fingerprint=str(payload["instance_fingerprint"]),
        objective=EanPassengerObjective(payload["objective"]),
        conflict_row_mode=DddTrajectoryConflictRowMode(payload["conflict_row_mode"]),
        completed_rounds=int(payload["completed_rounds"]),
        certified_lower_bound=float(payload["certified_lower_bound"]),
        best_upper_bound=(
            None
            if payload["best_upper_bound"] is None
            else float(payload["best_upper_bound"])
        ),
        root_lp_certified=bool(root_lp_certified),
        incumbent_option_ids=tuple(
            str(item) for item in payload["incumbent_option_ids"]
        ),
        incumbent_ride_values_by_id={
            str(ride_id): float(value)
            for ride_id, value in payload.get(
                "incumbent_ride_values_by_id",
                {},
            ).items()
        },
        iterations=iterations,
        trajectories=tuple(
            _trajectory_from_dict(item) for item in payload["trajectories"]
        ),
        resource_windows=tuple(
            _resource_window_from_dict(item) for item in payload["resource_windows"]
        ),
        total_seconds=float(payload["total_seconds"]),
    )


def _iteration_from_dict(payload: dict[str, Any]) -> DddTrajectoryRootCgIteration:
    values = dict(payload)
    values["pricing_diagnostics"] = tuple(
        _pricing_diagnostic_from_dict(item) for item in payload["pricing_diagnostics"]
    )
    return DddTrajectoryRootCgIteration(**values)


def _pricing_diagnostic_from_dict(
    payload: dict[str, Any],
) -> DddTrajectoryRootCgPricingDiagnostic:
    values = dict(payload)
    values["status"] = DddTrajectoryExactPricingStatus(payload["status"])
    return DddTrajectoryRootCgPricingDiagnostic(**values)


def _trajectory_from_dict(payload: dict[str, Any]) -> DddReferenceTrajectory:
    return DddReferenceTrajectory(
        cabin_id=int(payload["cabin_id"]),
        visits=tuple(_visit_from_dict(item) for item in payload["visits"]),
    )


def _visit_from_dict(payload: dict[str, Any]) -> DddReferenceVisit:
    return DddReferenceVisit(
        cabin_id=int(payload["cabin_id"]),
        visit_index=int(payload["visit_index"]),
        state_id=str(payload["state_id"]),
        route_option_id=str(payload["route_option_id"]),
        decision=DddRouteDecision(payload["decision"]),
        switch_time_seconds=float(payload["switch_time_seconds"]),
        next_switch_time_seconds=float(payload["next_switch_time_seconds"]),
        resource_occurrences=tuple(
            DddReferenceResourceOccurrence(**item)
            for item in payload["resource_occurrences"]
        ),
    )


def _resource_window_from_dict(
    payload: dict[str, Any],
) -> DddTrajectoryResourceWindow:
    return DddTrajectoryResourceWindow(
        resource_id=str(payload["resource_id"]),
        anchor_tick=int(payload["anchor_tick"]),
        capacity=int(payload["capacity"]),
        waiting_domain=DddTrajectoryWaitingDomain(payload["waiting_domain"]),
        interval_semantics=str(payload["interval_semantics"]),
    )
