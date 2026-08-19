from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
from typing import Any

from ropeway_skip_stop_optimization.optimization.ddd.models import (
    DddResourceUsage,
    DddRouteDecision,
)
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
from ropeway_skip_stop_optimization.optimization.ddd.trajectory_problem import (
    DddReservoirBoundaryConfig,
    DddReservoirBoundaryMode,
    DddReservoirDispatchCardinalityMode,
    DddReservoirTrajectoryKind,
    DddReservoirTrajectoryStartDomain,
    DddReservoirTrajectoryState,
    DddTrajectoryFleetMode,
    DddTrajectoryWaitingPolicy,
)
from ropeway_skip_stop_optimization.optimization.ean.fleet import (
    EanInitialPlacementState,
    EanInitialPlacementStateKind,
)
from ropeway_skip_stop_optimization.optimization.ean.passenger_objective import (
    EanPassengerObjective,
)


DDD_TRAJECTORY_ROOT_CHECKPOINT_SCHEMA_VERSION = 5


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
    schema_version = payload.get("schema_version")
    if schema_version not in (1, 2, 3, 4, DDD_TRAJECTORY_ROOT_CHECKPOINT_SCHEMA_VERSION):
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
        checkpoint_cabin_count = len(
            {int(item["cabin_id"]) for item in payload["trajectories"]}
        )
        root_lp_certified = bool(
            iterations
            and iterations[-1].added_trajectory_count == 0
            and iterations[-1].minimum_reduced_cost is not None
            and iterations[-1].minimum_reduced_cost >= -1e-7
            and iterations[-1].exact_pricing_cabin_count
            == checkpoint_cabin_count
        )
    reservoir_payload = payload.get("reservoir_start_domain")
    reservoir_start_domain = (
        None
        if reservoir_payload is None
        else DddReservoirTrajectoryStartDomain(
            cabin_ids=tuple(int(item) for item in reservoir_payload["cabin_ids"]),
            boundary=DddReservoirBoundaryConfig(
                id=str(reservoir_payload["boundary"]["id"]),
                entry_state_id=str(
                    reservoir_payload["boundary"]["entry_state_id"]
                ),
                boundary_mode=DddReservoirBoundaryMode(
                    reservoir_payload["boundary"].get(
                        "boundary_mode",
                        DddReservoirBoundaryMode.IDEAL_NON_LIMITING.value,
                    )
                ),
                dispatch_resource_usages=tuple(
                    DddResourceUsage(
                        resource_id=str(item["resource_id"]),
                        leader_clear_offset_seconds=float(
                            item["leader_clear_offset_seconds"]
                        ),
                        follower_enter_offset_seconds=float(
                            item["follower_enter_offset_seconds"]
                        ),
                        separation_after_seconds=(
                            None
                            if item.get("separation_after_seconds") is None
                            else float(item["separation_after_seconds"])
                        ),
                        leader_clear_wait_coefficient=int(
                            item.get("leader_clear_wait_coefficient", 0)
                        ),
                        follower_enter_wait_coefficient=int(
                            item.get("follower_enter_wait_coefficient", 0)
                        ),
                    )
                    for item in reservoir_payload["boundary"].get(
                        "dispatch_resource_usages", ()
                    )
                ),
                required_entry_resource_ids=tuple(
                    str(item)
                    for item in reservoir_payload["boundary"].get(
                        "required_entry_resource_ids", ()
                    )
                ),
                allowed_first_route_option_ids=tuple(
                    str(item)
                    for item in reservoir_payload["boundary"].get(
                        "allowed_first_route_option_ids", ()
                    )
                ),
            ),
            warmup_seconds=float(reservoir_payload["warmup_seconds"]),
            maximum_visit_count=int(reservoir_payload["maximum_visit_count"]),
            cardinality_mode=DddReservoirDispatchCardinalityMode(
                reservoir_payload["cardinality_mode"]
            ),
        )
    )
    waiting_payload = payload.get("waiting_policy")
    waiting_policy = (
        DddTrajectoryWaitingPolicy()
        if waiting_payload is None
        else DddTrajectoryWaitingPolicy(
            domain=DddTrajectoryWaitingDomain(waiting_payload["domain"]),
            step_seconds=(
                None
                if waiting_payload.get("step_seconds") is None
                else float(waiting_payload["step_seconds"])
            ),
            maximum_wait_seconds_by_station_id=tuple(
                (str(station_id), float(maximum))
                for station_id, maximum in waiting_payload.get(
                    "maximum_wait_seconds_by_station_id", ()
                )
            ),
            earliest_wait_time_seconds=float(
                waiting_payload.get("earliest_wait_time_seconds", 0.0)
            ),
        )
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
        fleet_mode=DddTrajectoryFleetMode(
            payload.get("fleet_mode", DddTrajectoryFleetMode.FIXED_STARTS.value)
        ),
        reservoir_start_domain=reservoir_start_domain,
        waiting_policy=waiting_policy,
    )


def _iteration_from_dict(payload: dict[str, Any]) -> DddTrajectoryRootCgIteration:
    values = dict(payload)
    values["pricing_diagnostics"] = tuple(
        _pricing_diagnostic_from_dict(item) for item in payload["pricing_diagnostics"]
    )
    values["primal_pricing_status_counts"] = tuple(
        (str(status), int(count))
        for status, count in payload.get("primal_pricing_status_counts", ())
    )
    values["primal_pricing_details"] = tuple(
        str(item) for item in payload.get("primal_pricing_details", ())
    )
    return DddTrajectoryRootCgIteration(**values)


def _pricing_diagnostic_from_dict(
    payload: dict[str, Any],
) -> DddTrajectoryRootCgPricingDiagnostic:
    values = dict(payload)
    values["status"] = DddTrajectoryExactPricingStatus(payload["status"])
    return DddTrajectoryRootCgPricingDiagnostic(**values)


def _trajectory_from_dict(payload: dict[str, Any]) -> DddReferenceTrajectory:
    initial_payload = payload.get("initial_state")
    initial_state = (
        None
        if initial_payload is None
        else EanInitialPlacementState(
            cabin_id=int(initial_payload["cabin_id"]),
            kind=EanInitialPlacementStateKind(initial_payload["kind"]),
            switch_id=str(initial_payload["switch_id"]),
            visit_index=int(initial_payload["visit_index"]),
            progress=float(initial_payload["progress"]),
            previous_event_time_seconds=float(
                initial_payload["previous_event_time_seconds"]
            ),
            next_event_time_seconds=float(initial_payload["next_event_time_seconds"]),
            previous_service=initial_payload.get("previous_service"),
        )
    )
    reservoir_payload = payload.get("reservoir_state")
    reservoir_state = (
        None
        if reservoir_payload is None
        else DddReservoirTrajectoryState(
            kind=DddReservoirTrajectoryKind(reservoir_payload["kind"]),
            interface_id=str(reservoir_payload["interface_id"]),
            dispatch_time_seconds=(
                None
                if reservoir_payload.get("dispatch_time_seconds") is None
                else float(reservoir_payload["dispatch_time_seconds"])
            ),
        )
    )
    return DddReferenceTrajectory(
        cabin_id=int(payload["cabin_id"]),
        visits=tuple(
            _visit_from_dict(
                item,
                continuous=(initial_state is not None or reservoir_state is not None),
            )
            for item in payload["visits"]
        ),
        initial_state=initial_state,
        boundary_resource_occurrences=tuple(
            _occurrence_from_dict(item, continuous=True)
            for item in payload.get("boundary_resource_occurrences", ())
        ),
        reservoir_state=reservoir_state,
    )


def _visit_from_dict(payload: dict[str, Any], *, continuous: bool = False) -> DddReferenceVisit:
    return DddReferenceVisit(
        cabin_id=int(payload["cabin_id"]),
        visit_index=int(payload["visit_index"]),
        state_id=str(payload["state_id"]),
        route_option_id=str(payload["route_option_id"]),
        decision=DddRouteDecision(payload["decision"]),
        switch_time_seconds=float(payload["switch_time_seconds"]),
        next_switch_time_seconds=float(payload["next_switch_time_seconds"]),
        resource_occurrences=tuple(
            _occurrence_from_dict(item, continuous=continuous)
            for item in payload["resource_occurrences"]
        ),
        wait_seconds=float(payload.get("wait_seconds", 0.0)),
        quantize_times=not continuous,
    )


def _occurrence_from_dict(
    payload: dict[str, Any], *, continuous: bool
) -> DddReferenceResourceOccurrence:
    return DddReferenceResourceOccurrence(
        resource_id=str(payload["resource_id"]),
        cabin_id=int(payload["cabin_id"]),
        visit_index=int(payload["visit_index"]),
        leader_clear_time_seconds=float(payload["leader_clear_time_seconds"]),
        follower_enter_time_seconds=float(payload["follower_enter_time_seconds"]),
        separation_after_seconds=(
            None
            if payload.get("separation_after_seconds") is None
            else float(payload["separation_after_seconds"])
        ),
        boundary_only=bool(payload.get("boundary_only", False)),
        boundary_origin=bool(payload.get("boundary_origin", False)),
        quantize_times=not continuous,
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
