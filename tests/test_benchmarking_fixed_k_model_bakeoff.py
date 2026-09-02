from __future__ import annotations

import json

from ropeway_skip_stop_optimization.benchmarking.fixed_k_model_bakeoff import (
    FixedKModelBakeoffConfig,
    FixedKModelBakeoffMethod,
    FixedKModelBakeoffTrialResult,
    prepare_fixed_k_bakeoff_instance,
    run_fixed_k_bakeoff_trial,
    write_fixed_k_bakeoff_summary,
)


def test_bakeoff_config_parses_reproducible_contract() -> None:
    config = FixedKModelBakeoffConfig.from_dict(
        {
            "campaign_id": "comparison",
            "example_id": "three_station_v0",
            "cabin_counts": [2, 3],
            "methods": ["ean_pairwise_shared", "ddd_arc_flow_labeled"],
            "total_time_limit_seconds_per_trial": 30,
            "threads": 1,
        }
    )

    config.validate()
    assert config.cabin_counts == (2, 3)
    assert config.total_time_limit_seconds == 30
    assert config.threads == 1


def test_bakeoff_summary_combines_best_certified_bounds(tmp_path) -> None:
    config = FixedKModelBakeoffConfig(
        campaign_id="comparison",
        example_id="three_station_v0",
        cabin_counts=(2,),
    )
    results = (
        FixedKModelBakeoffTrialResult(
            method=FixedKModelBakeoffMethod.EAN_PAIRWISE_SHARED,
            cabin_count=2,
            problem_fingerprint="same",
            status="time_limit",
            certified_lower_bound=80.0,
            validated_upper_bound=120.0,
            relative_gap=1 / 3,
            total_seconds=30.0,
            payload={},
        ),
        FixedKModelBakeoffTrialResult(
            method=FixedKModelBakeoffMethod.DDD_ARC_FLOW_LABELED,
            cabin_count=2,
            problem_fingerprint="same",
            status="time_limit",
            certified_lower_bound=90.0,
            validated_upper_bound=130.0,
            relative_gap=40 / 130,
            total_seconds=30.0,
            payload={},
        ),
    )
    path = tmp_path / "summary.json"

    write_fixed_k_bakeoff_summary(
        path,
        config=config,
        results=results,
    )

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["portfolio_by_k"]["2"] == {
        "certified_lower_bound": 90.0,
        "validated_upper_bound": 120.0,
        "relative_gap": 0.25,
    }


def test_tiny_bakeoff_methods_share_problem_fingerprint(tmp_path) -> None:
    config = FixedKModelBakeoffConfig(
        campaign_id="tiny",
        example_id="three_station_v0",
        cabin_counts=(1,),
        total_time_limit_seconds=10.0,
        start_layout_time_limit_seconds=5.0,
        cp_seed_time_limit_seconds=2.0,
        seed_passenger_time_limit_seconds=2.0,
        sample_interval_seconds=1.0,
        threads=1,
        cp_seed_workers=1,
    )
    prepared = prepare_fixed_k_bakeoff_instance(config, 1)

    results = tuple(
        run_fixed_k_bakeoff_trial(
            config,
            method=method,
            prepared=prepared,
            output_dir=tmp_path,
        )
        for method in config.methods
    )

    assert {result.problem_fingerprint for result in results} == {
        prepared.problem.fingerprint
    }
    assert all(result.validated_upper_bound is not None for result in results)
