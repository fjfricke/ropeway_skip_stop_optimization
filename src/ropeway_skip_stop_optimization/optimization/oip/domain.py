from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from enum import StrEnum
import hashlib
import json
import math

from ropeway_skip_stop_optimization.models import (
    ConstantHeadwayRule,
    LeaderBehaviorHeadwayRule,
    Scenario,
)
from ropeway_skip_stop_optimization.optimization.ean.artifact import EanBuildArtifact
from ropeway_skip_stop_optimization.optimization.ean.models import (
    EanFleetCardinalityMode,
    EanFleetMode,
    StationWaitingMode,
)


class OipBackend(StrEnum):
    CP_SAT = "cp_sat"
    GUROBI = "gurobi"


class OipOperation(StrEnum):
    ALL_STOP = "all_stop"
    SKIP_STOP = "skip_stop"


class OipPassengerEncoding(StrEnum):
    OD_INVENTORY = "od_inventory"
    GROUPS = "groups"
    RIDE_COUNTS = "ride_counts"
    SLOTS = "slots"


def shift_scenario_for_oip_warmup(
    scenario: Scenario,
    warmup_seconds: float,
) -> Scenario:
    """Move only the OIP time origin before the original service start.

    Absolute demand and availability timestamps remain unchanged, so their
    release offsets increase by the requested warmup.  This is deliberately
    opt-in and does not mutate historical scenarios.
    """

    if not math.isfinite(warmup_seconds) or warmup_seconds < 0:
        raise ValueError("OIP warmup must be finite and nonnegative")
    if warmup_seconds == 0:
        return scenario
    anchor = datetime.combine(date(2000, 1, 2), scenario.service_start_time)
    shifted = anchor - timedelta(seconds=warmup_seconds)
    if shifted.date() != anchor.date():
        raise ValueError("OIP warmup may not cross midnight")
    result = replace(scenario, service_start_time=shifted.time())
    result.validate()
    return result


@dataclass(frozen=True)
class OipTimeGrid:
    """Isolated conservative integer-time grid for the OIP comparison.

    Minimum durations, releases, and separations are rounded upward.  Upper
    deadlines are rounded downward.  This deliberately does not alter the
    repository-wide DDD microsecond clock.
    """

    ticks_per_second: int = 1_000

    def validate(self) -> None:
        if self.ticks_per_second <= 0:
            raise ValueError("OIP time grid must have a positive tick rate")

    def lower_tick(self, seconds: float) -> int:
        self._validate_seconds(seconds)
        return math.ceil(seconds * self.ticks_per_second - 1e-9)

    def upper_tick(self, seconds: float) -> int:
        self._validate_seconds(seconds)
        return math.floor(seconds * self.ticks_per_second + 1e-9)

    def signed_lower_tick(self, seconds: float) -> int:
        if not math.isfinite(seconds):
            raise ValueError("OIP event time must be finite")
        return math.ceil(seconds * self.ticks_per_second - 1e-9)

    def signed_upper_tick(self, seconds: float) -> int:
        if not math.isfinite(seconds):
            raise ValueError("OIP event time must be finite")
        return math.floor(seconds * self.ticks_per_second + 1e-9)

    def seconds(self, ticks: int) -> float:
        return ticks / self.ticks_per_second

    def rounding_error_seconds(self, seconds: float, *, upper: bool = False) -> float:
        tick = self.upper_tick(seconds) if upper else self.lower_tick(seconds)
        return self.seconds(tick) - seconds

    @staticmethod
    def _validate_seconds(seconds: float) -> None:
        if not math.isfinite(seconds) or seconds < 0:
            raise ValueError("OIP duration must be finite and nonnegative")


@dataclass(frozen=True)
class OipDomain:
    scenario: Scenario
    artifact: EanBuildArtifact
    grid: OipTimeGrid
    operation: OipOperation
    fixed_k: int | None
    k_max: int
    fingerprint: str
    comparison_fingerprint: str
    quantization_manifest: tuple[tuple[str, float, int, float], ...]

    @property
    def exact_k(self) -> bool:
        return self.fixed_k is not None

    def validate(self) -> None:
        self.scenario.validate()
        self.artifact.validate()
        self.grid.validate()
        if self.artifact.fleet_mode is not EanFleetMode.OPTIMIZED_INITIAL_PLACEMENT:
            raise ValueError("OIP requires an optimized-initial-placement artifact")
        _validate_oip_waiting(self.artifact)
        if self.k_max <= 0:
            raise ValueError("OIP k_max must be positive")
        if self.fixed_k is not None and not 0 <= self.fixed_k <= self.k_max:
            raise ValueError("OIP fixed_k must lie between zero and k_max")
        if len(self.artifact.cabin_starts) != self.k_max:
            raise ValueError("OIP artifact available fleet does not equal k_max")


def prepare_oip_domain(
    *,
    scenario: Scenario,
    artifact: EanBuildArtifact,
    operation: OipOperation = OipOperation.SKIP_STOP,
    fixed_k: int | None = None,
    grid: OipTimeGrid = OipTimeGrid(),
) -> OipDomain:
    """Freeze one solver-independent OIP comparison domain."""

    scenario.validate()
    artifact.validate()
    grid.validate()
    parameters = artifact.initial_placement_parameters
    if artifact.fleet_mode is not EanFleetMode.OPTIMIZED_INITIAL_PLACEMENT or parameters is None:
        raise ValueError("OIP preparation needs an optimized-initial-placement artifact")
    _validate_oip_waiting(artifact)
    k_max = parameters.available_fleet_count
    expected_mode = (
        EanFleetCardinalityMode.EXACT
        if fixed_k is not None
        else EanFleetCardinalityMode.UP_TO_AVAILABLE
    )
    if artifact.fleet_cardinality_mode is not expected_mode:
        raise ValueError(
            "OIP artifact fleet cardinality does not match fixed_k/k_max request"
        )

    scenario = _quantized_scenario_releases(scenario, grid)

    values: list[tuple[str, float, int, float]] = []
    for timing in artifact.timings:
        for label, seconds in (
            (f"{timing.switch_id}.entry_to_platform", timing.entry_to_platform_entry_seconds),
            (f"{timing.switch_id}.platform", timing.min_platform_entry_to_platform_exit_seconds),
            (f"{timing.switch_id}.platform_to_exit", timing.platform_exit_to_exit_switch_seconds),
            (f"{timing.switch_id}.skip", timing.skip_entry_to_exit_switch_seconds),
            (f"{timing.switch_id}.rope", timing.rope_to_next_switch_seconds),
        ):
            tick = grid.lower_tick(seconds)
            values.append((label, seconds, tick, grid.seconds(tick) - seconds))
    for checkpoint in artifact.headway_checkpoints:
        tick = grid.lower_tick(checkpoint.headway_seconds)
        values.append(
            (
                f"headway.{checkpoint.id}",
                checkpoint.headway_seconds,
                tick,
                grid.seconds(tick) - checkpoint.headway_seconds,
            )
        )
    for station in artifact.config.station_configs:
        if station.max_wait_seconds is None:
            continue
        tick = grid.lower_tick(station.max_wait_seconds)
        values.append(
            (
                f"waiting.{station.station_id}.maximum",
                station.max_wait_seconds,
                tick,
                grid.seconds(tick) - station.max_wait_seconds,
            )
        )
    for index, pair in enumerate(artifact.headway_pairs):
        tick = grid.lower_tick(pair.headway_seconds)
        values.append(
            (
                f"headway_pair.{index}",
                pair.headway_seconds,
                tick,
                grid.seconds(tick) - pair.headway_seconds,
            )
        )
    start_datetime = datetime.combine(date(2000, 1, 2), scenario.service_start_time)
    for index, demand in enumerate(scenario.demands):
        release = (
            datetime.combine(date(2000, 1, 2), demand.arrival_time)
            - start_datetime
        ).total_seconds()
        tick = grid.lower_tick(release)
        values.append(
            (
                f"demand.{index}.release",
                release,
                tick,
                grid.seconds(tick) - release,
            )
        )
    solver_policy = artifact.effective_headway_policy or artifact.headway_policy
    if solver_policy is not None:
        for rule in solver_policy.rules:
            components = (
                (("seconds", rule.seconds),)
                if isinstance(rule, ConstantHeadwayRule)
                else (
                    ("bypass", rule.bypass_leader_seconds),
                    ("service", rule.service_leader_seconds),
                )
            )
            for component, seconds in components:
                tick = grid.lower_tick(seconds)
                values.append(
                    (
                        f"headway_rule.{rule.id}.{component}",
                        seconds,
                        tick,
                        grid.seconds(tick) - seconds,
                    )
                )
    horizon_tick = grid.upper_tick(artifact.config.horizon_seconds)
    values.append(
        (
            "passenger_service_deadline",
            artifact.config.horizon_seconds,
            horizon_tick,
            grid.seconds(horizon_tick) - artifact.config.horizon_seconds,
        )
    )

    comparison_payload = {
        "version": 1,
        "scenario": scenario.id,
        "ticks_per_second": grid.ticks_per_second,
        "fixed_k": fixed_k,
        "k_max": k_max,
        "states": artifact.state_ids,
        "horizon": artifact.config.horizon_seconds,
        "tail": artifact.config.tail_seconds,
        "capacity": artifact.config.cabin_capacity,
        "station_waiting": [
            (item.station_id, item.waiting_mode.value, item.max_wait_seconds)
            for item in artifact.config.station_configs
        ],
        "quantized": [(label, tick) for label, _, tick, _ in values],
        "demand": [
            (
                demand.arrival_time.isoformat(),
                demand.origin,
                demand.destination,
                demand.count,
            )
            for demand in scenario.demands
        ],
    }
    comparison_fingerprint = hashlib.sha256(
        json.dumps(comparison_payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    fingerprint_payload = {**comparison_payload, "operation": operation.value}
    fingerprint = hashlib.sha256(
        json.dumps(fingerprint_payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    quantized_artifact = _quantized_artifact(artifact, grid, operation)
    domain = OipDomain(
        scenario=scenario,
        artifact=quantized_artifact,
        grid=grid,
        operation=operation,
        fixed_k=fixed_k,
        k_max=k_max,
        fingerprint=fingerprint,
        comparison_fingerprint=comparison_fingerprint,
        quantization_manifest=tuple(values),
    )
    domain.validate()
    return domain


def _quantized_artifact(
    artifact: EanBuildArtifact,
    grid: OipTimeGrid,
    operation: OipOperation,
) -> EanBuildArtifact:
    """Return the isolated OIP artifact with compositional 1-ms offsets."""

    timings = tuple(
        replace(
            timing,
            entry_to_platform_entry_seconds=grid.seconds(
                grid.lower_tick(timing.entry_to_platform_entry_seconds)
            ),
            min_platform_entry_to_platform_exit_seconds=grid.seconds(
                grid.lower_tick(timing.min_platform_entry_to_platform_exit_seconds)
            ),
            platform_exit_to_exit_switch_seconds=grid.seconds(
                grid.lower_tick(timing.platform_exit_to_exit_switch_seconds)
            ),
            skip_entry_to_exit_switch_seconds=grid.seconds(
                grid.lower_tick(timing.skip_entry_to_exit_switch_seconds)
            ),
            rope_to_next_switch_seconds=grid.seconds(
                grid.lower_tick(timing.rope_to_next_switch_seconds)
            ),
            skip_allowed=(
                False if operation is OipOperation.ALL_STOP else timing.skip_allowed
            ),
        )
        for timing in artifact.timings
    )
    checkpoints = tuple(
        replace(
            checkpoint,
            headway_seconds=grid.seconds(grid.lower_tick(checkpoint.headway_seconds)),
        )
        for checkpoint in artifact.headway_checkpoints
    )
    headway_pairs = tuple(
        replace(
            pair,
            headway_seconds=grid.seconds(grid.lower_tick(pair.headway_seconds)),
        )
        for pair in artifact.headway_pairs
    )
    headway_policy = _quantized_policy(artifact.headway_policy, grid)
    effective_headway_policy = _quantized_policy(
        artifact.effective_headway_policy, grid
    )
    if effective_headway_policy is not None and headway_policy is not None:
        effective_headway_policy = replace(
            effective_headway_policy,
            dominance_certificates=tuple(
                replace(
                    certificate,
                    required_headway_seconds=max(
                        headway_policy.rule(
                            headway_policy.resource(
                                certificate.dominated_resource_id
                            ).rule_id
                        ).required_seconds(leader, follower)
                        for leader, follower in certificate.behavior_pairs
                    ),
                    minimum_implied_headway_seconds=min(
                        headway_policy.rule(
                            headway_policy.resource(
                                certificate.dominating_resource_id
                            ).rule_id
                        ).required_seconds(leader, follower)
                        for leader, follower in certificate.behavior_pairs
                    ),
                )
                for certificate in effective_headway_policy.dominance_certificates
            ),
        )
    horizon_tick = grid.upper_tick(artifact.config.horizon_seconds)
    operation_tick = grid.upper_tick(artifact.config.operational_end_seconds)
    config = replace(
        artifact.config,
        horizon_seconds=grid.seconds(horizon_tick),
        tail_seconds=grid.seconds(max(0, operation_tick - horizon_tick)),
        station_configs=tuple(
            replace(
                item,
                max_wait_seconds=(
                    None
                    if item.max_wait_seconds is None
                    else grid.seconds(grid.lower_tick(item.max_wait_seconds))
                ),
            )
            for item in artifact.config.station_configs
        ),
    )
    result = replace(
        artifact,
        timings=timings,
        headway_checkpoints=checkpoints,
        headway_pairs=headway_pairs,
        headway_policy=headway_policy,
        effective_headway_policy=effective_headway_policy,
        config=config,
    )
    result.validate()
    return result


def _validate_oip_waiting(artifact: EanBuildArtifact) -> None:
    supported = {
        StationWaitingMode.NO_WAITING,
        StationWaitingMode.END_OF_PLATFORM_WAIT,
    }
    for config in artifact.config.station_configs:
        if config.waiting_mode not in supported:
            raise ValueError(
                f"unsupported OIP waiting mode: {config.waiting_mode.value}"
            )
        if (
            config.waiting_mode is StationWaitingMode.END_OF_PLATFORM_WAIT
            and (config.max_wait_seconds is None or config.max_wait_seconds <= 0)
        ):
            raise ValueError("OIP end-of-platform waiting needs a positive finite cap")


def _quantized_policy(policy, grid: OipTimeGrid):
    if policy is None:
        return None
    rules = []
    for rule in policy.rules:
        if isinstance(rule, ConstantHeadwayRule):
            rules.append(
                replace(rule, seconds=grid.seconds(grid.lower_tick(rule.seconds)))
            )
        elif isinstance(rule, LeaderBehaviorHeadwayRule):
            rules.append(
                replace(
                    rule,
                    bypass_leader_seconds=grid.seconds(
                        grid.lower_tick(rule.bypass_leader_seconds)
                    ),
                    service_leader_seconds=grid.seconds(
                        grid.lower_tick(rule.service_leader_seconds)
                    ),
                )
            )
        else:
            raise TypeError(f"unsupported OIP headway rule: {rule!r}")
    return replace(policy, rules=tuple(rules))


def _quantized_scenario_releases(scenario: Scenario, grid: OipTimeGrid) -> Scenario:
    anchor = datetime.combine(date(2000, 1, 2), scenario.service_start_time)
    demands = []
    for demand in scenario.demands:
        arrival = datetime.combine(date(2000, 1, 2), demand.arrival_time)
        release = (arrival - anchor).total_seconds()
        quantized = anchor + timedelta(seconds=grid.seconds(grid.lower_tick(release)))
        demands.append(replace(demand, arrival_time=quantized.time()))
    result = replace(scenario, demands=tuple(demands))
    result.validate()
    return result
