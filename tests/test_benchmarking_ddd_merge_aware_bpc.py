from __future__ import annotations

import json

import pytest

from ropeway_skip_stop_optimization.benchmarking.ddd_merge_aware_bpc import (
    DddMergeAwareRootGateConfig,
    DddMergeAwareRootGateRunner,
    DddMergeAwareRootVariant,
)


def test_merge_aware_root_gate_config_rejects_duplicate_variants(tmp_path) -> None:
    config = DddMergeAwareRootGateConfig(
        example_id="three_station_v0",
        cabin_count=1,
        output_path=tmp_path / "gate.json",
        variants=(
            DddMergeAwareRootVariant.PAIR_ONLY,
            DddMergeAwareRootVariant.PAIR_ONLY,
        ),
    )

    with pytest.raises(ValueError, match="unique"):
        config.validate()


def test_tiny_merge_aware_root_gate_matches_complete_arc_flow_lp(tmp_path) -> None:
    output = tmp_path / "gate.json"
    result = DddMergeAwareRootGateRunner().run(
        DddMergeAwareRootGateConfig(
            example_id="three_station_v0",
            cabin_count=1,
            output_path=output,
            root_time_limit_seconds=15.0,
            reference_lp_time_limit_seconds=15.0,
            start_layout_time_limit_seconds=10.0,
            maximum_iterations=5,
            pricing_tiers_seconds=(5.0,),
            compatible_batch_time_limit_seconds=5.0,
            restricted_mip_time_limit_seconds=5.0,
            final_mip_time_limit_seconds=5.0,
            threads=1,
        )
    )

    reference = result.reference_lp
    reference_value = float(reference["lp_primal_objective"])
    assert reference["status"] == "optimal"
    assert len(result.variants) == len(DddMergeAwareRootVariant)
    for variant in result.variants:
        assert variant["certificate_valid"] is True
        assert variant["root_lp_certified"] is True
        assert float(variant["certified_lower_bound"]) == pytest.approx(
            reference_value,
            abs=1e-4,
        )

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert payload["result"]["problem_fingerprint"] == result.problem_fingerprint
    assert {
        item["variant"] for item in payload["result"]["variants"]
    } == {item.value for item in DddMergeAwareRootVariant}
