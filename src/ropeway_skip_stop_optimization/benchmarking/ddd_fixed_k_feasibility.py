from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from dataclasses import asdict, dataclass, replace
from enum import StrEnum
from hashlib import sha256
import json
import math
import multiprocessing
from multiprocessing.connection import Connection
from pathlib import Path
import resource
import sys
from time import perf_counter
import traceback

from ropeway_skip_stop_optimization.benchmarking.ddd_fixed_k_arc_flow import (
    DddFixedKArcFlowRunConfig,
    build_ddd_fixed_k_arc_flow_problem,
)
from ropeway_skip_stop_optimization.benchmarking.ddd_scaling import (
    build_initial_ddd_network_problem,
)
from ropeway_skip_stop_optimization.benchmarking.optimization_events import (
    OptimizationEventKind,
)
from ropeway_skip_stop_optimization.benchmarking.optimization_live_store import (
    OptimizationLiveStore,
    reduce_optimization_events,
)
from ropeway_skip_stop_optimization.optimization.ddd import (
    DddFixedKOperatingMode,
    DddFixedKSeedCoordinator,
    DddFixedKSeedStatus,
)


class DddFixedKFeasibilityTermination(StrEnum):
    FEASIBLE = "feasible"
    PROVED_INFEASIBLE = "proved_infeasible"
    TIME_LIMIT_UNKNOWN = "time_limit_unknown"
    PREMATURE_UNKNOWN = "premature_unknown"
    WORKER_TIMEOUT = "worker_timeout"
    WORKER_ERROR = "worker_error"
    INTERNAL_VALIDATION_ERROR = "internal_validation_error"


@dataclass(frozen=True, slots=True)
class DddFixedKFeasibilitySweepConfig:
    example_id: str
    minimum_k: int
    maximum_k: int
    operating_mode: DddFixedKOperatingMode = DddFixedKOperatingMode.SKIP_STOP
    time_limit_seconds_per_k: float = 600.0
    cp_sat_workers: int = 8
    stop_on_unknown: bool = True
    stop_on_infeasible: bool = True
    premature_unknown_ratio: float = 0.9
    premature_unknown_retries: int = 1
    worker_grace_seconds: float = 120.0
    isolate_attempts: bool = True

    def validate(self) -> None:
        if not self.example_id:
            raise ValueError("fixed-K feasibility sweep needs an example")
        if self.minimum_k <= 0 or self.maximum_k < self.minimum_k:
            raise ValueError("fixed-K feasibility sweep K range is invalid")
        if (
            not math.isfinite(self.time_limit_seconds_per_k)
            or self.time_limit_seconds_per_k <= 0
        ):
            raise ValueError("fixed-K feasibility time limit must be positive")
        if self.cp_sat_workers <= 0:
            raise ValueError("fixed-K feasibility workers must be positive")
        if not isinstance(self.operating_mode, DddFixedKOperatingMode):
            raise ValueError("fixed-K feasibility operating mode is invalid")
        if not 0 < self.premature_unknown_ratio <= 1:
            raise ValueError("premature UNKNOWN ratio must lie in (0, 1]")
        if self.premature_unknown_retries < 0:
            raise ValueError("premature UNKNOWN retries must be nonnegative")
        if (
            not math.isfinite(self.worker_grace_seconds)
            or self.worker_grace_seconds <= 0
        ):
            raise ValueError("fixed-K feasibility worker grace must be positive")

    @property
    def fingerprint(self) -> str:
        return _fingerprint(self._fingerprint_payload())

    @property
    def legacy_fingerprint(self) -> str:
        return _fingerprint(
            {
                "example_id": self.example_id,
                "minimum_k": self.minimum_k,
                "maximum_k": self.maximum_k,
                "operating_mode": self.operating_mode.value,
                "time_limit_seconds_per_k": self.time_limit_seconds_per_k,
                "cp_sat_workers": self.cp_sat_workers,
                "stop_on_unknown": self.stop_on_unknown,
                "stop_on_infeasible": self.stop_on_infeasible,
            }
        )

    def _fingerprint_payload(self) -> dict[str, object]:
        return {
            "example_id": self.example_id,
            "minimum_k": self.minimum_k,
            "maximum_k": self.maximum_k,
            "operating_mode": self.operating_mode.value,
            "time_limit_seconds_per_k": self.time_limit_seconds_per_k,
            "cp_sat_workers": self.cp_sat_workers,
            "stop_on_unknown": self.stop_on_unknown,
            "stop_on_infeasible": self.stop_on_infeasible,
            "premature_unknown_ratio": self.premature_unknown_ratio,
            "premature_unknown_retries": self.premature_unknown_retries,
            "worker_grace_seconds": self.worker_grace_seconds,
            "isolate_attempts": self.isolate_attempts,
        }


@dataclass(frozen=True, slots=True)
class DddFixedKFeasibilityProbeResult:
    cabin_count: int
    attempt_index: int
    status: DddFixedKSeedStatus
    termination: DddFixedKFeasibilityTermination
    seed_kind: str | None
    cp_sat_seconds: float
    total_seconds: float
    trajectory_count: int
    problem_fingerprint: str
    cp_sat_solver_status_name: str | None = None
    cp_sat_conflict_count: int = 0
    cp_sat_branch_count: int = 0
    cp_sat_search_complete: bool = False
    cp_sat_response_stats: str | None = None
    worker_exit_code: int | None = None
    peak_rss_bytes: int | None = None
    detail: str | None = None

    def to_dict(self) -> dict[str, object]:
        result = asdict(self)
        result["status"] = self.status.value
        result["termination"] = self.termination.value
        return result

    @classmethod
    def from_dict(
        cls,
        value: dict[str, object],
        *,
        config: DddFixedKFeasibilitySweepConfig,
        inferred_attempt_index: int,
    ) -> DddFixedKFeasibilityProbeResult:
        status = DddFixedKSeedStatus(str(value["status"]))
        cp_sat_seconds = float(value["cp_sat_seconds"])
        termination = (
            DddFixedKFeasibilityTermination(str(value["termination"]))
            if value.get("termination") is not None
            else _legacy_termination(config, status, cp_sat_seconds)
        )
        return cls(
            cabin_count=int(value["cabin_count"]),
            attempt_index=int(value.get("attempt_index", inferred_attempt_index)),
            status=status,
            termination=termination,
            seed_kind=(
                None if value.get("seed_kind") is None else str(value["seed_kind"])
            ),
            cp_sat_seconds=cp_sat_seconds,
            total_seconds=float(value["total_seconds"]),
            trajectory_count=int(value["trajectory_count"]),
            problem_fingerprint=str(value["problem_fingerprint"]),
            cp_sat_solver_status_name=_optional_str(
                value.get("cp_sat_solver_status_name")
            ),
            cp_sat_conflict_count=int(value.get("cp_sat_conflict_count", 0)),
            cp_sat_branch_count=int(value.get("cp_sat_branch_count", 0)),
            cp_sat_search_complete=bool(value.get("cp_sat_search_complete", False)),
            cp_sat_response_stats=_optional_str(value.get("cp_sat_response_stats")),
            worker_exit_code=_optional_int(value.get("worker_exit_code")),
            peak_rss_bytes=_optional_int(value.get("peak_rss_bytes")),
            detail=_optional_str(value.get("detail")),
        )


DddFixedKFeasibilityProgressHook = Callable[[DddFixedKFeasibilityProbeResult], None]
DddFixedKFeasibilityProbe = Callable[
    [DddFixedKFeasibilitySweepConfig, int, int], DddFixedKFeasibilityProbeResult
]


@dataclass(frozen=True, slots=True)
class DddFixedKFeasibilitySweepResult:
    config_fingerprint: str
    probes: tuple[DddFixedKFeasibilityProbeResult, ...]

    @property
    def largest_feasible_k(self) -> int | None:
        feasible = tuple(
            probe.cabin_count
            for probe in self.probes
            if probe.status is DddFixedKSeedStatus.FEASIBLE
        )
        return None if not feasible else max(feasible)

    @property
    def frontier_probe(self) -> DddFixedKFeasibilityProbeResult | None:
        return None if not self.probes else self.probes[-1]

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": 2,
            "config_fingerprint": self.config_fingerprint,
            "largest_certified_feasible_k": self.largest_feasible_k,
            "largest_feasible_k": self.largest_feasible_k,
            "frontier_status": (
                None
                if self.frontier_probe is None
                else self.frontier_probe.status.value
            ),
            "frontier_termination": (
                None
                if self.frontier_probe is None
                else self.frontier_probe.termination.value
            ),
            "probes": [probe.to_dict() for probe in self.probes],
        }


@dataclass(slots=True)
class DddFixedKFeasibilityLivePublisher:
    store: OptimizationLiveStore
    campaign_id: str
    config: DddFixedKFeasibilitySweepConfig
    label: str

    def begin(self) -> None:
        events = self.store.read_events()
        if events:
            snapshot = reduce_optimization_events(events)
            if snapshot["status"] == "running":
                self._publish()
                return
        self.store.append_new(
            OptimizationEventKind.CAMPAIGN_STARTED,
            self.campaign_id,
            payload={
                "label": self.label,
                "objective": "movement_feasibility",
                "example_id": self.config.example_id,
                "method": "fixed_k_cp_sat_feasibility",
                "campaign_kind": "movement_feasibility",
                "operating_mode": self.config.operating_mode.value,
                "minimum_k": self.config.minimum_k,
                "maximum_k": self.config.maximum_k,
                "trial_count": self.config.maximum_k - self.config.minimum_k + 1,
                "time_limit_seconds_per_k": self.config.time_limit_seconds_per_k,
            },
        )
        self._publish()

    def import_probes(
        self,
        probes: tuple[DddFixedKFeasibilityProbeResult, ...],
    ) -> None:
        self.begin()
        for index, probe in enumerate(probes):
            final_for_k = (
                index + 1 == len(probes)
                or probes[index + 1].cabin_count != probe.cabin_count
            )
            self.record_attempt(probe, final_for_k=final_for_k)

    def record_attempt(
        self,
        probe: DddFixedKFeasibilityProbeResult,
        *,
        final_for_k: bool,
    ) -> None:
        attempt_key = (probe.cabin_count, probe.attempt_index)
        if attempt_key in self._published_attempt_keys():
            return
        policy_id = self.config.operating_mode.value
        snapshot = reduce_optimization_events(self.store.read_events())
        trial = snapshot["trials"].get(f"{policy_id}__k{probe.cabin_count}")
        if trial is None or trial["status"] != "running":
            self.store.append_new(
                OptimizationEventKind.TRIAL_STARTED,
                self.campaign_id,
                policy_id=policy_id,
                available_fleet_count=probe.cabin_count,
                trial_fingerprint=probe.problem_fingerprint or None,
                stage="cp_sat_feasibility",
                payload={
                    "method": "fixed_k_cp_sat_feasibility",
                    "exact_active_cabin_count": probe.cabin_count,
                },
            )
        self.store.append_new(
            OptimizationEventKind.SOLVER_SAMPLE,
            self.campaign_id,
            policy_id=policy_id,
            available_fleet_count=probe.cabin_count,
            trial_fingerprint=probe.problem_fingerprint or None,
            stage="cp_sat_attempt_completed",
            round_index=probe.attempt_index,
            elapsed_seconds=probe.total_seconds,
            payload={
                "method": "fixed_k_cp_sat_feasibility",
                "feasibility_attempt": probe.to_dict(),
            },
        )
        if final_for_k:
            self.store.append_new(
                OptimizationEventKind.TRIAL_COMPLETED,
                self.campaign_id,
                policy_id=policy_id,
                available_fleet_count=probe.cabin_count,
                trial_fingerprint=probe.problem_fingerprint or None,
                stage="movement_feasibility_complete",
                elapsed_seconds=probe.total_seconds,
                payload={
                    "method": "fixed_k_cp_sat_feasibility",
                    "certificate_kind": "movement_feasibility",
                    "status": probe.status.value,
                    "termination": probe.termination.value,
                    "attempt_count": probe.attempt_index,
                    "cp_sat_seconds": probe.cp_sat_seconds,
                    "cp_sat_solver_status_name": (probe.cp_sat_solver_status_name),
                    "cp_sat_conflict_count": probe.cp_sat_conflict_count,
                    "cp_sat_branch_count": probe.cp_sat_branch_count,
                    "cp_sat_search_complete": probe.cp_sat_search_complete,
                    "peak_rss_bytes": probe.peak_rss_bytes,
                    "trajectory_count": probe.trajectory_count,
                    "worker_exit_code": probe.worker_exit_code,
                    "detail": probe.detail,
                },
            )
        self._publish()

    def complete(self, result: DddFixedKFeasibilitySweepResult) -> None:
        frontier = result.frontier_probe
        self.store.append_new(
            OptimizationEventKind.CAMPAIGN_COMPLETED,
            self.campaign_id,
            payload={
                "status": "complete",
                "largest_certified_feasible_k": result.largest_feasible_k,
                "frontier_k": None if frontier is None else frontier.cabin_count,
                "frontier_status": None if frontier is None else frontier.status.value,
                "frontier_termination": (
                    None if frontier is None else frontier.termination.value
                ),
            },
        )
        self._publish()

    def publish_checkpoint(self, result: DddFixedKFeasibilitySweepResult) -> None:
        """Idempotently expose a checkpoint without starting a solver run."""
        expected = {
            (probe.cabin_count, probe.attempt_index) for probe in result.probes
        }
        events = self.store.read_events()
        if events:
            snapshot = reduce_optimization_events(events)
            if (
                expected.issubset(self._published_attempt_keys())
                and snapshot["status"] == "complete"
            ):
                self._publish()
                return
        self.import_probes(result.probes)
        snapshot = reduce_optimization_events(self.store.read_events())
        if snapshot["status"] != "complete":
            self.complete(result)
        else:
            self._publish()

    def _published_attempt_keys(self) -> set[tuple[int, int]]:
        result = set()
        for event in self.store.read_events():
            attempt = event.payload.get("feasibility_attempt")
            if not isinstance(attempt, dict):
                continue
            result.add((int(attempt["cabin_count"]), int(attempt["attempt_index"])))
        return result

    def _publish(self) -> None:
        self.store.publish(reduce_optimization_events(self.store.read_events()))


def run_ddd_fixed_k_feasibility_sweep(
    config: DddFixedKFeasibilitySweepConfig,
    *,
    existing_probes: tuple[DddFixedKFeasibilityProbeResult, ...] = (),
    progress_hook: DddFixedKFeasibilityProgressHook | None = None,
    probe: DddFixedKFeasibilityProbe | None = None,
) -> DddFixedKFeasibilitySweepResult:
    config.validate()
    _validate_existing_probes(config, existing_probes)
    probes = list(existing_probes)
    solve_probe = probe or (
        _solve_fixed_k_probe_isolated
        if config.isolate_attempts
        else _solve_fixed_k_probe
    )
    cabin_count = _next_cabin_count(config, probes)
    while cabin_count <= config.maximum_k:
        attempt_index = 1 + sum(item.cabin_count == cabin_count for item in probes)
        result = solve_probe(config, cabin_count, attempt_index)
        probes.append(result)
        if progress_hook is not None:
            progress_hook(result)
        if _should_retry(config, result):
            continue
        if _must_stop(config, result):
            break
        cabin_count += 1
    return DddFixedKFeasibilitySweepResult(
        config_fingerprint=config.fingerprint,
        probes=tuple(probes),
    )


def read_ddd_fixed_k_feasibility_sweep(
    path: Path,
    *,
    config: DddFixedKFeasibilitySweepConfig,
) -> tuple[DddFixedKFeasibilityProbeResult, ...]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("config_fingerprint") not in {
        config.fingerprint,
        config.legacy_fingerprint,
    }:
        raise ValueError("fixed-K feasibility checkpoint configuration differs")
    attempts_by_k: Counter[int] = Counter()
    probes = []
    for value in payload.get("probes", ()):
        cabin_count = int(value["cabin_count"])
        attempts_by_k[cabin_count] += 1
        probes.append(
            DddFixedKFeasibilityProbeResult.from_dict(
                value,
                config=config,
                inferred_attempt_index=attempts_by_k[cabin_count],
            )
        )
    result = tuple(probes)
    _validate_existing_probes(config, result)
    return result


def write_ddd_fixed_k_feasibility_sweep(
    result: DddFixedKFeasibilitySweepResult,
    path: Path,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(
        json.dumps(result.to_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _solve_fixed_k_probe_isolated(
    config: DddFixedKFeasibilitySweepConfig,
    cabin_count: int,
    attempt_index: int,
) -> DddFixedKFeasibilityProbeResult:
    context = multiprocessing.get_context("spawn")
    receiving, sending = context.Pipe(duplex=False)
    process = context.Process(
        target=_isolated_probe_worker,
        args=(config, cabin_count, attempt_index, sending),
        name=f"ddd-fixed-k-{cabin_count}-attempt-{attempt_index}",
    )
    started = perf_counter()
    process.start()
    sending.close()
    process.join(config.time_limit_seconds_per_k + config.worker_grace_seconds)
    if process.is_alive():
        process.terminate()
        process.join(10.0)
        if process.is_alive():
            process.kill()
            process.join()
        receiving.close()
        return _worker_failure_result(
            cabin_count,
            attempt_index,
            DddFixedKFeasibilityTermination.WORKER_TIMEOUT,
            perf_counter() - started,
            process.exitcode,
            "isolated worker exceeded CP-SAT budget plus setup grace",
        )
    if not receiving.poll():
        receiving.close()
        return _worker_failure_result(
            cabin_count,
            attempt_index,
            DddFixedKFeasibilityTermination.WORKER_ERROR,
            perf_counter() - started,
            process.exitcode,
            "isolated worker exited without a result",
        )
    payload = receiving.recv()
    receiving.close()
    result = DddFixedKFeasibilityProbeResult.from_dict(
        payload,
        config=config,
        inferred_attempt_index=attempt_index,
    )
    return replace(result, worker_exit_code=process.exitcode)


def _isolated_probe_worker(
    config: DddFixedKFeasibilitySweepConfig,
    cabin_count: int,
    attempt_index: int,
    connection: Connection,
) -> None:
    try:
        result = _solve_fixed_k_probe(config, cabin_count, attempt_index)
        result = replace(result, peak_rss_bytes=_peak_rss_bytes())
    except BaseException as error:
        result = _worker_failure_result(
            cabin_count,
            attempt_index,
            DddFixedKFeasibilityTermination.WORKER_ERROR,
            0.0,
            None,
            f"{type(error).__name__}: {error}\n{traceback.format_exc()}",
        )
    try:
        connection.send(result.to_dict())
    finally:
        connection.close()


def _solve_fixed_k_probe(
    config: DddFixedKFeasibilitySweepConfig,
    cabin_count: int,
    attempt_index: int,
) -> DddFixedKFeasibilityProbeResult:
    started = perf_counter()
    _, problem = build_ddd_fixed_k_arc_flow_problem(
        DddFixedKArcFlowRunConfig(
            example_id=config.example_id,
            cabin_count=cabin_count,
            operating_mode=config.operating_mode,
            total_time_limit_seconds=config.time_limit_seconds_per_k,
            cp_seed_time_limit_seconds=config.time_limit_seconds_per_k,
            cp_seed_workers=config.cp_sat_workers,
        )
    )
    movement = problem.resolved_trajectory_problem.structural_movement_problem
    cp_problem = build_initial_ddd_network_problem(movement)
    seed = DddFixedKSeedCoordinator(
        cp_sat_time_limit_seconds=config.time_limit_seconds_per_k,
        cp_sat_num_workers=config.cp_sat_workers,
    ).solve(cp_problem)
    return DddFixedKFeasibilityProbeResult(
        cabin_count=cabin_count,
        attempt_index=attempt_index,
        status=seed.status,
        termination=_termination(config, seed.status, seed.cp_sat_seconds),
        seed_kind=None if seed.kind is None else seed.kind.value,
        cp_sat_seconds=seed.cp_sat_seconds,
        total_seconds=perf_counter() - started,
        trajectory_count=len(seed.trajectories),
        problem_fingerprint=problem.fingerprint,
        cp_sat_solver_status_name=seed.cp_sat_solver_status_name,
        cp_sat_conflict_count=seed.cp_sat_conflict_count,
        cp_sat_branch_count=seed.cp_sat_branch_count,
        cp_sat_search_complete=seed.cp_sat_search_complete,
        cp_sat_response_stats=seed.cp_sat_response_stats,
        detail=seed.detail,
    )


def _validate_existing_probes(
    config: DddFixedKFeasibilitySweepConfig,
    probes: tuple[DddFixedKFeasibilityProbeResult, ...],
) -> None:
    if not probes:
        return
    if probes[0].cabin_count != config.minimum_k:
        raise ValueError("fixed-K feasibility checkpoint starts at another K")
    attempts_by_k: Counter[int] = Counter()
    previous_k = config.minimum_k
    for index, probe in enumerate(probes):
        if probe.cabin_count not in {previous_k, previous_k + 1}:
            raise ValueError(
                "fixed-K feasibility checkpoint has a noncontiguous K range"
            )
        if index and probe.cabin_count == previous_k + 1:
            previous = probes[index - 1]
            if previous.status is not DddFixedKSeedStatus.FEASIBLE and _must_stop(
                config, previous
            ):
                raise ValueError("fixed-K feasibility checkpoint continues after stop")
            previous_k = probe.cabin_count
        attempts_by_k[probe.cabin_count] += 1
        if probe.attempt_index != attempts_by_k[probe.cabin_count]:
            raise ValueError("fixed-K feasibility checkpoint attempt indices differ")


def _next_cabin_count(
    config: DddFixedKFeasibilitySweepConfig,
    probes: list[DddFixedKFeasibilityProbeResult],
) -> int:
    if not probes:
        return config.minimum_k
    frontier = probes[-1]
    if frontier.status is DddFixedKSeedStatus.FEASIBLE:
        return frontier.cabin_count + 1
    if _should_retry(config, frontier):
        return frontier.cabin_count
    if _must_stop(config, frontier):
        return config.maximum_k + 1
    return frontier.cabin_count + 1


def _should_retry(
    config: DddFixedKFeasibilitySweepConfig,
    probe: DddFixedKFeasibilityProbeResult,
) -> bool:
    return _is_retryable(probe) and (
        probe.attempt_index <= config.premature_unknown_retries
    )


def _is_retryable(probe: DddFixedKFeasibilityProbeResult) -> bool:
    return probe.termination in {
        DddFixedKFeasibilityTermination.PREMATURE_UNKNOWN,
        DddFixedKFeasibilityTermination.WORKER_ERROR,
        DddFixedKFeasibilityTermination.WORKER_TIMEOUT,
    }


def _must_stop(
    config: DddFixedKFeasibilitySweepConfig,
    probe: DddFixedKFeasibilityProbeResult,
) -> bool:
    if probe.status is DddFixedKSeedStatus.INTERNAL_VALIDATION_ERROR:
        return True
    if probe.status is DddFixedKSeedStatus.MOVEMENT_INFEASIBLE:
        return config.stop_on_infeasible
    if probe.status is DddFixedKSeedStatus.UNKNOWN_NO_FEASIBLE_SEED:
        return config.stop_on_unknown
    return False


def _termination(
    config: DddFixedKFeasibilitySweepConfig,
    status: DddFixedKSeedStatus,
    cp_sat_seconds: float,
) -> DddFixedKFeasibilityTermination:
    if status is DddFixedKSeedStatus.FEASIBLE:
        return DddFixedKFeasibilityTermination.FEASIBLE
    if status is DddFixedKSeedStatus.MOVEMENT_INFEASIBLE:
        return DddFixedKFeasibilityTermination.PROVED_INFEASIBLE
    if status is DddFixedKSeedStatus.INTERNAL_VALIDATION_ERROR:
        return DddFixedKFeasibilityTermination.INTERNAL_VALIDATION_ERROR
    if cp_sat_seconds < (
        config.premature_unknown_ratio * config.time_limit_seconds_per_k
    ):
        return DddFixedKFeasibilityTermination.PREMATURE_UNKNOWN
    return DddFixedKFeasibilityTermination.TIME_LIMIT_UNKNOWN


def _legacy_termination(
    config: DddFixedKFeasibilitySweepConfig,
    status: DddFixedKSeedStatus,
    cp_sat_seconds: float,
) -> DddFixedKFeasibilityTermination:
    return _termination(config, status, cp_sat_seconds)


def _worker_failure_result(
    cabin_count: int,
    attempt_index: int,
    termination: DddFixedKFeasibilityTermination,
    total_seconds: float,
    exit_code: int | None,
    detail: str,
) -> DddFixedKFeasibilityProbeResult:
    return DddFixedKFeasibilityProbeResult(
        cabin_count=cabin_count,
        attempt_index=attempt_index,
        status=DddFixedKSeedStatus.UNKNOWN_NO_FEASIBLE_SEED,
        termination=termination,
        seed_kind=None,
        cp_sat_seconds=0.0,
        total_seconds=total_seconds,
        trajectory_count=0,
        problem_fingerprint="",
        worker_exit_code=exit_code,
        detail=detail,
    )


def _peak_rss_bytes() -> int:
    value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return value if sys.platform == "darwin" else value * 1024


def _fingerprint(payload: dict[str, object]) -> str:
    return sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _optional_str(value: object) -> str | None:
    return None if value is None else str(value)


def _optional_int(value: object) -> int | None:
    return None if value is None else int(value)
