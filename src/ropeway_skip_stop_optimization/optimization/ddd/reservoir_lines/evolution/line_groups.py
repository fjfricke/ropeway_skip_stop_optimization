"""Line-family variation on the existing exact-K cabin representation.

Only sampling starts with few families. Splitting can introduce arbitrarily
many catalog patterns over generations; no schedule is silently repaired here.
"""
from collections import defaultdict

from .model import LineGenome, OperatorProfile
from .operators import GenomeFactory


class LineGroupGenomeFactory(GenomeFactory):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        demand = defaultdict(int)
        for group in self.problem.demand_groups:
            if group.count:
                demand[frozenset((group.origin_station_id, group.destination_station_id))] += group.count
        self.od_weights = dict(demand)

    def random(self, *, k=None, patterns=None, arrangement="random", rng=None):
        rng = self.rng if rng is None else rng
        if patterns is not None:
            return super().random(k=k, patterns=patterns, arrangement=arrangement, rng=rng)
        k = self.fixed_k if k is None and self.fixed_k is not None else k
        k = int(rng.integers(1, self.maximum_k + 1)) if k is None else k
        if k == 0:
            return self._tag(LineGenome((), 0, ()), "line_initial_sampler")
        count = int(rng.integers(1, min(4, k, len(self.patterns)) + 1))
        selected, covered = [], set()
        for _ in range(count):
            remaining = [p for p in self.patterns if p not in selected]
            # Sample halt counts uniformly, then favor currently uncovered OD
            # demand within that class. Every relevant pattern has positive weight.
            sizes = sorted({len(self.pattern_stops[p]) for p in remaining})
            size = int(rng.choice(sizes))
            pool = [p for p in remaining if len(self.pattern_stops[p]) == size]
            weights = [sum(n * (0.1 if pair in covered else 1.0)
                           for pair, n in self.od_weights.items()
                           if pair <= self.pattern_stops[p]) for p in pool]
            total = sum(weights)
            pattern = str(rng.choice(pool, p=[w / total for w in weights] if total else None))
            selected.append(pattern)
            covered.update(pair for pair in self.od_weights if pair <= self.pattern_stops[pattern])
        # Each chosen line receives at least one cabin; the rest vary jointly.
        weights = rng.dirichlet([1.0] * count)
        values = selected + list(rng.choice(selected, size=k-count, p=weights))
        if arrangement == "random":
            arrangement = str(rng.choice(("random", "alternating", "grouped")))
        if arrangement == "random":
            rng.shuffle(values)
        result = super().random(k=k, patterns=values, arrangement=arrangement, rng=rng)
        return self._tag(result, "line_initial_sampler")

    def change_line(self, genome, operation, *, rng=None):
        """Change pattern assignments only; preserve every preferred departure."""
        rng = self.rng if rng is None else rng
        patterns = list(genome.pattern_ids)
        families = sorted(set(patterns))
        if not families:
            return self.random(rng=rng)
        if operation == "halt":
            choices = [(p, q) for p in families for q in self.patterns
                       if len(self.pattern_stops[p] ^ self.pattern_stops[q]) == 1]
            if not choices:
                return self._tag(genome, "line_halt_unavailable")
            source, target = choices[int(rng.integers(len(choices)))]
            patterns = [target if p == source else p for p in patterns]
        elif operation == "reallocate":
            if len(families) < 2:
                return self.change_line(genome, "split", rng=rng)
            source, target = rng.choice(families, size=2, replace=False)
            indices = [i for i, p in enumerate(patterns) if p == source]
            count = int(rng.integers(1, len(indices) + 1))
            for i in rng.choice(indices, size=count, replace=False):
                patterns[int(i)] = str(target)
        elif operation == "split":
            choices = [p for p in families if patterns.count(p) >= 2]
            unused = [p for p in self.patterns if p not in families]
            if not choices or not unused:
                return self._tag(genome, "line_split_unavailable")
            source = str(rng.choice(choices))
            neighbours = [p for p in unused if len(self.pattern_stops[source] ^ self.pattern_stops[p]) == 1]
            target = str(rng.choice(neighbours or unused))
            indices = [i for i, p in enumerate(patterns) if p == source]
            count = int(rng.integers(1, len(indices)))
            for i in rng.choice(indices, size=count, replace=False):
                patterns[int(i)] = target
        else:
            raise ValueError("unknown line operation")
        return self._tag(LineGenome(tuple(patterns), genome.phase_tick, genome.extra_gap_ticks),
                         f"line_{operation}")

    def variation(self, first, second, profile, *, rng=None):
        rng = self.rng if rng is None else rng
        if profile is not OperatorProfile.MIXED_GLOBAL:
            return super().variation(first, second, profile, rng=rng)
        draw = rng.random()
        if draw < 0.5:
            return self.mutate(first, OperatorProfile.LOCAL, rng=rng)
        if draw < 0.8:
            operation = str(rng.choice(("halt", "reallocate", "split", "crossover")))
            return (self.crossover(first, second, rng=rng) if operation == "crossover"
                    else self.change_line(first, operation, rng=rng))
        operation = int(rng.integers(3))
        if operation == 0:
            patterns = list(first.pattern_ids)
            rng.shuffle(patterns)
            return self._tag(LineGenome(tuple(patterns), first.phase_tick, first.extra_gap_ticks),
                             "line_global_order")
        if operation == 1:
            result = self.random(k=first.fleet_size, patterns=first.pattern_ids, rng=rng)
            return self._tag(result, "line_global_dispatch")
        return self._tag(self.random(k=first.fleet_size, rng=rng), "line_global_restart")
