"""Shared builders and certificate interface for passenger formulations."""

from dataclasses import dataclass
import gurobipy as gp
from gurobipy import GRB

from .network import check
from .passenger_structure import prepare_passengers
from . import passenger_certificate as certificate


@dataclass
class PassengerModel:
    network: object
    structure: object
    variables: dict
    objective: object

    def reference_values(self, plan, paths):
        return certificate.reference_values(self, plan, paths)

    def extract_assignment(self, value, paths):
        return certificate.extract_assignment(self, value, paths)


class PassengerBuilder:
    encoding = "legacy"

    def build(self, network, model, movement, row, config, deadline=None):
        if config.passenger_encoding != self.encoding:
            raise ValueError("passenger builder/encoding mismatch")
        st = prepare_passengers(network, config, deadline)
        variables = {}
        for spec in st.variables:
            check(deadline)
            vtype = (
                GRB.INTEGER
                if config.passenger_integrality == "all" or spec.boarding
                else GRB.CONTINUOUS
            )
            name = (
                f"f[{spec.key[1]},{spec.key[2]}]"
                if spec.key[0] == "g"
                else f"{spec.key[0]}[{spec.key[1]},{spec.key[2]}]"
            )
            variables[spec.key] = model.addVar(
                lb=0, ub=spec.upper, vtype=vtype, name=name
            )
        for r in st.rows:
            expr = gp.quicksum(c * variables[k] for k, c in r.terms)
            row(expr == r.rhs if r.sense == "=" else expr <= r.rhs, r.family)
        for aid, terms in st.loads:
            row(
                gp.quicksum(c * variables[k] for k, c in terms)
                <= network.problem.cabin_capacity * movement[aid],
                "capacity",
            )
        objective = sum(g.count for g in st.groups) - gp.quicksum(
            variables[k] for k in st.alighting
        )
        return PassengerModel(network, st, variables, objective)


class OdFlowPassengerBuilder(PassengerBuilder):
    encoding = "od_flow"


class OdQueuePassengerBuilder(PassengerBuilder):
    encoding = "od_queue"


def build_passengers(network, model, movement, row, config, deadline=None):
    builder = {
        "legacy": PassengerBuilder,
        "od_flow": OdFlowPassengerBuilder,
        "od_queue": OdQueuePassengerBuilder,
    }[config.passenger_encoding]()
    return builder.build(network, model, movement, row, config, deadline)
