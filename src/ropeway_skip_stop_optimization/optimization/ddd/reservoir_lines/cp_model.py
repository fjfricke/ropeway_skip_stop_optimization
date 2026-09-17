from __future__ import annotations

from ..reservoir_boundary import state_protection_tick, state_resource_id

from dataclasses import dataclass
import os
import tempfile

from ortools.sat.python import cp_model

from ..cp_sat_certificate import stable_fingerprint
from ..reservoir_cp_sat_problem import DddReservoirCpSatProblem
from .config import ReservoirLineConfig, ReservoirLineFormulation
from .passenger_model import (
    BuiltLinePassengers,
    build_line_passengers,
    build_shared_line_passengers,
)
from .preparation import PreparedLineProblem, _pair_domain


def _serialized_model_bytes(model: cp_model.CpModel) -> int:
    handle = tempfile.NamedTemporaryFile(suffix=".bin", delete=False)
    path = handle.name
    handle.close()
    try:
        if not model.export_to_file(path):
            raise RuntimeError("OR-Tools failed to export line model")
        return os.path.getsize(path)
    finally:
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass


@dataclass(frozen=True)
class BuiltReservoirLineModel:
    model: cp_model.CpModel
    used: tuple[cp_model.IntVar, ...]
    dispatch: tuple[cp_model.IntVar, ...]
    dispatch_index: tuple[cp_model.IntVar, ...]
    selection: dict[tuple[int, str], cp_model.IntVar]
    round_active: dict[tuple[int, str, int], cp_model.IntVar]
    service_class_selection: dict[tuple[int, str], cp_model.IntVar]
    passengers: BuiltLinePassengers
    stats: dict
    fingerprint: str


def build_reservoir_line_model(
    problem: DddReservoirCpSatProblem,
    prepared: PreparedLineProblem,
    config: ReservoirLineConfig,
    *,
    service_classes=None,
) -> BuiltReservoirLineModel:
    problem.validate()
    config.validate(problem.available_fleet_count)
    if prepared.problem_fingerprint != problem.fingerprint:
        raise ValueError("prepared line problem has a different physical domain")
    model = cp_model.CpModel()
    limit = prepared.maximum_cabins
    end, step = prepared.dispatch_window_end_tick, prepared.dispatch_step_tick
    max_index = end // step
    used = tuple(model.new_bool_var(f"used::{k}") for k in range(limit))
    dispatch = tuple(model.new_int_var(0, end, f"dispatch::{k}") for k in range(limit))
    dispatch_index = tuple(
        model.new_int_var(0, max_index, f"dispatch_index::{k}") for k in range(limit)
    )
    templates = prepared.templates
    fixed_pattern_counts = dict(config.fixed_pattern_counts)
    active_pattern_ids = set(fixed_pattern_counts)
    specialize = (
        config.fixed_cabins == limit
        and len(config.fixed_pattern_sequence) == limit
    )
    templates_by_slot = tuple(
        tuple(
            t for t in templates
            if (not active_pattern_ids or t.pattern_id in active_pattern_ids)
            and (not specialize or t.pattern_id == config.fixed_pattern_sequence[k])
        )
        for k in range(limit)
    )
    if any(not values for values in templates_by_slot):
        raise ValueError("fixed pattern sequence contains a pattern without a line template")
    selection = {
        (k, template.id): model.new_bool_var(f"line::{k}::{template.id}")
        for k in range(limit)
        for template in templates_by_slot[k]
    }
    round_active: dict[tuple[int, str, int], cp_model.IntVar] = {}
    service_class_selection: dict[tuple[int, str], cp_model.IntVar] = {}
    potential_pair_rows = (
        sum(
            len(templates_by_slot[a]) * len(templates_by_slot[b])
            for a in range(limit) for b in range(a + 1, limit)
        )
    )
    if config.variant.value == "dispatch_domains" and potential_pair_rows > 2_000_000:
        raise ValueError(
            "dispatch-domain encoding would inspect more than two million "
            "slot/template pairs; use the exact intervals encoding"
        )
    for k in range(limit):
        model.add(sum(selection[k, t.id] for t in templates_by_slot[k]) == used[k])
        model.add(dispatch[k] == step * dispatch_index[k])
        model.add(dispatch[k] == 0).only_enforce_if(used[k].Not())
        for template in templates_by_slot[k]:
            choose = selection[k, template.id]
            model.add(dispatch[k] >= template.minimum_dispatch_tick).only_enforce_if(choose)
            model.add(dispatch[k] <= template.maximum_dispatch_tick).only_enforce_if(choose)
        if k:
            model.add(used[k] <= used[k - 1])
            model.add(dispatch[k] >= dispatch[k - 1] + step).only_enforce_if(used[k])
    if config.fixed_cabins is not None:
        for k in range(limit):
            model.add(used[k] == int(k < config.fixed_cabins))
    for k, pattern_id in enumerate(config.fixed_pattern_sequence):
        matching = [
            selection[k, template.id]
            for template in templates_by_slot[k]
            if template.pattern_id == pattern_id
        ]
        if not matching:
            raise ValueError(f"fixed line pattern {pattern_id!r} is absent from catalog")
        model.add(sum(matching) == 1)

    for pattern_id, count in config.fixed_pattern_counts:
        matching = [
            selection[k, template.id]
            for k in range(limit)
            for template in templates_by_slot[k]
            if template.pattern_id == pattern_id
        ]
        if not matching:
            raise ValueError(f"fixed line pattern {pattern_id!r} is absent from catalog")
        model.add(sum(matching) == count)

    if config.fixed_service_class_counts:
        if service_classes is None:
            raise ValueError(
                "fixed service classes require prepared service-class domains"
            )
        classes_by_id = service_classes.classes_by_id
        requested = dict(config.fixed_service_class_counts)
        missing = sorted(set(requested) - set(classes_by_id))
        if missing:
            raise ValueError(f"unknown fixed service class {missing[0]!r}")
        active_classes = tuple(classes_by_id[class_id] for class_id in requested)
        for k in range(limit):
            values = []
            for item in active_classes:
                chosen = model.new_bool_var(f"service_class::{k}::{item.id}")
                service_class_selection[k, item.id] = chosen
                values.append(chosen)
                model.add(dispatch[k] >= item.minimum_dispatch_tick).only_enforce_if(chosen)
                model.add(dispatch[k] <= item.maximum_dispatch_tick).only_enforce_if(chosen)
            model.add(sum(values) == used[k])
            for template in templates_by_slot[k]:
                model.add(
                    selection[k, template.id]
                    == sum(
                        service_class_selection[k, item.id]
                        for item in active_classes
                        if item.template_id == template.id
                    )
                )
        for class_id, count in requested.items():
            model.add(
                sum(service_class_selection[k, class_id] for k in range(limit))
                == count
            )

    # Passenger prefixes are independent of the resource encoding.  The lazy
    # dispatch-domain specialization needs the same round-activity literals as
    # the native-interval encoding.
    if config.formulation is not ReservoirLineFormulation.LEGACY_TEMPLATES:
        for k in range(limit):
            by_pattern: dict[str, list] = {}
            for template in templates_by_slot[k]:
                by_pattern.setdefault(template.pattern_id, []).append(template)
            for pattern_id, values in by_pattern.items():
                for lap in range(1, max(item.laps for item in values) + 1):
                    active = model.new_bool_var(f"round_active::{k}::{pattern_id}::{lap}")
                    model.add(
                        active
                        == sum(
                            selection[k, item.id]
                            for item in values
                            if item.laps >= lap
                        )
                    )
                    round_active[k, pattern_id, lap] = active

    pair_constraints = pair_exclusions = native_resource_intervals = 0
    if config.variant.value == "dispatch_domains":
        pair_domains = prepared.pair_domains_by_id
        lazy_pair_domains = {}
        def domain_for(first, second):
            key = (first.id, second.id)
            item = pair_domains.get(key) or lazy_pair_domains.get(key)
            if item is None:
                item = _pair_domain(first, second, end, problem)
                lazy_pair_domains[key] = item
            return item.allowed_delta
        for first_slot in range(limit):
            for second_slot in range(first_slot + 1, limit):
                delta = dispatch[second_slot] - dispatch[first_slot]
                for first in templates_by_slot[first_slot]:
                    for second in templates_by_slot[second_slot]:
                        domain = domain_for(first, second)
                        literals = [
                            selection[first_slot, first.id],
                            selection[second_slot, second.id],
                        ]
                        if not domain:
                            model.add_bool_or([literal.Not() for literal in literals])
                            pair_exclusions += 1
                        elif not (
                            len(domain) == 1
                            and domain[0].lower <= 1
                            and domain[0].upper >= end
                        ):
                            model.add_linear_expression_in_domain(
                                delta,
                                cp_model.Domain.from_intervals(
                                    [[item.lower, item.upper] for item in domain]
                                ),
                            ).only_enforce_if(literals)
                            pair_constraints += 1
    elif config.formulation is ReservoirLineFormulation.LEGACY_TEMPLATES:
        # Exact alternate encoding. Every protected interval has fixed length and
        # an affine start d_k + offset. Separate NoOverlap constraints preserve
        # resource-specific overtaking; state events are one-tick synthetic uses.
        by_resource: dict[str, list] = {}
        for k in range(limit):
            for template in templates_by_slot[k]:
                present = selection[k, template.id]
                for index, item in enumerate(template.resource_intervals):
                    interval = model.new_optional_fixed_size_interval_var(
                        dispatch[k] + item.start_tick,
                        item.end_tick - item.start_tick,
                        present,
                        f"resource::{item.resource_id}::{k}::{template.id}::{index}",
                    )
                    by_resource.setdefault(item.resource_id, []).append(interval)
                    native_resource_intervals += 1
                for index, (state_id, offset) in enumerate(
                    template.state_event_offsets
                ):
                    interval = model.new_optional_fixed_size_interval_var(
                        dispatch[k] + offset,
                        state_protection_tick(problem, state_id),
                        present,
                        f"state::{state_id}::{k}::{template.id}::{index}",
                    )
                    by_resource.setdefault(state_resource_id(problem, state_id), []).append(interval)
                    native_resource_intervals += 1
        for intervals in by_resource.values():
            model.add_no_overlap(intervals)

    else:
        # Preparation partitions dispatch times by the uniquely implied final
        # round. Repeated occurrences are represented once per pattern prefix;
        # the solver cannot end a deployment before the service deadline.
        by_resource: dict[str, list] = {}
        cycle_size = len(problem.cycle_states)
        for k in range(limit):
            by_pattern: dict[str, list] = {}
            for template in templates_by_slot[k]:
                by_pattern.setdefault(template.pattern_id, []).append(template)
            for pattern_id, values in by_pattern.items():
                longest = max(values, key=lambda item: item.laps)
                for index, item in enumerate(longest.resource_intervals):
                    lap = item.visit_index // cycle_size + 1
                    present = round_active[k, pattern_id, lap]
                    interval = model.new_optional_fixed_size_interval_var(
                        dispatch[k] + item.start_tick,
                        item.end_tick - item.start_tick,
                        present,
                        f"resource_prefix::{item.resource_id}::{k}::{pattern_id}::{index}",
                    )
                    by_resource.setdefault(item.resource_id, []).append(interval)
                    native_resource_intervals += 1
                for index, (state_id, offset) in enumerate(longest.state_event_offsets):
                    # A lap boundary is also the terminal return event when that
                    # lap is the selected final one, hence it belongs to the
                    # preceding active prefix.
                    lap = max(1, (index + cycle_size - 1) // cycle_size)
                    present = round_active[k, pattern_id, lap]
                    interval = model.new_optional_fixed_size_interval_var(
                        dispatch[k] + offset,
                        state_protection_tick(problem, state_id),
                        present,
                        f"state_prefix::{state_id}::{k}::{pattern_id}::{index}",
                    )
                    by_resource.setdefault(state_resource_id(problem, state_id), []).append(interval)
                    native_resource_intervals += 1
        for intervals in by_resource.values():
            model.add_no_overlap(intervals)

    if config.formulation is ReservoirLineFormulation.LEGACY_TEMPLATES:
        passengers = build_line_passengers(
            problem,
            model,
            templates,
            selection,
            dispatch,
            config.mode,
            service_start_tick=prepared.service_start_tick,
            templates_by_cabin=templates_by_slot,
        )
    else:
        passengers = build_shared_line_passengers(
            problem,
            model,
            templates,
            round_active,
            dispatch,
            config.mode,
            service_start_tick=prepared.service_start_tick,
            share_across_patterns=(
                config.formulation is ReservoirLineFormulation.SHARED_RIDES
            ),
            templates_by_cabin=templates_by_slot,
        )
    objective_scale = 1
    if config.mode.value != "feasibility":
        # Lexicographic in one exact integer expression: one additional served
        # passenger dominates every possible fleet-size difference.
        objective_scale = limit + 1
        model.maximize(
            objective_scale * passengers.served_expression - sum(used)
        )
    error = model.validate()
    if error:
        raise ValueError(f"invalid reservoir line CP-SAT model: {error}")
    stats = {
        **prepared.stats,
        **passengers.stats,
        "used_variables": len(used),
        "dispatch_variables": len(dispatch),
        "line_selection_variables": len(selection),
        "fixed_pattern_specialization": specialize,
        "fixed_pattern_count_classes": len(config.fixed_pattern_counts),
        "round_active_variables": len(round_active),
        "service_class_selection_variables": len(service_class_selection),
        "pair_domain_constraints": pair_constraints,
        "pair_exclusions": pair_exclusions,
        "lazy_template_pair_domains": len(lazy_pair_domains) if config.variant.value == "dispatch_domains" else 0,
        "native_resource_intervals": native_resource_intervals,
        "resource_encoding": config.variant.value,
        "line_formulation": config.formulation.value,
        "potential_template_pair_rows": potential_pair_rows,
        "variables": len(model.proto.variables),
        "constraints": len(model.proto.constraints),
        "objective_served_scale": objective_scale,
        "serialized_model_bytes": _serialized_model_bytes(model),
    }
    return BuiltReservoirLineModel(
        model,
        used,
        dispatch,
        dispatch_index,
        selection,
        round_active,
        service_class_selection,
        passengers,
        stats,
        stable_fingerprint(
            {
                "version": "reservoir_line_cp_sat_v4_free_phase",
                "prepared": prepared.model_fingerprint,
                "variant": config.variant.value,
                "preparation": config.preparation.value,
                "formulation": config.formulation.value,
                "mode": config.mode.value,
                "fixed_cabins": config.fixed_cabins,
                "fixed_pattern_sequence": config.fixed_pattern_sequence,
                "fixed_service_class_counts": config.fixed_service_class_counts,
                "service_classes": (
                    None if service_classes is None else service_classes.model_fingerprint
                ),
                "builder_contract": "free_phase_dispatch_then_continuous_service_v1",
            }
        ),
    )
