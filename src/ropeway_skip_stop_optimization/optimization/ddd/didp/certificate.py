"""Replay and extraction share only certificates, never the physical validator."""

import math
from ..cp_sat_certificate import (
    solution_from_cp_sat_payload,
    validate_ddd_cp_sat_incumbent,
)
from .structure import EXACT_FLOAT_LIMIT


def exact_tick(value):
    if (
        not math.isfinite(value)
        or abs(value) > EXACT_FLOAT_LIMIT
        or value != int(value)
    ):
        raise ValueError(f"DIDP produced a non-exact integer tick: {value}")
    return int(value)


def extract_didp_incumbent(problem, built, transitions, expected_served=None):
    state = built.model.target_state
    p, v = built.prepared, built.variables
    supports = {
        s.cabin_id: dict(
            cabin_id=s.cabin_id,
            route_option_ids=[],
            switch_times_tick=[],
            wait_ticks=[],
        )
        for s in p.starts
    }
    counts = {r.id: 0 for r in p.rides}
    cost = 0
    for transition in transitions:
        if not transition.is_applicable(state, built.model):
            raise ValueError(f"Invalid DIDP transition: {transition.name}")
        info = built.metadata[transition.name]
        if info and info[0] == "take":
            counts[p.rides[info[1]].id] += info[2]
        elif info and info[0] == "commit":
            op = p.operations[info[1]]
            raw = supports[p.starts[op.cabin].cabin_id]
            raw["route_option_ids"].append(op.route.id)
            raw["switch_times_tick"].append(exact_tick(state[v[f"time/{op.cabin}"]]))
            raw["wait_ticks"].append(state[v["lo"]] * p.waiting_step)
        cost += transition.eval_cost(0, state, built.model)
        state = transition.apply(state, built.model)
    if not built.model.is_base(state):
        raise ValueError("DIDP transition sequence is incomplete")
    if expected_served is not None and cost != expected_served:
        raise ValueError("DIDP native cost disagrees with replay")
    solution = solution_from_cp_sat_payload(
        problem, {"trajectory_supports": list(supports.values())}
    )
    incumbent = validate_ddd_cp_sat_incumbent(
        problem,
        solution,
        {key: n for key, n in counts.items() if n},
        provenance="didp-native",
    )
    if p.total_demand - sum(incumbent.unserved_counts.values()) != cost:
        raise ValueError(
            "DIDP delivered count disagrees with independent certificate validation"
        )
    return incumbent


def replay_didp_checkpoint(problem, built, incumbent):
    # Validate against the ORIGINAL domain before consulting this model.
    checked = validate_ddd_cp_sat_incumbent(
        problem,
        incumbent.solution,
        incumbent.ride_counts,
        provenance="didp-reference-replay",
        expected_objective_tick=incumbent.objective_tick,
    )
    p, v = built.prepared, built.variables
    raw = {x["cabin_id"]: x for x in checked.to_payload()["trajectory_supports"]}
    op_by_key = {(o.cabin, o.visit, o.route.id): o for o in p.operations}
    state = built.model.target_state
    transitions = []
    while not built.model.is_base(state):
        phase = state[v["phase"]]
        name = None
        if phase == 0:
            for r in range(len(p.resources)):
                tr = built.transitions.get(f"expire/{r}")
                if tr is not None and tr.is_applicable(state, built.model):
                    name = tr.name
                    break
            if name is None:
                k = min(range(len(p.starts)), key=lambda k: (state[v[f"time/{k}"]], k))
                i = state[v[f"visit/{k}"]]
                support = raw[p.starts[k].cabin_id]
                if i >= len(support["route_option_ids"]):
                    raise ValueError("Reference ends before the DIDP lifecycle")
                if exact_tick(state[v[f"time/{k}"]]) != support["switch_times_tick"][i]:
                    raise ValueError("Reference and DIDP switch times differ")
                op = op_by_key[k, i, support["route_option_ids"][i]]
                name = f"route/{op.index}"
        else:
            op = p.operations[state[v["operation"]]]
            if phase == 1:
                pos = state[v["cursor"]]
                n = checked.ride_counts.get(p.rides[op.candidates[pos]].id, 0)
                name = f"take/{op.index}/{pos}/{n}"
            elif phase == 2:
                support = raw[p.starts[op.cabin].cabin_id]
                wait = support.get(
                    "wait_ticks", [0] * len(support["route_option_ids"])
                )[op.visit]
                if wait % p.waiting_step:
                    raise ValueError("Reference wait lies outside the DIDP grid")
                target = wait // p.waiting_step
                lower, upper = state[v["lo"]], state[v["hi"]]
                if not lower <= target <= upper:
                    raise ValueError("Reference wait excluded by DIDP range")
                if lower == upper:
                    name = f"wait/{op.index}"
                else:
                    direction = (
                        "low" if target <= lower + (upper - lower) // 2 else "high"
                    )
                    name = f"split/{op.index}/{direction}"
            elif phase == 3:
                pos = state[v["cursor"]]
                usage = op.route.resource_usages[pos]
                entry = (
                    exact_tick(state[v[f"time/{op.cabin}"]])
                    + usage.follower_enter_offset_tick
                    + usage.follower_enter_wait_coefficient
                    * state[v["lo"]]
                    * p.waiting_step
                )
                side = "inside" if entry <= p.operation_end else "outside"
                name = f"reserve/{op.index}/{pos}/{side}"
                if side == "inside":
                    r = next(
                        j
                        for j, x in enumerate(p.resources)
                        if x.id == usage.resource_id
                    )
                    if state[v[f"count/{r}"]] >= p.calendar_sizes[r]:
                        raise RuntimeError(
                            "DIDP calendar bound violated; refusing to truncate reservations"
                        )
            elif phase == 4:
                name = f"commit/{op.index}"
            elif phase == 5:
                name = f"insert/{state[v['pending_resource']]}"
        tr = built.transitions.get(name)
        if tr is None or not tr.is_applicable(state, built.model):
            raise ValueError(
                f"Reference is not representable at DIDP transition {name}"
            )
        transitions.append(tr)
        state = tr.apply(state, built.model)
    reproduced = extract_didp_incumbent(
        problem,
        built,
        transitions,
        p.total_demand - sum(checked.unserved_counts.values()),
    )
    if reproduced.objective_tick != checked.objective_tick:
        raise ValueError("Reference journey-time check changed in DIDP replay")
    return transitions, reproduced
