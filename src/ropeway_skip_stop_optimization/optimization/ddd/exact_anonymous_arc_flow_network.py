from __future__ import annotations

from dataclasses import dataclass, replace
from hashlib import sha256
import json

from ropeway_skip_stop_optimization.optimization.ddd.arc_flow_network import (
    DddArcFlowResourceClique,
    DddArcFlowResourceInterval,
    build_ddd_arc_flow_resource_cliques_from_intervals,
)
from ropeway_skip_stop_optimization.optimization.ddd.arc_flow_preparation import (
    DddPreparedArcFlowProblem,
)
from ropeway_skip_stop_optimization.optimization.ddd.models import DddFixedStart


@dataclass(frozen=True, order=True, slots=True)
class DddExactAnonymousNode:
    """One exact physical entry/merge state at one integer time tick."""

    state_id: str
    time_tick: int

    @property
    def id(self) -> str:
        return f"node::{self.state_id}::t{self.time_tick}"

    def validate(self) -> None:
        if not self.state_id or self.time_tick < 0:
            raise ValueError("exact anonymous node identity is invalid")


@dataclass(frozen=True, order=True, slots=True)
class DddExactAnonymousStartToken:
    """A fixed physical start slot; cabin labels end at this adapter boundary."""

    id: str
    canonical_cabin_id: int
    start: DddFixedStart

    def validate(self) -> None:
        self.start.validate()
        if not self.id or self.canonical_cabin_id != self.start.cabin_id:
            raise ValueError("exact anonymous start token is inconsistent")


@dataclass(frozen=True, slots=True)
class DddExactAnonymousArc:
    id: str
    source_state_id: str
    source_tick: int
    option_id: str
    target_state_id: str
    target_tick: int
    source_node_id: str | None
    target_node_id: str | None
    source_token_id: str | None = None
    resource_intervals: tuple[DddArcFlowResourceInterval, ...] = ()
    represented_labeled_arc_ids: tuple[str, ...] = ()

    @property
    def is_source(self) -> bool:
        return self.source_token_id is not None

    @property
    def is_terminal(self) -> bool:
        return self.target_node_id is None

    def validate(self) -> None:
        if (
            not self.id
            or not self.source_state_id
            or not self.target_state_id
            or not self.option_id
            or self.source_tick < 0
            or self.target_tick <= self.source_tick
        ):
            raise ValueError("exact anonymous arc identity or timing is invalid")
        if (self.source_token_id is None) == (self.source_node_id is None):
            raise ValueError(
                "exact anonymous arc needs exactly one source node or start token"
            )
        if not self.represented_labeled_arc_ids:
            raise ValueError("exact anonymous arc needs labeled provenance")
        if tuple(sorted(set(self.represented_labeled_arc_ids))) != (
            self.represented_labeled_arc_ids
        ):
            raise ValueError("exact anonymous arc provenance must be sorted and unique")
        for interval in self.resource_intervals:
            interval.validate()
            if interval.arc_id != self.id:
                raise ValueError(
                    "exact anonymous resource interval references another arc"
                )


@dataclass(frozen=True, slots=True)
class DddExactAnonymousArcFlowNetwork:
    """Exact no-wait fixed-start network after quotienting cabin/visit labels."""

    problem_fingerprint: str
    start_tokens: tuple[DddExactAnonymousStartToken, ...]
    nodes: tuple[DddExactAnonymousNode, ...]
    arcs: tuple[DddExactAnonymousArc, ...]
    resource_cliques: tuple[DddArcFlowResourceClique, ...]
    fingerprint: str

    @property
    def node_by_id(self) -> dict[str, DddExactAnonymousNode]:
        return {node.id: node for node in self.nodes}

    @property
    def arc_by_id(self) -> dict[str, DddExactAnonymousArc]:
        return {arc.id: arc for arc in self.arcs}

    @property
    def source_arcs(self) -> tuple[DddExactAnonymousArc, ...]:
        return tuple(arc for arc in self.arcs if arc.is_source)

    @property
    def movement_arcs(self) -> tuple[DddExactAnonymousArc, ...]:
        return tuple(arc for arc in self.arcs if not arc.is_source)

    @property
    def terminal_arcs(self) -> tuple[DddExactAnonymousArc, ...]:
        return tuple(arc for arc in self.arcs if arc.is_terminal)

    def validate(self) -> None:
        if not self.problem_fingerprint or not self.fingerprint:
            raise ValueError("exact anonymous network fingerprints must be nonempty")
        for token in self.start_tokens:
            token.validate()
        for node in self.nodes:
            node.validate()
        for arc in self.arcs:
            arc.validate()
        token_ids = tuple(token.id for token in self.start_tokens)
        node_ids = tuple(node.id for node in self.nodes)
        arc_ids = tuple(arc.id for arc in self.arcs)
        if not token_ids or len(set(token_ids)) != len(token_ids):
            raise ValueError("exact anonymous start tokens must be nonempty and unique")
        if len(set(node_ids)) != len(node_ids) or len(set(arc_ids)) != len(arc_ids):
            raise ValueError("exact anonymous node and arc IDs must be unique")
        known_tokens = set(token_ids)
        known_nodes = set(node_ids)
        known_arcs = set(arc_ids)
        if any(
            (
                arc.source_token_id is not None
                and arc.source_token_id not in known_tokens
            )
            or (
                arc.source_node_id is not None and arc.source_node_id not in known_nodes
            )
            or (
                arc.target_node_id is not None and arc.target_node_id not in known_nodes
            )
            for arc in self.arcs
        ):
            raise ValueError("exact anonymous arc references an unknown endpoint")
        if any(
            not set(arc_id for arc_id, _ in clique.coefficients) <= known_arcs
            for clique in self.resource_cliques
        ):
            raise ValueError("exact anonymous clique references an unknown arc")
        source_tokens = {arc.source_token_id for arc in self.source_arcs}
        if source_tokens != known_tokens:
            raise ValueError("every exact anonymous start token needs a source arc")
        if not self.terminal_arcs:
            raise ValueError("exact anonymous network needs terminal arcs")
        if self.fingerprint != _network_fingerprint(self):
            raise ValueError("exact anonymous network fingerprint is inconsistent")


@dataclass(frozen=True, slots=True)
class DddExactAnonymousArcFlowNetworkBuilder:
    """Quotient the complete labeled DAG by exact physical state and time."""

    def build(
        self,
        prepared: DddPreparedArcFlowProblem,
    ) -> DddExactAnonymousArcFlowNetwork:
        prepared.validate()
        token_by_cabin = {
            network.cabin_id: DddExactAnonymousStartToken(
                id=f"start_slot::{index}",
                canonical_cabin_id=network.cabin_id,
                start=network.start,
            )
            for index, network in enumerate(prepared.networks)
        }
        nodes: dict[str, DddExactAnonymousNode] = {}
        arcs_by_key: dict[tuple[object, ...], DddExactAnonymousArc] = {}
        for network in prepared.networks:
            for labeled in network.arcs:
                if not labeled.source_active or labeled.option_id is None:
                    continue
                source_state = network.state_ids[labeled.visit_index]
                target_state = network.state_ids[labeled.visit_index + 1]
                source_token = (
                    token_by_cabin[network.cabin_id]
                    if labeled.visit_index == 0
                    else None
                )
                source_node = None
                if source_token is None:
                    source_node = DddExactAnonymousNode(
                        source_state,
                        labeled.source_tick,
                    )
                    nodes[source_node.id] = source_node
                target_node = None
                if labeled.target_active:
                    target_node = DddExactAnonymousNode(
                        target_state,
                        labeled.target_tick,
                    )
                    nodes[target_node.id] = target_node
                interval_signature = tuple(
                    (
                        interval.resource_id,
                        interval.usage_index,
                        interval.enter_tick,
                        interval.clear_with_headway_tick,
                    )
                    for interval in labeled.resource_intervals
                )
                key = (
                    None if source_token is None else source_token.id,
                    None if source_node is None else source_node.id,
                    None if target_node is None else target_node.id,
                    source_state,
                    labeled.source_tick,
                    labeled.option_id,
                    target_state,
                    labeled.target_tick,
                    interval_signature,
                )
                existing = arcs_by_key.get(key)
                if existing is not None:
                    arcs_by_key[key] = replace(
                        existing,
                        represented_labeled_arc_ids=tuple(
                            sorted((*existing.represented_labeled_arc_ids, labeled.id))
                        ),
                    )
                    continue
                arc_id = f"exact_arc::{_stable_digest(key)}"
                intervals = tuple(
                    DddArcFlowResourceInterval(
                        resource_id=interval.resource_id,
                        arc_id=arc_id,
                        usage_index=interval.usage_index,
                        enter_tick=interval.enter_tick,
                        clear_with_headway_tick=interval.clear_with_headway_tick,
                    )
                    for interval in labeled.resource_intervals
                )
                arcs_by_key[key] = DddExactAnonymousArc(
                    id=arc_id,
                    source_state_id=source_state,
                    source_tick=labeled.source_tick,
                    option_id=labeled.option_id,
                    target_state_id=target_state,
                    target_tick=labeled.target_tick,
                    source_node_id=None if source_node is None else source_node.id,
                    target_node_id=None if target_node is None else target_node.id,
                    source_token_id=(None if source_token is None else source_token.id),
                    resource_intervals=intervals,
                    represented_labeled_arc_ids=(labeled.id,),
                )
        arcs = tuple(sorted(arcs_by_key.values(), key=lambda item: item.id))
        incomplete = DddExactAnonymousArcFlowNetwork(
            problem_fingerprint=prepared.problem.fingerprint,
            start_tokens=tuple(
                token_by_cabin[network.cabin_id] for network in prepared.networks
            ),
            nodes=tuple(sorted(nodes.values())),
            arcs=arcs,
            resource_cliques=build_ddd_arc_flow_resource_cliques_from_intervals(
                tuple(interval for arc in arcs for interval in arc.resource_intervals)
            ),
            fingerprint="",
        )
        result = replace(incomplete, fingerprint=_network_fingerprint(incomplete))
        result.validate()
        return result


def _stable_digest(value: object) -> str:
    return sha256(
        json.dumps(value, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()[:20]


def _network_fingerprint(network: DddExactAnonymousArcFlowNetwork) -> str:
    payload = {
        "problem": network.problem_fingerprint,
        "starts": [
            (
                token.id,
                token.canonical_cabin_id,
                token.start.state_id,
                token.start.time_tick,
            )
            for token in network.start_tokens
        ],
        "nodes": [(node.state_id, node.time_tick) for node in network.nodes],
        "arcs": [
            (
                arc.id,
                arc.source_state_id,
                arc.source_tick,
                arc.option_id,
                arc.target_state_id,
                arc.target_tick,
                arc.source_node_id,
                arc.target_node_id,
                arc.source_token_id,
                tuple(
                    (
                        item.resource_id,
                        item.usage_index,
                        item.enter_tick,
                        item.clear_with_headway_tick,
                    )
                    for item in arc.resource_intervals
                ),
                arc.represented_labeled_arc_ids,
            )
            for arc in network.arcs
        ],
        "cliques": [
            (item.id, item.resource_id, item.anchor_tick, item.coefficients)
            for item in network.resource_cliques
        ],
    }
    return sha256(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()
