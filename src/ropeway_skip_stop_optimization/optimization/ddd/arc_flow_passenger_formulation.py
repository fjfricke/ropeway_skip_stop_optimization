"""Solver-independent, exact passenger reformulations for labeled cabin DAGs."""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, replace
from hashlib import sha256
import json

from .arc_flow_network import check_ddd_arc_flow_build_deadline
from .arc_flow_passenger_domain import (
    DddArcFlowPassengerDomain,
    DddArcFlowPassengerDomainBuilder,
    DddArcFlowPassengerEqualityRow,
    _domain_fingerprint,
)
from .arc_flow_preparation import DddPreparedArcFlowProblem


PASSENGER_PROFILES = (
    "legacy", "reachability", "ride_integrality", "drop_redundant_links",
    "alight_links", "destination_flows",
)


@dataclass(frozen=True, slots=True)
class DddArcFlowPassengerFormulationConfig:
    reachability: bool = False
    ride_integrality: bool = False
    drop_redundant_links: bool = False
    alight_links: bool = False
    destination_flows: bool = False

    @classmethod
    def from_profile(cls, profile: str) -> DddArcFlowPassengerFormulationConfig:
        if profile not in PASSENGER_PROFILES:
            raise ValueError(f"unknown passenger profile: {profile}")
        return cls() if profile == "legacy" else cls(**{profile: True})

    @property
    def profile(self) -> str:
        active = [key for key, value in asdict(self).items() if value]
        return "+".join(active) if active else "legacy"


@dataclass(frozen=True, slots=True)
class DddPreparedArcFlowPassengers:
    source: DddArcFlowPassengerDomain
    algebra: DddArcFlowPassengerDomain
    config: DddArcFlowPassengerFormulationConfig
    # Original variable -> algebra variable. Missing original variables are zero.
    projection: tuple[tuple[str, str], ...]
    dropped_links: tuple[tuple[str, str], ...]
    alight_rows: tuple[tuple[str, tuple[str, ...], float], ...]
    audit_json: str
    fingerprint: str


def _refingerprint(domain: DddArcFlowPassengerDomain) -> DddArcFlowPassengerDomain:
    return replace(domain, fingerprint=_domain_fingerprint(domain))


def prepare_arc_flow_passengers(
    prepared: DddPreparedArcFlowProblem,
    config: DddArcFlowPassengerFormulationConfig = DddArcFlowPassengerFormulationConfig(),
    *, deadline_monotonic: float | None = None,
) -> DddPreparedArcFlowPassengers:
    source = DddArcFlowPassengerDomainBuilder().build(
        prepared, deadline_monotonic=deadline_monotonic,
    )
    domain = source
    arcs = {arc.id: arc for arc in prepared.arcs}
    audit: dict[str, object] = {"profile": config.profile, "rides": []}
    if config.reachability:
        kept: set[str] = set()
        for flow in source.flows:
            check_ddd_arc_flow_build_deadline(deadline_monotonic)
            items = sorted(flow.variable_ids_by_arc_id, key=lambda p: arcs[p[0]].visit_index)
            forward: set[tuple[int, int, bool]] = set()
            forward_arcs: set[str] = set()
            for arc_id, variable_id in items:
                arc = arcs[arc_id]
                if arc.visit_index == flow.board_visit_index or arc.source_node in forward:
                    forward.add(arc.target_node)
                    forward_arcs.add(variable_id)
            backward: set[tuple[int, int, bool]] = set()
            ride_kept: set[str] = set()
            for arc_id, variable_id in reversed(items):
                arc = arcs[arc_id]
                if arc.visit_index == flow.alight_visit_index or arc.target_node in backward:
                    backward.add(arc.source_node)
                    if variable_id in forward_arcs:
                        ride_kept.add(variable_id)
            kept.update(ride_kept)
            audit["rides"].append({
                "candidate_id": flow.candidate_id,
                "removed_variables": [v for _, v in items if v not in ride_kept],
                "reason": "not_on_board_to_alight_path",
            })
        rows = tuple(
            replace(row, coefficients=tuple((v, c) for v, c in row.coefficients if v in kept))
            for row in source.equality_rows
        )
        domain = _refingerprint(replace(
            source,
            variables=tuple(v for v in source.variables if v.id in kept),
            flows=tuple(replace(f, variable_ids_by_arc_id=tuple(
                (a, v) for a, v in f.variable_ids_by_arc_id if v in kept
            )) for f in source.flows if any(v in kept for _, v in f.variable_ids_by_arc_id)),
            equality_rows=tuple(r for r in rows if r.coefficients),
            demand_rows=tuple(replace(r, variable_ids=tuple(v for v in r.variable_ids if v in kept))
                              for r in source.demand_rows),
            capacity_rows=tuple(replace(r, variable_ids=tuple(v for v in r.variable_ids if v in kept))
                                for r in source.capacity_rows
                                if any(v in kept for v in r.variable_ids)),
        ))
        audit["removed_equality_rows"] = len(source.equality_rows) - len(domain.equality_rows)

    projection = {v.id: v.id for v in domain.variables}
    if config.destination_flows:
        domain, projection, blocks = _destination_flows(domain, prepared, deadline_monotonic)
        audit["destination_blocks"] = blocks

    dropped: list[tuple[str, str]] = []
    if config.drop_redundant_links:
        capacity_by_var = {v: row for row in domain.capacity_rows
                           for v, count in Counter(row.variable_ids).items() if count == 1}
        for variable in domain.variables:
            row = capacity_by_var.get(variable.id)
            if row is not None and variable.upper_bound == row.movement_coefficient:
                dropped.append((variable.id, row.id))
    audit["dropped_links"] = dropped
    alight: dict[str, set[str]] = defaultdict(set)
    if config.alight_links:
        for variable in source.variables:
            if variable.visit_index == variable.alight_visit_index and variable.id in projection:
                alight[variable.arc_id].add(projection[variable.id])
    alight_rows = tuple((a, tuple(sorted(vs)), float(prepared.problem.artifact.config.cabin_capacity))
                        for a, vs in sorted(alight.items()))
    audit.update({"source_variables": len(source.variables), "algebra_variables": len(domain.variables),
                  "source_row_families": {"equalities": len(source.equality_rows), "demand": len(source.demand_rows),
                                          "capacity": len(source.capacity_rows), "links": len(source.variables)},
                  "algebra_row_families": {"equalities": len(domain.equality_rows), "demand": len(domain.demand_rows),
                                           "capacity": len(domain.capacity_rows), "links": len(domain.variables)-len(dropped),
                                           "alight": len(alight_rows)}})
    fingerprint = sha256(json.dumps({
        "source": source.fingerprint, "algebra": domain.fingerprint,
        "config": asdict(config), "projection": sorted(projection.items()),
        "dropped_links": dropped, "alight_rows": alight_rows,
    }, sort_keys=True).encode()).hexdigest()
    return DddPreparedArcFlowPassengers(
        source, domain, config, tuple(sorted(projection.items())), tuple(dropped),
        alight_rows, json.dumps(audit, sort_keys=True), fingerprint,
    )


def _destination_flows(domain, prepared, deadline):
    """Sum compatible commodity conservation rows, retaining separate boarding.

    A shared variable is the SUM of the original non-boarding variables. Its
    coefficient occurs once in each summed conservation/capacity equation.
    Boarding variables keep demand debits and release-dependent arc support.
    """
    arcs = {a.id: a for a in prepared.arcs}
    variables = domain.variable_by_id
    blocks: list[list] = []
    supports = {}
    for flow in domain.flows:
        layers = defaultdict(set)
        for arc_id, _ in flow.variable_ids_by_arc_id:
            if arcs[arc_id].visit_index > flow.board_visit_index:
                layers[arcs[arc_id].visit_index].add(arc_id)
        supports[flow.candidate_id] = layers
    for flow in domain.flows:
        check_ddd_arc_flow_build_deadline(deadline)
        for block in blocks:
            if (flow.cabin_id, flow.alight_visit_index) != (block[0].cabin_id, block[0].alight_visit_index):
                continue
            if all(all(
                supports[flow.candidate_id].get(i, set()) == supports[other.candidate_id].get(i, set())
                for i in range(max(flow.board_visit_index, other.board_visit_index) + 1,
                               flow.alight_visit_index + 1)
            ) for other in block):
                block.append(flow)
                break
        else:
            blocks.append([flow])
    projection = {}
    new_variables = {}
    row_terms = defaultdict(dict)
    for block_index, block in enumerate(blocks):
        for flow in block:
            for arc_id, variable_id in flow.variable_ids_by_arc_id:
                variable = variables[variable_id]
                arc = arcs[arc_id]
                new_id = (variable_id if arc.visit_index == flow.board_visit_index
                          else f"destination[{block_index},{arc_id}]")
                projection[variable_id] = new_id
                if new_id not in new_variables:
                    new_variables[new_id] = replace(variable, id=new_id)
                else:
                    previous_variable = new_variables[new_id]
                    if previous_variable.objective_coefficient != variable.objective_coefficient:
                        raise ValueError("cannot aggregate passenger variables with different costs")
                    # Sum the ORIGINAL linking bounds. In particular do not
                    # introduce the separate C alighting cut into isolated D.
                    new_variables[new_id] = replace(previous_variable,
                        upper_bound=previous_variable.upper_bound + variable.upper_bound)
                for node, coefficient in ((arc.source_node, -1.0), (arc.target_node, 1.0)):
                    if flow.board_visit_index < node[0] <= flow.alight_visit_index:
                        key = (block_index, node)
                        previous = row_terms[key].get(new_id)
                        if previous is not None and previous != coefficient:
                            raise ValueError("destination-flow aggregation crosses a state boundary")
                        row_terms[key][new_id] = coefficient
    rows = tuple(DddArcFlowPassengerEqualityRow(
        f"destination_flow[{i}]", tuple(sorted(terms.items())),
    ) for i, (_, terms) in enumerate(sorted(row_terms.items())))
    result = _refingerprint(replace(
        domain, variables=tuple(new_variables.values()), equality_rows=rows, flows=(),
        capacity_rows=tuple(replace(row, variable_ids=tuple(sorted({projection[v] for v in row.variable_ids})))
                            for row in domain.capacity_rows),
        # Boarding remains separate, so original demand rows are unchanged.
    ))
    return result, projection, [tuple(f.candidate_id for f in block) for block in blocks]
