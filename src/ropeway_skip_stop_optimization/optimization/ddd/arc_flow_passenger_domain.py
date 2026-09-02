from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass, replace
from hashlib import sha256
import json
import math

from ropeway_skip_stop_optimization.optimization.ddd.arc_flow_preparation import (
    DddPreparedArcFlowProblem,
)
from ropeway_skip_stop_optimization.optimization.ddd.arc_flow_network import (
    DddCabinTimeExpandedArc,
    check_ddd_arc_flow_build_deadline,
)
from ropeway_skip_stop_optimization.optimization.ddd.route_topology import (
    unique_stop_route_option,
)
from ropeway_skip_stop_optimization.optimization.ddd.time_ticks import (
    ddd_seconds_to_tick,
    ddd_tick_to_seconds,
)
from ropeway_skip_stop_optimization.optimization.ean.passenger_objective import (
    EanPassengerObjectiveEvent,
    ean_passenger_objective_definition,
)


@dataclass(frozen=True, slots=True)
class DddArcFlowPassengerVariable:
    id: str
    candidate_id: str
    demand_group_id: str
    cabin_id: int
    board_visit_index: int
    alight_visit_index: int
    arc_id: str
    visit_index: int
    upper_bound: float
    objective_coefficient: float


@dataclass(frozen=True, slots=True)
class DddArcFlowPassengerFlow:
    candidate_id: str
    demand_group_id: str
    cabin_id: int
    board_visit_index: int
    alight_visit_index: int
    variable_ids_by_arc_id: tuple[tuple[str, str], ...]

    @property
    def variable_id_by_arc_id(self) -> dict[str, str]:
        return dict(self.variable_ids_by_arc_id)


@dataclass(frozen=True, slots=True)
class DddArcFlowPassengerEqualityRow:
    id: str
    coefficients: tuple[tuple[str, float], ...]


@dataclass(frozen=True, slots=True)
class DddArcFlowPassengerDemandRow:
    id: str
    demand_group_id: str
    variable_ids: tuple[str, ...]
    right_hand_side: float


@dataclass(frozen=True, slots=True)
class DddArcFlowPassengerCapacityRow:
    id: str
    arc_id: str
    variable_ids: tuple[str, ...]
    movement_coefficient: float


@dataclass(frozen=True, slots=True)
class DddArcFlowPassengerDomain:
    problem_fingerprint: str
    objective_constant: float
    variables: tuple[DddArcFlowPassengerVariable, ...]
    flows: tuple[DddArcFlowPassengerFlow, ...]
    equality_rows: tuple[DddArcFlowPassengerEqualityRow, ...]
    demand_rows: tuple[DddArcFlowPassengerDemandRow, ...]
    capacity_rows: tuple[DddArcFlowPassengerCapacityRow, ...]
    fingerprint: str

    @property
    def variable_by_id(self) -> dict[str, DddArcFlowPassengerVariable]:
        return {variable.id: variable for variable in self.variables}

    @property
    def constraint_count(self) -> int:
        return (
            len(self.variables)
            + len(self.equality_rows)
            + len(self.demand_rows)
            + len(self.capacity_rows)
        )

    def to_payload(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_payload(
        cls,
        payload: dict[str, object],
    ) -> DddArcFlowPassengerDomain:
        return cls(
            problem_fingerprint=str(payload["problem_fingerprint"]),
            objective_constant=float(payload["objective_constant"]),
            variables=tuple(
                DddArcFlowPassengerVariable(**item)
                for item in payload["variables"]
            ),
            flows=tuple(
                DddArcFlowPassengerFlow(
                    **{
                        **item,
                        "variable_ids_by_arc_id": tuple(
                            tuple(pair)
                            for pair in item["variable_ids_by_arc_id"]
                        ),
                    }
                )
                for item in payload["flows"]
            ),
            equality_rows=tuple(
                DddArcFlowPassengerEqualityRow(
                    id=item["id"],
                    coefficients=tuple(
                        tuple(pair) for pair in item["coefficients"]
                    ),
                )
                for item in payload["equality_rows"]
            ),
            demand_rows=tuple(
                DddArcFlowPassengerDemandRow(
                    **{
                        **item,
                        "variable_ids": tuple(item["variable_ids"]),
                    }
                )
                for item in payload["demand_rows"]
            ),
            capacity_rows=tuple(
                DddArcFlowPassengerCapacityRow(
                    **{
                        **item,
                        "variable_ids": tuple(item["variable_ids"]),
                    }
                )
                for item in payload["capacity_rows"]
            ),
            fingerprint=str(payload["fingerprint"]),
        )

    def validate(self, prepared: DddPreparedArcFlowProblem) -> None:
        if self.problem_fingerprint != prepared.problem.fingerprint:
            raise ValueError("Passenger domain and prepared problem differ")
        variable_ids = tuple(variable.id for variable in self.variables)
        if len(variable_ids) != len(set(variable_ids)):
            raise ValueError("Passenger-domain variable IDs must be unique")
        known_variables = set(variable_ids)
        known_arcs = {arc.id for arc in prepared.arcs}
        if any(variable.arc_id not in known_arcs for variable in self.variables):
            raise ValueError("Passenger variable references an unknown Movement arc")
        row_ids = tuple(
            row.id
            for rows in (self.equality_rows, self.demand_rows, self.capacity_rows)
            for row in rows
        )
        if len(row_ids) != len(set(row_ids)):
            raise ValueError("Passenger-domain row IDs must be unique")
        referenced = {
            variable_id
            for row in self.equality_rows
            for variable_id, _ in row.coefficients
        } | {
            variable_id
            for row in self.demand_rows
            for variable_id in row.variable_ids
        } | {
            variable_id
            for row in self.capacity_rows
            for variable_id in row.variable_ids
        }
        if not referenced <= known_variables:
            raise ValueError("Passenger row references an unknown variable")
        if any(row.arc_id not in known_arcs for row in self.capacity_rows):
            raise ValueError("Passenger capacity row references an unknown arc")
        if any(variable.upper_bound <= 0 for variable in self.variables):
            raise ValueError("Passenger variable upper coefficients must be positive")
        if self.fingerprint != _domain_fingerprint(self):
            raise ValueError("Passenger-domain fingerprint is inconsistent")


@dataclass(frozen=True, slots=True)
class DddArcFlowPassengerDomainBuilder:
    def build(
        self,
        prepared: DddPreparedArcFlowProblem,
        *,
        deadline_monotonic: float | None = None,
    ) -> DddArcFlowPassengerDomain:
        prepared.validate()
        problem = prepared.problem
        movement = prepared.movement
        definition = ean_passenger_objective_definition(problem.objective)
        horizon = problem.artifact.config.horizon_seconds
        objective_constant = sum(
            group.count
            * definition.unserved_cost_seconds(
                release_time_seconds=group.release_time_seconds,
                horizon_seconds=horizon,
            )
            for group in problem.passenger_build.demand_groups
        )
        group_by_id = {
            group.id: group for group in problem.passenger_build.demand_groups
        }
        network_by_cabin = {
            network.cabin_id: network for network in prepared.networks
        }
        arcs_by_visit_by_cabin = {}
        for network in prepared.networks:
            arcs_by_visit: dict[int, list[DddCabinTimeExpandedArc]] = defaultdict(
                list
            )
            for arc_index, arc in enumerate(network.arcs):
                if arc_index % 4096 == 0:
                    check_ddd_arc_flow_build_deadline(deadline_monotonic)
                arcs_by_visit[arc.visit_index].append(arc)
            arcs_by_visit_by_cabin[network.cabin_id] = {
                visit_index: tuple(arcs_by_visit.get(visit_index, ()))
                for visit_index in range(network.start.max_visit_count)
            }
        variables: list[DddArcFlowPassengerVariable] = []
        flows: list[DddArcFlowPassengerFlow] = []
        equality_rows: list[DddArcFlowPassengerEqualityRow] = []
        demand_board_variables: dict[str, list[str]] = defaultdict(list)
        onboard_variables_by_arc_id: dict[str, list[str]] = defaultdict(list)
        for candidate_index, candidate in enumerate(
            sorted(
                problem.passenger_build.ride_candidates,
                key=lambda item: item.id,
            )
        ):
            if candidate_index % 16 == 0:
                check_ddd_arc_flow_build_deadline(deadline_monotonic)
            network = network_by_cabin.get(candidate.cabin_id)
            if (
                network is None
                or candidate.alight_visit_index >= len(network.state_ids) - 1
            ):
                continue
            board_stop = unique_stop_route_option(
                movement,
                network.state_ids[candidate.board_visit_index],
                error_context="fixed-K arc-flow passenger boarding",
            )
            alight_stop = unique_stop_route_option(
                movement,
                network.state_ids[candidate.alight_visit_index],
                error_context="fixed-K arc-flow passenger alighting",
            )
            assert board_stop.platform_exit_offset_seconds is not None
            assert alight_stop.platform_entry_offset_seconds is not None
            board_offset = ddd_seconds_to_tick(
                board_stop.platform_exit_offset_seconds
            )
            alight_offset = ddd_seconds_to_tick(
                alight_stop.platform_entry_offset_seconds
            )
            group = group_by_id[candidate.demand_group_id]
            upper = float(
                min(
                    group.count,
                    int(round(problem.artifact.config.cabin_capacity)),
                )
            )
            variable_ids_by_arc_id: list[tuple[str, str]] = []
            coefficients_by_node: dict[
                tuple[int, int, bool], list[tuple[str, float]]
            ] = defaultdict(list)
            candidate_arc_index = 0
            arcs_by_visit = arcs_by_visit_by_cabin[candidate.cabin_id]
            for visit_index in range(
                candidate.board_visit_index,
                candidate.alight_visit_index + 1,
            ):
                for arc in arcs_by_visit[visit_index]:
                    candidate_arc_index += 1
                    if candidate_arc_index % 4096 == 0:
                        check_ddd_arc_flow_build_deadline(deadline_monotonic)
                    if not arc.source_active or arc.option_id is None:
                        continue
                    if arc.visit_index == candidate.board_visit_index and (
                        arc.option_id != board_stop.id
                        or arc.source_tick + board_offset + arc.wait_tick
                        < ddd_seconds_to_tick(group.release_time_seconds)
                    ):
                        continue
                    if arc.visit_index == candidate.alight_visit_index and (
                        arc.option_id != alight_stop.id
                        or arc.source_tick + alight_offset
                        > movement.passenger_service_end_tick
                    ):
                        continue
                    coefficient = 0.0
                    if arc.visit_index == candidate.board_visit_index:
                        coefficient -= horizon
                        if definition.event is EanPassengerObjectiveEvent.BOARDING:
                            coefficient += ddd_tick_to_seconds(
                                arc.source_tick + board_offset + arc.wait_tick
                            )
                    if (
                        arc.visit_index == candidate.alight_visit_index
                        and definition.event is EanPassengerObjectiveEvent.ALIGHTING
                    ):
                        coefficient += ddd_tick_to_seconds(
                            arc.source_tick + alight_offset
                        )
                    variable_id = f"passenger[{len(variables)}]"
                    variables.append(
                        DddArcFlowPassengerVariable(
                            id=variable_id,
                            candidate_id=candidate.id,
                            demand_group_id=candidate.demand_group_id,
                            cabin_id=candidate.cabin_id,
                            board_visit_index=candidate.board_visit_index,
                            alight_visit_index=candidate.alight_visit_index,
                            arc_id=arc.id,
                            visit_index=arc.visit_index,
                            upper_bound=upper,
                            objective_coefficient=coefficient,
                        )
                    )
                    variable_ids_by_arc_id.append((arc.id, variable_id))
                    coefficients_by_node[arc.source_node].append(
                        (variable_id, -1.0)
                    )
                    coefficients_by_node[arc.target_node].append(
                        (variable_id, 1.0)
                    )
                    if arc.visit_index == candidate.board_visit_index:
                        demand_board_variables[candidate.demand_group_id].append(
                            variable_id
                        )
                    if arc.visit_index < candidate.alight_visit_index:
                        onboard_variables_by_arc_id[arc.id].append(variable_id)
            if not variable_ids_by_arc_id:
                continue
            for layer in range(
                candidate.board_visit_index + 1,
                candidate.alight_visit_index + 1,
            ):
                check_ddd_arc_flow_build_deadline(deadline_monotonic)
                nodes = tuple(
                    sorted(
                        node for node in coefficients_by_node if node[0] == layer
                    )
                )
                for node in sorted(nodes):
                    equality_rows.append(
                        DddArcFlowPassengerEqualityRow(
                            id=(
                                f"passenger_flow[{len(equality_rows)},"
                                f"{layer},{node[1]}]"
                            ),
                            coefficients=tuple(coefficients_by_node[node]),
                        )
                    )
            flows.append(
                DddArcFlowPassengerFlow(
                    candidate_id=candidate.id,
                    demand_group_id=candidate.demand_group_id,
                    cabin_id=candidate.cabin_id,
                    board_visit_index=candidate.board_visit_index,
                    alight_visit_index=candidate.alight_visit_index,
                    variable_ids_by_arc_id=tuple(variable_ids_by_arc_id),
                )
            )

        check_ddd_arc_flow_build_deadline(deadline_monotonic)
        demand_rows = tuple(
            DddArcFlowPassengerDemandRow(
                id=f"demand[{group_id}]",
                demand_group_id=group_id,
                variable_ids=tuple(demand_board_variables[group_id]),
                right_hand_side=float(group.count),
            )
            for group_id, group in sorted(group_by_id.items())
        )
        capacity_rows: list[DddArcFlowPassengerCapacityRow] = []
        for network in prepared.networks:
            for arc_index, arc in enumerate(network.arcs):
                if arc_index % 4096 == 0:
                    check_ddd_arc_flow_build_deadline(deadline_monotonic)
                onboard = tuple(onboard_variables_by_arc_id.get(arc.id, ()))
                if onboard:
                    capacity_rows.append(
                        DddArcFlowPassengerCapacityRow(
                            id=(
                                f"capacity[{len(capacity_rows)},"
                                f"{network.cabin_id},"
                                f"{arc.visit_index},{arc.source_tick}]"
                            ),
                            arc_id=arc.id,
                            variable_ids=onboard,
                            movement_coefficient=float(
                                problem.artifact.config.cabin_capacity
                            ),
                        )
                    )
        check_ddd_arc_flow_build_deadline(deadline_monotonic)
        incomplete = DddArcFlowPassengerDomain(
            problem_fingerprint=problem.fingerprint,
            objective_constant=objective_constant,
            variables=tuple(variables),
            flows=tuple(flows),
            equality_rows=tuple(equality_rows),
            demand_rows=demand_rows,
            capacity_rows=tuple(capacity_rows),
            fingerprint="",
        )
        result = replace(
            incomplete,
            fingerprint=_domain_fingerprint(incomplete),
        )
        check_ddd_arc_flow_build_deadline(deadline_monotonic)
        result.validate(prepared)
        return result


def build_ddd_arc_flow_passenger_subdomain(
    domain: DddArcFlowPassengerDomain,
    *,
    demand_group_ids: frozenset[str],
    objective_constant: float,
    prepared: DddPreparedArcFlowProblem | None = None,
) -> DddArcFlowPassengerDomain:
    """Return the exact row/column restriction for selected demand groups.

    Variable and row IDs intentionally remain the canonical IDs of the full
    domain.  This makes core/residual values directly comparable and lets the
    partial-master coupling layer refer back to the original capacity rows.
    """

    if not math.isfinite(objective_constant) or objective_constant < 0:
        raise ValueError("Passenger subdomain objective constant is invalid")
    known_groups = {row.demand_group_id for row in domain.demand_rows}
    unknown = demand_group_ids - known_groups
    if unknown:
        raise ValueError(
            "Passenger subdomain references unknown demand groups: "
            f"{sorted(unknown)[:3]}"
        )
    variables = tuple(
        variable
        for variable in domain.variables
        if variable.demand_group_id in demand_group_ids
    )
    variable_ids = {variable.id for variable in variables}
    flows = tuple(
        flow
        for flow in domain.flows
        if flow.demand_group_id in demand_group_ids
    )
    equality_rows = tuple(
        replace(
            row,
            coefficients=tuple(
                item for item in row.coefficients if item[0] in variable_ids
            ),
        )
        for row in domain.equality_rows
        if any(variable_id in variable_ids for variable_id, _ in row.coefficients)
    )
    demand_rows = tuple(
        row for row in domain.demand_rows if row.demand_group_id in demand_group_ids
    )
    capacity_rows = tuple(
        replace(
            row,
            variable_ids=tuple(
                variable_id
                for variable_id in row.variable_ids
                if variable_id in variable_ids
            ),
        )
        for row in domain.capacity_rows
        if any(variable_id in variable_ids for variable_id in row.variable_ids)
    )
    incomplete = DddArcFlowPassengerDomain(
        problem_fingerprint=domain.problem_fingerprint,
        objective_constant=objective_constant,
        variables=variables,
        flows=flows,
        equality_rows=equality_rows,
        demand_rows=demand_rows,
        capacity_rows=capacity_rows,
        fingerprint="",
    )
    result = replace(incomplete, fingerprint=_domain_fingerprint(incomplete))
    if prepared is not None:
        result.validate(prepared)
    return result


def _domain_fingerprint(domain: DddArcFlowPassengerDomain) -> str:
    payload = asdict(domain)
    payload.pop("fingerprint")
    return sha256(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()
