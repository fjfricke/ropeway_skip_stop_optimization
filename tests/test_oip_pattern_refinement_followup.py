from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


def _runner():
    path = Path(__file__).parents[1] / "benchmarks" / "run_oip_pattern_refinement_followup.py"
    spec = importlib.util.spec_from_file_location("oip_refinement_followup", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _source(tmp_path: Path, *, status: str = "complete") -> Path:
    attempt = tmp_path / "source" / "trials" / "all_stop__k2" / "attempt_1"
    attempt.mkdir(parents=True)
    for name in ("result.json", "detail.json", "movement_certificate.json"):
        (attempt / name).write_text("{}")
    campaign = {
        "campaign_id": "source_campaign",
        "status": status,
        "contract_id": "contract",
        "demand_family": "f2",
        "demand_total": 20,
        "trials": [
            {
                "trial_id": "all_stop__k2",
                "policy_id": "all_stop",
                "allocation_id": "all_stop",
                "allocation_label": "All-Stop",
                "available_fleet_count": 2,
                "pattern_identity": "patterns",
                "pattern_composition": {"S0+S1": 2},
                "patterns_by_cabin_id": [["S0", "S1"], ["S0", "S1"]],
                "movement_status": "feasible",
                "served": 12,
                "unserved": 8,
                "journey_time_seconds": 100.0,
                "attempts": [
                    {
                        "status": "complete",
                        "directory": "trials/all_stop__k2/attempt_1",
                    }
                ],
            },
            {
                "trial_id": "direct__k2",
                "movement_status": "unknown",
                "served": None,
                "attempts": [{"status": "complete", "directory": "unused"}],
            },
        ],
    }
    path = tmp_path / "source" / "campaign.json"
    path.write_text(json.dumps(campaign))
    return path


def test_collect_candidates_keeps_only_complete_feasible_results(tmp_path: Path) -> None:
    runner = _runner()
    sources, candidates = runner.collect_candidates([_source(tmp_path)])
    assert sources[0]["eligible_count"] == 1
    assert len(candidates) == 1
    assert candidates[0]["source_trial_id"] == "all_stop__k2"
    assert candidates[0]["source_served"] == 12


def test_collect_candidates_rejects_incomplete_campaign(tmp_path: Path) -> None:
    runner = _runner()
    with pytest.raises(ValueError, match="not complete"):
        runner.collect_candidates([_source(tmp_path, status="partial")])
