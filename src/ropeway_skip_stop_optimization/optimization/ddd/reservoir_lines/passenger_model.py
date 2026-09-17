from __future__ import annotations

from dataclasses import dataclass

from ortools.sat.python import cp_model

from ..reservoir_cp_sat_problem import DddReservoirCpSatProblem
from ..time_ticks import ddd_seconds_to_tick
from .config import ReservoirLineMode
from .preparation import LineTemplate


@dataclass(frozen=True)
class LineRideSupport:
    cabin_id: int
    template_id: str | None
    pattern_id: str
    minimum_laps: int
    ride_id: str
    demand_group_id: str
    board_visit_index: int
    alight_visit_index: int
    departure_offset_tick: int
    arrival_offset_tick: int


@dataclass(frozen=True)
class BuiltLinePassengers:
    ride_count: dict[tuple[int, str, str], cp_model.IntVar]
    positive: dict[tuple[int, str, str], cp_model.IntVar]
    supports: dict[tuple[int, str, str], LineRideSupport]
    served_expression: cp_model.LinearExpr
    stats: dict


def build_line_passengers(
    problem: DddReservoirCpSatProblem,
    model: cp_model.CpModel,
    templates: tuple[LineTemplate, ...],
    selections: dict[tuple[int, str], cp_model.IntVar],
    dispatches: tuple[cp_model.IntVar, ...],
    mode: ReservoirLineMode,
    *,
    service_start_tick: int,
    templates_by_cabin=None,
) -> BuiltLinePassengers:
    if mode is ReservoirLineMode.FEASIBILITY:
        return BuiltLinePassengers({}, {}, {}, 0, {
            "integer_ride_variables": 0,
            "positive_literals": 0,
            "temporal_link_constraints": 0,
            "capacity_constraints": 0,
        })
    groups = {group.id: group for group in problem.demand_groups}
    candidates_by_cabin: dict[int, list] = {}
    for candidate in problem.passenger_build.ride_candidates:
        candidates_by_cabin.setdefault(candidate.cabin_id, []).append(candidate)

    ride_count, positive, supports = {}, {}, {}
    temporal_links = 0
    capacity_terms: dict[tuple[int, str, int], list[cp_model.IntVar]] = {}
    demand_terms: dict[str, list[cp_model.IntVar]] = {
        group.id: [] for group in problem.demand_groups
    }
    horizon = problem.resolved_core.passenger_service_end_tick
    for cabin_id in range(len(dispatches)):
        for template in (templates if templates_by_cabin is None else templates_by_cabin[cabin_id]):
            selected = selections[cabin_id, template.id]
            visits = template.visits
            for candidate in candidates_by_cabin.get(cabin_id, ()):
                if candidate.alight_visit_index >= len(visits):
                    continue
                board = visits[candidate.board_visit_index]
                alight = visits[candidate.alight_visit_index]
                if board.platform_exit_tick is None or alight.platform_entry_tick is None:
                    continue
                group = groups[candidate.demand_group_id]
                release = max(
                    service_start_tick,
                    ddd_seconds_to_tick(group.release_time_seconds),
                )
                departure_offset = board.platform_exit_tick
                arrival_offset = alight.platform_entry_tick
                if mode is ReservoirLineMode.EXACT_SERVICE:
                    feasible_lower = max(
                        template.minimum_dispatch_tick, release - departure_offset
                    )
                    feasible_upper = min(
                        template.maximum_dispatch_tick,
                        horizon - departure_offset,
                        horizon - arrival_offset,
                    )
                    if feasible_lower > feasible_upper:
                        continue
                upper = min(problem.cabin_capacity, group.count)
                if upper <= 0:
                    continue
                key = cabin_id, template.id, candidate.id
                q = model.new_int_var(0, upper, f"q::{cabin_id}::{template.id}::{candidate.id}")
                pos = model.new_bool_var(f"q_pos::{cabin_id}::{template.id}::{candidate.id}")
                model.add(q <= upper * selected)
                model.add(q <= upper * pos)
                model.add(q >= pos)
                if mode is ReservoirLineMode.EXACT_SERVICE:
                    model.add(dispatches[cabin_id] + departure_offset >= release).only_enforce_if(pos)
                    model.add(dispatches[cabin_id] + departure_offset <= horizon).only_enforce_if(pos)
                    model.add(dispatches[cabin_id] + arrival_offset <= horizon).only_enforce_if(pos)
                    temporal_links += 3
                ride_count[key], positive[key] = q, pos
                supports[key] = LineRideSupport(
                    cabin_id,
                    template.id,
                    template.pattern_id,
                    template.laps,
                    candidate.id,
                    candidate.demand_group_id,
                    candidate.board_visit_index,
                    candidate.alight_visit_index,
                    departure_offset,
                    arrival_offset,
                )
                demand_terms[group.id].append(q)
                for segment in range(
                    candidate.board_visit_index, candidate.alight_visit_index
                ):
                    capacity_terms.setdefault(
                        (cabin_id, template.id, segment), []
                    ).append(q)

    for group_id, terms in demand_terms.items():
        model.add(sum(terms) <= groups[group_id].count)
    for (cabin_id, template_id, _), terms in capacity_terms.items():
        model.add(
            sum(terms)
            <= problem.cabin_capacity * selections[cabin_id, template_id]
        )
    served = sum(ride_count.values())
    model.maximize(served)
    return BuiltLinePassengers(
        ride_count,
        positive,
        supports,
        served,
        {
            "integer_ride_variables": len(ride_count),
            "positive_literals": len(positive),
            "temporal_link_constraints": temporal_links,
            "capacity_constraints": len(capacity_terms),
            "demand_constraints": len(demand_terms),
        },
    )


def build_shared_line_passengers(
    problem: DddReservoirCpSatProblem,
    model: cp_model.CpModel,
    templates: tuple[LineTemplate, ...],
    round_active: dict[tuple[int, str, int], cp_model.IntVar],
    dispatches: tuple[cp_model.IntVar, ...],
    mode: ReservoirLineMode,
    *,
    service_start_tick: int,
    share_across_patterns: bool,
    templates_by_cabin=None,
) -> BuiltLinePassengers:
    """Build ride quantities once per round prefix, optionally across patterns."""
    if mode is ReservoirLineMode.FEASIBILITY:
        return BuiltLinePassengers({}, {}, {}, 0, {
            "integer_ride_variables": 0,
            "positive_literals": 0,
            "temporal_link_constraints": 0,
            "capacity_constraints": 0,
            "passenger_sharing": "patterns" if share_across_patterns else "rounds",
        })

    groups = {group.id: group for group in problem.demand_groups}
    cycle_size = len(problem.cycle_states)
    horizon = problem.resolved_core.passenger_service_end_tick
    templates_by_pattern: dict[str, list[LineTemplate]] = {}
    for template in templates:
        templates_by_pattern.setdefault(template.pattern_id, []).append(template)
    candidates_by_cabin: dict[int, list] = {}
    for candidate in problem.passenger_build.ride_candidates:
        candidates_by_cabin.setdefault(candidate.cabin_id, []).append(candidate)

    ride_count: dict[tuple, cp_model.IntVar] = {}
    positive: dict[tuple, cp_model.IntVar] = {}
    supports: dict[tuple, LineRideSupport] = {}
    demand_terms: dict[str, list[cp_model.IntVar]] = {
        group.id: [] for group in problem.demand_groups
    }
    capacity_terms: dict[tuple[int, int], list[cp_model.IntVar]] = {}
    temporal_links = 0

    for cabin_id, dispatch in enumerate(dispatches):
        local_templates = templates if templates_by_cabin is None else templates_by_cabin[cabin_id]
        local_by_pattern: dict[str, list[LineTemplate]] = {}
        for template in local_templates:
            local_by_pattern.setdefault(template.pattern_id, []).append(template)
        longest = {
            pattern: max(values, key=lambda item: item.laps)
            for pattern, values in local_by_pattern.items()
        }
        for candidate in candidates_by_cabin.get(cabin_id, ()):
            group = groups[candidate.demand_group_id]
            release = max(
                service_start_tick,
                ddd_seconds_to_tick(group.release_time_seconds),
            )
            required_laps = candidate.alight_visit_index // cycle_size + 1
            compatible: list[tuple[str, LineTemplate, cp_model.IntVar, int, int]] = []
            for pattern_id, template in longest.items():
                if candidate.alight_visit_index >= len(template.visits):
                    continue
                board = template.visits[candidate.board_visit_index]
                alight = template.visits[candidate.alight_visit_index]
                if board.platform_exit_tick is None or alight.platform_entry_tick is None:
                    continue
                active = round_active.get((cabin_id, pattern_id, required_laps))
                if active is None:
                    continue
                departure_offset = board.platform_exit_tick
                arrival_offset = alight.platform_entry_tick
                possible = any(
                    t.laps >= required_laps
                    and max(t.minimum_dispatch_tick, release - departure_offset)
                    <= min(
                        t.maximum_dispatch_tick,
                        horizon - departure_offset,
                        horizon - arrival_offset,
                    )
                    for t in local_by_pattern[pattern_id]
                )
                if possible or mode is ReservoirLineMode.OPTIMISTIC_SERVICE:
                    compatible.append(
                        (pattern_id, template, active, departure_offset, arrival_offset)
                    )
            if not compatible:
                continue

            pattern_groups = [compatible] if share_across_patterns else [
                [item] for item in compatible
            ]
            for items in pattern_groups:
                suffix = "shared" if share_across_patterns else items[0][0]
                key = (cabin_id, suffix, candidate.id)
                upper = min(problem.cabin_capacity, group.count)
                q = model.new_int_var(0, upper, f"q::{cabin_id}::{suffix}::{candidate.id}")
                pos = model.new_bool_var(f"q_pos::{cabin_id}::{suffix}::{candidate.id}")
                model.add(q <= upper * sum(item[2] for item in items))
                model.add(q <= upper * pos)
                model.add(q >= pos)
                if mode is ReservoirLineMode.EXACT_SERVICE:
                    for _, _, active, departure_offset, arrival_offset in items:
                        model.add(dispatch + departure_offset >= release).only_enforce_if(
                            [pos, active]
                        )
                        model.add(dispatch + departure_offset <= horizon).only_enforce_if(
                            [pos, active]
                        )
                        model.add(dispatch + arrival_offset <= horizon).only_enforce_if(
                            [pos, active]
                        )
                        temporal_links += 3
                first_pattern, _, _, departure_offset, arrival_offset = items[0]
                ride_count[key], positive[key] = q, pos
                supports[key] = LineRideSupport(
                    cabin_id,
                    None,
                    "*" if share_across_patterns else first_pattern,
                    required_laps,
                    candidate.id,
                    candidate.demand_group_id,
                    candidate.board_visit_index,
                    candidate.alight_visit_index,
                    departure_offset,
                    arrival_offset,
                )
                demand_terms[group.id].append(q)
                for segment in range(
                    candidate.board_visit_index, candidate.alight_visit_index
                ):
                    capacity_terms.setdefault((cabin_id, segment), []).append(q)

    for group_id, terms in demand_terms.items():
        model.add(sum(terms) <= groups[group_id].count)
    for (cabin_id, segment), terms in capacity_terms.items():
        required_laps = segment // cycle_size + 1
        active_options = [
            variable
            for (k, _, lap), variable in round_active.items()
            if k == cabin_id and lap == required_laps
        ]
        model.add(sum(terms) <= problem.cabin_capacity * sum(active_options))

    return BuiltLinePassengers(
        ride_count,
        positive,
        supports,
        sum(ride_count.values()),
        {
            "integer_ride_variables": len(ride_count),
            "positive_literals": len(positive),
            "temporal_link_constraints": temporal_links,
            "capacity_constraints": len(capacity_terms),
            "demand_constraints": len(demand_terms),
            "passenger_sharing": "patterns" if share_across_patterns else "rounds",
        },
    )
