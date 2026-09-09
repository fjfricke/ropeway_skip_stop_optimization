import json
from types import SimpleNamespace

import pytest
from test_optimization_ddd_cp_sat_integrated import tiny_problem
from test_optimization_ddd_reservation_insertion import skip_seed

from ropeway_skip_stop_optimization.benchmarking.ddd_reservation_insertion import (
    DddReservationInsertionRunConfig,
    run_ddd_reservation_insertion,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservation_checkpoint import (
    DddReservationCheckpointAdapter,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservation_models import (
    DddReservationInsertionConfig,
)


@pytest.mark.parametrize("passenger_seconds", [0, 2])
def test_runner_uses_prepared_problem_preserves_source_and_writes_reproducible_requests(
    tmp_path,
    passenger_seconds,
):
    scenario, p = tiny_problem(maximum_wait=20, waiting_step=1e-6)
    seed = skip_seed(p)
    source = tmp_path / "source"
    source.mkdir()
    (source / "config.json").write_text("{}")
    DddReservationCheckpointAdapter().export_cp_seed(
        source / "incumbent.json", problem=p, plan=seed
    )
    before = (source / "incumbent.json").read_bytes()
    prepared = SimpleNamespace(scenario=scenario, problem=p)
    config = DddReservationInsertionRunConfig(
        source,
        tmp_path / "result",
        DddReservationInsertionConfig(
            total_time_limit_seconds=5, attempt_time_limit_seconds=0.5
        ),
        request_count=4,
        passenger_refinement_seconds=passenger_seconds,
    )
    result = run_ddd_reservation_insertion(config, prepared_run=prepared)
    if passenger_seconds:
        assert result["post_assignment_ip"] != "NOT_RUN"
        assert result["validated_upper_bound"] <= result["native_upper_bound"]
    assert (config.output_dir / "cp_seed.json").exists()
    assert result["roundtrip_passed"] and result["attempt_count"] == 4
    assert result["validated_upper_bound"] < result["initial_objective"]
    assert result["lower_bound"] is None and not result["proven_optimal"]
    assert (source / "incumbent.json").read_bytes() == before
    assert json.loads((config.output_dir / "config.json").read_text())[
        "domain_fingerprint"
    ]
    assert len((config.output_dir / "attempts.jsonl").read_text().splitlines()) == 4
    with pytest.raises(ValueError, match="fresh"):
        run_ddd_reservation_insertion(config, prepared_run=prepared)
    second = DddReservationInsertionRunConfig(
        source, tmp_path / "second", config.solver, request_count=4
    )
    run_ddd_reservation_insertion(second, prepared_run=prepared)
    assert (config.output_dir / "requests.json").read_bytes() == (
        second.output_dir / "requests.json"
    ).read_bytes()
