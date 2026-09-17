import json
import threading

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


def test_campaign_index_serializes_concurrent_publishers(tmp_path):
    threads = [
        threading.Thread(
            target=update_campaign_index,
            args=(tmp_path, {"campaign_id": f"campaign-{index}", "status": "running"}),
        )
        for index in range(8)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    payload = json.loads((tmp_path / "index.json").read_text())
    assert {item["campaign_id"] for item in payload["campaigns"]} == {
        f"campaign-{index}" for index in range(8)
    }
