"""Deterministic fleet-cap policy for progressive line-plan warm starts."""

from __future__ import annotations

from dataclasses import dataclass
import math


@dataclass(frozen=True, slots=True)
class AdaptiveFleetPolicy:
    all_stop_cabins: int
    hard_cap: int
    reserve_fraction: float = 0.20
    maximum_growth_factor: float = 1.25
    minimum_step: int | None = None

    @property
    def step(self) -> int:
        return self.minimum_step or max(2, round(self.all_stop_cabins / 20))

    def validate(self) -> None:
        if self.all_stop_cabins <= 0 or self.hard_cap <= 0:
            raise ValueError("fleet bounds must be positive")
        if self.hard_cap < self.all_stop_cabins:
            raise ValueError("hard fleet cap must admit the all-stop reference fleet")
        if not 0 < self.reserve_fraction < 1:
            raise ValueError("reserve fraction must lie in (0, 1)")
        if not 1 < self.maximum_growth_factor <= 2:
            raise ValueError("maximum growth factor must lie in (1, 2]")
        if self.step <= 0:
            raise ValueError("minimum fleet step must be positive")

    def round_up(self, value: float) -> int:
        self.validate()
        return self.step * math.ceil(value / self.step)

    def initial_cap(self, used_fleet: int) -> int:
        if not 0 <= used_fleet <= self.hard_cap:
            raise ValueError("initial used fleet lies outside the hard cap")
        target = max(self.step, used_fleet / (1 - self.reserve_fraction))
        cap = min(self.hard_cap, self.round_up(target))
        if cap < used_fleet:
            raise ValueError("hard cap cannot contain the initial witness")
        return cap

    def next_cap(self, current_cap: int, used_fleet: int) -> int:
        if not 0 <= used_fleet <= current_cap <= self.hard_cap:
            raise ValueError("invalid current cap or used fleet")
        unrounded = min(
            self.maximum_growth_factor * current_cap,
            max(
                current_cap + self.step,
                used_fleet / (1 - self.reserve_fraction),
            ),
        )
        return min(self.hard_cap, self.round_up(unrounded))

