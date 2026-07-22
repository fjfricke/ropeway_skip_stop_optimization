"""Cabin-independent periodic route certificates for directed EAN rings.

The capacity finder needs a constructive lower bound before it creates a
cabins-times-visits MILP.  A homogeneous route around the ring provides that
certificate: equally spaced cabins repeat the same route indefinitely.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from ropeway_skip_stop_optimization.optimization.ean.artifact import EanBuildArtifact
from ropeway_skip_stop_optimization.optimization.ean.models import (
    HeadwayCheckpointDefinition,
    SkipStopTiming,
)
from ropeway_skip_stop_optimization.optimization.ean.plan import EanRouteDecision


_EPSILON_SECONDS = 1e-9


class EanNoPeriodicRouteCertificateError(ValueError):
    """No indefinitely repeatable homogeneous route exists for this artifact."""


@dataclass(frozen=True)
class EanPeriodicRouteLeg:
    """One station choice and its following common rope section."""

    switch_id: str
    decision: EanRouteDecision
    entry_to_exit_seconds: float
    rope_to_next_switch_seconds: float
    checkpoint_ids: tuple[str, ...]

    @property
    def duration_seconds(self) -> float:
        return self.entry_to_exit_seconds + self.rope_to_next_switch_seconds

    def validate(self) -> None:
        if not self.switch_id:
            raise ValueError("periodic route leg needs a switch id")
        if self.entry_to_exit_seconds <= 0 or self.rope_to_next_switch_seconds <= 0:
            raise ValueError("periodic route leg durations must be positive")
        if not self.checkpoint_ids:
            raise ValueError("periodic route leg needs an active checkpoint")


@dataclass(frozen=True)
class EanPeriodicRouteCapacityBound:
    """A constructive lower-bound certificate for one repeated ring route."""

    legs: tuple[EanPeriodicRouteLeg, ...]
    cycle_seconds: float
    bottleneck_headway_seconds: float
    throughput_cabins_per_second: float
    fleet_lower_bound: int

    @property
    def decisions_by_switch_id(self) -> dict[str, EanRouteDecision]:
        return {leg.switch_id: leg.decision for leg in self.legs}

    def validate(self) -> None:
        if not self.legs:
            raise ValueError("periodic route needs at least one leg")
        if len({leg.switch_id for leg in self.legs}) != len(self.legs):
            raise ValueError("periodic route switch ids must be unique")
        for leg in self.legs:
            leg.validate()
        if self.cycle_seconds <= 0 or self.bottleneck_headway_seconds <= 0:
            raise ValueError("periodic route times must be positive")
        if not math.isclose(
            self.cycle_seconds,
            sum(leg.duration_seconds for leg in self.legs),
            rel_tol=0.0,
            abs_tol=_EPSILON_SECONDS,
        ):
            raise ValueError("periodic route cycle disagrees with its legs")
        if self.throughput_cabins_per_second <= 0 or self.fleet_lower_bound <= 0:
            raise ValueError("periodic route capacity must be positive")
        if not math.isclose(
            self.throughput_cabins_per_second,
            1.0 / self.bottleneck_headway_seconds,
            rel_tol=0.0,
            abs_tol=_EPSILON_SECONDS,
        ):
            raise ValueError("periodic route throughput disagrees with its bottleneck")
        expected = math.floor(
            (self.cycle_seconds + _EPSILON_SECONDS)
            / self.bottleneck_headway_seconds
        )
        if expected < 1:
            raise ValueError(
                "periodic route cannot repeat even one cabin at its bottleneck headway"
            )
        if self.fleet_lower_bound != expected:
            raise ValueError("periodic route fleet bound disagrees with its timings")

    def validate_for_artifact(self, artifact: EanBuildArtifact) -> None:
        """Validate both the arithmetic and the physical origin of a certificate."""

        self.validate()
        artifact.validate()
        if tuple(leg.switch_id for leg in self.legs) != artifact.switch_cycle:
            raise ValueError("periodic route legs do not follow the artifact ring")
        timing_by_switch_id = {
            timing.switch_id: timing for timing in artifact.timings
        }
        checkpoints_by_switch_id = {
            switch_id: tuple(
                checkpoint
                for checkpoint in artifact.headway_checkpoints
                if checkpoint.switch_id == switch_id
            )
            for switch_id in artifact.switch_cycle
        }
        try:
            expected_legs = tuple(
                _leg_for_decision(
                    timing=timing_by_switch_id[leg.switch_id],
                    checkpoints=checkpoints_by_switch_id[leg.switch_id],
                    decision=leg.decision,
                )
                for leg in self.legs
            )
        except (KeyError, ValueError) as error:
            raise ValueError(
                "periodic route certificate does not match its artifact"
            ) from error
        if self.legs != expected_legs:
            raise ValueError("periodic route certificate does not match its artifact")
        expected = _bound_for_legs(expected_legs, artifact.headway_checkpoints)
        if expected is None or self != expected:
            raise ValueError("periodic route capacity does not match its artifact")


@dataclass(frozen=True)
class EanPeriodicRouteCapacityBoundBuilder:
    """Find the strongest homogeneous no-wait ring circulation.

    The present physical EAN is a ring whose local service and skip branches
    reconverge before the next rope.  For a fixed maximum headway, each station
    can therefore choose its longest admissible local option independently.
    Iterating the finitely many checkpoint headways yields an O(|H|*|P|)
    algorithm rather than enumerating all stop/skip patterns.
    """

    def build(self, artifact: EanBuildArtifact) -> EanPeriodicRouteCapacityBound:
        artifact.validate()
        timings = {timing.switch_id: timing for timing in artifact.timings}
        checkpoints_by_switch: dict[str, tuple[HeadwayCheckpointDefinition, ...]] = {
            switch_id: tuple(
                checkpoint
                for checkpoint in artifact.headway_checkpoints
                if checkpoint.switch_id == switch_id
            )
            for switch_id in artifact.switch_cycle
        }
        thresholds = tuple(
            sorted({checkpoint.headway_seconds for checkpoint in artifact.headway_checkpoints})
        )
        best: EanPeriodicRouteCapacityBound | None = None
        for threshold in thresholds:
            legs: list[EanPeriodicRouteLeg] = []
            for switch_id in artifact.switch_cycle:
                leg = _longest_admissible_leg(
                    timing=timings[switch_id],
                    checkpoints=checkpoints_by_switch[switch_id],
                    threshold_seconds=threshold,
                )
                if leg is None:
                    break
                legs.append(leg)
            else:
                candidate = _bound_for_legs(tuple(legs), artifact.headway_checkpoints)
                if candidate is None:
                    continue
                if best is None or _preference_key(candidate) > _preference_key(best):
                    best = candidate
        if best is None:
            raise EanNoPeriodicRouteCertificateError(
                "no homogeneous periodic route is admissible"
            )
        best.validate()
        return best

    def build_optional(
        self, artifact: EanBuildArtifact
    ) -> EanPeriodicRouteCapacityBound | None:
        """Return no certificate when the infinite-periodicity proof fails."""

        try:
            return self.build(artifact)
        except EanNoPeriodicRouteCertificateError:
            return None


def _longest_admissible_leg(
    *,
    timing: SkipStopTiming,
    checkpoints: tuple[HeadwayCheckpointDefinition, ...],
    threshold_seconds: float,
) -> EanPeriodicRouteLeg | None:
    options: list[EanPeriodicRouteLeg] = []
    for decision in (EanRouteDecision.STOP, EanRouteDecision.SKIP):
        if decision is EanRouteDecision.SKIP and not timing.skip_allowed:
            continue
        leg = _leg_for_decision(
            timing=timing,
            checkpoints=checkpoints,
            decision=decision,
        )
        active = tuple(
            checkpoint
            for checkpoint in checkpoints
            if checkpoint.id in leg.checkpoint_ids
        )
        if not active or any(
            checkpoint.headway_seconds > threshold_seconds + _EPSILON_SECONDS
            for checkpoint in active
        ):
            continue
        options.append(leg)
    if not options:
        return None
    # STOP is deliberately the deterministic tie break.
    return max(
        options,
        key=lambda leg: (
            leg.duration_seconds,
            1 if leg.decision is EanRouteDecision.STOP else 0,
        ),
    )


def _bound_for_legs(
    legs: tuple[EanPeriodicRouteLeg, ...],
    checkpoints: tuple[HeadwayCheckpointDefinition, ...],
) -> EanPeriodicRouteCapacityBound | None:
    checkpoint_by_id = {checkpoint.id: checkpoint for checkpoint in checkpoints}
    cycle_seconds = sum(leg.duration_seconds for leg in legs)
    bottleneck = max(
        checkpoint_by_id[checkpoint_id].headway_seconds
        for leg in legs
        for checkpoint_id in leg.checkpoint_ids
    )
    fleet = math.floor((cycle_seconds + _EPSILON_SECONDS) / bottleneck)
    if fleet < 1:
        return None
    return EanPeriodicRouteCapacityBound(
        legs=legs,
        cycle_seconds=cycle_seconds,
        bottleneck_headway_seconds=bottleneck,
        throughput_cabins_per_second=1.0 / bottleneck,
        fleet_lower_bound=fleet,
    )


def _leg_for_decision(
    *,
    timing: SkipStopTiming,
    checkpoints: tuple[HeadwayCheckpointDefinition, ...],
    decision: EanRouteDecision,
) -> EanPeriodicRouteLeg:
    if decision is EanRouteDecision.SKIP and not timing.skip_allowed:
        raise ValueError("periodic route selects an unavailable skip branch")
    active = tuple(
        checkpoint
        for checkpoint in checkpoints
        if (
            checkpoint.applies_to_serve
            if decision is EanRouteDecision.STOP
            else checkpoint.applies_to_skip
        )
    )
    if not active:
        raise ValueError("periodic route leg has no active checkpoint")
    entry_to_exit = (
        timing.entry_to_platform_entry_seconds
        + timing.min_platform_entry_to_platform_exit_seconds
        + timing.platform_exit_to_exit_switch_seconds
        if decision is EanRouteDecision.STOP
        else timing.skip_entry_to_exit_switch_seconds
    )
    return EanPeriodicRouteLeg(
        switch_id=timing.switch_id,
        decision=decision,
        entry_to_exit_seconds=entry_to_exit,
        rope_to_next_switch_seconds=timing.rope_to_next_switch_seconds,
        checkpoint_ids=tuple(checkpoint.id for checkpoint in active),
    )


def _preference_key(bound: EanPeriodicRouteCapacityBound) -> tuple[float, ...]:
    phase_slack = (
        bound.cycle_seconds / bound.fleet_lower_bound
        - bound.bottleneck_headway_seconds
    )
    # The final values make output deterministic without affecting capacity.
    decisions = tuple(
        1 if leg.decision is EanRouteDecision.STOP else 0 for leg in bound.legs
    )
    return (
        float(bound.fleet_lower_bound),
        phase_slack,
        bound.throughput_cabins_per_second,
        *decisions,
    )
