from __future__ import annotations

from dataclasses import dataclass
import os
import tempfile

from ortools.sat.python import cp_model

from ..cp_sat_certificate import stable_fingerprint
from ..reservoir_cp_sat_problem import DddReservoirCpSatProblem
from .config import ReservoirLineConfig
from .passenger_model import BuiltLinePassengers, build_line_passengers
from .preparation import PreparedLineProblem


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
    passengers: BuiltLinePassengers
    stats: dict
    fingerprint: str


def build_reservoir_line_model(
    problem: DddReservoirCpSatProblem,
    prepared: PreparedLineProblem,
    config: ReservoirLineConfig,
) -> BuiltReservoirLineModel:
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
    selection = {
        (k, template.id): model.new_bool_var(f"line::{k}::{template.id}")
        for k in range(limit)
        for template in templates
    }
    potential_pair_rows = (
        limit * (limit - 1) // 2 * len(templates) * len(templates)
    )
    if config.variant.value == "dispatch_domains" and potential_pair_rows > 2_000_000:
        raise ValueError(
            "dispatch-domain encoding would inspect more than two million "
            "slot/template pairs; use the exact intervals encoding"
        )
    for k in range(limit):
        model.add(sum(selection[k, t.id] for t in templates) == used[k])
        model.add(dispatch[k] == step * dispatch_index[k])
        model.add(dispatch[k] == 0).only_enforce_if(used[k].Not())
        for template in templates:
            choose = selection[k, template.id]
            model.add(dispatch[k] >= template.minimum_dispatch_tick).only_enforce_if(choose)
            model.add(dispatch[k] <= template.maximum_dispatch_tick).only_enforce_if(choose)
        if k:
            model.add(used[k] <= used[k - 1])
            model.add(dispatch[k] >= dispatch[k - 1] + step).only_enforce_if(used[k])
    model.add(dispatch[0] == 0)

    if config.fixed_cabins is not None:
        for k in range(limit):
            model.add(used[k] == int(k < config.fixed_cabins))
    for k, pattern_id in enumerate(config.fixed_pattern_sequence):
        matching = [
            selection[k, template.id]
            for template in templates
            if template.pattern_id == pattern_id
        ]
        if not matching:
            raise ValueError(f"fixed line pattern {pattern_id!r} is absent from catalog")
        model.add(sum(matching) == 1)

    pair_constraints = pair_exclusions = native_resource_intervals = 0
    if config.variant.value == "dispatch_domains":
        pair_domains = prepared.pair_domains_by_id
        for first_slot in range(limit):
            for second_slot in range(first_slot + 1, limit):
                delta = dispatch[second_slot] - dispatch[first_slot]
                for first in templates:
                    for second in templates:
                        domain = pair_domains[first.id, second.id].allowed_delta
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
    else:
        # Exact alternate encoding. Every protected interval has fixed length and
        # an affine start d_k + offset. Separate NoOverlap constraints preserve
        # resource-specific overtaking; state events are one-tick synthetic uses.
        by_resource: dict[str, list] = {}
        for k in range(limit):
            for template in templates:
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
                        1,
                        present,
                        f"state::{state_id}::{k}::{template.id}::{index}",
                    )
                    by_resource.setdefault(f"__state__::{state_id}", []).append(interval)
                    native_resource_intervals += 1
        for intervals in by_resource.values():
            model.add_no_overlap(intervals)

    passengers = build_line_passengers(
        problem, model, templates, selection, dispatch, config.mode
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
        "pair_domain_constraints": pair_constraints,
        "pair_exclusions": pair_exclusions,
        "native_resource_intervals": native_resource_intervals,
        "resource_encoding": config.variant.value,
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
        passengers,
        stats,
        stable_fingerprint(
            {
                "version": "reservoir_line_cp_sat_v1",
                "prepared": prepared.model_fingerprint,
                "variant": config.variant.value,
                "mode": config.mode.value,
                "fixed_cabins": config.fixed_cabins,
                "fixed_pattern_sequence": config.fixed_pattern_sequence,
                "builder_contract": "ordered_dispatch_exact_resources_integer_rides_v1",
            }
        ),
    )
