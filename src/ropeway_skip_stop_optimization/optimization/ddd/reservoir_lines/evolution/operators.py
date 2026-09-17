from __future__ import annotations

import math

import numpy as np

from .decoder import minimum_dispatch_gap_tick
from .model import LineGenome, OperatorProfile


class GenomeFactory:
    def __init__(self, problem, prepared, *, seed=0, fixed_k=None):
        self.problem, self.prepared = problem, prepared
        self.rng = np.random.default_rng(seed)
        self.patterns = tuple(sorted({t.pattern_id for t in prepared.templates}))
        self.pattern_stops = {
            pattern: next(t.stop_station_ids for t in prepared.templates if t.pattern_id == pattern)
            for pattern in self.patterns
        }
        self.origin_by_identity: dict[str, str] = {}
        self.minimum_gap = minimum_dispatch_gap_tick(problem)
        self.dispatch_step = prepared.dispatch_step_tick
        self.maximum_k = min(
            prepared.maximum_cabins,
            1 + prepared.dispatch_window_end_tick // self.minimum_gap,
        )

        self.fixed_k = fixed_k
        if fixed_k is not None and not 1 <= fixed_k <= self.maximum_k:
            raise ValueError("fixed_k must fit the fleet and dispatch window")

    def _tag(self, genome: LineGenome, origin: str) -> LineGenome:
        if self.fixed_k is not None and genome.fleet_size != self.fixed_k:
            raise ValueError("candidate does not have exactly fixed_k active cabins")
        self.origin_by_identity[genome.identity] = origin
        return genome

    def _neighbour_pattern(self, pattern: str, rng) -> str:
        stops = set(self.pattern_stops[pattern])
        neighbours = [
            candidate for candidate in self.patterns
            if len(stops.symmetric_difference(self.pattern_stops[candidate])) == 1
        ]
        return str(rng.choice(neighbours or self.patterns))

    def random(self, *, k=None, patterns=None, arrangement="random", rng=None):
        rng = rng or self.rng
        if k is None and self.fixed_k is not None:
            k = self.fixed_k
        k = int(rng.integers(1, self.maximum_k + 1)) if k is None else k
        if patterns is None:
            values = list(rng.choice(self.patterns, size=k, replace=True))
        else:
            values = list(patterns)
            if len(values) != k:
                raise ValueError("initial pattern sequence differs from requested fleet")
        if arrangement == "grouped":
            values.sort()
        elif arrangement == "alternating":
            groups = {}
            for value in values:
                groups.setdefault(value, []).append(value)
            values = []
            while groups:
                for key in sorted(tuple(groups)):
                    values.append(groups[key].pop())
                    if not groups[key]:
                        del groups[key]
        slack = self.prepared.dispatch_window_end_tick - max(0, k - 1) * self.minimum_gap
        used = (
            int(rng.integers(0, slack // self.dispatch_step + 1)) * self.dispatch_step
            if slack else 0
        )
        if k == 1:
            return self._tag(LineGenome(tuple(values), used, ()), "initial_sampler")
        cuts = sorted(
            int(x) * self.dispatch_step
            for x in rng.integers(0, used // self.dispatch_step + 1, size=k)
        )
        portions = tuple(b - a for a, b in zip((0, *cuts), (*cuts, used), strict=True))
        return self._tag(
            LineGenome(tuple(values), portions[0], portions[1:k]),
            "initial_sampler",
        )

    def from_dispatches(self, patterns, dispatches):
        if not patterns:
            return self._tag(LineGenome((), 0, ()), "from_dispatches")
        extras = tuple(
            b - a - self.minimum_gap for a, b in zip(dispatches, dispatches[1:])
        )
        genome = LineGenome(tuple(patterns), dispatches[0], extras)
        genome.validate(
            maximum_cabins=self.maximum_k,
            minimum_gap_tick=self.minimum_gap,
            window_tick=self.prepared.dispatch_window_end_tick,
            dispatch_step_tick=self.dispatch_step,
        )
        return self._tag(genome, "from_dispatches")

    def mutate(self, genome, profile: OperatorProfile, *, rng=None, forced_level=None):
        rng = rng or self.rng
        if profile is OperatorProfile.LOCAL:
            level = "local"
        elif profile is OperatorProfile.LOCAL_BLOCK:
            level = "local" if rng.random() < 0.6 else "block"
        else:
            draw = rng.random()
            level = "local" if draw < 0.5 else "block" if draw < 0.8 else "global"
        level = forced_level or level
        if level == "global":
            kind = int(rng.integers(4))
            if kind == 0:
                result = self.random(k=genome.fleet_size, arrangement="alternating", rng=rng)
                return self._tag(result, "global_patterns")
            if kind == 1:
                return self._tag(self.random(rng=rng), "global_fleet" if self.fixed_k is None else "global_fixed_restart")
            if kind == 2:
                result = self.random(k=max(1, genome.fleet_size), patterns=genome.pattern_ids, rng=rng)
                return self._tag(result, "global_dispatch")
            return self._tag(self.random(rng=rng), "global_restart")
        patterns = list(genome.pattern_ids)
        dispatches = list(genome.dispatch_ticks(self.minimum_gap))
        if not patterns:
            return self._tag(self.random(k=1, rng=rng), "local_insert")
        if level == "block":
            length = int(rng.integers(2, max(3, math.ceil(len(patterns) / 4) + 1)))
            length = min(length, len(patterns))
            start = int(rng.integers(0, len(patterns) - length + 1))
            if rng.random() < 0.5:
                patterns[start:start + length] = list(rng.choice(self.patterns, size=length))
            else:
                lower = 0 if start == 0 else dispatches[start - 1] + self.minimum_gap
                end = start + length
                upper = (self.prepared.dispatch_window_end_tick if end == len(patterns)
                         else dispatches[end] - self.minimum_gap)
                delta = int(rng.integers(
                    (lower - dispatches[start]) // self.dispatch_step,
                    (upper - dispatches[end - 1]) // self.dispatch_step + 1,
                )) * self.dispatch_step
                dispatches[start:end] = [t + delta for t in dispatches[start:end]]
            return self._tag(self.from_dispatches(patterns, dispatches), "block_local")
        kind = int(rng.integers(6 if self.fixed_k is None else 4))
        if kind == 0:
            index = int(rng.integers(len(patterns)))
            patterns[index] = self._neighbour_pattern(patterns[index], rng)
        elif kind == 1 and len(patterns) > 1:
            i = int(rng.integers(len(patterns) - 1))
            patterns[i], patterns[i + 1] = patterns[i + 1], patterns[i]
        elif kind == 2:
            total_slack = self.prepared.dispatch_window_end_tick - dispatches[-1]
            lower = -genome.phase_tick // self.dispatch_step
            upper = total_slack // self.dispatch_step
            delta = int(rng.integers(lower, upper + 1)) * self.dispatch_step
            dispatches = [x + delta for x in dispatches]
        elif kind == 3 and len(patterns) > 2:
            i = int(rng.integers(len(patterns) - 2))
            extras = list(genome.extra_gap_ticks)
            lower = -extras[i + 1] // self.dispatch_step
            upper = extras[i] // self.dispatch_step
            move = int(rng.integers(lower, upper + 1)) * self.dispatch_step
            extras[i] -= move
            extras[i + 1] += move
            return self._tag(
                LineGenome(tuple(patterns), genome.phase_tick, tuple(extras)),
                "local_gap",
            )
        elif kind == 4 and len(patterns) < self.maximum_k:
            slots = [i for i in range(len(dispatches) - 1) if dispatches[i + 1] - dispatches[i] >= 2 * self.minimum_gap]
            if slots:
                i = int(rng.choice(slots))
                dispatches.insert(i + 1, dispatches[i] + self.minimum_gap)
                patterns.insert(i + 1, str(rng.choice(self.patterns)))
            else:
                if dispatches[-1] + self.minimum_gap <= self.prepared.dispatch_window_end_tick:
                    dispatches.append(dispatches[-1] + self.minimum_gap)
                    patterns.append(str(rng.choice(self.patterns)))
                elif dispatches[0] >= self.minimum_gap:
                    dispatches.insert(0, dispatches[0] - self.minimum_gap)
                    patterns.insert(0, str(rng.choice(self.patterns)))
                else:
                    return self._tag(genome, "local_insert_unavailable")
        elif kind == 5 and len(patterns) > 1:
            i = int(rng.integers(len(patterns)))
            del patterns[i], dispatches[i]
        result = self.from_dispatches(patterns, dispatches)
        labels = (
            "local_pattern", "local_swap", "local_phase", "local_gap",
            "local_insert", "local_remove",
        )
        return self._tag(result, labels[kind])

    def transplant(self, base, donor, start, donor_start, length):
        """Transfer patterns and internal timing, preserving every outside dispatch.

        Anchor the incoming block at the original first dispatch. Reject a
        mismatching right boundary instead of retiming unrelated cabins.
        """
        times = list(base.dispatch_ticks(self.minimum_gap))
        donor_times = donor.dispatch_ticks(self.minimum_gap)
        if length <= 0 or start < 0 or donor_start < 0:
            raise ValueError("invalid crossover block")
        if start + length > len(times) or donor_start + length > len(donor_times):
            raise ValueError("crossover block exceeds parent sequence")
        incoming = [times[start] + donor_times[j] - donor_times[donor_start]
                    for j in range(donor_start, donor_start + length)]
        end = start + length
        upper = (self.prepared.dispatch_window_end_tick if end == len(times)
                 else times[end] - self.minimum_gap)
        if incoming[-1] > upper:
            return self._tag(base, "crossover_boundary_rejected")
        patterns = list(base.pattern_ids)
        patterns[start:end] = donor.pattern_ids[donor_start:donor_start + length]
        times[start:end] = incoming
        return self._tag(self.from_dispatches(patterns, times), "crossover_coupled")

    def crossover(self, first, second, *, rng=None):
        rng = rng or self.rng
        base, donor = first, second
        if rng.random() < 0.5:
            base, donor = donor, base
        maximum = min(base.fleet_size, donor.fleet_size, max(2, math.ceil(base.fleet_size / 4)))
        if maximum < 2:
            return self._tag(base, "crossover_unavailable")
        length = int(rng.integers(2, maximum + 1))
        start = int(rng.integers(0, base.fleet_size - length + 1))
        donor_start = int(rng.integers(0, donor.fleet_size - length + 1))
        return self.transplant(base, donor, start, donor_start, length)

    def variation(self, first, second, profile, *, rng=None):
        """One variation category per child; local never hides block crossover."""
        rng = rng or self.rng
        draw = rng.random()
        local, block = {
            OperatorProfile.LOCAL: (1.0, 0.0),
            OperatorProfile.LOCAL_BLOCK: (0.6, 0.4),
            OperatorProfile.MIXED_GLOBAL: (0.5, 0.3),
        }[profile]
        if draw < local:
            return self.mutate(first, OperatorProfile.LOCAL, rng=rng)
        if draw < local + block:
            if rng.random() < 0.5:
                return self.crossover(first, second, rng=rng)
            return self.mutate(first, profile, rng=rng, forced_level="block")
        return self.mutate(first, profile, rng=rng, forced_level="global")
