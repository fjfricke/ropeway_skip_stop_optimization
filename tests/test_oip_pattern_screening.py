from __future__ import annotations

from collections import Counter
import importlib.util
import json
from pathlib import Path
import sys

import pytest

from ropeway_skip_stop_optimization.benchmarking.oip_pattern_screening import (
    OipScreeningDemandFamily,
    demand_fingerprint,
    materialize_pattern_allocation,
    pattern_allocations,
    pattern_sequence_identity,
)
from ropeway_skip_stop_optimization.benchmarking.oip_pattern_waiting import (
    prepare_oip_pattern_waiting_pilot,
)
from ropeway_skip_stop_optimization.benchmarking.thesis_cases import ThesisDemandFamily


STATIONS = ("S0", "S1", "S2", "S3", "S4")


def _catalog(family=OipScreeningDemandFamily.F2):
    return {item.id: item for item in pattern_allocations(family, STATIONS)}


def test_all_families_define_six_valid_allocations() -> None:
    for family in OipScreeningDemandFamily:
        allocations = pattern_allocations(family, STATIONS)
        assert len(allocations) == 6
        assert len({item.id for item in allocations}) == 6
        for allocation in allocations:
            allocation.validate(STATIONS)


def test_f3_catalog_targets_long_distance_od_pairs() -> None:
    catalog = {
        item.id: item
        for item in pattern_allocations(OipScreeningDemandFamily.F3, STATIONS)
    }
    assert set(catalog) == {
        "all_stop",
        "direct",
        "express_three",
        "direct_express_three",
        "direct_all_stop",
        "express_all_stop",
    }
    mixed = materialize_pattern_allocation(
        catalog["direct_express_three"], 40, STATIONS
    )
    direct_patterns = {
        (STATIONS[index], STATIONS[(index + 2) % len(STATIONS)])
        for index in range(len(STATIONS))
    }
    express_patterns = {
        (
            STATIONS[index],
            STATIONS[(index + 2) % len(STATIONS)],
            STATIONS[(index + 4) % len(STATIONS)],
        )
        for index in range(len(STATIONS))
    }
    assert sum(count for pattern, count in mixed.counts if pattern in direct_patterns) == 20
    assert sum(count for pattern, count in mixed.counts if pattern in express_patterns) == 20


def test_f2_k40_allocations_match_the_frozen_table() -> None:
    catalog = _catalog()
    expected = {
        "all_stop": {("S0", "S1", "S2", "S3", "S4"): 40},
        "direct": {("S1", "S3"): 20, ("S2", "S4"): 20},
        "four_stop": {("S1", "S2", "S3", "S4"): 40},
        "direct_four_stop": {
            ("S1", "S3"): 10,
            ("S2", "S4"): 10,
            ("S1", "S2", "S3", "S4"): 20,
        },
        "direct_all_stop": {
            ("S1", "S3"): 10,
            ("S2", "S4"): 10,
            ("S0", "S1", "S2", "S3", "S4"): 20,
        },
        "four_stop_all_stop": {
            ("S1", "S2", "S3", "S4"): 20,
            ("S0", "S1", "S2", "S3", "S4"): 20,
        },
    }
    for allocation_id, counts in expected.items():
        result = materialize_pattern_allocation(
            catalog[allocation_id], 40, STATIONS
        )
        assert dict(result.counts) == counts


@pytest.mark.parametrize("cabin_count", [1, 2, 3, 5, 41, 50, 62])
def test_largest_remainder_uses_exactly_k_cabins(cabin_count: int) -> None:
    for allocation in _catalog().values():
        result = materialize_pattern_allocation(
            allocation, cabin_count, STATIONS
        )
        assert len(result.patterns_by_cabin_id) == cabin_count
        assert sum(result.composition.values()) == cabin_count


def test_largest_remainder_has_stable_tie_breaking() -> None:
    result = materialize_pattern_allocation(_catalog()["direct"], 3, STATIONS)
    assert dict(result.counts) == {("S1", "S3"): 2, ("S2", "S4"): 1}


def test_pattern_identity_ignores_cabin_numbering() -> None:
    result = materialize_pattern_allocation(
        _catalog()["direct_all_stop"], 41, STATIONS
    )
    assert result.identity == pattern_sequence_identity(
        reversed(result.patterns_by_cabin_id), family=OipScreeningDemandFamily.F2
    )
    assert Counter(result.patterns_by_cabin_id) == Counter(
        reversed(result.patterns_by_cabin_id)
    )


def test_frozen_demand_and_windows_do_not_change_with_k() -> None:
    low = prepare_oip_pattern_waiting_pilot(
        maximum_wait_seconds=0, cabin_count=40
    )
    high = prepare_oip_pattern_waiting_pilot(
        maximum_wait_seconds=0, cabin_count=62
    )
    assert low.demand_window_seconds == high.demand_window_seconds == 1464
    assert low.passenger_horizon_seconds == high.passenger_horizon_seconds == 2364
    assert low.operation_seconds == high.operation_seconds == 2664
    assert demand_fingerprint(
        low.domain.scenario,
        horizon_seconds=low.passenger_horizon_seconds,
        operation_seconds=low.operation_seconds,
    ) == demand_fingerprint(
        high.domain.scenario,
        horizon_seconds=high.passenger_horizon_seconds,
        operation_seconds=high.operation_seconds,
    )


def test_f0_f2_f3_use_distinct_demands_under_the_same_technical_windows() -> None:
    prepared = {
        family: prepare_oip_pattern_waiting_pilot(
            maximum_wait_seconds=0,
            cabin_count=2,
            demand_family=family,
        )
        for family in (ThesisDemandFamily.F0, ThesisDemandFamily.F2, ThesisDemandFamily.F3)
    }
    assert {item.demand_window_seconds for item in prepared.values()} == {1464}
    assert {item.passenger_horizon_seconds for item in prepared.values()} == {2364}
    assert {
        sum(demand.count for demand in item.domain.scenario.demands)
        for item in prepared.values()
    } == {3210}
    assert len({
        demand_fingerprint(
            item.domain.scenario,
            horizon_seconds=item.passenger_horizon_seconds,
            operation_seconds=item.operation_seconds,
        )
        for item in prepared.values()
    }) == 3


def test_build_only_manifest_and_resume_do_not_duplicate_trials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner_path = Path(__file__).parents[1] / "benchmarks" / "run_oip_pattern_screening.py"
    spec = importlib.util.spec_from_file_location("run_oip_pattern_screening", runner_path)
    assert spec is not None and spec.loader is not None
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)

    output = tmp_path / "campaign"
    frontend = tmp_path / "frontend"
    common = [
        "run_oip_pattern_screening.py",
        "--output", str(output),
        "--frontend-root", str(frontend),
        "--allocations", "direct",
        "--k-values", "2",
        "--wall-limit-seconds", "0.01",
    ]
    monkeypatch.setattr(sys, "argv", [*common, "--build-only"])
    runner.main()
    prepared = json.loads((output / "campaign.json").read_text())
    assert prepared["status"] == "prepared"
    assert prepared["trial_count"] == 1
    assert prepared["trials"][0]["pattern_composition"] == {
        "S1+S3": 1,
        "S2+S4": 1,
    }
    assert not list(output.glob("trials/**/process.log"))

    monkeypatch.setattr(sys, "argv", [*common, "--resume"])
    runner.main()
    resumed = json.loads((output / "campaign.json").read_text())
    assert resumed["trial_count"] == 1
    assert len(resumed["trials"]) == 1
    assert resumed["trials"][0]["attempts"] == []
    assert resumed["trials"][0]["status"] == "not_started_deadline"
    assert resumed["resume_count"] == 1


def test_refinement_selection_keeps_best_two_per_k() -> None:
    runner_path = Path(__file__).parents[1] / "benchmarks" / "run_oip_pattern_screening.py"
    spec = importlib.util.spec_from_file_location(
        "run_oip_pattern_screening_selection", runner_path
    )
    assert spec is not None and spec.loader is not None
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    trials = []
    for allocation_id, served, journey in (
        ("all_stop", 10, 100.0),
        ("direct", 12, 140.0),
        ("four_stop", 12, 120.0),
    ):
        trials.append(
            {
                "trial_id": f"{allocation_id}__k2",
                "policy_id": allocation_id,
                "allocation_id": allocation_id,
                "allocation_label": allocation_id,
                "available_fleet_count": 2,
                "pattern_identity": allocation_id,
                "pattern_composition": {allocation_id: 2},
                "patterns_by_cabin_id": [["S0"], ["S0"]],
                "served": served,
                "unserved": 20 - served,
                "journey_time_seconds": journey,
                "attempts": [
                    {"status": "complete", "directory": f"trials/{allocation_id}"}
                ],
            }
        )
    selected = runner._select_refinements(
        {
            "k_values": [2],
            "allocation_order": ["all_stop", "direct", "four_stop"],
            "trials": trials,
        },
        candidates_per_k=2,
    )
    assert [item["allocation_id"] for item in selected] == [
        "four_stop",
        "direct",
    ]
