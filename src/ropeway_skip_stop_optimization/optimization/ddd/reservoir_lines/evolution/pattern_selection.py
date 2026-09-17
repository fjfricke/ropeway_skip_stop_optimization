from __future__ import annotations

from .grouped_selection import passenger_score


def pattern_group(value):
    if value.passengers is not None:
        return "valid"
    status = (value.decoder or {}).get("status")
    return "infeasible" if status == "PATTERN_INFEASIBLE" else "unknown"


def _identity(value):
    return (value.decoder or {}).get("input_pattern_identity", value.movement.genome.identity)


def _patterns(value):
    return tuple((value.decoder or {}).get("input_pattern_ids", value.movement.genome.pattern_ids))


def _hamming(a, b):
    return sum(x != y for x, y in zip(a, b)) + abs(len(a)-len(b))


def _diverse(indices, values, count, seed_indices=()):
    chosen = list(seed_indices)
    remaining = list(indices)
    while remaining and len(chosen) < len(seed_indices) + count:
        if not chosen:
            selected = remaining[0]
        else:
            selected = max(remaining, key=lambda i: (
                min(_hamming(_patterns(values[i]), _patterns(values[j])) for j in chosen),
                _identity(values[i]),
            ))
        chosen.append(selected); remaining.remove(selected)
    return chosen[len(seed_indices):]


def pattern_survivor_indices(values, count, objective="service_then_journey"):
    unique = {}
    for i, value in enumerate(values):
        key = _identity(value)
        rank = (0 if value.passengers is not None else 1,
                passenger_score(value.passengers, objective) if value.passengers is not None else ())
        if key not in unique or rank < unique[key][0]: unique[key] = (rank, i)
    buckets = {g: [] for g in ("valid", "unknown", "infeasible")}
    for _, i in unique.values(): buckets[pattern_group(values[i])].append(i)
    buckets["valid"].sort(key=lambda i: (passenger_score(values[i].passengers, objective), _identity(values[i])))
    # Protect different fleet sizes before filling by global service quality.
    # Fixed-K behavior is unchanged.
    by_k = {}
    for i in buckets["valid"]:
        by_k.setdefault(len(_patterns(values[i])), i)
    representatives = []
    if len(by_k) > 1:
        keys = sorted(by_k)
        n = min(8, count, len(keys))
        representatives = [by_k[keys[round(j * (len(keys)-1) / max(1, n-1))]] for j in range(n)]
    selected = representatives + [i for i in buckets["valid"] if i not in representatives][:max(0, min(24, count)-len(representatives))]
    if selected:
        for group in ("unknown", "infeasible"):
            selected += _diverse(buckets[group], values, min(4, count-len(selected)), selected)
    else:
        for group in ("unknown", "infeasible"):
            selected += _diverse(buckets[group], values, min(count//2, count-len(selected)), selected)
    leftovers = [i for group in ("valid", "unknown", "infeasible")
                 for i in buckets[group] if i not in selected]
    selected += _diverse(leftovers, values, count-len(selected), selected)
    return selected[:count]


def pattern_parent_index(values, rng, objective="service_then_journey"):
    buckets = {g: [] for g in ("valid", "unknown", "infeasible")}
    for i, value in enumerate(values): buckets[pattern_group(value)].append(i)
    weights = {"valid": 16, "unknown": 8, "infeasible": 8}
    available = [(g, weights[g]) for g in buckets if buckets[g]]
    total = sum(w for _, w in available)
    group = str(rng.choice([g for g,_ in available], p=[w/total for _,w in available]))
    if group != "valid": return int(rng.choice(buckets[group])), group
    fleets = sorted({len(_patterns(values[i])) for i in buckets[group]})
    if len(fleets) > 1 and rng.random() < 0.5:
        k = int(rng.choice(fleets))
        candidates = [i for i in buckets[group] if len(_patterns(values[i])) == k]
        return min(candidates, key=lambda i: passenger_score(values[i].passengers, objective)), group
    a,b=(int(i) for i in rng.choice(buckets[group],size=2))
    sa,sb=(passenger_score(values[a].passengers, objective),
           passenger_score(values[b].passengers, objective))
    return (a if sa<sb else b if sb<sa else int(rng.choice([a,b]))),group
