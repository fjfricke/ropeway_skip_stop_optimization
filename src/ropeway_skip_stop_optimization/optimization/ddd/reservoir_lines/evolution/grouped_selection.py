"""Stage-separated selection; never compare missing cabins with conflicts."""
from collections import defaultdict

GROUPS = ('valid', 'complete', 'incomplete')


def candidate_group(value):
    if value.passengers is not None:
        return 'valid'
    if value.movement.relaxed_timetable is not None or value.movement.feasible:
        return 'complete'
    return 'incomplete'


def passenger_score(passengers, objective="service_then_journey"):
    """Return the configured search order; smaller is always better."""
    journey = getattr(passengers, "journey_time_tick", None)
    if objective == "journey_time":
        return (journey if journey is not None else float("inf"),)
    if objective == "unserved":
        return (passengers.unserved,)
    if objective == "service_then_journey":
        return (passengers.unserved, journey if journey is not None else float("inf"))
    raise ValueError("unknown evolution objective")


def within_group_score(value, objective="service_then_journey"):
    group = candidate_group(value)
    if group == 'valid':
        return passenger_score(value.passengers, objective)
    if group == 'complete':
        return (len(value.movement.conflicts), value.movement.total_overlap_ticks)
    d = value.decoder or {}
    missing = (max(1, value.movement.genome.fleet_size-d['completed_cabins'])
               if d.get('status') == 'CONSTRUCTION_FAILED' else value.movement.genome.fleet_size+1)
    return (missing,)


def schedule_key(value):
    """Deduplicate actual full schedules; incomplete genomes stay distinct."""
    plan = value.passengers.plan if value.passengers is not None else value.movement.plan or value.movement.relaxed_timetable
    if plan is not None:
        return ('schedule', tuple((t.cabin_id, tuple(t.route_option_ids), tuple(t.switch_ticks),
                                   tuple(t.wait_ticks), t.return_tick) for t in plan.trips))
    return ('genome', value.movement.genome.identity)


def group_weights(has_valid):
    return (16, 12, 4) if has_valid else (0, 24, 8)


def survivor_indices(values, count, objective="service_then_journey"):
    # Duplicated schedules can have differing passenger incumbents. Retain the
    # best known evaluation; never synthesize a certificate or service value.
    buckets = {g: [] for g in GROUPS}
    unique = {}
    for i, value in enumerate(values):
        key = schedule_key(value)
        rank = (GROUPS.index(candidate_group(value)), within_group_score(value, objective))
        if key not in unique or rank < unique[key][0]:
            unique[key] = (rank, i)
    for _, i in unique.values():
        buckets[candidate_group(values[i])].append(i)
    for g in GROUPS:
        buckets[g].sort(key=lambda i: within_group_score(values[i], objective))
    weights = group_weights(bool(buckets['valid']))
    selected = []
    for group, weight in zip(GROUPS, weights):
        quota = count*weight//32
        selected.extend(buckets[group][:quota])
        del buckets[group][:quota]
    # Fill vacancies without cross-group objective comparisons or clones.
    while len(selected) < count:
        added = False
        for group in GROUPS:
            if buckets[group] and len(selected) < count:
                selected.append(buckets[group].pop(0)); added = True
        if not added:
            break
    return selected


def parent_index(values, rng, objective="service_then_journey"):
    buckets = defaultdict(list)
    for i, value in enumerate(values):
        buckets[candidate_group(value)].append(i)
    weights = group_weights(bool(buckets['valid']))
    available = [(g, w) for g, w in zip(GROUPS, weights) if buckets[g] and w]
    total = sum(w for _, w in available)
    group = str(rng.choice([g for g, _ in available], p=[w/total for _, w in available]))
    a, b = (int(i) for i in rng.choice(buckets[group], size=2))
    sa, sb = within_group_score(values[a], objective), within_group_score(values[b], objective)
    return (a if sa < sb else b if sb < sa else int(rng.choice([a, b]))), group
