from __future__ import annotations

import math


DDD_TIME_TICKS_PER_SECOND = 1_000_000
DDD_TIME_TICK_SECONDS = 1.0 / DDD_TIME_TICKS_PER_SECOND

type DddTimeTick = int


def ddd_seconds_to_tick(value: float) -> DddTimeTick:
    """Quantize seconds once to the canonical DDD microsecond domain."""
    if not math.isfinite(value):
        raise ValueError("DDD time value must be finite")
    return int(round(value * DDD_TIME_TICKS_PER_SECOND))


def ddd_headway_seconds_to_tick(value: float) -> DddTimeTick:
    """Round a safety separation outward in the canonical DDD time domain."""
    if not math.isfinite(value):
        raise ValueError("DDD headway value must be finite")
    return int(math.ceil(value * DDD_TIME_TICKS_PER_SECOND))


def ddd_tick_to_seconds(value: DddTimeTick) -> float:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("DDD time tick must be an integer")
    return value / DDD_TIME_TICKS_PER_SECOND


def ddd_quantize_time_seconds(value: float) -> float:
    return ddd_tick_to_seconds(ddd_seconds_to_tick(value))


def ddd_quantize_headway_seconds(value: float) -> float:
    return ddd_tick_to_seconds(ddd_headway_seconds_to_tick(value))
