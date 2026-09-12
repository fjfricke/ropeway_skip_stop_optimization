from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass

from ..cp_sat_certificate import stable_fingerprint
from ..models import DddRouteDecision
from ..reservoir_cp_sat_problem import DddReservoirCpSatProblem
from ..time_ticks import ddd_seconds_to_tick
from .catalog import LinePattern, line_patterns, option_for_pattern
from .config import ReservoirLineConfig
from .dispatch_domains import (
    TickInterval,
    complement_closed,
    forbidden_delta_for_half_open_intervals,
    merge_closed,
)


@dataclass(frozen=True)
class RelativeResourceInterval:
    resource_id: str
    start_tick: int
    end_tick: int
    visit_index: int
    option_id: str


@dataclass(frozen=True)
class RelativeVisit:
    visit_index: int
    state_id: str
    station_id: str
    option_id: str
    decision: DddRouteDecision
    start_tick: int
    platform_entry_tick: int | None
    platform_exit_tick: int | None


@dataclass(frozen=True)
class LineTemplate:
    id: str
    pattern_id: str
    stop_station_ids: frozenset[str]
    laps: int
    duration_tick: int
    minimum_dispatch_tick: int
    maximum_dispatch_tick: int
    route_option_ids: tuple[str, ...]
    visits: tuple[RelativeVisit, ...]
    resource_intervals: tuple[RelativeResourceInterval, ...]
    state_event_offsets: tuple[tuple[str, int], ...]


@dataclass(frozen=True)
class TemplatePairDomain:
    first_template_id: str
    second_template_id: str
    allowed_delta: tuple[TickInterval, ...]
    forbidden_delta: tuple[TickInterval, ...]


@dataclass(frozen=True)
class PreparedLineProblem:
    problem_fingerprint: str
    model_fingerprint: str
    maximum_cabins: int
    dispatch_window_end_tick: int
    dispatch_step_tick: int
    templates: tuple[LineTemplate, ...]
    pair_domains: tuple[TemplatePairDomain, ...]
    stats: dict

    @property
    def templates_by_id(self):
        return {template.id: template for template in self.templates}

    @property
    def pair_domains_by_id(self):
        return {
            (item.first_template_id, item.second_template_id): item
            for item in self.pair_domains
        }

    @property
    def payload(self):
        payload = asdict(self)
        for template in payload["templates"]:
            template["stop_station_ids"] = sorted(template["stop_station_ids"])
        return payload


def _template(
    problem: DddReservoirCpSatProblem,
    pattern: LinePattern,
    laps: int,
    window_end_tick: int,
) -> LineTemplate | None:
    core = problem.resolved_core
    state = problem.entry_state_id
    now = 0
    visits, route_ids, protected = [], [], []
    events: list[tuple[str, int]] = []
    for visit_index in range(laps * len(problem.cycle_states)):
        option = option_for_pattern(problem, state, pattern)
        entry = (
            None
            if option.platform_entry_offset_seconds is None
            else now + ddd_seconds_to_tick(option.platform_entry_offset_seconds)
        )
        exit_ = (
            None
            if option.platform_exit_offset_seconds is None
            else now + ddd_seconds_to_tick(option.platform_exit_offset_seconds)
        )
        visits.append(
            RelativeVisit(
                visit_index,
                state,
                option.station_id,
                option.id,
                option.decision,
                now,
                entry,
                exit_,
            )
        )
        events.append((state, now))
        route_ids.append(option.id)
        for usage in option.resource_usages:
            resource = core.resources_by_id[usage.resource_id]
            start = now + usage.follower_enter_offset_tick
            end = (
                now
                + usage.leader_clear_offset_tick
                + usage.separation_after_tick(resource.minimum_headway_tick)
            )
            if end <= start:
                raise ValueError("line template contains an empty resource interval")
            protected.append(
                RelativeResourceInterval(
                    usage.resource_id, start, end, visit_index, option.id
                )
            )
        state = option.to_state_id
        now += option.duration_tick
    if state != problem.entry_state_id:
        raise AssertionError("complete line template did not return to reservoir")
    events.append((state, now))

    # A single cabin must not collide with itself; this is independent of dispatch.
    by_resource: dict[str, list[RelativeResourceInterval]] = defaultdict(list)
    for interval in protected:
        by_resource[interval.resource_id].append(interval)
    for intervals in by_resource.values():
        previous_end = -1
        for interval in sorted(intervals, key=lambda item: item.start_tick):
            if interval.start_tick < previous_end:
                return None
            previous_end = max(previous_end, interval.end_tick)
    seen_events = set()
    for event in events:
        if event in seen_events:
            return None
        seen_events.add(event)

    minimum = max(0, ddd_seconds_to_tick(problem.return_start_seconds) - now)
    maximum = min(
        window_end_tick,
        ddd_seconds_to_tick(problem.dispatch_end_seconds),
        core.operational_end_tick - now,
    )
    if minimum > maximum:
        return None
    return LineTemplate(
        id=f"{pattern.id}__laps_{laps}",
        pattern_id=pattern.id,
        stop_station_ids=pattern.stop_station_ids,
        laps=laps,
        duration_tick=now,
        minimum_dispatch_tick=minimum,
        maximum_dispatch_tick=maximum,
        route_option_ids=tuple(route_ids),
        visits=tuple(visits),
        resource_intervals=tuple(protected),
        state_event_offsets=tuple(events),
    )


def _pair_domain(first: LineTemplate, second: LineTemplate, maximum_delta: int):
    forbidden: list[tuple[int, int]] = []
    by_first: dict[str, list[RelativeResourceInterval]] = defaultdict(list)
    by_second: dict[str, list[RelativeResourceInterval]] = defaultdict(list)
    for item in first.resource_intervals:
        by_first[item.resource_id].append(item)
    for item in second.resource_intervals:
        by_second[item.resource_id].append(item)
    for resource_id in by_first.keys() & by_second.keys():
        for a in by_first[resource_id]:
            for b in by_second[resource_id]:
                interval = forbidden_delta_for_half_open_intervals(
                    a.start_tick, a.end_tick, b.start_tick, b.end_tick
                )
                forbidden.append((interval.lower, interval.upper))
    first_events: dict[str, list[int]] = defaultdict(list)
    second_events: dict[str, list[int]] = defaultdict(list)
    for state, tick in first.state_event_offsets:
        first_events[state].append(tick)
    for state, tick in second.state_event_offsets:
        second_events[state].append(tick)
    for state in first_events.keys() & second_events.keys():
        for a in first_events[state]:
            for b in second_events[state]:
                forbidden.append((a - b, a - b))
    allowed = complement_closed(forbidden, 1, maximum_delta)
    clipped = []
    for interval in merge_closed(forbidden):
        lower = max(1, interval.lower)
        upper = min(maximum_delta, interval.upper)
        if lower <= upper:
            clipped.append(TickInterval(lower, upper))
    clipped_forbidden = tuple(clipped)
    return TemplatePairDomain(first.id, second.id, allowed, clipped_forbidden)


def prepare_line_problem(
    problem: DddReservoirCpSatProblem, config: ReservoirLineConfig
) -> PreparedLineProblem:
    problem.validate()
    config.validate(problem.available_fleet_count)
    if ddd_seconds_to_tick(problem.dispatch_start_seconds) != 0:
        raise ValueError("reservoir line v1 requires first dispatch domain to start at zero")
    # A bounded-wait source domain is accepted because zero waiting is always a
    # legal member of it. The prepared/model fingerprints and reported proof
    # scope explicitly identify that V1 fixes every wait to zero.
    step = ddd_seconds_to_tick(problem.dispatch_step_seconds)
    end = config.dispatch_window_end_tick
    if end > ddd_seconds_to_tick(problem.dispatch_end_seconds):
        raise ValueError("line dispatch window exceeds the reservoir dispatch domain")
    maximum_cabins = (
        problem.available_fleet_count
        if config.maximum_cabins is None
        else config.maximum_cabins
    )

    patterns = line_patterns(problem, config.catalog_profile)
    min_cycle = sum(
        min(o.duration_tick for o in problem.resolved_core.route_options_by_state_id[s])
        for s in problem.cycle_states
    )
    max_laps = problem.resolved_core.operational_end_tick // min_cycle
    templates = tuple(
        template
        for pattern in patterns
        for laps in range(1, max_laps + 1)
        if (template := _template(problem, pattern, laps, end)) is not None
    )
    if not templates:
        raise ValueError("line catalog has no complete dispatch-return template")
    if not any(t.minimum_dispatch_tick == 0 for t in templates):
        raise ValueError("line catalog cannot dispatch its first cabin at zero")

    pair_domains = tuple(
        _pair_domain(first, second, end)
        for first in templates
        for second in templates
    )
    interval_count = sum(len(item.allowed_delta) for item in pair_domains)
    manifest = {
        "version": "reservoir_line_preparation_v1",
        "problem_fingerprint": problem.fingerprint,
        "maximum_cabins": maximum_cabins,
        "dispatch_window_end_tick": end,
        "dispatch_step_tick": step,
        "catalog_profile": config.catalog_profile.value,
        "source_waiting_domain": problem.waiting_policy.domain.value,
        "waiting_fixed_to_zero": True,
        "templates": [
            {
                **asdict(item),
                "stop_station_ids": sorted(item.stop_station_ids),
            }
            for item in templates
        ],
        "pair_domains": [asdict(item) for item in pair_domains],
    }
    return PreparedLineProblem(
        problem.fingerprint,
        stable_fingerprint(manifest),
        maximum_cabins,
        end,
        step,
        templates,
        pair_domains,
        {
            "patterns": len(patterns),
            "source_waiting_domain": problem.waiting_policy.domain.value,
            "waiting_fixed_to_zero": True,
            "templates": len(templates),
            "template_resource_intervals": sum(
                len(item.resource_intervals) for item in templates
            ),
            "template_pairs": len(pair_domains),
            "allowed_delta_intervals": interval_count,
        },
    )
