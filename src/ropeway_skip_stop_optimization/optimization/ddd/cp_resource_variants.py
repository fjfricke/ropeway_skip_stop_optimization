"""Equivalent resource encodings; preserve the original horizon guard."""

from ortools.sat.python import cp_model


def variable_for(model, expression, name):
    flat = cp_model.FlatIntExpr(expression)
    lo = hi = flat.offset
    for v, c in zip(flat.vars, flat.coeffs):
        domain = list(v.proto.domain)
        lo += c * (domain[0] if c >= 0 else domain[-1])
        hi += c * (domain[-1] if c >= 0 else domain[0])
    v = model.new_int_var(lo, hi, name)
    model.add(v == expression)
    return v


def presence(model, selected, entry, horizon):
    p = model.new_bool_var("resource_present_variant")
    model.add_implication(p, selected)
    model.add(entry <= horizon).only_enforce_if(p)
    model.add(entry >= horizon + 1).only_enforce_if([selected, p.Not()])
    return p


def add_compact_interval(
    model,
    movement,
    expression,
    size,
    selected,
    usage,
    intervals,
    max_completion,
    max_wait,
    step,
):
    flat = cp_model.FlatIntExpr(expression)
    entry = (
        expression
        if len(flat.vars) <= 1
        else variable_for(model, expression, "compact_entry")
    )
    p = (
        selected
        if usage.follower_enter_offset_tick == 0
        and usage.follower_enter_wait_coefficient == 0
        else presence(model, selected, entry, movement.operational_end_tick)
    )
    intervals[usage.resource_id].append(
        model.new_optional_fixed_size_interval_var(entry, size, p, "compact_resource")
    )


def add_merged_exit(
    model,
    movement,
    time,
    active,
    wait,
    step,
    options,
    selection,
    intervals,
    horizon,
    maximum_wait,
):
    if len(options) != 2 or {o.decision.value for o in options} != {"stop", "skip"}:
        return set()
    stop = next(o for o in options if o.decision.value == "stop")
    skip = next(o for o in options if o.decision.value == "skip")
    us = {u.resource_id: u for u in stop.resource_usages}
    uk = {u.resource_id: u for u in skip.resource_usages}
    merged = set()
    for rid in us.keys() & uk.keys() & intervals.keys():
        if not rid.startswith("exit_switch::"):
            continue
        a, b = us[rid], uk[rid]
        # Only merge fixed-duration guards with STOP delay, no SKIP delay.
        if (
            a.follower_enter_wait_coefficient != a.leader_clear_wait_coefficient
            or b.follower_enter_wait_coefficient
            or b.leader_clear_wait_coefficient
        ):
            continue
        resource = movement.resources_by_id[rid]
        sa = (
            a.leader_clear_offset_tick
            - a.follower_enter_offset_tick
            + a.separation_after_tick(resource.minimum_headway_tick)
        )
        sb = (
            b.leader_clear_offset_tick
            - b.follower_enter_offset_tick
            + b.separation_after_tick(resource.minimum_headway_tick)
        )
        if min(sa, sb) <= 0:
            continue
        entry = variable_for(
            model,
            time
            + b.follower_enter_offset_tick
            + (a.follower_enter_offset_tick - b.follower_enter_offset_tick)
            * selection[stop.id]
            + a.follower_enter_wait_coefficient * step * wait,
            "merged_exit_entry",
        )
        size = variable_for(
            model, sb + (sa - sb) * selection[stop.id], "merged_exit_size"
        )
        end = variable_for(model, entry + size, "merged_exit_end")
        p = presence(model, active, entry, movement.operational_end_tick)
        intervals[rid].append(
            model.new_optional_interval_var(entry, size, end, p, "merged_exit")
        )
        merged.add(rid)
    return merged
