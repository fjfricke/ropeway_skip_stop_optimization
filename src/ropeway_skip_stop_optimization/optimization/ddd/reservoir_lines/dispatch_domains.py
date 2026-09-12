from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True)
class TickInterval:
    lower: int
    upper: int

    def __post_init__(self):
        if self.lower > self.upper:
            raise ValueError("empty closed tick interval")


def merge_closed(intervals: Iterable[tuple[int, int]]) -> tuple[TickInterval, ...]:
    ordered = sorted((a, b) for a, b in intervals if a <= b)
    merged: list[list[int]] = []
    for lower, upper in ordered:
        if not merged or lower > merged[-1][1] + 1:
            merged.append([lower, upper])
        else:
            merged[-1][1] = max(merged[-1][1], upper)
    return tuple(TickInterval(a, b) for a, b in merged)


def complement_closed(
    forbidden: Iterable[tuple[int, int]], lower: int, upper: int
) -> tuple[TickInterval, ...]:
    if lower > upper:
        return ()
    result, cursor = [], lower
    for interval in merge_closed(forbidden):
        a, b = max(lower, interval.lower), min(upper, interval.upper)
        if a > b:
            continue
        if cursor < a:
            result.append(TickInterval(cursor, a - 1))
        cursor = max(cursor, b + 1)
    if cursor <= upper:
        result.append(TickInterval(cursor, upper))
    return tuple(result)


def forbidden_delta_for_half_open_intervals(
    first_start: int, first_end: int, second_start: int, second_end: int
) -> TickInterval:
    """Integer deltas for which [a,b) overlaps delta+[c,e)."""
    if first_start >= first_end or second_start >= second_end:
        raise ValueError("resource intervals must be nonempty")
    return TickInterval(first_start - second_end + 1, first_end - second_start - 1)
