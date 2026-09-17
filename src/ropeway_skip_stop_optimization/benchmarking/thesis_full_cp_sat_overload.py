"""Validated preparation and portable reporting for the thesis overload pilot."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
import json
import math
from pathlib import Path
from time import time

from .optimization_live_store import OptimizationLivePaths, OptimizationLiveStore
from .reservoir_cp_fleet_continuation import plan_diagnostics
from .thesis_cases import (
    ExperimentCaseSpec,
    ThesisDemandFamily,
    ThesisDemandProfile,
    ThesisGeometry,
    ThesisObjective,
    ThesisTopology,
    prepare_experiment_case,
)
from ..optimization.ddd.cp_sat_certificate import atomic_json, stable_fingerprint
from ..optimization.ddd.reservoir_cp_sat import DddReservoirCpObjective
from ..optimization.ddd.reservoir_cp_sat_certificate import (
    DddReservoirCpPlan,
    reservoir_cp_plan_from_payload,
    validate_reservoir_cp_plan,
)
from ..optimization.ddd.time_ticks import DDD_TIME_TICKS_PER_SECOND
from ..optimization.ddd.reservoir_hybrid.domain import load_reference


@dataclass(frozen=True, slots=True)
class ThesisOverloadPilotConfig:
    reference_dir: Path
    output_dir: Path
    frontend_root: Path | None = None
    campaign_id: str = "thesis_t5r_f2_full_cp_sat_overload_20260916"
    demand_total: int = 3210
    fleet_cap: int = 69
    release_resolution_seconds: int = 15
    total_time_limit_seconds: float = 1800.0
    reference_time_limit_seconds: float = 120.0
    workers: int = 12
    memory_limit_gib: float = 32.0
    seed: int = 0
    passenger_encoding: str = "groups"

    def validate(self) -> None:
        if not (self.reference_dir / "result.json").is_file() or not (
            self.reference_dir / "best.json"
        ).is_file():
            raise ValueError("All-Stop reference directory is incomplete")
        if self.demand_total != 3210 or self.fleet_cap != 69:
            raise ValueError("first overload pilot is frozen at N=3,210 and K<=69")
        if self.release_resolution_seconds != 15:
            raise ValueError("first overload pilot requires 15-second releases")
        if self.total_time_limit_seconds <= self.reference_time_limit_seconds + 10:
            raise ValueError("total budget must leave time for the full solve and finalization")
        if self.workers <= 0 or not 0 < self.memory_limit_gib <= 32:
            raise ValueError("invalid resource configuration")
        if self.passenger_encoding not in {"groups", "od_inventory"}:
            raise ValueError("invalid passenger encoding")


def pilot_spec(demand_total: int = 3210) -> ExperimentCaseSpec:
    return ExperimentCaseSpec(
        topology=ThesisTopology.T5R,
        geometry=ThesisGeometry.G500,
        demand_family=ThesisDemandFamily.F2,
        demand_profile=ThesisDemandProfile.P0,
        objective=ThesisObjective.UNSERVED,
        demand_total=demand_total,
        release_resolution_seconds=15,
        maximum_wait_seconds=1200.0,
    )


def prepare_pilot(config: ThesisOverloadPilotConfig):
    config.validate()
    reference_result = json.loads((config.reference_dir / "result.json").read_text())
    run = reference_result.get("run", {})
    if (
        reference_result.get("method") != "all_stop_phase"
        or run.get("capacity") != 2918
        or run.get("capacity_proven") is not True
        or run.get("proof_scope")
        != "REGULAR_NO_WAIT_ALL_STOP_COMMON_PHASE_AND_NESTED_DEMAND"
    ):
        raise ValueError("reference is not the proven T5R/F2 All-Stop capacity")

    prepared = prepare_experiment_case(pilot_spec(config.demand_total), fleet_cap=config.fleet_cap)
    source_domain, source_plan = load_reference(config.reference_dir / "best.json")
    source_problem = source_domain.problem
    target_problem = prepared.problem

    excluded = {"available_fleet_count", "demand_groups", "operating_mode", "derived_visit_count"}
    source_contract = {k: v for k, v in source_problem.manifest.items() if k not in excluded}
    target_contract = {k: v for k, v in target_problem.manifest.items() if k not in excluded}
    if source_contract != target_contract:
        raise ValueError("All-Stop reference and overload problem differ physically")
    source_groups = {group.id: group for group in source_problem.demand_groups}
    target_groups = {group.id: group for group in target_problem.demand_groups}
    if source_groups.keys() != target_groups.keys() or any(
        target_groups[key].count < group.count for key, group in source_groups.items()
    ):
        raise ValueError("overload demand is not a deterministic nesting of the reference")

    transferred = DddReservoirCpPlan(source_plan.trips, dict(source_plan.ride_counts))
    metrics = validate_reservoir_cp_plan(target_problem, transferred)
    if metrics.served != 2918 or metrics.unserved != config.demand_total - 2918:
        raise ValueError("transferred All-Stop plan does not preserve the reference service")
    return prepared, transferred, reference_result


def lexicographic_score(problem, plan: DddReservoirCpPlan) -> int:
    metrics = validate_reservoir_cp_plan(problem, plan)
    horizon = problem.movement.passenger_service_end_tick
    from ..optimization.ddd.time_ticks import ddd_seconds_to_tick

    bound = sum(
        group.count * max(0, horizon - ddd_seconds_to_tick(group.release_time_seconds))
        for group in problem.demand_groups
    )
    return (bound + 1) * metrics.unserved + metrics.journey_time_tick


def detail_point(problem, plan: DddReservoirCpPlan, *, seconds: float, lb=None) -> dict:
    metrics = validate_reservoir_cp_plan(problem, plan)
    upper = lexicographic_score(problem, plan)
    lower = None if lb is None or not math.isfinite(float(lb)) else max(0, math.floor(float(lb)))
    return {
        "seconds": seconds,
        "ub": upper,
        "lb": lower,
        "gap_percent": None
        if lower is None
        else max(0, upper - lower) / max(1, abs(upper)) * 100,
        "served": metrics.served,
        "unserved": metrics.unserved,
        "journey_time_seconds": (
            metrics.journey_time_tick / DDD_TIME_TICKS_PER_SECOND
        ),
        "used_fleet": metrics.used_fleet,
    }


def publish_live(
    config: ThesisOverloadPilotConfig,
    *,
    status: str,
    reference: dict,
    points: list[dict],
    started_unix: float,
    model_stats: dict | None = None,
    termination: str | None = None,
) -> dict:
    latest = points[-1] if points else reference
    payload = {
        "schema": "thesis_full_cp_sat_overload_frontend_v1",
        "campaign_id": config.campaign_id,
        "status": status,
        "updated_unix": time(),
        "elapsed_seconds": max(0.0, time() - started_unix),
        "demand_total": config.demand_total,
        "fleet_cap": config.fleet_cap,
        "all_stop_capacity": 2918,
        "objective": DddReservoirCpObjective.SERVICE_THEN_JOURNEY.value,
        "passenger_encoding": config.passenger_encoding,
        "reference": reference,
        "points": points,
        "latest": latest,
        "model_stats": model_stats or {},
        "termination": termination,
    }
    atomic_json(config.output_dir / "detail.json", payload)
    if config.frontend_root is not None:
        atomic_json(config.frontend_root / config.campaign_id / "detail.json", payload)
    snapshot = {
        "schema_version": 1,
        "campaign_id": config.campaign_id,
        "label": "T5R/F2 · full CP-SAT at 110% All-Stop capacity",
        "status": status,
        "objective": "service_then_journey",
        "method": "full_reservoir_cp_sat",
        "formulation": "legacy_product",
        "campaign_kind": "thesis_full_cp_sat_overload",
        "operating_mode": "skip_stop",
        "updated_at_utc": datetime.now(UTC).isoformat(),
        "trials": [],
        "events": [],
        "trial_count": 1,
        "completed_trial_count": int(status in {"complete", "failed", "interrupted", "resource_limit"}),
    }
    store = OptimizationLiveStore(OptimizationLivePaths(config.output_dir, config.frontend_root))
    store.publish(snapshot)
    return payload


def campaign_identity(config: ThesisOverloadPilotConfig, problem) -> str:
    return stable_fingerprint(
        {
            "schema": "thesis_full_cp_sat_overload_campaign_v1",
            "config": {
                **asdict(config),
                "reference_dir": str(config.reference_dir),
                "output_dir": str(config.output_dir),
                "frontend_root": None if config.frontend_root is None else str(config.frontend_root),
            },
            "problem": problem.manifest,
        }
    )
