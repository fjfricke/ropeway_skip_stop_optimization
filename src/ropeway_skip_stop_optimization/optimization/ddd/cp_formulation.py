"""Opt-in CP formulations and solver-independent, conservative preprocessing."""

from dataclasses import dataclass, asdict
from enum import StrEnum
from .time_ticks import ddd_seconds_to_tick as tick
from .route_topology import unique_stop_route_option


class DddCpFormulationProfile(StrEnum):
    LEGACY = "legacy"
    HINTS = "hints"
    TEMPORAL = "temporal"
    PASSENGER_LINKS = "passenger_links"
    JOURNEY_BOUNDS = "journey_bounds"
    STRENGTHENED = "strengthened"


@dataclass(frozen=True)
class DddCpFormulationConfig:
    profile: str = "legacy"
    resource_encoding: str = "legacy"
    movement_encoding: str = "legacy"

    def validate(self, backend="cp_sat"):
        if self.profile not in set(DddCpFormulationProfile):
            raise ValueError("unknown CP formulation profile")
        if self.resource_encoding not in ("legacy", "compact_fixed", "merged_exit"):
            raise ValueError("unknown CP resource encoding")
        if self.movement_encoding not in ("legacy", "native_visits"):
            raise ValueError("unknown IBM movement encoding")
        if backend == "cp_sat" and self.movement_encoding != "legacy":
            raise ValueError("native_visits requires IBM")
        if backend == "ibm" and self.resource_encoding != "legacy":
            raise ValueError("resource encoding requires CP-SAT")

    def enabled(self, name):
        return self.profile in (name, "strengthened")

    @property
    def legacy(self):
        return self == DddCpFormulationConfig()


@dataclass(frozen=True)
class CpVisitBounds:
    cabin_id: int
    visit_index: int
    earliest: int
    latest: int
    minimum_duration: int
    return_after: int


@dataclass(frozen=True)
class CpRideBounds:
    candidate_id: str
    minimum_arrival: int
    minimum_journey: int
    exclusion: str | None
    earliest_return: int | None


@dataclass(frozen=True)
class PreparedCpStructure:
    visits: tuple[CpVisitBounds, ...]
    rides: tuple[CpRideBounds, ...]
    boarding: tuple
    alighting: tuple
    onboard: tuple
    analytical_lower_bound: int

    @property
    def visit_map(self):
        return {(v.cabin_id, v.visit_index): v for v in self.visits}

    @property
    def ride_map(self):
        return {r.candidate_id: r for r in self.rides}

    @property
    def manifest(self):
        return asdict(self)


def prepare_cp_structure(movement, passenger_build, states_by_cabin, *, reservoir=None):
    """Bounds ignore conflicts, hence remain optimistic. Canonical IDs untouched."""
    from collections import defaultdict

    options = movement.route_options_by_state_id
    fastest = {s: min(o.duration_tick for o in os) for s, os in options.items()}
    stops = {
        s: unique_stop_route_option(movement, s, error_context="CP bounds")
        for s in options
    }
    starts = {s.cabin_id: s.time_tick for s in movement.starts}

    def return_after(state):
        if reservoir is None:
            return 0
        total, seen = 0, set()
        while state != reservoir.entry_state_id:
            if state in seen:
                raise ValueError("no return to reservoir port")
            seen.add(state)
            total += fastest[state]
            state = options[state][0].to_state_id
        return total

    visits, prefixes = [], {}
    for k, states in states_by_cabin.items():
        prefix = [
            starts[k] if reservoir is None else tick(reservoir.dispatch_start_seconds)
        ]
        for i, state in enumerate(states[:-1]):
            remaining = return_after(options[state][0].to_state_id)
            latest = movement.operational_end_tick
            if reservoir is not None:
                latest -= fastest[state] + remaining
            visits.append(
                CpVisitBounds(k, i, prefix[-1], latest, fastest[state], remaining)
            )
            prefix.append(prefix[-1] + fastest[state])
        prefixes[k] = prefix
    groups = {g.id: g for g in passenger_build.demand_groups}
    rides, board, alight, onboard, minima = (
        [],
        defaultdict(list),
        defaultdict(list),
        defaultdict(list),
        {},
    )
    for q in passenger_build.ride_candidates:
        k, b, a = q.cabin_id, q.board_visit_index, q.alight_visit_index
        states = states_by_cabin[k]
        bo, ao = stops[states[b]], stops[states[a]]
        release = tick(groups[q.demand_group_id].release_time_seconds)
        delta = (
            bo.duration_tick
            + sum(fastest[states[i]] for i in range(b + 1, a))
            + tick(ao.platform_entry_offset_seconds)
        )
        minimum = max(
            prefixes[k][b] + delta,
            release + delta - tick(bo.platform_exit_offset_seconds),
        )
        returned = (
            None
            if reservoir is None
            else minimum
            - tick(ao.platform_entry_offset_seconds)
            + ao.duration_tick
            + return_after(ao.to_state_id)
        )
        exclusion = (
            "service_horizon"
            if minimum > movement.passenger_service_end_tick
            else "return_horizon"
            if returned is not None and returned > movement.operational_end_tick
            else None
        )
        journey = max(0, minimum - release)
        rides.append(CpRideBounds(q.id, minimum, journey, exclusion, returned))
        if exclusion is None:
            minima[q.demand_group_id] = min(
                minima.get(q.demand_group_id, journey), journey
            )
        board[k, b].append(q.id)
        alight[k, a].append(q.id)
        for i in range(b, a):
            onboard[k, i].append(q.id)
    lower = 0
    for g in groups.values():
        penalty = max(
            0, movement.passenger_service_end_tick - tick(g.release_time_seconds)
        )
        lower += g.count * min(penalty, minima.get(g.id, penalty))

    def pack(d):
        return tuple((k, tuple(v)) for k, v in sorted(d.items()))

    return PreparedCpStructure(
        tuple(visits), tuple(rides), pack(board), pack(alight), pack(onboard), lower
    )


def apply_cp_temporal(built, prepared, *, reservoir=False):
    for v in prepared.visits:
        active = built.active_by_cabin[v.cabin_id][v.visit_index]
        time = built.time_by_cabin[v.cabin_id][v.visit_index]
        if v.earliest > v.latest:
            built.model.add(active == 0)
        else:
            built.model.add(time >= v.earliest).only_enforce_if(active)
            built.model.add(time <= v.latest).only_enforce_if(active)
        if reservoir:
            wait = built.wait_steps_by_key[v.cabin_id, v.visit_index]
            built.model.add(
                time + built.waiting_step_tick * wait <= v.latest
            ).only_enforce_if(active)


def formulation_identity(config, prepared):
    if config.legacy:
        return {}
    return {
        "formulation": asdict(config),
        "prepared_structure": None if prepared is None else prepared.manifest,
    }


def add_formulation_arguments(parser, backend="cp_sat"):
    parser.add_argument(
        "--formulation-profile", choices=list(DddCpFormulationProfile), default="legacy"
    )
    if backend == "cp_sat":
        parser.add_argument(
            "--resource-encoding",
            choices=["legacy", "compact_fixed", "merged_exit"],
            default="legacy",
        )
    else:
        parser.add_argument(
            "--movement-encoding", choices=["legacy", "native_visits"], default="legacy"
        )


def formulation_from_args(args):
    return DddCpFormulationConfig(
        args.formulation_profile,
        getattr(args, "resource_encoding", "legacy"),
        getattr(args, "movement_encoding", "legacy"),
    )
