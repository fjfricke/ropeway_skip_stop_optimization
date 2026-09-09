from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from enum import StrEnum
from time import perf_counter

from ortools.sat.python import cp_model

from .cp_sat_movement import DddCpSatMovementModel
from .fixed_k import DddFixedKTrajectoryProblem
from .route_topology import unique_stop_route_option
from .time_ticks import ddd_seconds_to_tick


class DddCpSatCostEncoding(StrEnum):
    PRODUCT = "product"
    UNARY = "unary"


@dataclass(frozen=True)
class DddCpSatPassengerModel:
    ride_count: dict[str, cp_model.IntVar]
    used: dict[str, cp_model.IntVar]
    unserved: dict[str, cp_model.IntVar]
    alight_count: dict[tuple[int, int], cp_model.IntVar]
    alight_time: dict[tuple[int, int], cp_model.IntVar]
    products: dict[tuple[int, int], cp_model.IntVar]
    unary: dict[tuple[int, int, int], tuple[cp_model.IntVar, cp_model.IntVar]]
    objective_constant_tick: int
    objective_expression: cp_model.LinearExpr
    capacity_row_count: int
    cost_encoding: DddCpSatCostEncoding

    def add_hints(
        self,
        problem: DddFixedKTrajectoryProblem,
        model: cp_model.CpModel,
        counts: dict[str, int],
        times: dict[tuple[int, int], int],
    ) -> None:
        served: dict[str, int] = defaultdict(int)
        alight: dict[tuple[int, int], int] = defaultdict(int)
        for candidate in problem.passenger_build.ride_candidates:
            count = counts.get(candidate.id, 0)
            model.add_hint(self.ride_count[candidate.id], count)
            model.add_hint(self.used[candidate.id], int(count > 0))
            served[candidate.demand_group_id] += count
            alight[candidate.cabin_id, candidate.alight_visit_index] += count
        for group in problem.passenger_build.demand_groups:
            model.add_hint(self.unserved[group.id], group.count - served[group.id])
        for event, variable in self.alight_count.items():
            count, time = alight[event], times[event]
            model.add_hint(variable, count)
            model.add_hint(self.alight_time[event], time)
            if event in self.products:
                model.add_hint(self.products[event], count * time)
        for (cabin, visit, k), (present, value) in self.unary.items():
            event = (cabin, visit)
            model.add_hint(present, int(alight[event] >= k))
            model.add_hint(value, times[event] if alight[event] >= k else 0)


def build_ddd_cp_sat_passengers(
    problem: DddFixedKTrajectoryProblem,
    built: DddCpSatMovementModel,
    *,
    cost_encoding: DddCpSatCostEncoding = DddCpSatCostEncoding.PRODUCT,
    deadline_monotonic: float | None = None,
) -> DddCpSatPassengerModel:
    """Full structural integer assignment, with shared seats and exact costs.

    Call through the integrated builder, which validates the supported domain.
    No heuristic passenger pruning and no time-expanded graph are used here.
    """
    if not isinstance(cost_encoding, DddCpSatCostEncoding):
        raise ValueError("unknown CP-SAT cost encoding")
    movement = problem.resolved_trajectory_problem.structural_movement_problem
    model = built.model
    capacity = problem.artifact.config.cabin_capacity
    horizon = movement.passenger_service_end_tick
    groups = {group.id: group for group in problem.passenger_build.demand_groups}
    stops = {
        state: unique_stop_route_option(movement, state, error_context="CP passengers")
        for states in built.states_by_cabin.values() for state in states
    }
    board_times = {}
    alight_times = {}
    stop_literals = {}
    for cabin, states in built.states_by_cabin.items():
        for visit, state in enumerate(states[:-1]):
            stop = stops[state]
            assert stop.platform_entry_offset_seconds is not None
            assert stop.platform_exit_offset_seconds is not None
            key = (cabin, visit)
            board_times[key] = built.time_by_cabin[cabin][visit] + ddd_seconds_to_tick(
                stop.platform_exit_offset_seconds
            )
            offset = ddd_seconds_to_tick(stop.platform_entry_offset_seconds)
            alight_time = model.new_int_var(
                offset, built.max_completion_tick + offset, f"alight_time[{cabin},{visit}]"
            )
            model.add(alight_time == built.time_by_cabin[cabin][visit] + offset)
            alight_times[key] = alight_time
            stop_literals[key] = built.selection_by_key[cabin, visit, stop.id]

    counts, used, unserved = {}, {}, {}
    by_group = defaultdict(list)
    by_alight = defaultdict(list)
    onboard = defaultdict(list)
    for index, candidate in enumerate(problem.passenger_build.ride_candidates):
        if deadline_monotonic is not None and perf_counter() >= deadline_monotonic:
            raise TimeoutError("CP-SAT passenger build budget exhausted")
        group = groups[candidate.demand_group_id]
        board = candidate.cabin_id, candidate.board_visit_index
        alight = candidate.cabin_id, candidate.alight_visit_index
        count = model.new_int_var(0, min(capacity, group.count), f"passengers[{index}]")
        present = model.new_bool_var(f"ride_used[{index}]")
        model.add(count >= 1).only_enforce_if(present)
        model.add(count == 0).only_enforce_if(present.Not())
        model.add_implication(present, stop_literals[board])
        model.add_implication(present, stop_literals[alight])
        model.add(board_times[board] >= max(0, ddd_seconds_to_tick(group.release_time_seconds))).only_enforce_if(present)
        model.add(board_times[board] <= horizon).only_enforce_if(present)
        model.add(alight_times[alight] <= horizon).only_enforce_if(present)
        model.add(alight_times[alight] >= board_times[board]).only_enforce_if(present)
        counts[candidate.id], used[candidate.id] = count, present
        by_group[group.id].append(count)
        by_alight[alight].append(count)
        for visit in range(candidate.board_visit_index, candidate.alight_visit_index):
            onboard[candidate.cabin_id, visit].append(count)
    for group in groups.values():
        unserved[group.id] = model.new_int_var(0, group.count, f"unserved[{group.id}]")
        model.add(sum(by_group[group.id]) + unserved[group.id] == group.count)
    for values in onboard.values():
        model.add(sum(values) <= capacity)

    constant = sum(
        group.count * max(0, horizon - ddd_seconds_to_tick(group.release_time_seconds))
        for group in groups.values()
    )
    alight_counts, products, unary = {}, {}, {}
    terms = []
    expression_magnitude = constant
    for event, values in sorted(by_alight.items()):
        count = model.new_int_var(0, capacity, f"alight_count[{event}]")
        model.add(count == sum(values))
        time = alight_times[event]
        # The installed pybind repeated-field wrapper does not implement Python
        # negative indexing (domain[-1] silently returns 0). Use a list first.
        time_upper = int(list(time.proto.domain)[-1])
        # Stay in the exact integer range of the solver's double-valued reports,
        # and well inside int64 for both expressions and product domains.
        expression_magnitude += capacity * (time_upper + horizon)
        if expression_magnitude >= 2**53:
            raise ValueError("CP-SAT objective exceeds supported exact reporting range")
        alight_counts[event] = count
        if cost_encoding is DddCpSatCostEncoding.PRODUCT:
            product = model.new_int_var(0, capacity * time_upper, f"alight_product[{event}]")
            model.add_multiplication_equality(product, [count, time])
            terms.append(product - horizon * count)
            products[event] = product
        else:
            levels = []
            for k in range(1, capacity + 1):
                present = model.new_bool_var(f"alight_level[{event},{k}]")
                value = model.new_int_var(0, time_upper, f"alight_cost[{event},{k}]")
                model.add(value == time).only_enforce_if(present)
                model.add(value == 0).only_enforce_if(present.Not())
                if levels:
                    model.add(levels[-1] >= present)
                levels.append(present)
                unary[*event, k] = present, value
                terms.append(value - horizon * present)
            model.add(count == sum(levels))
    if expression_magnitude >= 2**53:
        raise ValueError("CP-SAT objective exceeds supported exact reporting range")
    expression = cp_model.LinearExpr.sum(terms) + constant
    model.minimize(expression)
    return DddCpSatPassengerModel(
        counts, used, unserved, alight_counts,
        {event: alight_times[event] for event in alight_counts},
        products, unary, constant, expression, len(onboard), cost_encoding,
    )
