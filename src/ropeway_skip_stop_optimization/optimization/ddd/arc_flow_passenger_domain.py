from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from hashlib import sha256
import json

from ropeway_skip_stop_optimization.optimization.ddd.arc_flow_preparation import (
    DddPreparedArcFlowProblem,
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
        variables: list[DddArcFlowPassengerVariable] = []
        flows: list[DddArcFlowPassengerFlow] = []
        equality_rows: list[DddArcFlowPassengerEqualityRow] = []
        for candidate in sorted(
            problem.passenger_build.ride_candidates,
            key=lambda item: item.id,
        ):
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
            for arc in network.arcs:
                if (
                    not arc.source_active
                    or arc.option_id is None
                    or not candidate.board_visit_index
                    <= arc.visit_index
                    <= candidate.alight_visit_index
                ):
                    continue
                if arc.visit_index == candidate.board_visit_index and (
                    arc.option_id != board_stop.id
                    or arc.source_tick + board_offset
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
                            arc.source_tick + board_offset
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
            if not variable_ids_by_arc_id:
                continue
            variable_id_by_arc_id = dict(variable_ids_by_arc_id)
            for layer in range(
                candidate.board_visit_index + 1,
                candidate.alight_visit_index + 1,
            ):
                nodes = {
                    arc.target_node
                    for arc in network.arcs
                    if arc.id in variable_id_by_arc_id
                    and arc.visit_index == layer - 1
                } | {
                    arc.source_node
                    for arc in network.arcs
                    if arc.id in variable_id_by_arc_id
                    and arc.visit_index == layer
                }
                for node in sorted(nodes):
                    coefficients = tuple(
                        (variable_id_by_arc_id[arc.id], 1.0)
                        for arc in network.arcs
                        if arc.id in variable_id_by_arc_id
                        and arc.target_node == node
                    ) + tuple(
                        (variable_id_by_arc_id[arc.id], -1.0)
                        for arc in network.arcs
                        if arc.id in variable_id_by_arc_id
                        and arc.source_node == node
                    )
                    equality_rows.append(
                        DddArcFlowPassengerEqualityRow(
                            id=(
                                f"passenger_flow[{len(equality_rows)},"
                                f"{layer},{node[1]}]"
                            ),
                            coefficients=coefficients,
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

        variable_by_id = {variable.id: variable for variable in variables}
        demand_rows = tuple(
            DddArcFlowPassengerDemandRow(
                id=f"demand[{group_id}]",
                demand_group_id=group_id,
                variable_ids=tuple(
                    variable_id
                    for flow in flows
                    if flow.demand_group_id == group_id
                    for _, variable_id in flow.variable_ids_by_arc_id
                    if variable_by_id[variable_id].visit_index
                    == flow.board_visit_index
                ),
                right_hand_side=float(group.count),
            )
            for group_id, group in sorted(group_by_id.items())
        )
        flows_by_cabin: dict[int, list[DddArcFlowPassengerFlow]] = {}
        flow_variable_ids_by_candidate = {
            flow.candidate_id: flow.variable_id_by_arc_id for flow in flows
        }
        for flow in flows:
            flows_by_cabin.setdefault(flow.cabin_id, []).append(flow)
        capacity_rows: list[DddArcFlowPassengerCapacityRow] = []
        for network in prepared.networks:
            cabin_flows = flows_by_cabin.get(network.cabin_id, [])
            for arc in network.arcs:
                onboard = tuple(
                    flow_variable_ids_by_candidate[flow.candidate_id][arc.id]
                    for flow in cabin_flows
                    if arc.id
                    in flow_variable_ids_by_candidate[flow.candidate_id]
                    and flow.board_visit_index
                    <= arc.visit_index
                    < flow.alight_visit_index
                )
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
        result.validate(prepared)
        return result


def _domain_fingerprint(domain: DddArcFlowPassengerDomain) -> str:
    payload = asdict(domain)
    payload.pop("fingerprint")
    return sha256(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()
