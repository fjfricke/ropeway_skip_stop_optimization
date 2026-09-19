"""No-Wait motion: a cabin type and shift determine its entire trajectory.

Initial-state indicators are derived from the shift for certificate export.
Resources use the same trajectory before/after zero, without boundary copies.
"""

from collections import defaultdict
from dataclasses import replace
from itertools import pairwise
from time import perf_counter

from ortools.sat.python import cp_model

from ropeway_skip_stop_optimization.models import HeadwayRouteBehavior
from ropeway_skip_stop_optimization.optimization.ean.models import (
    EanActivationReference,
    EanTimeReference,
)

from .passenger_candidates import oip_passenger_candidate_builder


def _and(model, literals, name):
    result = model.new_bool_var(name)
    model.add_bool_and(literals).only_enforce_if(result)
    model.add_bool_or([result, *(v.Not() for v in literals)])
    return result


def _le(model, expression, bound, name):
    result = model.new_bool_var(name)
    model.add(expression <= bound).only_enforce_if(result)
    model.add(expression > bound).only_enforce_if(result.Not())
    return result


def build_nowait_template_model(
    domain,
    *,
    type_catalog,
    passenger_encoding,
    passenger_builder=None,
    fixed_type_counts=None,
    specialize_fixed_types=True,
    reduce_headways=True,
):
    from .cp_sat import (
        BuiltOipCpSatModel,
        OipCpSatMovementVariables,
        _build_group_passengers,
        _build_inventory_passengers,
        _type_ids,
        _type_serves,
    )

    started = perf_counter()
    artifact, grid = domain.artifact, domain.grid
    types = _type_ids(type_catalog)
    if not types or domain.fixed_k is None or domain.fixed_k != domain.k_max:
        raise ValueError("No-Wait templates require a type catalog and exact K")
    if any((s.max_wait_seconds or 0) != 0 for s in artifact.config.station_configs):
        raise ValueError("No-Wait templates do not support waiting")
    if fixed_type_counts is not None:
        if (
            set(fixed_type_counts) != set(types)
            or any(
                type(value) is not int or value < 0
                for value in fixed_type_counts.values()
            )
            or sum(fixed_type_counts.values()) != domain.fixed_k
        ):
            raise ValueError(
                "Fixed type counts must specify every catalog type, nonnegative integers, and sum to K"
            )
    model = cp_model.CpModel()
    timing = {t.switch_id: t for t in artifact.timings}
    ring = artifact.circulation_state_ids
    n = len(ring)
    by_cabin = defaultdict(list)
    by_key = {}
    for visit in artifact.switch_visits:
        by_cabin[visit.cabin_id].append(visit)
        by_key[visit.cabin_id, visit.visit_index] = visit
    for visits in by_cabin.values():
        visits.sort(key=lambda v: v.visit_index)
    end = grid.upper_tick(artifact.config.operational_end_seconds)

    def serves(p, i):
        t = timing[ring[i % n]]
        return _type_serves(
            p, station_id=t.station_id, visit_index=i, skip_allowed=t.skip_allowed
        )

    def route(p, i):
        t = timing[ring[i % n]]
        return grid.lower_tick(
            t.entry_to_platform_entry_seconds
            + t.min_platform_entry_to_platform_exit_seconds
            + t.platform_exit_to_exit_switch_seconds
            if serves(p, i)
            else t.skip_entry_to_exit_switch_seconds
        )

    def rope(i):
        return grid.lower_tick(timing[ring[i % n]].rope_to_next_switch_seconds)

    # Negative shifts cover the incoming rope of visit zero; positive shifts
    # cover the remaining spatial lap. Both alternating parities are retained.
    shift_min = -rope(-1) + 1
    offsets, shift_max = {}, {}
    visit_count = max(v.visit_index for v in artifact.switch_visits) + 1
    checkpoints = {c.id: c for c in artifact.headway_checkpoints}
    rules = [artifact.headway_rule_for_checkpoint(c) for c in checkpoints.values()]
    rules += [
        artifact.headway_rule_for_full_resource(r)
        for sid in ring
        if (r := artifact.initial_boundary_service_resource(sid)) is not None
    ]
    max_protection = max((grid.lower_tick(r.maximum_seconds) for r in rules), default=0)
    for p in types:
        values = {0: 0}
        for i in range(visit_count):
            values[i + 1] = values[i] + route(p, i) + rope(i)
        shift_max[p] = values[n - 1] + route(p, n - 1)
        i = -1
        while True:
            values[i] = values[i + 1] - route(p, i) - rope(i)
            if values[i + 1] - shift_min + max_protection < 0:
                break
            i -= 1
        offsets[p] = values

    active, station, initial_rope, previous_service = {}, {}, {}, {}
    route_active, switch, exits, waits, stops, cabin_type = {}, {}, {}, {}, {}, {}
    categories, type_indices = {}, {}
    intervals = defaultdict(list)
    interval_cache = {}
    raw_interval_count = 0
    fixed_types = {}
    if fixed_type_counts is not None and specialize_fixed_types:
        assigned = [p for p in types for _ in range(fixed_type_counts[p])]
        fixed_types = dict(zip(sorted(by_cabin), assigned, strict=True))
    zero = model.new_constant(0)
    resource_specs = defaultdict(set)
    for c in artifact.headway_candidates:
        resource_specs[checkpoints[c.checkpoint_id].switch_id].add(
            (c.checkpoint_id, c.time_reference, c.activation_reference)
        )

    for cabin, visits in by_cabin.items():
        cabin_types = (fixed_types[cabin],) if fixed_types else types
        active[cabin] = model.new_constant(1)
        if not fixed_types:
            for p in types:
                cabin_type[cabin, p] = model.new_bool_var(f"type[{cabin},{p}]")
            model.add_exactly_one(cabin_type[cabin, p] for p in types)
        shift = model.new_int_var(
            shift_min, max(shift_max[p] for p in cabin_types), f"shift[{cabin}]"
        )
        shift_bounds = {}

        def shift_bound(
            sign, bound, *, cache=shift_bounds, variable=shift, cabin_id=cabin
        ):
            key = (sign, bound)
            if key not in cache:
                cache[key] = _le(
                    model,
                    sign * variable,
                    bound,
                    f"shift_bound[{cabin_id},{sign},{bound}]",
                )
            return cache[key]

        if not fixed_types:
            for p in types:
                model.add(shift <= shift_max[p]).only_enforce_if(cabin_type[cabin, p])
        selected_station, selected_rope = [], []
        for v in visits:
            i, key = v.visit_index, (cabin, v.visit_index)
            if fixed_types:
                p = fixed_types[cabin]
                switch[key] = offsets[p][i] - shift
                exits[key] = offsets[p][i] + route(p, i) - shift
            else:
                switch[key] = model.new_int_var(
                    min(offsets[p][i] - shift_max[p] for p in types),
                    max(offsets[p][i] - shift_min for p in types),
                    f"switch[{cabin},{i}]",
                )
                exits[key] = model.new_int_var(
                    min(offsets[p][i] + route(p, i) - shift_max[p] for p in types),
                    max(offsets[p][i] + route(p, i) - shift_min for p in types),
                    f"exit[{cabin},{i}]",
                )
                model.add(
                    switch[key]
                    == sum(offsets[p][i] * cabin_type[cabin, p] for p in types) - shift
                )
                model.add(
                    exits[key]
                    == sum(
                        (offsets[p][i] + route(p, i)) * cabin_type[cabin, p]
                        for p in types
                    )
                    - shift
                )
            waits[key] = zero
            began = _le(model, switch[key], end, f"began[{cabin},{i}]")
            remains = _le(model, -exits[key], 0, f"remains[{cabin},{i}]")
            route_active[key] = _and(
                model, [began, remains], f"route_active[{cabin},{i}]"
            )
            if fixed_types:
                stops[key] = (
                    route_active[key] if serves(fixed_types[cabin], i) else zero
                )
            else:
                service_type = model.new_bool_var(f"service_type[{cabin},{i}]")
                model.add(
                    service_type
                    == sum(cabin_type[cabin, p] for p in types if serves(p, i))
                )
                stops[key] = _and(
                    model, [route_active[key], service_type], f"stop[{cabin},{i}]"
                )
            if i < n:
                station[key] = _and(
                    model,
                    [remains, _le(model, switch[key], 0, f"at_station[{cabin},{i}]")],
                    f"station[{cabin},{i}]",
                )
                initial_rope[key] = _and(
                    model,
                    [
                        _le(model, -switch[key], -1, f"rope_positive[{cabin},{i}]"),
                        _le(
                            model,
                            switch[key],
                            rope(i - 1) - 1,
                            f"rope_end[{cabin},{i}]",
                        ),
                    ],
                    f"rope[{cabin},{i}]",
                )
                selected_station.append(station[key])
                selected_rope.append(initial_rope[key])
        model.add(sum(selected_station + selected_rope) == 1)
        model.add(switch[cabin, visits[-1].visit_index] > end)
        categories[cabin] = sum(
            2 * i * selected_station[i] + (2 * i + 1) * selected_rope[i]
            for i in range(n)
        )
        if not fixed_types:
            type_indices[cabin] = sum(
                i * cabin_type[cabin, p] for i, p in enumerate(types)
            )

        for p in cabin_types:
            for i, entry in sorted(offsets[p].items()):
                t = timing[ring[i % n]]
                service = serves(p, i)
                behavior = (
                    HeadwayRouteBehavior.SERVICE
                    if service
                    else HeadwayRouteBehavior.BYPASS
                )
                times = {
                    EanTimeReference.ENTRY_TIME: entry,
                    EanTimeReference.EXIT_SWITCH_TIME: entry + route(p, i),
                    EanTimeReference.PLATFORM_ENTRY_TIME: entry
                    + grid.lower_tick(t.entry_to_platform_entry_seconds),
                    EanTimeReference.PLATFORM_EXIT_TIME: entry
                    + grid.lower_tick(
                        t.entry_to_platform_entry_seconds
                        + t.min_platform_entry_to_platform_exit_seconds
                    ),
                }
                resources = []
                for rid, reference, presence in sorted(
                    resource_specs[t.switch_id], key=lambda x: tuple(str(v) for v in x)
                ):
                    if presence is EanActivationReference.SERVE and not service:
                        continue
                    if presence is EanActivationReference.SKIP and service:
                        continue
                    rule = artifact.headway_rule_for_checkpoint(checkpoints[rid])
                    resources.append(
                        (
                            rid,
                            times[reference],
                            grid.lower_tick(rule.required_seconds(behavior, behavior)),
                            times[reference],
                        )
                    )
                full = artifact.initial_boundary_service_resource(t.switch_id)
                if full is not None and service:
                    rule = artifact.headway_rule_for_full_resource(full)
                    # Complete the protection of every begun station traversal,
                    # including one whose exit lies beyond the operation end.
                    resources.append(
                        (
                            f"initial_service::{t.switch_id}",
                            entry + route(p, i),
                            grid.lower_tick(rule.required_seconds(behavior, behavior)),
                            entry,
                        )
                    )
                for rid, offset, duration, activation_offset in resources:
                    lower = max(shift_min, activation_offset - end)
                    upper = min(shift_max[p], offset + duration - 1)
                    if lower > upper:
                        continue
                    raw_interval_count += 1
                    # Translate complete resource families, never their presence windows.
                    canonical, translated = rid, offset
                    if reduce_headways:
                        canonical, translated = canonical_resource(
                            rid,
                            offset,
                            t.switch_id,
                            checkpoints,
                            artifact,
                            grid,
                            timing,
                            ring,
                        )
                    cache_key = (
                        canonical,
                        cabin,
                        p,
                        translated,
                        duration,
                        lower,
                        upper,
                    )
                    if cache_key in interval_cache:
                        intervals[rid].append(interval_cache[cache_key])
                        continue
                    literals = [] if fixed_types else [cabin_type[cabin, p]]
                    if lower > shift_min:
                        literals.append(shift_bound(-1, -lower))
                    if upper < shift_max[p]:
                        literals.append(shift_bound(1, upper))
                    presence = (
                        model.new_constant(1)
                        if not literals
                        else literals[0]
                        if len(literals) == 1
                        else _and(model, literals, f"resource[{cabin},{p},{i},{rid}]")
                    )
                    interval = model.new_optional_fixed_size_interval_var(
                        translated - shift,
                        duration,
                        presence,
                        f"interval[{cabin},{p},{i},{rid}]",
                    )
                    interval_cache[cache_key] = interval
                    intervals[rid].append(interval)

    if fixed_type_counts is not None and not fixed_types:
        for p, count in fixed_type_counts.items():
            model.add(sum(cabin_type[c, p] for c in active) == count)

    for a, b in pairwise(sorted(active)):
        if fixed_types:
            if fixed_types[a] == fixed_types[b]:
                model.add(categories[a] <= categories[b])
        else:
            model.add(type_indices[a] <= type_indices[b])
            for p in types:
                model.add(categories[a] <= categories[b]).only_enforce_if(
                    [cabin_type[a, p], cabin_type[b, p]]
                )
    seen_groups = set()
    for items in intervals.values():
        signature = frozenset(item.index for item in items)
        if signature not in seen_groups:
            model.add_no_overlap(items)
            seen_groups.add(signature)
    movement = OipCpSatMovementVariables(
        active,
        station,
        initial_rope,
        previous_service,
        route_active,
        switch,
        exits,
        waits,
        stops,
        cabin_type,
        types,
        fixed_types or None,
    )
    candidates = (passenger_builder or oip_passenger_candidate_builder()).build(
        domain.scenario, artifact
    )
    candidate_count = len(candidates.ride_candidates)
    if fixed_types:
        candidates = replace(
            candidates,
            ride_candidates=tuple(
                r
                for r in candidates.ride_candidates
                if serves(fixed_types[r.cabin_id], r.board_visit_index)
                and serves(fixed_types[r.cabin_id], r.alight_visit_index)
            ),
        )
    builders = {
        "od_inventory": _build_inventory_passengers,
        "groups": _build_group_passengers,
    }
    if passenger_encoding not in builders:
        raise ValueError("unknown OIP CP-SAT passenger encoding")
    passengers = builders[passenger_encoding](
        domain, model, movement, candidates, by_key, timing, objective="served"
    )
    model.minimize(passengers.unserved_total)
    return BuiltOipCpSatModel(
        domain,
        model,
        movement,
        passengers,
        candidates,
        perf_counter() - started,
        len(interval_cache),
        "nowait_templates",
        "served",
        {
            "fixed_type_specialization": bool(fixed_types),
            "headway_reduction": reduce_headways,
            "mechanical_resource_families": sum(
                c.kind.value == "service_mechanism" for c in checkpoints.values()
            ),
            "headway_contract": (domain.scenario.experiment_metadata or {}).get(
                "headway_contract"
            ),
            "raw_resource_intervals": raw_interval_count,
            "resource_intervals": len(interval_cache),
            "shared_intervals": raw_interval_count - len(interval_cache),
            "resource_families": len(intervals),
            "no_overlap_constraints": len(seen_groups),
            "passenger_candidates_before": candidate_count,
            "passenger_candidates_after": len(candidates.ride_candidates),
        },
    )


def canonical_resource(
    rid, offset, switch_id, checkpoints, artifact, grid, timing, ring
):
    """Share only translated intervals with identical duration and shift-presence.

    Original NoOverlap families survive: boundary-only occurrences cannot acquire
    conflicts with occurrences from the other family through an unsafe union.
    """
    if rid not in checkpoints:
        return rid, offset
    checkpoint = checkpoints[rid]
    kind = checkpoint.kind.value
    if kind == "platform_exit":
        target_kind, target_switch = "platform_entry", switch_id
        t = timing[switch_id]
        delta = -(
            grid.lower_tick(
                t.entry_to_platform_entry_seconds
                + t.min_platform_entry_to_platform_exit_seconds
            )
            - grid.lower_tick(t.entry_to_platform_entry_seconds)
        )
    elif kind == "exit_switch":
        target_kind = "entry_switch"
        target_switch = ring[(ring.index(switch_id) + 1) % len(ring)]
        delta = grid.lower_tick(timing[switch_id].rope_to_next_switch_seconds)
    else:
        return rid, offset
    target = next(
        (
            c
            for c in checkpoints.values()
            if c.switch_id == target_switch and c.kind.value == target_kind
        ),
        None,
    )
    if target is None:
        return rid, offset
    first, second = (
        artifact.headway_rule_for_checkpoint(c) for c in (checkpoint, target)
    )
    # Strict equal constant rules; historical STOP-dependent rules are untouched.
    from ropeway_skip_stop_optimization.models import ConstantHeadwayRule

    if not isinstance(first, ConstantHeadwayRule) or not isinstance(
        second, ConstantHeadwayRule
    ):
        return rid, offset
    if grid.lower_tick(first.seconds) != grid.lower_tick(second.seconds):
        return rid, offset
    return target.id, offset + delta
