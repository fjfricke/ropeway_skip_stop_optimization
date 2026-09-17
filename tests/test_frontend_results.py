import json

from ropeway_skip_stop_optimization.benchmarking.frontend_results import (
    update_campaign_index,
)


def test_campaign_index_replaces_entry_and_keeps_membership(tmp_path):
    first = {
        "campaign_id": "current", "status": "prepared",
        "contract_id": "contract", "study_membership": "current_thesis",
    }
    update_campaign_index(tmp_path, first)
    update_campaign_index(tmp_path, {**first, "status": "running"})
    payload = json.loads((tmp_path / "index.json").read_text())
    assert len(payload["campaigns"]) == 1
    assert payload["campaigns"][0]["status"] == "running"
    assert payload["campaigns"][0]["study_membership"] == "current_thesis"
