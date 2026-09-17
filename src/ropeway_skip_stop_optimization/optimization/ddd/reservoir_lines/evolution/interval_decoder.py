"""Sequential exact no-wait insertion, with an optional waiting-candidate path.

Genes are preferred absolute dispatch ticks, not certified dispatches. A tick
already allowed is unchanged; otherwise use the next allowed tick, wrapping to
the first allowed tick. Consequently every valid no-wait genome is a fixed
point. Construction failure is not a proof about other prefix decisions.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import replace
from time import perf_counter

from ...models import DddRouteDecision
from ...reservoir_boundary import state_protection_tick, state_resource_id
from ...time_ticks import ddd_seconds_to_tick as tick
from ..dispatch_domains import TickInterval, complement_closed, merge_closed
from .decoder import decode_no_wait, minimum_dispatch_gap_tick
from .model import LineGenome, MovementEvaluation


def grid_intervals(intervals, step):
    """Closed intervals on the original dispatch grid; never round movement."""
    return tuple(TickInterval(a, b) for item in intervals
                 if (a := ((item.lower + step - 1) // step) * step)
                 <= (b := (item.upper // step) * step))


def select_tick(intervals, preferred):
    for interval in intervals:
        if preferred <= interval.upper:
            return max(preferred, interval.lower)
    return intervals[0].lower


class IntervalDispatchDecoder:
    def __init__(self, problem, prepared):
        self.problem, self.prepared = problem, prepared
        self.gap = minimum_dispatch_gap_tick(problem)
        self.templates = defaultdict(list)
        self.options = {o.id: o for o in problem.resolved_core.route_options}
        self.full = {}
        self.prefixes = {}
        for template in prepared.templates:
            self.templates[template.pattern_id].append(template)
            self.full[template.id] = self._intervals(template, len(template.visits))

    def _intervals(self, template, first_wait):
        by_resource = defaultdict(list)
        for item in template.resource_intervals:
            if item.visit_index > first_wait:
                continue
            if item.visit_index == first_wait:
                option = self.options[item.option_id]
                # With fixed entry and nonnegative extension, the no-wait
                # interval is contained in EVERY possible waiting occupancy.
                visit_start = template.visits[item.visit_index].start_tick
                resource = self.problem.resolved_core.resources_by_id[item.resource_id]
                usage = next(u for u in option.resource_usages
                             if u.resource_id == item.resource_id
                             and visit_start + u.follower_enter_offset_tick == item.start_tick
                             and visit_start + u.leader_clear_offset_tick
                             + u.separation_after_tick(resource.minimum_headway_tick) == item.end_tick)
                if usage.follower_enter_wait_coefficient != 0 or usage.leader_clear_wait_coefficient < 0:
                    continue
            by_resource[item.resource_id].append((item.start_tick, item.end_tick))
        for i, (state, offset) in enumerate(template.state_event_offsets):
            if i <= first_wait:
                by_resource[state_resource_id(self.problem, state)].append(
                    (offset, offset + state_protection_tick(self.problem, state)))
        return {key: tuple(sorted(values)) for key, values in by_resource.items()}

    def _wait_thresholds(self, template):
        policy = self.problem.waiting_policy
        step = tick(policy.step_seconds or 0.000001)
        release = tick(policy.earliest_wait_time_seconds)
        return tuple((v.visit_index, release - v.platform_exit_tick)
                     for v in template.visits
                     if v.decision is DddRouteDecision.STOP
                     and v.platform_exit_tick is not None
                     and tick(policy.maximum_wait_seconds(v.station_id)) >= step)

    def prefix(self, template, dispatch):
        first = next((i for i, threshold in self._wait_thresholds(template)
                      if dispatch >= threshold), len(template.visits))
        key = template.id, first
        if key not in self.prefixes:
            self.prefixes[key] = self._intervals(template, first)
        return self.prefixes[key]

    def allowed(self, pattern, lower, upper, reservations, *, prefix_only=False, deadline=None):
        """All feasible dispatch ticks against reservations, or necessary prefix ticks.

        All resources and all previously inserted cabins participate, including
        delayed resource entries and final port returns. No template-pair table.
        """
        from .evaluator import EvaluationDeadline
        output = []
        for template in self.templates[pattern]:
            lo = max(lower, template.minimum_dispatch_tick)
            hi = min(upper, template.maximum_dispatch_tick)
            if lo > hi:
                continue
            boundaries = {lo, hi + 1}
            if prefix_only:
                boundaries.update(t for _, t in self._wait_thresholds(template) if lo < t <= hi)
            boundaries = sorted(boundaries)
            for a, b in zip(boundaries, boundaries[1:]):
                uses = self.prefix(template, a) if prefix_only else self.full[template.id]
                forbidden = []
                for resource, relative in uses.items():
                    if deadline is not None and perf_counter() >= deadline:
                        raise EvaluationDeadline
                    for s, e in reservations.get(resource, ()):
                        for start, end in relative:
                            # [d+start,d+end) intersects [s,e) iff
                            # s-end < d < e-start. Boundaries may touch.
                            f_lo, f_hi = max(a, s-end+1), min(b-1, e-start-1)
                            if f_lo <= f_hi:
                                forbidden.append((f_lo, f_hi))
                output.extend(complement_closed(forbidden, a, b-1))
        merged = merge_closed((x.lower, x.upper) for x in output)
        return grid_intervals(merged, self.prepared.dispatch_step_tick)

    @staticmethod
    def reserve(reservations, relative, dispatch):
        for resource, values in relative.items():
            reservations[resource].extend((dispatch+a, dispatch+b) for a, b in values)

    def decode(self, genome, *, allow_waiting_candidate=False,
               waiting_construction="no_wait_first", deadline=None):
        if waiting_construction not in ("no_wait_first", "prefix_first"):
            raise ValueError("unknown waiting construction policy")
        if waiting_construction == "prefix_first" and not allow_waiting_candidate:
            raise ValueError("prefix_first requires waiting candidates")
        started = perf_counter()
        p = self.prepared
        genome.validate(maximum_cabins=p.maximum_cabins, minimum_gap_tick=self.gap,
                        window_tick=p.dispatch_window_end_tick, dispatch_step_tick=p.dispatch_step_tick)
        if any(pattern not in self.templates for pattern in genome.pattern_ids):
            raise ValueError("interval genome contains a pattern outside the prepared catalog")
        preferred = genome.dispatch_ticks(self.gap)
        full, prefixes = defaultdict(list), defaultdict(list)
        dispatches, steps = [], []
        needs_waiting = False
        for i, pattern in enumerate(genome.pattern_ids):
            lower = dispatches[-1] + self.gap if dispatches else 0
            upper = p.dispatch_window_end_tick - (genome.fleet_size-i-1)*self.gap
            if waiting_construction == "prefix_first":
                # A later no-wait-compatible departure must not displace an
                # earlier prefix-compatible proposal. CP owns all post-prefix
                # resource feasibility; this construction makes no such claim.
                allowed = self.allowed(pattern, lower, upper, prefixes, prefix_only=True, deadline=deadline)
                kind = "necessary_prefix"
                needs_waiting = needs_waiting or bool(allowed)
            else:
                allowed = self.allowed(pattern, lower, upper, full, deadline=deadline)
                kind = "no_wait"
                if not allowed and allow_waiting_candidate:
                    allowed = self.allowed(pattern, lower, upper, prefixes, prefix_only=True, deadline=deadline)
                    kind = "necessary_prefix"
                    needs_waiting = needs_waiting or bool(allowed)
            if not allowed:
                stats = {"waiting_construction": waiting_construction, "status": "CONSTRUCTION_FAILED", "failed_cabin": i,
                         "completed_cabins": i, "partial_dispatch_ticks": dispatches,
                         "steps": steps, "global_infeasibility_proof": False,
                         "seconds": perf_counter()-started}
                return MovementEvaluation(genome, False, None, (), 0, 0,
                                          stats["seconds"], "no dispatch slot for this constructed prefix"), stats
            chosen = select_tick(allowed, preferred[i])
            template = next(t for t in self.templates[pattern]
                            if t.minimum_dispatch_tick <= chosen <= t.maximum_dispatch_tick)
            self.reserve(full, self.full[template.id], chosen)
            self.reserve(prefixes, self.prefix(template, chosen), chosen)
            dispatches.append(chosen)
            steps.append({"cabin": i, "kind": kind, "allowed_intervals": len(allowed),
                          "allowed_ticks": sum((x.upper-x.lower)//p.dispatch_step_tick+1 for x in allowed),
                          "preferred_tick": preferred[i], "dispatch_tick": chosen})
        decoded = LineGenome(genome.pattern_ids, dispatches[0] if dispatches else 0,
                             tuple(b-a-self.gap for a,b in zip(dispatches, dispatches[1:])))
        movement = decode_no_wait(self.problem, p, decoded)
        elapsed = perf_counter()-started
        movement = replace(movement, decode_seconds=elapsed)
        if not needs_waiting and not movement.feasible:
            raise RuntimeError("interval insertion disagrees with independent no-wait validation")
        return movement, {"waiting_construction": waiting_construction, "status": "NO_WAIT_VALID" if movement.feasible else "WAITING_CANDIDATE",
                          "steps": steps, "completed_cabins": len(dispatches),
                          "seconds": elapsed, "input_identity": genome.identity,
                          "decoded_identity": decoded.identity,
                          "changed_dispatches": sum(a != b for a,b in zip(preferred, dispatches))}
