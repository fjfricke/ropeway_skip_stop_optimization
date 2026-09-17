"""Progress must preserve solver scope, retries, missing bounds and exact units."""

import json

import pytest
from test_reservoir_greedy import tiny

from ropeway_skip_stop_optimization.optimization.ddd.reservoir_cp_sat_certificate import (
    DddReservoirCpPlan,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_greedy.optimizer import (
    solve_insertion,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_greedy.progress import (
    GreedyProgress,
    gap_percent,
    replay_progress,
)


def test_bound_before_solution_is_not_a_fake_incumbent():
    p = GreedyProgress()
    p.consume(
        {
            "kind": "local_bound",
            "insertion_k": 3,
            "elapsed_seconds": 0.4,
            "local_unserved_bound": 20,
        }
    )
    p.consume(
        {
            "kind": "native_solution",
            "insertion_k": 3,
            "elapsed_seconds": 1,
            "unserved": 40,
        }
    )
    p.consume(
        {
            "kind": "local_bound",
            "insertion_k": 3,
            "elapsed_seconds": 2,
            "local_unserved_bound": 30,
        }
    )
    p.consume(
        {
            "kind": "native_solution",
            "insertion_k": 3,
            "elapsed_seconds": 3,
            "unserved": 45,
        }
    )
    i = p.iterations[0]
    assert i["points"][0]["ub"] is None and i["points"][0]["gap_percent"] is None
    assert i["ub"] == 40 and i["lb"] == 30 and i["gap_percent"] == 25
    assert i["last_improvement_seconds"] == 1
    assert len(i["points"]) == 3


def test_retry_resets_local_bounds_and_retains_cost_ticks():
    p = GreedyProgress()
    for attempt in (0, 1):
        p.consume(
            {
                "kind": "insertion_started",
                "insertion_k": 4,
                "attempt": attempt,
                "objective": "journey_time",
                "elapsed_seconds": 0,
            }
        )
        p.consume(
            {
                "kind": "native_solution",
                "insertion_k": 4,
                "attempt": attempt,
                "objective": "journey_time",
                "elapsed_seconds": 1,
                "journey_time_tick": 2_000_000_000_001,
                "local_journey_time_bound_tick": 1_000_000_000_000,
            }
        )
    p.consume({"kind": "accepted_insertion", "fleet_size": 4})
    assert len(p.iterations) == 2
    assert not p.iterations[0]["accepted"] and p.iterations[1]["accepted"]
    assert p.iterations[1]["ub"] == 2_000_000_000_001
    assert (
        json.loads(json.dumps(p.export()))["iterations"][1]["ub"] == 2_000_000_000_001
    )


def test_missing_and_inconsistent_bounds_do_not_claim_zero_gap():
    assert gap_percent(None, 0) is None
    assert gap_percent(0, 0) == 0
    assert gap_percent(0, -1) is None
    assert gap_percent(5, 6) is None


@pytest.mark.parametrize("backend", ["cp_sat", "gurobi"])
def test_real_events_survive_json_and_reproduce_terminal_bounds(backend):
    events = []
    r = solve_insertion(
        tiny(),
        DddReservoirCpPlan((), {}),
        backend=backend,
        objective="journey_time",
        seconds=3,
        workers=1,
        on_event=events.append,
    )
    assert events[0]["kind"] == "insertion_started"
    assert events[-1]["kind"] == "insertion_finished"
    encoded = json.loads(json.dumps(events))
    p = replay_progress(encoded)
    i = p.iterations[0]
    assert i["ub"] == r["metrics"]["journey_time_tick"]
    assert i["lb"] == r["local_journey_time_bound_tick"]
    assert i["status"] == "OPTIMAL" and i["gap_percent"] == 0
    assert i["summary"]["model_stats"]["variable_cabins"] == 1


def test_incomplete_historical_log_does_not_borrow_other_attempt_bound():
    p = replay_progress(
        [{"kind": "native_solution", "insertion_k": 2,
          "elapsed_seconds": 1, "unserved": 40}],
        [{"total_wall_seconds": 2, "local_unserved_bound": 100},
         {"total_wall_seconds": 2, "local_unserved_bound": 30}],
    )
    assert p.iterations[0]["ub"] == 40
    assert p.iterations[0]["lb"] is None
