"""Read-only exports must preserve uncertainty and exact certificate events."""
import json

from benchmarks.export_thesis_frontend import (
    _copy_portable,
    _live_directories,
    _run_summary,
)
from benchmarks.thesis_detail_export import read_events, replay_payload

CASE = {
    "topology": "t5r",
    "geometry": "g500",
    "demand_family": "f2",
    "demand_profile": "p0",
    "objective": "journey_time",
    "demand_total": 10,
}


def test_supervisor_abort_keeps_validated_value_without_completed_status(tmp_path):
    (tmp_path / "supervisor.json").write_text(json.dumps({"supervisor_reason": "WALL_DEADLINE", "exit_code": -15}))
    result = {"run": {"independent_validation_status": "feasible", "validated_upper_bound": 42}}
    summary = _run_summary(tmp_path, result, CASE, {"method": "labelled_arc_flow"})
    assert summary["status"] == "failed"
    assert summary["stopReason"] == "WALL_DEADLINE"
    assert summary["journeyTime"] == 42
    assert summary["validated"]


def test_failed_preflight_without_result_is_discoverable(tmp_path):
    (tmp_path / "preflight.json").write_text(json.dumps({"status": "partial", "jobs": [{"id": "failed", "status": "failed"}]}))
    assert _live_directories(tmp_path) == {tmp_path / "failed": "failed"}


def test_portable_snapshot_omits_local_paths_and_partial_event(tmp_path):
    source = tmp_path / "events.jsonl"
    source.write_text('{"path":"/Users/test/private/a.py","source":"https://example.org/paper"}\n{"unfinished":')
    target = tmp_path / "copy.jsonl"
    _copy_portable(source, target)
    assert read_events(target) == [{"path": "[local-path]", "source": "https://example.org/paper"}]


def test_waiting_boarding_alighting_and_loads_replayed_from_certificate():
    core = {"route_options": [{"id": "a", "station_id": "A", "duration_seconds": 10,
        "platform_entry_offset_seconds": 2, "platform_exit_offset_seconds": 4, "decision": "stop"}]}
    certificate = {"domain_manifest": {"movement_core": core}, "plan": {
        "trips": [{"cabin_id": 0, "route_option_ids": ["a", "a"], "switch_ticks": [0, 13_000_000], "wait_ticks": [3_000_000, 2_000_000]}],
        "ride_counts": {"g::0::0::1": 4}}}
    replay = replay_payload(certificate=certificate)
    first, last = replay["visits"]
    assert (first["arrival"], first["boarding"], first["end"]) == (2, 7, 13)
    assert (last["arrival"], last["boarding"]) == (15, 19)
    assert (first["boarded"], first["load"], last["alighted"], last["load"]) == (4, 4, 4, 0)
    assert replay["loadsAvailable"]


def test_export_cache_skips_unchanged_raw_results(tmp_path, monkeypatch):
    from benchmarks import export_thesis_frontend as exporter
    source, destination = tmp_path / "run", tmp_path / "package"
    source.mkdir()
    (source / "case_spec.json").write_text(json.dumps(CASE))
    (source / "arguments.json").write_text(json.dumps({"method": "labelled_arc_flow"}))
    (source / "result.json").write_text(json.dumps({"method": "labelled_arc_flow", "run": {"status": "unknown"}}))
    first = exporter._export_one(source, destination, None)
    original = exporter._read
    def read(path):
        if path == source / "result.json":
            raise AssertionError("unchanged large raw result was reparsed")
        return original(path)
    monkeypatch.setattr(exporter, "_read", read)
    assert exporter._export_one(source, destination, None) == first


def test_historical_thesis_run_is_exported_only_to_archive_index(tmp_path):
    from benchmarks import export_thesis_frontend as exporter
    source = tmp_path / "historical" / "run"
    source.mkdir(parents=True)
    (source / "case_spec.json").write_text(json.dumps(CASE))
    (source / "arguments.json").write_text(json.dumps({
        "method": "labelled_arc_flow", "fixed_k": 10,
    }))
    (source / "result.json").write_text(json.dumps({
        "method": "labelled_arc_flow",
        "run": {
            "status": "complete",
            "independent_validation_status": "feasible",
            "independent_validation_objective": 42,
        },
    }))
    destination = tmp_path / "package"
    current = exporter.export((source.parent,), destination)
    archived = json.loads((destination / "archive-index.json").read_text())
    assert current["runs"] == []
    assert len(archived["runs"]) == 1
    assert archived["runs"][0]["studyMembership"] == "archive"


def test_resolution_decision_requires_bounds_not_only_matching_incumbents():
    from benchmarks.summarize_thesis_resolution import relative_interval_difference
    assert relative_interval_difference((99, 100), (100, 100)) == .01
    assert relative_interval_difference((0, 100), (100, 100)) is None
    assert relative_interval_difference((100, None), (100, 100)) is None
    assert relative_interval_difference((95, 100), (100, 100)) == .05
