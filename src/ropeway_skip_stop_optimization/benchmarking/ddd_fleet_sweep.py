from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, datetime
from enum import StrEnum
import hashlib
import json
from pathlib import Path
import threading
import time
from typing import Any, Callable, Mapping, Protocol, Sequence

from ropeway_skip_stop_optimization.benchmarking.optimization_events import (
    OptimizationEventKind,
)
from ropeway_skip_stop_optimization.benchmarking.optimization_live_store import (
    OptimizationLiveStore,
    reduce_optimization_events,
)


class DispatchCardinality(StrEnum):
    OPTIONAL = "optional"
    EXACT = "exact"


@dataclass(frozen=True, slots=True)
class DddFleetPolicyConfig:
    id: str
    label: str
    example_id: str
    reservoir_entry_state: str
    reservoir_entry_resource_ids: tuple[str, ...] = ()
    reservoir_first_route_option_ids: tuple[str, ...] = ()
    reservoir_boundary_mode: str = "ideal_non_limiting"
    reservoir_dispatch_resource_ids: tuple[str, ...] = ()
    waiting_step_seconds: float = 1.0
    force_all_stop: bool = False
    tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.id or not self.example_id or not self.reservoir_entry_state:
            raise ValueError("policy id, example id, and entry state are required")
        if self.waiting_step_seconds <= 0:
            raise ValueError("waiting_step_seconds must be positive")


@dataclass(frozen=True, slots=True)
class DddFleetSweepConfig:
    campaign_id: str
    label: str
    policies: tuple[DddFleetPolicyConfig, ...]
    fleet_counts: tuple[int, ...]
    objective: str = "journey_time"
    dispatch_cardinality: DispatchCardinality = DispatchCardinality.OPTIONAL
    warmup_seconds: float = 300.0
    max_iterations: int = 30
    total_time_limit_seconds: float | None = None
    pricing_time_limit_seconds: float = 5.0
    pricing_threads: int = 1
    reservoir_primal_pricing_time_limit_seconds: float = 0.0
    reservoir_primal_maximum_cabin_calls_per_round: int = 4
    service_targets: tuple[float, ...] = ()
    cabin_costs: tuple[float, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.campaign_id or not self.label:
            raise ValueError("campaign id and label are required")
        if not self.policies:
            raise ValueError("at least one policy is required")
        if len({item.id for item in self.policies}) != len(self.policies):
            raise ValueError("policy ids must be unique")
        if not self.fleet_counts or any(item < 1 for item in self.fleet_counts):
            raise ValueError("fleet counts must contain positive integers")
        if len(set(self.fleet_counts)) != len(self.fleet_counts):
            raise ValueError("fleet counts must be unique")
        if self.max_iterations < 1:
            raise ValueError("max_iterations must be positive")
        if self.total_time_limit_seconds is not None and self.total_time_limit_seconds <= 0:
            raise ValueError("total_time_limit_seconds must be positive")
        if self.pricing_time_limit_seconds <= 0:
            raise ValueError("pricing_time_limit_seconds must be positive")
        if self.pricing_threads < 1:
            raise ValueError("pricing_threads must be positive")
        if self.reservoir_primal_pricing_time_limit_seconds < 0:
            raise ValueError(
                "reservoir_primal_pricing_time_limit_seconds must be nonnegative"
            )
        if self.reservoir_primal_maximum_cabin_calls_per_round < 1:
            raise ValueError(
                "reservoir_primal_maximum_cabin_calls_per_round must be positive"
            )

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> DddFleetSweepConfig:
        return cls(
            campaign_id=str(value["campaign_id"]),
            label=str(value.get("label", value["campaign_id"])),
            policies=tuple(
                DddFleetPolicyConfig(
                    id=str(item["id"]),
                    label=str(item.get("label", item["id"])),
                    example_id=str(item["example_id"]),
                    reservoir_entry_state=str(item["reservoir_entry_state"]),
                    reservoir_entry_resource_ids=tuple(
                        str(part) for part in item.get("reservoir_entry_resource_ids", ())
                    ),
                    reservoir_first_route_option_ids=tuple(
                        str(part)
                        for part in item.get("reservoir_first_route_option_ids", ())
                    ),
                    reservoir_boundary_mode=str(
                        item.get("reservoir_boundary_mode", "ideal_non_limiting")
                    ),
                    reservoir_dispatch_resource_ids=tuple(
                        str(part)
                        for part in item.get("reservoir_dispatch_resource_ids", ())
                    ),
                    waiting_step_seconds=float(item.get("waiting_step_seconds", 1.0)),
                    force_all_stop=bool(item.get("force_all_stop", False)),
                    tags=tuple(str(part) for part in item.get("tags", ())),
                )
                for item in value["policies"]
            ),
            fleet_counts=tuple(int(item) for item in value["fleet_counts"]),
            objective=str(value.get("objective", "journey_time")),
            dispatch_cardinality=DispatchCardinality(
                str(value.get("dispatch_cardinality", "optional"))
            ),
            warmup_seconds=float(value.get("warmup_seconds", 300.0)),
            max_iterations=int(value.get("max_iterations", 30)),
            total_time_limit_seconds=(
                None
                if value.get("total_time_limit_seconds") is None
                else float(value["total_time_limit_seconds"])
            ),
            pricing_time_limit_seconds=float(
                value.get("pricing_time_limit_seconds", 5.0)
            ),
            pricing_threads=int(value.get("pricing_threads", 1)),
            reservoir_primal_pricing_time_limit_seconds=float(
                value.get("reservoir_primal_pricing_time_limit_seconds", 0.0)
            ),
            reservoir_primal_maximum_cabin_calls_per_round=int(
                value.get("reservoir_primal_maximum_cabin_calls_per_round", 4)
            ),
            service_targets=tuple(float(item) for item in value.get("service_targets", ())),
            cabin_costs=tuple(float(item) for item in value.get("cabin_costs", ())),
            metadata=dict(value.get("metadata", {})),
        )

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["dispatch_cardinality"] = self.dispatch_cardinality.value
        return value


@dataclass(frozen=True, slots=True)
class DddFleetTrialResult:
    policy_id: str
    available_fleet_count: int
    status: str
    certified_lower_bound: float
    validated_upper_bound: float | None
    relative_gap: float | None
    root_lp_certified: bool
    elapsed_seconds: float
    checkpoint_path: str | None = None
    result_path: str | None = None
    dispatched_fleet_count: int | None = None
    detail: str = ""
    fingerprint: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class BoundEnvelopePoint:
    available_fleet_count: int
    raw_lower_bound: float
    raw_upper_bound: float | None
    tightened_lower_bound: float
    tightened_upper_bound: float | None
    lower_bound_source_k: int
    upper_bound_source_k: int | None


class DddFleetSweepAnalyzer:
    def analyze(
        self,
        config: DddFleetSweepConfig,
        trials: Sequence[DddFleetTrialResult],
    ) -> dict[str, Any]:
        by_policy: dict[str, list[DddFleetTrialResult]] = {}
        for trial in trials:
            by_policy.setdefault(trial.policy_id, []).append(trial)
        policy_results: dict[str, Any] = {}
        for policy in config.policies:
            policy_trials = sorted(
                by_policy.get(policy.id, ()),
                key=lambda item: item.available_fleet_count,
            )
            envelope = self._envelope(
                policy_trials,
                optional=config.dispatch_cardinality is DispatchCardinality.OPTIONAL,
            )
            policy_results[policy.id] = {
                "policy": asdict(policy),
                "trials": [item.to_dict() for item in policy_trials],
                "bounds": [asdict(item) for item in envelope],
                "service_targets": [
                    self._service_target(target, envelope)
                    for target in config.service_targets
                ],
                "cabin_costs": [
                    self._cabin_cost(cost, envelope) for cost in config.cabin_costs
                ],
            }
        return {
            "policies": policy_results,
            "policy_comparisons": self._policy_comparisons(
                policy_results,
                {item.id: item for item in config.policies},
            ),
        }

    @staticmethod
    def _envelope(
        trials: Sequence[DddFleetTrialResult], *, optional: bool
    ) -> tuple[BoundEnvelopePoint, ...]:
        points: list[BoundEnvelopePoint] = []
        for trial in trials:
            lower_candidates = (
                [item for item in trials if item.available_fleet_count >= trial.available_fleet_count]
                if optional
                else [trial]
            )
            lower_source = max(
                lower_candidates, key=lambda item: item.certified_lower_bound
            )
            upper_candidates = [
                item
                for item in trials
                if item.validated_upper_bound is not None
                and (
                    not optional
                    and item.available_fleet_count == trial.available_fleet_count
                    or optional
                    and item.available_fleet_count <= trial.available_fleet_count
                )
            ]
            upper_source = (
                min(upper_candidates, key=lambda item: float(item.validated_upper_bound))
                if upper_candidates
                else None
            )
            points.append(
                BoundEnvelopePoint(
                    available_fleet_count=trial.available_fleet_count,
                    raw_lower_bound=trial.certified_lower_bound,
                    raw_upper_bound=trial.validated_upper_bound,
                    tightened_lower_bound=lower_source.certified_lower_bound,
                    tightened_upper_bound=(
                        None
                        if upper_source is None
                        else upper_source.validated_upper_bound
                    ),
                    lower_bound_source_k=lower_source.available_fleet_count,
                    upper_bound_source_k=(
                        None
                        if upper_source is None
                        else upper_source.available_fleet_count
                    ),
                )
            )
        return tuple(points)

    @staticmethod
    def _service_target(target: float, points: Sequence[BoundEnvelopePoint]) -> dict[str, Any]:
        sufficient = [
            item.available_fleet_count
            for item in points
            if item.tightened_upper_bound is not None
            and item.tightened_upper_bound <= target
        ]
        insufficient = [
            item.available_fleet_count
            for item in points
            if item.tightened_lower_bound > target
        ]
        unresolved = [
            item.available_fleet_count
            for item in points
            if item.available_fleet_count not in sufficient + insufficient
        ]
        return {
            "target": target,
            "smallest_certified_sufficient_k": min(sufficient) if sufficient else None,
            "largest_certified_insufficient_k": max(insufficient) if insufficient else None,
            "unresolved_k": unresolved,
        }

    @staticmethod
    def _cabin_cost(cost: float, points: Sequence[BoundEnvelopePoint]) -> dict[str, Any]:
        possible: list[int] = []
        certified: int | None = None
        for point in points:
            if point.tightened_upper_bound is None:
                continue
            upper = point.tightened_upper_bound + cost * point.available_fleet_count
            if all(
                other.available_fleet_count == point.available_fleet_count
                or upper
                < other.tightened_lower_bound
                + cost * other.available_fleet_count
                for other in points
            ):
                certified = point.available_fleet_count
            if not any(
                other.tightened_upper_bound is not None
                and other.tightened_upper_bound
                + cost * other.available_fleet_count
                < point.tightened_lower_bound
                + cost * point.available_fleet_count
                for other in points
            ):
                possible.append(point.available_fleet_count)
        return {
            "cost": cost,
            "certified_optimal_k": certified,
            "possible_optimal_k": possible,
        }

    @staticmethod
    def _policy_comparisons(
        policy_results: Mapping[str, Any],
        policies: Mapping[str, DddFleetPolicyConfig],
    ) -> list[dict[str, Any]]:
        comparisons: list[dict[str, Any]] = []
        policy_ids = sorted(policy_results)
        for left_index, left_id in enumerate(policy_ids):
            left_bounds = {
                item["available_fleet_count"]: item
                for item in policy_results[left_id]["bounds"]
            }
            for right_id in policy_ids[left_index + 1 :]:
                left_policy = policies[left_id]
                right_policy = policies[right_id]
                if (
                    left_policy.waiting_step_seconds
                    != right_policy.waiting_step_seconds
                    or left_policy.reservoir_entry_state
                    != right_policy.reservoir_entry_state
                    or left_policy.reservoir_boundary_mode
                    != right_policy.reservoir_boundary_mode
                    or left_policy.reservoir_dispatch_resource_ids
                    != right_policy.reservoir_dispatch_resource_ids
                ):
                    continue
                right_bounds = {
                    item["available_fleet_count"]: item
                    for item in policy_results[right_id]["bounds"]
                }
                for fleet_count in sorted(set(left_bounds) & set(right_bounds)):
                    left = left_bounds[fleet_count]
                    right = right_bounds[fleet_count]
                    if (
                        left["tightened_upper_bound"] is None
                        or right["tightened_upper_bound"] is None
                    ):
                        continue
                    comparisons.append(
                        {
                            "left_policy_id": left_id,
                            "right_policy_id": right_id,
                            "available_fleet_count": fleet_count,
                            "difference_lower_bound": (
                                left["tightened_lower_bound"]
                                - right["tightened_upper_bound"]
                            ),
                            "difference_upper_bound": (
                                left["tightened_upper_bound"]
                                - right["tightened_lower_bound"]
                            ),
                        }
                    )
        return comparisons


class FleetTrialExecutor(Protocol):
    def __call__(
        self,
        *,
        config: DddFleetSweepConfig,
        policy: DddFleetPolicyConfig,
        available_fleet_count: int,
        trial_dir: Path,
        resume_checkpoint: Path | None,
        neighbor_checkpoint: Path | None,
        on_round: Callable[[Mapping[str, Any]], None],
    ) -> DddFleetTrialResult: ...


class DddFleetSweepRunner:
    def __init__(
        self,
        *,
        executor: FleetTrialExecutor,
        analyzer: DddFleetSweepAnalyzer | None = None,
    ) -> None:
        self.executor = executor
        self.analyzer = analyzer or DddFleetSweepAnalyzer()

    def run(
        self,
        config: DddFleetSweepConfig,
        *,
        output_root: Path,
        live_store: OptimizationLiveStore,
        progress: bool = False,
    ) -> dict[str, Any]:
        campaign_dir = output_root / config.campaign_id
        campaign_dir.mkdir(parents=True, exist_ok=True)
        _write_json(campaign_dir / "resolved_config.json", config.to_dict())
        self._emit(
            live_store,
            OptimizationEventKind.CAMPAIGN_STARTED,
            config,
            payload={
                "label": config.label,
                "objective": config.objective,
                "trial_count": len(config.policies) * len(config.fleet_counts),
            },
        )
        self._publish(live_store)
        trials: list[DddFleetTrialResult] = []
        for policy in config.policies:
            completed_for_policy: list[DddFleetTrialResult] = []
            for fleet_count in config.fleet_counts:
                trial_dir = campaign_dir / "policies" / policy.id / f"k{fleet_count}"
                trial_dir.mkdir(parents=True, exist_ok=True)
                fingerprint = trial_fingerprint(config, policy, fleet_count)
                existing_result = self._read_completed_trial(
                    trial_dir,
                    expected_fingerprint=fingerprint,
                )
                if existing_result is not None:
                    trials.append(existing_result)
                    completed_for_policy.append(existing_result)
                    self._emit(
                        live_store,
                        OptimizationEventKind.TRIAL_COMPLETED,
                        config,
                        policy=policy,
                        fleet_count=fleet_count,
                        fingerprint=fingerprint,
                        lower=existing_result.certified_lower_bound,
                        upper=existing_result.validated_upper_bound,
                        gap=existing_result.relative_gap,
                        elapsed=existing_result.elapsed_seconds,
                        payload={
                            **existing_result.to_dict(),
                            "resumed_from_result": True,
                        },
                    )
                    self._publish(live_store)
                    if progress:
                        print(
                            f"{policy.id} K={fleet_count} reused completed result "
                            f"LB={existing_result.certified_lower_bound} "
                            f"UB={existing_result.validated_upper_bound}"
                        )
                    continue
                resume = trial_dir / "checkpoint.json"
                neighbor = self._nearest_neighbor_checkpoint(
                    completed_for_policy, fleet_count
                )
                self._emit(
                    live_store,
                    OptimizationEventKind.TRIAL_QUEUED,
                    config,
                    policy=policy,
                    fleet_count=fleet_count,
                    fingerprint=fingerprint,
                )
                self._publish(live_store)
                self._emit(
                    live_store,
                    OptimizationEventKind.TRIAL_STARTED,
                    config,
                    policy=policy,
                    fleet_count=fleet_count,
                    fingerprint=fingerprint,
                )
                self._publish(live_store)
                self._emit(
                    live_store,
                    OptimizationEventKind.STAGE_STARTED,
                    config,
                    policy=policy,
                    fleet_count=fleet_count,
                    fingerprint=fingerprint,
                    stage="root_column_generation",
                )
                self._publish(live_store)
                heartbeat_stop = threading.Event()
                trial_started_at = time.monotonic()
                heartbeat = threading.Thread(
                    target=self._heartbeat,
                    args=(
                        heartbeat_stop,
                        live_store,
                        config,
                        policy,
                        fleet_count,
                        fingerprint,
                        trial_started_at,
                    ),
                    daemon=True,
                    name=f"ddd-heartbeat-{policy.id}-k{fleet_count}",
                )
                heartbeat.start()
                try:
                    result = self.executor(
                        config=config,
                        policy=policy,
                        available_fleet_count=fleet_count,
                        trial_dir=trial_dir,
                        resume_checkpoint=resume if resume.exists() else None,
                        neighbor_checkpoint=(None if resume.exists() else neighbor),
                        on_round=lambda item, p=policy, k=fleet_count, f=fingerprint: self._round(
                            live_store, config, p, k, f, item, progress
                        ),
                    )
                except BaseException as error:
                    self._emit(
                        live_store,
                        OptimizationEventKind.TRIAL_FAILED,
                        config,
                        policy=policy,
                        fleet_count=fleet_count,
                        fingerprint=fingerprint,
                        payload={"error": f"{type(error).__name__}: {error}"},
                    )
                    self._publish(live_store)
                    raise
                finally:
                    heartbeat_stop.set()
                    heartbeat.join(timeout=2.0)
                self._emit(
                    live_store,
                    OptimizationEventKind.STAGE_COMPLETED,
                    config,
                    policy=policy,
                    fleet_count=fleet_count,
                    fingerprint=fingerprint,
                    stage="root_column_generation",
                    elapsed=time.monotonic() - trial_started_at,
                )
                result = replace(result, fingerprint=fingerprint)
                trials.append(result)
                completed_for_policy.append(result)
                _write_json(trial_dir / "result.json", result.to_dict())
                self._emit(
                    live_store,
                    OptimizationEventKind.TRIAL_COMPLETED,
                    config,
                    policy=policy,
                    fleet_count=fleet_count,
                    fingerprint=fingerprint,
                    lower=result.certified_lower_bound,
                    upper=result.validated_upper_bound,
                    gap=result.relative_gap,
                    elapsed=result.elapsed_seconds,
                    payload=result.to_dict(),
                )
                self._publish(live_store)
        analysis = self.analyzer.analyze(config, trials)
        payload = {
            "schema_version": 1,
            "campaign_id": config.campaign_id,
            "label": config.label,
            "objective": config.objective,
            "status": "complete",
            "updated_at_utc": datetime.now(UTC).isoformat(),
            "trial_count": len(trials),
            "completed_trial_count": len(trials),
            "trials": [item.to_dict() for item in trials],
            **analysis,
        }
        self._emit(
            live_store,
            OptimizationEventKind.CAMPAIGN_COMPLETED,
            config,
            payload=payload,
        )
        self._publish(live_store)
        return payload

    @staticmethod
    def _read_completed_trial(
        trial_dir: Path,
        *,
        expected_fingerprint: str,
    ) -> DddFleetTrialResult | None:
        result_path = trial_dir / "result.json"
        if not result_path.exists():
            return None
        value = json.loads(result_path.read_text(encoding="utf-8"))
        if value.get("fingerprint") != expected_fingerprint:
            raise ValueError(
                f"existing trial result fingerprint mismatch at {result_path}"
            )
        return DddFleetTrialResult(
            policy_id=str(value["policy_id"]),
            available_fleet_count=int(value["available_fleet_count"]),
            status=str(value["status"]),
            certified_lower_bound=float(value["certified_lower_bound"]),
            validated_upper_bound=(
                None
                if value.get("validated_upper_bound") is None
                else float(value["validated_upper_bound"])
            ),
            relative_gap=(
                None
                if value.get("relative_gap") is None
                else float(value["relative_gap"])
            ),
            root_lp_certified=bool(value["root_lp_certified"]),
            elapsed_seconds=float(value["elapsed_seconds"]),
            checkpoint_path=(
                None
                if value.get("checkpoint_path") is None
                else str(value["checkpoint_path"])
            ),
            result_path=(
                None if value.get("result_path") is None else str(value["result_path"])
            ),
            dispatched_fleet_count=(
                None
                if value.get("dispatched_fleet_count") is None
                else int(value["dispatched_fleet_count"])
            ),
            detail=str(value.get("detail", "")),
            fingerprint=str(value["fingerprint"]),
        )

    @staticmethod
    def _nearest_neighbor_checkpoint(
        completed: Sequence[DddFleetTrialResult], target_k: int
    ) -> Path | None:
        candidates = [
            item
            for item in completed
            if item.checkpoint_path is not None and Path(item.checkpoint_path).exists()
        ]
        if not candidates:
            return None
        nearest = min(
            candidates,
            key=lambda item: (
                abs(item.available_fleet_count - target_k),
                item.available_fleet_count,
            ),
        )
        return Path(str(nearest.checkpoint_path))

    def _round(
        self,
        store: OptimizationLiveStore,
        config: DddFleetSweepConfig,
        policy: DddFleetPolicyConfig,
        fleet_count: int,
        fingerprint: str,
        item: Mapping[str, Any],
        progress: bool,
    ) -> None:
        lower = _optional_float(item.get("global_lower_bound"))
        upper = _optional_float(item.get("global_upper_bound"))
        gap = _relative_gap(lower, upper)
        self._emit(
            store,
            OptimizationEventKind.CG_ROUND_COMPLETED,
            config,
            policy=policy,
            fleet_count=fleet_count,
            fingerprint=fingerprint,
            lower=lower,
            upper=upper,
            gap=gap,
            elapsed=_optional_float(item.get("cumulative_seconds")),
            round_index=int(item.get("round_index", 0)),
            payload=dict(item),
        )
        self._publish(store)
        if progress:
            print(
                f"{policy.id} K={fleet_count} r={item.get('round_index', '-')} "
                f"LB={lower if lower is not None else '-'} "
                f"UB={upper if upper is not None else '-'} "
                f"gap={gap if gap is not None else '-'}"
            )

    def _heartbeat(
        self,
        stop: threading.Event,
        store: OptimizationLiveStore,
        config: DddFleetSweepConfig,
        policy: DddFleetPolicyConfig,
        fleet_count: int,
        fingerprint: str,
        started_at: float,
    ) -> None:
        while not stop.wait(1.0):
            self._emit(
                store,
                OptimizationEventKind.HEARTBEAT,
                config,
                policy=policy,
                fleet_count=fleet_count,
                fingerprint=fingerprint,
                stage="root_column_generation",
                elapsed=time.monotonic() - started_at,
            )
            self._publish(store)

    @staticmethod
    def _emit(
        store: OptimizationLiveStore,
        kind: OptimizationEventKind,
        config: DddFleetSweepConfig,
        *,
        policy: DddFleetPolicyConfig | None = None,
        fleet_count: int | None = None,
        fingerprint: str | None = None,
        lower: float | None = None,
        upper: float | None = None,
        gap: float | None = None,
        elapsed: float | None = None,
        round_index: int | None = None,
        stage: str | None = None,
        payload: Mapping[str, Any] | None = None,
    ) -> None:
        store.append_new(
                kind,
                config.campaign_id,
                policy_id=None if policy is None else policy.id,
                available_fleet_count=fleet_count,
                trial_fingerprint=fingerprint,
                round_index=round_index,
                stage=stage,
                global_certified_lower_bound=lower,
                global_validated_upper_bound=upper,
                global_relative_gap=gap,
                elapsed_seconds=elapsed,
                payload={} if payload is None else payload,
        )

    @staticmethod
    def _publish(
        store: OptimizationLiveStore,
        payload: Mapping[str, Any] | None = None,
    ) -> None:
        store.publish(
            reduce_optimization_events(store.read_events())
            if payload is None
            else payload
        )


def trial_fingerprint(
    config: DddFleetSweepConfig,
    policy: DddFleetPolicyConfig,
    fleet_count: int,
) -> str:
    payload = {
        "campaign": config.to_dict(),
        "policy": asdict(policy),
        "available_fleet_count": fleet_count,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _relative_gap(lower: float | None, upper: float | None) -> float | None:
    if lower is None or upper is None:
        return None
    return max(0.0, upper - lower) / max(abs(upper), 1e-9)


def _optional_float(value: object) -> float | None:
    return None if value is None else float(value)


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)
