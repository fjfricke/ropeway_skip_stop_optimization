import json
from pathlib import Path
import runpy
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
campaign = runpy.run_path(str(ROOT / "benchmarks/run_arc_flow_passenger_campaign.py"))
report = runpy.run_path(str(ROOT / "benchmarks/summarize_arc_flow_passenger_campaign.py"))


def test_integer_export_checks_before_conversion():
    assert campaign["integer_counts"]({"a": 2.0, "b": 0}) == {"a": 2}
    for value in (.5, -1, float("nan")):
        with pytest.raises(ValueError):
            campaign["integer_counts"]({"a": value})


def test_supervisor_terminates_without_claiming_proof(tmp_path):
    folder = tmp_path / "run"
    assert not campaign["isolated"]([sys.executable, "-c", "import time; time.sleep(10)"], folder, .2)
    result = json.loads((folder / "process.json").read_text())
    assert result["timed_out"]
    assert result["actual_seconds"] < 3
    assert not (folder / "result.json").exists()


def test_seed_adoption_is_not_a_speedup(tmp_path):
    (tmp_path / "events.jsonl").write_text("")
    row = dict(folder=str(tmp_path), validated_upper_bound=1000, certified_lower_bound=0,
               seed_value=1000, actual_total_seconds=60)
    assert not report["compare"](row, row)["passed"]
    assert report["compare"](dict(row, validated_upper_bound=999), row)["cost_criterion"]
    assert not report["compare"](dict(row, validated_upper_bound=999.5), row)["passed"]
    assert report["compare"](dict(row, certified_lower_bound=10), row)["gap_criterion"]
