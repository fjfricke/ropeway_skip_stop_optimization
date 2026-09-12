"""Optional single-use cabin lifecycles using the shared CP resource physics."""

from __future__ import annotations

from time import perf_counter
from ortools.sat.python import cp_model

from .cp_sat_movement import DddCpSatMovementModel, _add_resource_intervals
from .models import DddRouteDecision
from .reservoir_cp_sat_problem import DddReservoirCpSatProblem
from .time_ticks import ddd_seconds_to_tick


def build_reservoir_cp_movement(
    problem: DddReservoirCpSatProblem,
    *,
    deadline=None,
    resource_encoding="legacy",
    dispatch_order_symmetry=True,
):
    problem.validate()
    movement, states = problem.movement, problem.visit_states
    horizon = movement.operational_end_tick
    policy = problem.waiting_policy
    step = ddd_seconds_to_tick(policy.step_seconds or 0.000001)
    model = cp_model.CpModel()
    times, active, selection, waits = {}, {}, {}, {}
    intervals = {r.id: [] for r in movement.resources}
    state_intervals = {s.id: [] for s in movement.states}
    first = ddd_seconds_to_tick(problem.dispatch_start_seconds)
    last = ddd_seconds_to_tick(problem.dispatch_end_seconds)
    dispatch_step = ddd_seconds_to_tick(problem.dispatch_step_seconds)
    for k in range(problem.available_fleet_count):
        if deadline is not None and perf_counter() >= deadline:
            raise TimeoutError("reservoir CP movement build budget exhausted")
        times[k] = [
            model.new_int_var(0, horizon, f"time[{k},{i}]") for i in range(len(states))
        ]
        active[k] = [model.new_bool_var(f"active[{k},{i}]") for i in range(len(states))]
        t, a = times[k], active[k]
        model.add(a[-1] == 0)
        dispatch = model.new_int_var(
            0, (last - first) // dispatch_step, f"dispatch_step[{k}]"
        )
        model.add(t[0] == first + dispatch_step * dispatch).only_enforce_if(a[0])
        model.add(t[0] == 0).only_enforce_if(a[0].Not())
        model.add(dispatch == 0).only_enforce_if(a[0].Not())
        if k:
            model.add(a[0] <= active[k - 1][0])
            if dispatch_order_symmetry:
                model.add(t[0] >= times[k - 1][0]).only_enforce_if(a[0])
        for i, state in enumerate(states):
            present = a[0] if i == 0 else a[i - 1]
            # Same unique state-time occupancy as the anonymous reservoir net;
            # one tick is uniqueness, NOT an invented physical depot headway.
            state_intervals[state].append(
                model.new_optional_fixed_size_interval_var(
                    t[i], 1, present, f"state[{k},{i}]"
                )
            )
            if i:
                model.add(a[i] <= a[i - 1])
                if state != problem.entry_state_id:
                    model.add(a[i] == a[i - 1])
                else:
                    returned = model.new_bool_var(f"return[{k},{i}]")
                    model.add(returned == a[i - 1] - a[i])
                    model.add(
                        t[i] >= ddd_seconds_to_tick(problem.return_start_seconds)
                    ).only_enforce_if(returned)
            if i == len(states) - 1:
                continue
            options = movement.route_options_by_state_id[state]
            chosen = []
            maxima = {}
            for o in options:
                selection[k, i, o.id] = model.new_bool_var(f"route[{k},{i},{o.id}]")
                chosen.append(selection[k, i, o.id])
                maxima[o.id] = (
                    ddd_seconds_to_tick(policy.maximum_wait_seconds(o.station_id))
                    // step
                    if o.decision is DddRouteDecision.STOP
                    else 0
                )
            model.add(sum(chosen) == a[i])
            maximum = max(maxima.values())
            w = model.new_int_var(0, maximum, f"wait[{k},{i}]")
            waits[k, i] = w
            model.add(w <= sum(maxima[o.id] * selection[k, i, o.id] for o in options))
            if maximum:
                positive = model.new_bool_var(f"wait_positive[{k},{i}]")
                model.add(w >= 1).only_enforce_if(positive)
                model.add(w == 0).only_enforce_if(positive.Not())
                for o in options:
                    if maxima[o.id]:
                        model.add(
                            t[i] + ddd_seconds_to_tick(o.platform_exit_offset_seconds)
                            >= ddd_seconds_to_tick(policy.earliest_wait_time_seconds)
                        ).only_enforce_if([positive, selection[k, i, o.id]])
            merged = set()
            if resource_encoding == "merged_exit":
                from .cp_resource_variants import add_merged_exit
                merged = add_merged_exit(model, movement, t[i], a[i], w, step, options, {o.id: selection[k,i,o.id] for o in options}, intervals, horizon, maximum)
            for o in options:
                _add_resource_intervals(
                    model=model,
                    movement=movement,
                    cabin_id=k,
                    visit_index=i,
                    event_time=t[i],
                    wait_steps=w,
                    maximum_wait_steps=maximum,
                    waiting_step_tick=step,
                    max_completion_tick=horizon,
                    selected=selection[k, i, o.id],
                    option=o,
                    intervals_by_resource=intervals,
                    resource_encoding=resource_encoding, excluded_resources=merged,
                )
            model.add(
                t[i + 1]
                == t[i]
                + sum(o.duration_tick * selection[k, i, o.id] for o in options)
                + step * w
            )
    for values in (*intervals.values(), *state_intervals.values()):
        model.add_no_overlap(values)
    return DddCpSatMovementModel(
        model,
        times,
        active,
        selection,
        {k: states for k in times},
        intervals,
        horizon,
        waits,
        step,
    )
