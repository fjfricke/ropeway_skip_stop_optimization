"""Restrictions for diagnosis only; never claim their bounds for the full domain."""

from collections import defaultdict
from dataclasses import dataclass

from .reservoir_cp_sat_certificate import validate_reservoir_cp_plan
from .time_ticks import ddd_seconds_to_tick as tick

PROFILES = ("passengers", "timing", "timing_order", "routes", "lifecycle", "full")


EXTRA_PROFILES = ("timing_assignment", "timing_order_assignment")
ALL_PROFILES = PROFILES + EXTRA_PROFILES


def occurrences(problem, plan):
    """All selected physical uses, including uses entering after the horizon."""
    result = defaultdict(list)
    options = {o.id: o for o in problem.movement.route_options}
    for trip in plan.trips:
        for i, oid in enumerate(trip.route_option_ids):
            o = options[oid]
            for j, u in enumerate(o.resource_usages):
                r = problem.movement.resources_by_id[u.resource_id]
                start = (
                    trip.switch_ticks[i]
                    + u.follower_enter_offset_tick
                    + u.follower_enter_wait_coefficient * trip.wait_ticks[i]
                )
                end = (
                    trip.switch_ticks[i]
                    + u.leader_clear_offset_tick
                    + u.leader_clear_wait_coefficient * trip.wait_ticks[i]
                    + u.separation_after_tick(r.minimum_headway_tick)
                )
                result[u.resource_id].append(((trip.cabin_id, i, j), start, end, o, u))
    return result


@dataclass(frozen=True)
class ReservoirDiagnostic:
    profile: str

    def __post_init__(self):
        if self.profile not in ALL_PROFILES:
            raise ValueError("unknown reservoir diagnostic profile")

    @property
    def proof_scope(self):
        return (
            "RESERVOIR_SINGLE_USE_GLOBAL"
            if self.profile == "full"
            else "RESERVOIR_DIAGNOSTIC_RESTRICTED"
        )

    def apply(self, problem, built, reference):
        from .reservoir_cp_sat import _movement_values

        validate_reservoir_cp_plan(problem, reference)
        b, model = built.movement, built.movement.model
        values = _movement_values(problem, built, reference)
        indices = set()
        base = self.profile.removesuffix("_assignment")
        if base == "passengers":
            indices.update(values)
        elif base in ("timing", "timing_order", "routes"):
            indices.update(v.index for a in b.active_by_cabin.values() for v in a)
            if base in ("timing", "timing_order"):
                indices.update(v.index for v in b.selection_by_key.values())
        for i in sorted(indices):
            model.add(model.get_int_var_from_proto_index(i) == values[i])
        if base == "lifecycle":
            model.add(
                sum(a[0] for a in b.active_by_cabin.values()) == len(reference.trips)
            )
        order = (
            self._add_orders(problem, built, reference)
            if base == "timing_order"
            else {}
        )
        fixed_passengers = self.profile in EXTRA_PROFILES
        if fixed_passengers:
            for q, v in built.passengers.ride_count.items():
                model.add(v == reference.ride_counts.get(q, 0))
        return {
            "fixed_passenger_rides": len(built.passengers.ride_count)
            if fixed_passengers
            else 0,
            "profile": self.profile,
            "proof_scope": self.proof_scope,
            "fixed_scalar_decisions": len(indices),
            "reference_used_cabins": len(reference.trips),
            "fleet_count_fixed": self.profile != "full",
            "orders": order,
        }

    def _add_orders(self, problem, built, reference):
        """Conditional ordered chain: an absent middle use never breaks ordering.

        Only uses present in the seed are ranked. Other uses keep their original
        freedom and are counted explicitly. Original NoOverlap remains intact.
        """
        b, model = built.movement, built.movement.model
        H = problem.movement.operational_end_tick
        ranked, unranked, extra = 0, 0, 0
        for resource, uses in occurrences(problem, reference).items():
            selected = sorted(
                (u for u in uses if u[1] <= H), key=lambda u: (u[1], u[2], u[0])
            )
            unranked += len(uses) - len(selected)
            ranked += len(selected)
            if not selected:
                continue
            # Conservative bounds on affine interval expressions; no time grid change.
            lo, hi = -1, H
            for _, _, _, option, usage in selected:
                max_wait = tick(
                    problem.waiting_policy.maximum_wait_seconds(option.station_id)
                )
                sep = usage.separation_after_tick(
                    problem.movement.resources_by_id[resource].minimum_headway_tick
                )
                for offset, coefficient in (
                    (
                        usage.follower_enter_offset_tick,
                        usage.follower_enter_wait_coefficient,
                    ),
                    (
                        usage.leader_clear_offset_tick + sep,
                        usage.leader_clear_wait_coefficient,
                    ),
                ):
                    lo = min(lo, offset, offset + coefficient * max_wait)
                    hi = max(hi, H + offset, H + offset + coefficient * max_wait)
            previous = lo
            for pos, (key, _, _, option, usage) in enumerate(selected):
                k, i, _ = key
                t, w = (
                    b.time_by_cabin[k][i],
                    b.wait_steps_by_key[k, i] * b.waiting_step_tick,
                )
                start = (
                    t
                    + usage.follower_enter_offset_tick
                    + usage.follower_enter_wait_coefficient * w
                )
                end = (
                    t
                    + usage.leader_clear_offset_tick
                    + usage.leader_clear_wait_coefficient * w
                    + usage.separation_after_tick(
                        problem.movement.resources_by_id[resource].minimum_headway_tick
                    )
                )
                present = model.new_bool_var(f"diag_present[{resource},{pos}]")
                # Route and lifecycle are fixed in this profile, so selection is true.
                model.add(start <= H).only_enforce_if(present)
                model.add(start >= H + 1).only_enforce_if(present.Not())
                model.add(start >= previous).only_enforce_if(present)
                protected_end = model.new_int_var(lo, hi, f"diag_end[{resource},{pos}]")
                model.add(protected_end == end).only_enforce_if(present)
                model.add(protected_end == lo).only_enforce_if(present.Not())
                running = model.new_int_var(lo, hi, f"diag_running[{resource},{pos}]")
                model.add_max_equality(running, [previous, protected_end])
                previous = running
                extra += 3
        return {
            "ranked_seed_present_uses": ranked,
            "unranked_seed_absent_uses": unranked,
            "extra_variables": extra,
            "scope": "per-resource seed-present uses only; optional absence handled; state uniqueness remains free",
        }

    def validate(self, problem, reference, found):
        """Check restrictions independently on the exported timetable."""
        validate_reservoir_cp_plan(problem, found)
        if self.profile in EXTRA_PROFILES and (
            {k: v for k, v in reference.ride_counts.items() if v}
            != {k: v for k, v in found.ride_counts.items() if v}
        ):
            raise ValueError("diagnostic passenger assignment changed")
        base = self.profile.removesuffix("_assignment")
        old = {t.cabin_id: t for t in reference.trips}
        new = {t.cabin_id: t for t in found.trips}
        if base == "full":
            return
        if len(old) != len(new):
            raise ValueError("diagnostic fleet count changed")
        if base == "lifecycle":
            return
        if set(old) != set(new) or any(
            len(old[k].route_option_ids) != len(new[k].route_option_ids) for k in old
        ):
            raise ValueError("diagnostic lifecycle changed")
        if base == "routes":
            return
        if any(old[k].route_option_ids != new[k].route_option_ids for k in old):
            raise ValueError("diagnostic routes changed")
        if base == "passengers" and reference.trips != found.trips:
            raise ValueError("diagnostic movement changed")
        if base != "timing_order":
            return
        actual = occurrences(problem, found)
        H = problem.movement.operational_end_tick
        for resource, uses in occurrences(problem, reference).items():
            ranked = sorted(
                (u for u in uses if u[1] <= H), key=lambda u: (u[1], u[2], u[0])
            )
            by_key = {u[0]: u for u in actual[resource]}
            end = None
            for key, *_ in ranked:
                _, start, finish, *_ = by_key[key]
                if start > H:
                    continue
                if end is not None and start < end:
                    raise ValueError("diagnostic resource order changed")
                end = finish
