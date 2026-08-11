from __future__ import annotations

from itertools import combinations, product

import pytest

from ropeway_skip_stop_optimization.optimization.ddd.models import (
    DddResource,
    DddResourceUsage,
)
from ropeway_skip_stop_optimization.optimization.ddd.resource_time import (
    DddAnonymousResourceRowKind,
    DddBoundedTickDelay,
    DddResourceTimingAssumption,
    DddTickInterval,
    DddTimedResourceUsageWindow,
    build_ddd_mandatory_resource_rows,
    build_ddd_universal_resource_row,
    ddd_feasible_source_interval,
    find_ddd_universal_resource_conflict,
    find_ddd_violated_interval_capacity_rows,
)
from ropeway_skip_stop_optimization.optimization.ddd.time_space import DddTimeCell
from ropeway_skip_stop_optimization.optimization.ddd.time_ticks import (
    ddd_tick_to_seconds,
)


def _ticks(interval: DddTickInterval | None) -> set[int]:
    if interval is None:
        return set()
    return set(range(interval.lower_tick, interval.upper_tick))


def _window(
    timed_arc_id: str,
    *,
    source: tuple[int, int],
    enter_offset: int = 0,
    clear_offset: int = 0,
    headway: int = 1,
    enter_delay: tuple[int, int] = (0, 0),
    clear_delay: tuple[int, int] = (0, 0),
) -> DddTimedResourceUsageWindow:
    has_wait = enter_delay != (0, 0) or clear_delay != (0, 0)
    return DddTimedResourceUsageWindow(
        timed_arc_id=timed_arc_id,
        resource_id="merge",
        source_interval=DddTickInterval(*source),
        follower_enter_offset_tick=enter_offset,
        leader_clear_offset_tick=clear_offset,
        headway_tick=headway,
        follower_enter_delay=DddBoundedTickDelay(*enter_delay),
        leader_clear_delay=DddBoundedTickDelay(*clear_delay),
        timing_assumption=(
            DddResourceTimingAssumption.BOUNDED_WAIT_ENVELOPE
            if has_wait
            else DddResourceTimingAssumption.NO_WAIT
        ),
    )


def _realizations(
    window: DddTimedResourceUsageWindow,
) -> tuple[tuple[int, int], ...]:
    return tuple(
        (
            source_tick + window.follower_enter_offset_tick + enter_delay_tick,
            source_tick + window.leader_clear_offset_tick + clear_delay_tick,
        )
        for source_tick, enter_delay_tick, clear_delay_tick in product(
            range(
                window.source_interval.lower_tick,
                window.source_interval.upper_tick,
            ),
            range(
                window.follower_enter_delay.minimum_tick,
                window.follower_enter_delay.maximum_tick + 1,
            ),
            range(
                window.leader_clear_delay.minimum_tick,
                window.leader_clear_delay.maximum_tick + 1,
            ),
        )
    )


def test_feasible_source_interval_equals_exhaustive_tick_enumeration() -> None:
    for (
        source_lower,
        source_upper,
        target_lower,
        target_upper,
        duration,
        horizon,
    ) in product(range(3), range(1, 5), range(5), range(1, 7), range(1, 4), range(5)):
        if source_lower >= source_upper or target_lower >= target_upper:
            continue
        source = DddTimeCell.from_ticks("source", source_lower, source_upper)
        target = DddTimeCell.from_ticks("target", target_lower, target_upper)
        expected = {
            source_tick
            for source_tick in range(source_lower, source_upper)
            if source_tick <= horizon
            and target_lower <= source_tick + duration < target_upper
        }
        actual = ddd_feasible_source_interval(
            source_cell=source,
            fixed_source_tick=None,
            target_cell=target,
            duration_tick=duration,
            operational_end_tick=horizon,
        )
        assert _ticks(actual) == expected


def test_fixed_source_interval_includes_route_entry_at_horizon() -> None:
    target = DddTimeCell.from_ticks("target", 7, 9)

    actual = ddd_feasible_source_interval(
        source_cell=None,
        fixed_source_tick=5,
        target_cell=target,
        duration_tick=2,
        operational_end_tick=5,
    )

    assert actual == DddTickInterval(5, 6)


@pytest.mark.parametrize(
    "window",
    [
        _window("point", source=(10, 11), headway=3),
        _window(
            "bounded_wait",
            source=(10, 13),
            enter_offset=1,
            clear_offset=4,
            headway=2,
            enter_delay=(0, 1),
            clear_delay=(0, 2),
        ),
        _window(
            "empty_core",
            source=(10, 18),
            enter_offset=1,
            clear_offset=3,
            headway=2,
            clear_delay=(0, 1),
        ),
    ],
)
def test_mandatory_occupancy_core_is_exact_intersection(
    window: DddTimedResourceUsageWindow,
) -> None:
    window.validate()
    blocked_sets = [
        set(range(enter_tick, clear_tick + window.headway_tick))
        for enter_tick, clear_tick in _realizations(window)
    ]
    exact_intersection = set.intersection(*blocked_sets)

    assert _ticks(window.mandatory_occupancy_core) == exact_intersection


def test_universal_conflict_matches_exhaustive_no_wait_enumeration() -> None:
    for first_lower, first_upper, second_lower, second_upper, headway in product(
        range(4), range(1, 6), range(4), range(1, 6), range(1, 4)
    ):
        if first_lower >= first_upper or second_lower >= second_upper:
            continue
        first = _window(
            "first",
            source=(first_lower, first_upper),
            clear_offset=1,
            headway=headway,
        )
        second = _window(
            "second",
            source=(second_lower, second_upper),
            clear_offset=1,
            headway=headway,
        )
        has_feasible_realization = any(
            second_enter - first_clear >= headway
            or first_enter - second_clear >= headway
            for (first_enter, first_clear), (second_enter, second_clear) in product(
                _realizations(first),
                _realizations(second),
            )
        )

        proof = find_ddd_universal_resource_conflict(first, second)

        assert (proof is None) is has_feasible_realization


def test_universal_conflict_remains_safe_with_bounded_waiting() -> None:
    for first_lower, first_upper, second_lower, second_upper, headway in product(
        range(3), range(1, 5), range(3), range(1, 5), range(1, 4)
    ):
        if first_lower >= first_upper or second_lower >= second_upper:
            continue
        first = _window(
            "first",
            source=(first_lower, first_upper),
            clear_offset=2,
            headway=headway,
            enter_delay=(0, 1),
            clear_delay=(0, 1),
        )
        second = _window(
            "second",
            source=(second_lower, second_upper),
            clear_offset=2,
            headway=headway,
            enter_delay=(0, 1),
            clear_delay=(0, 1),
        )
        has_feasible_realization = any(
            second_enter - first_clear >= headway
            or first_enter - second_clear >= headway
            for (first_enter, first_clear), (second_enter, second_clear) in product(
                _realizations(first),
                _realizations(second),
            )
        )

        proof = find_ddd_universal_resource_conflict(first, second)

        # Marginal envelopes may miss a proof, but may never invent one.
        assert proof is None or not has_feasible_realization


def test_wait_envelope_distinguishes_universal_and_observed_conflicts() -> None:
    fixed = _window("fixed", source=(12, 13), headway=5)
    narrow = _window("narrow", source=(10, 14), headway=5)
    wide = _window("wide", source=(10, 18), headway=5)

    assert find_ddd_universal_resource_conflict(narrow, fixed) is not None
    assert find_ddd_universal_resource_conflict(wide, fixed) is None
    assert abs(12 - 10) < 5  # The observed early realization still conflicts.


def test_mandatory_resource_sweep_returns_only_maximal_cliques() -> None:
    windows = (
        _window("a", source=(0, 1), headway=5),
        _window("b", source=(2, 3), headway=5),
        _window("c", source=(6, 7), headway=5),
    )

    rows = build_ddd_mandatory_resource_rows(windows)

    assert [row.witness_tick for row in rows] == [4, 6]
    assert [tuple(term.timed_arc_id for term in row.terms) for row in rows] == [
        ("a", "b"),
        ("b", "c"),
    ]
    assert all(row.kind is DddAnonymousResourceRowKind.MANDATORY_CORE for row in rows)


def test_mandatory_resource_sweep_exhaustively_dominates_every_tick_row() -> None:
    interval_bounds = tuple(
        (lower, upper) for lower in range(4) for upper in range(lower + 1, 5)
    )
    for subset_size in range(1, len(interval_bounds) + 1):
        for selected_bounds in combinations(interval_bounds, subset_size):
            windows = tuple(
                DddTimedResourceUsageWindow(
                    timed_arc_id=f"arc_{lower}_{upper}",
                    resource_id="merge",
                    source_interval=DddTickInterval(lower, lower + 1),
                    follower_enter_offset_tick=0,
                    leader_clear_offset_tick=upper - lower - 1,
                    headway_tick=1,
                )
                for lower, upper in selected_bounds
            )

            rows = build_ddd_mandatory_resource_rows(windows)
            row_arc_ids = tuple(
                {term.timed_arc_id for term in row.terms} for row in rows
            )

            for row, emitted_arc_ids in zip(rows, row_arc_ids, strict=True):
                assert emitted_arc_ids == {
                    window.timed_arc_id
                    for window in windows
                    if (
                        window.mandatory_occupancy_core is not None
                        and window.mandatory_occupancy_core.contains_tick(
                            row.witness_tick
                        )
                    )
                }
            for tick in range(4):
                active_arc_ids = {
                    window.timed_arc_id
                    for window in windows
                    if (
                        window.mandatory_occupancy_core is not None
                        and window.mandatory_occupancy_core.contains_tick(tick)
                    )
                }
                if active_arc_ids:
                    assert any(
                        active_arc_ids <= emitted_arc_ids
                        for emitted_arc_ids in row_arc_ids
                    )


def test_mandatory_resource_row_preserves_same_arc_multiplicity() -> None:
    windows = (
        _window("shared", source=(0, 1), headway=5),
        DddTimedResourceUsageWindow(
            timed_arc_id="shared",
            resource_id="merge",
            source_interval=DddTickInterval(0, 1),
            follower_enter_offset_tick=1,
            leader_clear_offset_tick=1,
            headway_tick=5,
            usage_index=1,
        ),
    )

    (row,) = build_ddd_mandatory_resource_rows(windows)

    assert row.terms[0].timed_arc_id == "shared"
    assert row.terms[0].coefficient == 2


def test_mandatory_resource_rows_reject_inconsistent_shared_headway() -> None:
    windows = (
        _window("first", source=(0, 1), headway=2),
        _window("second", source=(0, 1), headway=3),
    )

    with pytest.raises(ValueError, match="different headways"):
        build_ddd_mandatory_resource_rows(windows)


def test_universal_conflict_builds_distinct_and_self_capacity_rows() -> None:
    first = _window("first", source=(10, 14), headway=5)
    second = _window("second", source=(12, 13), headway=5)

    pair_row = build_ddd_universal_resource_row(first, second)
    self_row = build_ddd_universal_resource_row(second, second)

    assert pair_row is not None
    assert pair_row.kind is DddAnonymousResourceRowKind.UNIVERSAL_CONFLICT
    assert tuple(term.timed_arc_id for term in pair_row.terms) == (
        "first",
        "second",
    )
    assert pair_row.right_hand_side == 1
    assert self_row is not None
    assert self_row.terms[0].timed_arc_id == "second"
    assert self_row.right_hand_side == 1


def test_nonuniversal_observed_conflict_does_not_build_row() -> None:
    wide = _window("wide", source=(10, 18), headway=5)
    fixed = _window("fixed", source=(12, 13), headway=5)

    assert build_ddd_universal_resource_row(wide, fixed) is None


def test_interval_capacity_separator_finds_three_entries_in_two_slot_window() -> None:
    windows = (
        _window("a", source=(0, 1), headway=3),
        _window("b", source=(2, 3), headway=3),
        _window("c", source=(4, 5), headway=3),
    )

    rows = find_ddd_violated_interval_capacity_rows(
        windows,
        arc_flow_by_id={"a": 1, "b": 1, "c": 1},
    )

    row = next(
        item
        for item in rows
        if item.interval_lower_tick == 0 and item.interval_upper_tick == 4
    )
    assert row.kind is DddAnonymousResourceRowKind.INTERVAL_CAPACITY
    assert row.right_hand_side == 2
    assert tuple(term.timed_arc_id for term in row.terms) == ("a", "b", "c")


def test_interval_capacity_separator_preserves_anonymous_flow_multiplicity() -> None:
    rows = find_ddd_violated_interval_capacity_rows(
        (_window("shared", source=(7, 8), headway=2),),
        arc_flow_by_id={"shared": 3},
    )

    assert len(rows) == 1
    assert rows[0].terms[0].coefficient == 1
    assert rows[0].right_hand_side == 1


def test_interval_capacity_separator_uses_complete_waiting_window() -> None:
    flexible = _window(
        "flexible",
        source=(0, 1),
        headway=3,
        enter_delay=(0, 10),
    )
    fixed = _window("fixed", source=(0, 1), headway=3)

    rows = find_ddd_violated_interval_capacity_rows(
        (flexible, fixed),
        arc_flow_by_id={"flexible": 1, "fixed": 1},
    )

    assert all(
        tuple(term.timed_arc_id for term in row.terms) != ("fixed", "flexible")
        for row in rows
    )


def test_from_usage_preserves_canonical_tick_offsets() -> None:
    resource = DddResource("merge", ddd_tick_to_seconds(5))
    usage = DddResourceUsage(
        "merge",
        leader_clear_offset_seconds=ddd_tick_to_seconds(3),
        follower_enter_offset_seconds=ddd_tick_to_seconds(1),
    )

    window = DddTimedResourceUsageWindow.from_usage(
        timed_arc_id="arc",
        source_interval=DddTickInterval(10, 12),
        resource=resource,
        usage=usage,
    )

    assert window.headway_tick == 5
    assert window.follower_enter_offset_tick == 1
    assert window.leader_clear_offset_tick == 3


def test_no_wait_assumption_rejects_nonzero_delay() -> None:
    window = DddTimedResourceUsageWindow(
        timed_arc_id="arc",
        resource_id="merge",
        source_interval=DddTickInterval(0, 1),
        follower_enter_offset_tick=0,
        leader_clear_offset_tick=1,
        headway_tick=1,
        leader_clear_delay=DddBoundedTickDelay(0, 1),
    )

    with pytest.raises(ValueError, match="no-wait"):
        window.validate()


def test_universal_conflict_requires_one_resource_contract() -> None:
    first = _window("first", source=(0, 1))
    second = DddTimedResourceUsageWindow(
        timed_arc_id="second",
        resource_id="other",
        source_interval=DddTickInterval(0, 1),
        follower_enter_offset_tick=0,
        leader_clear_offset_tick=0,
        headway_tick=1,
    )

    with pytest.raises(ValueError, match="shared resource"):
        find_ddd_universal_resource_conflict(first, second)
