from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from ortools.sat.python import cp_model

from .models import DddMovementProblem, DddRouteDecision, DddRouteOption
from .reference import DddReferenceResourceOccurrence
from .time_refinement import DddRecoveredSchedule
from .time_space import DddPartialTimedPath
from .time_ticks import ddd_seconds_to_tick
from .trajectory_problem import DddTrajectoryWaitingPolicy


@dataclass(frozen=True)
class DddCpSatMovementModel:
    model: cp_model.CpModel
    time_by_cabin: dict[int, list[cp_model.IntVar]]
    active_by_cabin: dict[int, list[cp_model.IntVar]]
    selection_by_key: dict[tuple[int, int, str], cp_model.IntVar]
    states_by_cabin: dict[int, tuple[str, ...]]
    resource_intervals: dict[str, list[cp_model.IntervalVar]]
    max_completion_tick: int
    wait_steps_by_key: dict[tuple[int, int], cp_model.IntVar]
    waiting_step_tick: int


def build_ddd_cp_sat_movement(
    movement: DddMovementProblem,
    *,
    waiting_policy: DddTrajectoryWaitingPolicy = DddTrajectoryWaitingPolicy(),
    hint_paths: tuple[DddPartialTimedPath, ...] = (),
    hint_schedules: tuple[DddRecoveredSchedule, ...] = (),
    boundary_occurrences: tuple[DddReferenceResourceOccurrence, ...] = (),
    enabled_resource_ids: tuple[str, ...] | None = None,
    deadline_monotonic: float | None = None,
) -> DddCpSatMovementModel:
    """Shared physical construction; no objective or search restrictions.

    Waiting and optional resource subsets remain available to the legacy oracle.
    The integrated exact solver checks its stricter domain before calling this.
    """
    movement.validate()
    waiting_policy.validate(movement.core)
    waiting_step_tick = (1 if waiting_policy.step_seconds is None
                         else ddd_seconds_to_tick(waiting_policy.step_seconds))
    enabled_resource_id_set = (None if enabled_resource_ids is None
                               else set(enabled_resource_ids))
    model = cp_model.CpModel()
    max_completion_tick = movement.operational_end_tick + max(
        option.duration_tick
        + ddd_seconds_to_tick(
            waiting_policy.maximum_wait_seconds(option.station_id)
        )
        for option in movement.route_options
    )
    hint_schedule_by_cabin = {
        schedule.cabin_id: schedule for schedule in hint_schedules
    }
    hint_by_cabin = dict(hint_schedule_by_cabin)
    hint_by_cabin.update({path.cabin_id: path for path in hint_paths})
    wait_steps_by_key = {}
    time_by_cabin: dict[int, list[cp_model.IntVar]] = {}
    active_by_cabin: dict[int, list[cp_model.IntVar]] = {}
    selection_by_key: dict[tuple[int, int, str], cp_model.IntVar] = {}
    states_by_cabin: dict[int, tuple[str, ...]] = {}
    resource_intervals: dict[str, list[cp_model.IntervalVar]] = {
        resource.id: []
        for resource in movement.resources
        if enabled_resource_id_set is None or resource.id in enabled_resource_id_set
    }
    for index, occurrence in enumerate(boundary_occurrences):
        resource = movement.resources_by_id.get(occurrence.resource_id)
        if resource is None:
            raise ValueError("CP-SAT boundary occurrence uses an unknown resource")
        if (
            enabled_resource_id_set is not None
            and occurrence.resource_id not in enabled_resource_id_set
        ):
            continue
        end_tick = ddd_seconds_to_tick(
            occurrence.leader_clear_time_seconds
        ) + occurrence.separation_after_tick(resource)
        start_tick = max(
            0,
            ddd_seconds_to_tick(occurrence.follower_enter_time_seconds),
        )
        if end_tick <= start_tick:
            continue
        resource_intervals[occurrence.resource_id].append(
            model.new_fixed_size_interval_var(
                start_tick,
                end_tick - start_tick,
                f"boundary[{index}]",
            )
        )

    for start in sorted(movement.starts, key=lambda item: item.cabin_id):
        if deadline_monotonic is not None and perf_counter() >= deadline_monotonic:
            raise TimeoutError("CP-SAT movement build budget exhausted")
        states, options_by_visit = _deterministic_visit_structure(
            movement,
            start.state_id,
            start.max_visit_count,
        )
        states_by_cabin[start.cabin_id] = states
        event_times = [
            model.new_int_var(
                start.time_tick if visit_index == 0 else 0,
                start.time_tick if visit_index == 0 else max_completion_tick,
                f"time[{start.cabin_id},{visit_index}]",
            )
            for visit_index in range(start.max_visit_count + 1)
        ]
        active = [
            model.new_bool_var(f"active[{start.cabin_id},{visit_index}]")
            for visit_index in range(start.max_visit_count + 1)
        ]
        model.add(active[0] == 1)
        model.add(active[-1] == 0)
        for visit_index in range(start.max_visit_count + 1):
            model.add(
                event_times[visit_index] <= movement.operational_end_tick
            ).only_enforce_if(active[visit_index])
            model.add(
                event_times[visit_index] >= movement.operational_end_tick + 1
            ).only_enforce_if(active[visit_index].Not())

        hinted_route_ids = (
            hint_by_cabin[start.cabin_id].route_option_ids
            if start.cabin_id in hint_by_cabin
            else ()
        )
        hinted_events = (
            hint_schedule_by_cabin[start.cabin_id].events
            if start.cabin_id in hint_schedule_by_cabin
            else ()
        )
        for visit_index, event in enumerate(hinted_events):
            if visit_index < len(event_times):
                model.add_hint(event_times[visit_index], event.time_tick)
        for visit_index, options in enumerate(options_by_visit):
            selections = []
            maximum_wait_steps_by_option: dict[str, int] = {}
            maximum_wait_steps = 0
            for option in options:
                selected = model.new_bool_var(
                    f"route[{start.cabin_id},{visit_index},{option.id}]"
                )
                selection_by_key[(start.cabin_id, visit_index, option.id)] = (
                    selected
                )
                selections.append(selected)
                maximum_wait_tick = ddd_seconds_to_tick(
                    waiting_policy.maximum_wait_seconds(option.station_id)
                )
                if (
                    option.decision is DddRouteDecision.SKIP
                    or option.platform_exit_offset_seconds is None
                ):
                    maximum_wait_tick = 0
                maximum_wait_step = maximum_wait_tick // waiting_step_tick
                maximum_wait_steps_by_option[option.id] = maximum_wait_step
                maximum_wait_steps = max(
                    maximum_wait_steps,
                    maximum_wait_step,
                )
                if visit_index < len(hinted_route_ids):
                    model.add_hint(
                        selected,
                        int(hinted_route_ids[visit_index] == option.id),
                    )
            model.add(sum(selections) == active[visit_index])
            wait_steps = model.new_int_var(
                0,
                maximum_wait_steps,
                f"wait_steps[{start.cabin_id},{visit_index}]",
            )
            wait_steps_by_key[start.cabin_id, visit_index] = wait_steps
            model.add(
                wait_steps
                <= sum(
                    maximum_wait_steps_by_option[option.id]
                    * selection_by_key[
                        (start.cabin_id, visit_index, option.id)
                    ]
                    for option in options
                )
            )
            if maximum_wait_steps:
                wait_positive = model.new_bool_var(
                    f"wait_positive[{start.cabin_id},{visit_index}]"
                )
                model.add(wait_steps >= 1).only_enforce_if(wait_positive)
                model.add(wait_steps == 0).only_enforce_if(
                    wait_positive.Not()
                )
                for option in options:
                    if maximum_wait_steps_by_option[option.id] <= 0:
                        continue
                    assert option.platform_exit_offset_seconds is not None
                    model.add(
                        event_times[visit_index]
                        + ddd_seconds_to_tick(
                            option.platform_exit_offset_seconds
                        )
                        >= ddd_seconds_to_tick(
                            waiting_policy.earliest_wait_time_seconds
                        )
                    ).only_enforce_if(
                        [
                            selection_by_key[
                                (start.cabin_id, visit_index, option.id)
                            ],
                            wait_positive,
                        ]
                    )
            for option in options:
                _add_resource_intervals(
                    model=model,
                    movement=movement,
                    cabin_id=start.cabin_id,
                    visit_index=visit_index,
                    event_time=event_times[visit_index],
                    wait_steps=wait_steps,
                    maximum_wait_steps=maximum_wait_steps,
                    waiting_step_tick=waiting_step_tick,
                    max_completion_tick=max_completion_tick,
                    selected=selection_by_key[
                        (start.cabin_id, visit_index, option.id)
                    ],
                    option=option,
                    intervals_by_resource=resource_intervals,
                )
            model.add(
                event_times[visit_index + 1]
                == event_times[visit_index]
                + sum(
                    option.duration_tick
                    * selection_by_key[(start.cabin_id, visit_index, option.id)]
                    for option in options
                )
                + waiting_step_tick * wait_steps
            )

        time_by_cabin[start.cabin_id] = event_times
        active_by_cabin[start.cabin_id] = active

    for intervals in resource_intervals.values():
        if intervals:
            model.add_no_overlap(intervals)

    return DddCpSatMovementModel(
        model, time_by_cabin, active_by_cabin, selection_by_key,
        states_by_cabin, resource_intervals, max_completion_tick, wait_steps_by_key, waiting_step_tick,
    )


def _deterministic_visit_structure(
    movement: DddMovementProblem,
    start_state_id: str,
    max_visit_count: int,
) -> tuple[tuple[str, ...], tuple[tuple[DddRouteOption, ...], ...]]:
    state_id = start_state_id
    states = [state_id]
    options_by_visit: list[tuple[DddRouteOption, ...]] = []
    for _ in range(max_visit_count):
        options = movement.route_options_by_state_id.get(state_id, ())
        if not options:
            raise ValueError(f"DDD CP-SAT state {state_id!r} has no route option")
        target_ids = {option.to_state_id for option in options}
        if len(target_ids) != 1:
            raise ValueError(
                "DDD CP-SAT v1 requires route options to reconverge at every visit"
            )
        options_by_visit.append(options)
        state_id = next(iter(target_ids))
        states.append(state_id)
    return tuple(states), tuple(options_by_visit)


def _add_resource_intervals(
    *,
    model: cp_model.CpModel,
    movement: DddMovementProblem,
    cabin_id: int,
    visit_index: int,
    event_time: cp_model.IntVar,
    wait_steps: cp_model.IntVar,
    maximum_wait_steps: int,
    waiting_step_tick: int,
    max_completion_tick: int,
    selected: cp_model.IntVar,
    option: DddRouteOption,
    intervals_by_resource: dict[str, list[cp_model.IntervalVar]],
) -> None:
    for usage_index, usage in enumerate(option.resource_usages):
        if usage.resource_id not in intervals_by_resource:
            continue
        resource = movement.resources_by_id[usage.resource_id]
        base_size_tick = (
            usage.leader_clear_offset_tick
            - usage.follower_enter_offset_tick
            + usage.separation_after_tick(resource.minimum_headway_tick)
        )
        wait_size_coefficient = (
            usage.leader_clear_wait_coefficient
            - usage.follower_enter_wait_coefficient
        ) * waiting_step_tick
        if base_size_tick <= 0:
            raise ValueError("DDD CP-SAT resource interval must have positive size")
        entry_expression = (
            event_time
            + usage.follower_enter_offset_tick
            + usage.follower_enter_wait_coefficient
            * waiting_step_tick
            * wait_steps
        )
        end_expression = (
            event_time
            + usage.leader_clear_offset_tick
            + usage.leader_clear_wait_coefficient
            * waiting_step_tick
            * wait_steps
            + usage.separation_after_tick(resource.minimum_headway_tick)
        )
        size_expression = base_size_tick + wait_size_coefficient * wait_steps
        entry_wait_coefficient = (
            usage.follower_enter_wait_coefficient * waiting_step_tick
        )
        end_wait_coefficient = (
            usage.leader_clear_wait_coefficient * waiting_step_tick
        )
        entry = model.new_int_var(
            min(
                usage.follower_enter_offset_tick,
                usage.follower_enter_offset_tick
                + entry_wait_coefficient * maximum_wait_steps,
            ),
            max_completion_tick
            + max(
                usage.follower_enter_offset_tick,
                usage.follower_enter_offset_tick
                + entry_wait_coefficient * maximum_wait_steps,
            ),
            f"resource_entry[{usage.resource_id},{cabin_id},{visit_index},{usage_index}]",
        )
        end = model.new_int_var(
            min(
                usage.leader_clear_offset_tick
                + usage.separation_after_tick(resource.minimum_headway_tick),
                usage.leader_clear_offset_tick
                + end_wait_coefficient * maximum_wait_steps
                + usage.separation_after_tick(resource.minimum_headway_tick),
            ),
            max_completion_tick
            + max(
                usage.leader_clear_offset_tick
                + usage.separation_after_tick(resource.minimum_headway_tick),
                usage.leader_clear_offset_tick
                + end_wait_coefficient * maximum_wait_steps
                + usage.separation_after_tick(resource.minimum_headway_tick),
            ),
            f"resource_end[{usage.resource_id},{cabin_id},{visit_index},{usage_index}]",
        )
        minimum_size = min(
            base_size_tick,
            base_size_tick + wait_size_coefficient * maximum_wait_steps,
        )
        maximum_size = max(
            base_size_tick,
            base_size_tick + wait_size_coefficient * maximum_wait_steps,
        )
        if minimum_size <= 0:
            raise ValueError(
                "DDD CP-SAT resource interval must remain positive for every wait"
            )
        size = model.new_int_var(
            minimum_size,
            maximum_size,
            f"resource_size[{usage.resource_id},{cabin_id},{visit_index},{usage_index}]",
        )
        model.add(entry == entry_expression)
        model.add(end == end_expression)
        model.add(size == size_expression)
        if (
            usage.follower_enter_offset_tick == 0
            and usage.follower_enter_wait_coefficient == 0
        ):
            present = selected
        else:
            present = model.new_bool_var(
                f"resource_active[{cabin_id},{visit_index},{usage_index}]"
            )
            model.add_implication(present, selected)
            model.add(entry <= movement.operational_end_tick).only_enforce_if(present)
            model.add(entry >= movement.operational_end_tick + 1).only_enforce_if(
                [selected, present.Not()]
            )
        interval = model.new_optional_interval_var(
            entry,
            size,
            end,
            present,
            f"resource[{usage.resource_id},{cabin_id},{visit_index},{usage_index}]",
        )
        intervals_by_resource[usage.resource_id].append(interval)


