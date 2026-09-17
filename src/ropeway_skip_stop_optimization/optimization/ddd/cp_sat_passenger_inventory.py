"""Exact OD-inventory passenger aggregation for the reservoir CP-SAT model."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from time import perf_counter

from ortools.sat.python import cp_model

from ..ean.builders.passenger_builder import EanPassengerCandidateBuildResult
from ..ean.models import EanDemandGroup, EanRideCandidate
from .cp_sat_movement import DddCpSatMovementModel
from .cp_sat_passenger import DddCpSatCostEncoding, binary_count_time_product
from .models import DddMovementProblem
from .route_topology import unique_stop_route_option
from .time_ticks import ddd_seconds_to_tick


@dataclass(frozen=True, slots=True)
class DddOdInventoryRide:
    id: str
    origin_station_id: str
    destination_station_id: str
    cabin_id: int
    board_visit_index: int
    alight_visit_index: int
    legacy_candidate_by_group_id: dict[str, str]


@dataclass(frozen=True)
class DddCpSatInventoryPassengerModel:
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
    binary: dict[tuple[int, int, int], tuple[cp_model.IntVar, cp_model.IntVar]] = field(default_factory=dict)
    journey_expression: cp_model.LinearExpr | None = None
    unserved_expression: cp_model.LinearExpr | None = None
    lexicographic_weight: int | None = None
    rides: dict[str, DddOdInventoryRide] = field(default_factory=dict)
    groups_by_od: dict[tuple[str, str], tuple[EanDemandGroup, ...]] = field(default_factory=dict)
    board_time: dict[str, cp_model.IntVar] = field(default_factory=dict)
    inventory_interval_count: int = 0
    legacy_ride_candidate_count: int = 0

    @property
    def encoding(self) -> str:
        return "od_inventory"

    @property
    def cost_auxiliary_count(self) -> int:
        return len(self.products) + 2 * (len(self.unary) + len(self.binary))

    def supports_legacy_counts(self, counts: dict[str, int]) -> bool:
        known = {
            candidate_id
            for ride in self.rides.values()
            for candidate_id in ride.legacy_candidate_by_group_id.values()
        }
        return all(not count or ride_id in known for ride_id, count in counts.items())

    def _aggregate_legacy_counts(self, counts: dict[str, int]) -> dict[str, int]:
        aggregate_by_candidate = {
            candidate_id: ride_id
            for ride_id, ride in self.rides.items()
            for candidate_id in ride.legacy_candidate_by_group_id.values()
        }
        result = defaultdict(int)
        for candidate_id, count in counts.items():
            if not count:
                continue
            ride_id = aggregate_by_candidate.get(candidate_id)
            if ride_id is None:
                raise ValueError("positive seed count on ride outside OD-inventory encoding")
            result[ride_id] += count
        return dict(result)

    def add_hints(self, problem, model, counts: dict[str, int], times: dict[tuple[int, int], int]) -> None:
        aggregated = self._aggregate_legacy_counts(counts)
        served_by_od = defaultdict(int)
        alight = defaultdict(int)
        for ride_id, variable in self.ride_count.items():
            count = aggregated.get(ride_id, 0)
            ride = self.rides[ride_id]
            model.add_hint(variable, count)
            model.add_hint(self.used[ride_id], int(count > 0))
            served_by_od[ride.origin_station_id, ride.destination_station_id] += count
            alight[ride.cabin_id, ride.alight_visit_index] += count
        for od, groups in self.groups_by_od.items():
            model.add_hint(self.unserved[_od_id(*od)], sum(group.count for group in groups) - served_by_od[od])
        for event, variable in self.alight_count.items():
            count = alight[event]
            time = times[event]
            model.add_hint(variable, count)
            model.add_hint(self.alight_time[event], time)
            if event in self.products:
                model.add_hint(self.products[event], count * time)
        for (cabin, visit, level), (present, value) in self.unary.items():
            count, time = alight[cabin, visit], times[cabin, visit]
            model.add_hint(present, int(count >= level))
            model.add_hint(value, time if count >= level else 0)
        for (cabin, visit, bit_index), (present, value) in self.binary.items():
            count, time = alight[cabin, visit], times[cabin, visit]
            bit = (count >> bit_index) & 1
            model.add_hint(present, bit)
            model.add_hint(value, time if bit else 0)

    def extract_legacy_counts(self, value) -> dict[str, int]:
        remaining = {
            group.id: group.count
            for groups in self.groups_by_od.values()
            for group in groups
        }
        result: dict[str, int] = {}
        rides_by_od: dict[tuple[str, str], list[tuple[int, str, int]]] = defaultdict(list)
        for ride_id, variable in self.ride_count.items():
            count = int(value(variable))
            if count:
                ride = self.rides[ride_id]
                rides_by_od[ride.origin_station_id, ride.destination_station_id].append(
                    (int(value(self.board_time[ride_id])), ride_id, count)
                )
        for od, entries in rides_by_od.items():
            groups = self.groups_by_od[od]
            for board_tick, ride_id, count in sorted(entries):
                ride = self.rides[ride_id]
                needed = count
                for group in groups:
                    if needed == 0:
                        break
                    if ddd_seconds_to_tick(group.release_time_seconds) > board_tick:
                        break
                    available = remaining[group.id]
                    if not available:
                        continue
                    candidate_id = ride.legacy_candidate_by_group_id.get(group.id)
                    if candidate_id is None:
                        raise ValueError(
                            "OD-inventory reconstruction found a structurally missing legacy ride"
                        )
                    assigned = min(available, needed)
                    result[candidate_id] = assigned
                    remaining[group.id] -= assigned
                    needed -= assigned
                if needed:
                    raise ValueError("OD-inventory solution boards unavailable passengers")
        return result


def build_ddd_cp_sat_od_inventory_passengers(
    movement: DddMovementProblem,
    passenger_build: EanPassengerCandidateBuildResult,
    capacity: int,
    built: DddCpSatMovementModel,
    *,
    cost_encoding: DddCpSatCostEncoding,
    deadline_monotonic: float | None = None,
    with_journey_cost: bool = True,
) -> DddCpSatInventoryPassengerModel:
    """Aggregate release batches exactly through one availability profile per OD."""
    if not isinstance(cost_encoding, DddCpSatCostEncoding):
        raise ValueError("unknown CP-SAT cost encoding")
    model = built.model
    horizon = movement.passenger_service_end_tick
    inventory_end = horizon + 1
    groups = {group.id: group for group in passenger_build.demand_groups}
    if any(ddd_seconds_to_tick(group.release_time_seconds) > horizon for group in groups.values()):
        raise ValueError("OD-inventory passengers require releases within the service horizon")
    groups_by_od_lists: dict[tuple[str, str], list[EanDemandGroup]] = defaultdict(list)
    for group in groups.values():
        groups_by_od_lists[group.origin_station_id, group.destination_station_id].append(group)
    groups_by_od = {
        od: tuple(sorted(values, key=lambda group: (group.release_time_seconds, group.id)))
        for od, values in groups_by_od_lists.items()
    }
    rides = _aggregate_rides(passenger_build, groups)
    stops = {
        state: unique_stop_route_option(movement, state, error_context="OD-inventory passengers")
        for states in built.states_by_cabin.values()
        for state in states
    }
    board_expressions, alight_times, stop_literals = {}, {}, {}
    for cabin, states in built.states_by_cabin.items():
        for visit, state in enumerate(states[:-1]):
            stop = stops[state]
            assert stop.platform_entry_offset_seconds is not None
            assert stop.platform_exit_offset_seconds is not None
            event = cabin, visit
            board_expressions[event] = (
                built.time_by_cabin[cabin][visit]
                + ddd_seconds_to_tick(stop.platform_exit_offset_seconds)
                + built.waiting_step_tick * built.wait_steps_by_key[event]
            )
            alight = model.new_int_var(
                ddd_seconds_to_tick(stop.platform_entry_offset_seconds),
                built.max_completion_tick + ddd_seconds_to_tick(stop.platform_entry_offset_seconds),
                f"inventory_alight_time[{cabin},{visit}]",
            )
            model.add(
                alight
                == built.time_by_cabin[cabin][visit]
                + ddd_seconds_to_tick(stop.platform_entry_offset_seconds)
            )
            alight_times[event] = alight
            stop_literals[event] = built.selection_by_key[cabin, visit, stop.id]

    counts, used, board_times = {}, {}, {}
    by_alight, onboard = defaultdict(list), defaultdict(list)
    inventory_intervals: dict[tuple[str, str], list[cp_model.IntervalVar]] = defaultdict(list)
    inventory_demands: dict[tuple[str, str], list] = defaultdict(list)
    for od, od_groups in groups_by_od.items():
        for index, group in enumerate(od_groups):
            release = min(inventory_end, max(0, ddd_seconds_to_tick(group.release_time_seconds)))
            if release:
                inventory_intervals[od].append(
                    model.new_fixed_size_interval_var(0, release, f"unreleased[{_od_id(*od)},{index}]")
                )
                inventory_demands[od].append(group.count)

    for index, (ride_id, ride) in enumerate(sorted(rides.items())):
        if deadline_monotonic is not None and perf_counter() >= deadline_monotonic:
            raise TimeoutError("OD-inventory passenger build budget exhausted")
        count = model.new_int_var(0, capacity, f"inventory_passengers[{index}]")
        present = model.new_bool_var(f"inventory_ride_used[{index}]")
        model.add(count >= 1).only_enforce_if(present)
        model.add(count == 0).only_enforce_if(present.Not())
        board_event = ride.cabin_id, ride.board_visit_index
        alight_event = ride.cabin_id, ride.alight_visit_index
        model.add_implication(present, stop_literals[board_event])
        model.add_implication(present, stop_literals[alight_event])
        board = model.new_int_var(0, horizon, f"inventory_board_time[{index}]")
        model.add(board == board_expressions[board_event]).only_enforce_if(present)
        model.add(board == 0).only_enforce_if(present.Not())
        model.add(alight_times[alight_event] <= horizon).only_enforce_if(present)
        model.add(alight_times[alight_event] >= board).only_enforce_if(present)
        duration = model.new_int_var(1, inventory_end, f"inventory_duration[{index}]")
        model.add(duration == inventory_end - board)
        interval = model.new_optional_interval_var(
            board, duration, inventory_end, present, f"boarded_inventory[{index}]"
        )
        od = ride.origin_station_id, ride.destination_station_id
        inventory_intervals[od].append(interval)
        inventory_demands[od].append(count)
        counts[ride_id], used[ride_id], board_times[ride_id] = count, present, board
        by_alight[alight_event].append(count)
        for visit in range(ride.board_visit_index, ride.alight_visit_index):
            onboard[ride.cabin_id, visit].append(count)

    unserved = {}
    for od, od_groups in groups_by_od.items():
        total = sum(group.count for group in od_groups)
        model.add_cumulative(inventory_intervals[od], inventory_demands[od], total)
        served = [counts[ride_id] for ride_id, ride in rides.items() if (ride.origin_station_id, ride.destination_station_id) == od]
        variable = model.new_int_var(0, total, f"inventory_unserved[{_od_id(*od)}]")
        model.add(sum(served) + variable == total)
        unserved[_od_id(*od)] = variable
    for values in onboard.values():
        model.add(sum(values) <= capacity)

    constant = sum(
        group.count * max(0, horizon - ddd_seconds_to_tick(group.release_time_seconds))
        for group in groups.values()
    )
    alight_counts, products, unary, binary = {}, {}, {}, {}
    terms = []
    expression_magnitude = constant
    for event, values in sorted(by_alight.items()):
        count = model.new_int_var(0, capacity, f"inventory_alight_count[{event}]")
        model.add(count == sum(values))
        time = alight_times[event]
        time_upper = list(time.proto.domain)[-1]
        expression_magnitude += capacity * (time_upper + horizon)
        if expression_magnitude >= 2**53:
            raise ValueError("OD-inventory objective exceeds supported exact reporting range")
        alight_counts[event] = count
        if not with_journey_cost:
            continue
        if cost_encoding is DddCpSatCostEncoding.PRODUCT:
            product = model.new_int_var(0, capacity * time_upper, f"inventory_alight_product[{event}]")
            model.add_multiplication_equality(product, [count, time])
            products[event] = product
            terms.append(product - horizon * count)
        elif cost_encoding is DddCpSatCostEncoding.BINARY:
            product, bits = binary_count_time_product(
                model, count, time, capacity, time_upper, f"inventory_alight_binary[{event}]"
            )
            binary.update({(*event, bit): pair for bit, pair in bits.items()})
            terms.append(product - horizon * count)
        else:
            levels = []
            for level in range(1, capacity + 1):
                present = model.new_bool_var(f"inventory_alight_level[{event},{level}]")
                value = model.new_int_var(0, time_upper, f"inventory_alight_cost[{event},{level}]")
                model.add(value == time).only_enforce_if(present)
                model.add(value == 0).only_enforce_if(present.Not())
                if levels:
                    model.add(levels[-1] >= present)
                levels.append(present)
                unary[*event, level] = present, value
                terms.append(value - horizon * present)
            model.add(count == sum(levels))
    unserved_expression = cp_model.LinearExpr.sum(list(unserved.values()))
    journey_expression = cp_model.LinearExpr.sum(terms) + constant
    objective = journey_expression if with_journey_cost else unserved_expression
    model.minimize(objective)
    return DddCpSatInventoryPassengerModel(
        counts,
        used,
        unserved,
        alight_counts,
        {event: alight_times[event] for event in alight_counts},
        products,
        unary,
        constant,
        objective,
        len(onboard),
        cost_encoding,
        binary,
        journey_expression if with_journey_cost else None,
        unserved_expression,
        None,
        rides,
        groups_by_od,
        board_times,
        sum(len(values) for values in inventory_intervals.values()),
        len(passenger_build.ride_candidates),
    )


def _aggregate_rides(
    passenger_build: EanPassengerCandidateBuildResult,
    groups: dict[str, EanDemandGroup],
) -> dict[str, DddOdInventoryRide]:
    members: dict[tuple[str, str, int, int, int], dict[str, str]] = defaultdict(dict)
    for candidate in passenger_build.ride_candidates:
        group = groups[candidate.demand_group_id]
        key = (
            group.origin_station_id,
            group.destination_station_id,
            candidate.cabin_id,
            candidate.board_visit_index,
            candidate.alight_visit_index,
        )
        if group.id in members[key]:
            raise ValueError("duplicate legacy candidate in OD-inventory ride")
        members[key][group.id] = candidate.id
    result = {}
    for key, candidates in sorted(members.items()):
        origin, destination, cabin, board, alight = key
        ride_id = f"inventory::{origin}::{destination}::cabin_{cabin}::board_{board}::alight_{alight}"
        result[ride_id] = DddOdInventoryRide(
            ride_id, origin, destination, cabin, board, alight, dict(candidates)
        )
    return result


def _od_id(origin: str, destination: str) -> str:
    return f"{origin}::{destination}"
